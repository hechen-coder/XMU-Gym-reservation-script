import sys
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable

from xdty_booking.config import AppConfig
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.auth.session_manager import SessionManager
from xdty_booking.auth.harvester_service import HarvestService
from xdty_booking.solver.captcha_solver import CaptchaSolver
from xdty_booking.core.time_sync import TimeSync
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.notify.notifier import Notifier

logger = logging.getLogger(__name__)

def set_windows_keep_awake(enable: bool = True):
    """
    通过 Windows 底层 kernel32.SetThreadExecutionState 控制电源睡眠状态。
    enable=True 时：阻止系统进入挂起或睡眠，支持显示器关闭与锁屏(Win+L)，保证后台定时器与网络准点执行。
    enable=False 时：复原系统默认电源休眠策略。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_AWAYMODE_REQUIRED = 0x00000040
        if enable:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
            )
            logger.info("🛡️ 已激活 Windows 防休眠守护模式 (支持锁屏/息屏，主机 CPU 与网络持续在线)")
        else:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            logger.info("🛡️ 已恢复 Windows 系统默认电源休眠管理")
    except Exception as e:
        logger.debug(f"防休眠设置异常: {e}")


class BookingScheduler:
    """
    早 7 点准点抢票调度服务：
    1. 预检自愈机制 (Pre-flight check): 在 07:00 抢票前 (如 06:55，默认提前 5 分钟) 自动唤醒自检登录态，若失效则拉起方案 A 嗅探自愈；
    2. 等待期间完全静默免打扰：不在半夜无谓发送心跳、修改代理或弹窗微信；
    3. 服务端毫秒时间差校准：在放票前 30 秒高精度对时；
    4. 准点提前 advance_ms 毫秒并发突发抢票；
    5. 支持名额不足自动就近时段降级；
    6. 抢票成功联动即时通知。
    """
    def __init__(
        self,
        config: AppConfig,
        session_mgr: SessionManager,
        client: ApiClient,
        api: XdtyApi,
        solver: CaptchaSolver,
        config_path: str = "config/config.yaml",
        notifier: Optional[Notifier] = None
    ):
        self.cfg = config
        self.session_mgr = session_mgr
        self.client = client
        self.api = api
        self.solver = solver
        self.config_path = config_path
        self.notifier = notifier or Notifier(config.notify)
        self.harvest_service = HarvestService(config, config_path=config_path)
        self._stop_event = threading.Event()
        self.status_callback: Optional[Callable[[str], None]] = None

    def stop(self):
        """手动取消/停止定时调度守护"""
        logger.info("🛑 收到手动停止定时预约请求...")
        self._stop_event.set()
        set_windows_keep_awake(False)
        if self.status_callback:
            self.status_callback("已手动停止定时任务")

    def ensure_valid_session(self, timeout: float = 30.0) -> bool:
        """检查并确保登录态有效，若失效先尝试纯 HTTP 续登，失败后再触发微信小程序嗅探捕获"""
        is_missing = not bool(self.cfg.auth.phpsessid)
        is_alive = False if is_missing else self.session_mgr.check_alive()
        if is_alive:
            logger.info("✅ 当前 Session 凭证有效，无需自愈")
            return True

        reason = "未配置 PHPSESSID" if is_missing else "当前 PHPSESSID 已失效"
        logger.warning(f"检测到 {reason}，开始执行双阶自愈策略...")

        # 1. 优先尝试纯 HTTP checkLogin 续登
        if getattr(self.cfg.auth, "auth_params", None) and self.cfg.auth.auth_params.get("token"):
            if hasattr(self.session_mgr, "refresh_session_via_check_login"):
                new_token = self.session_mgr.refresh_session_via_check_login()
                if new_token:
                    self.client.set_session_token(new_token)
                    self.cfg.auth.phpsessid = new_token
                    token_str = str(new_token)
                    logger.info(f"✅ checkLogin 纯 HTTP 续登成功！新 PHPSESSID: {token_str[:8]}***")
                    return True

        # 2. 微信小程序嗅探兜底
        if not self.cfg.auth.auto_harvest_enabled:
            logger.warning(f"检测到 {reason}，但 auto_harvest_enabled 未开启，跳过自动嗅探")
            return False

        logger.info(f"启动第 2 阶自愈：微信小程序代理嗅探自愈闭环...")
        new_token = self.harvest_service.harvest(timeout=timeout)
        if new_token:
            self.session_mgr.update_token(new_token)
            self.client.set_session_token(new_token)
            self.cfg.auth.phpsessid = new_token
            token_str = str(new_token)
            logger.info(f"✅ Session 自动嗅探自愈完成！新 PHPSESSID: {token_str[:8]}***")
            return True
        else:
            logger.error("❌ 自动嗅探未成功获取到新凭证，请确认微信已登录且小程序可用")
            return False

    def run(self, target_time: Optional[str] = None) -> Dict[str, Any]:
        if self._stop_event.is_set():
            return {"success": False, "info": "定时任务已被手动终止"}
        target_time_str = target_time or self.cfg.scheduler.target_time or "07:00:00"
        logger.info(f"🚀 启动早间高精度定时抢票守护服务，目标时刻: 每日 [{target_time_str}]")

        # 启动 Windows 原生防睡眠守护，允许锁屏/息屏下维持后台执行
        set_windows_keep_awake(True)

        try:
            # 计算目标时间
            now = datetime.now()
            target_hour, target_minute, target_second = map(int, target_time_str.split(":"))
            target_dt = now.replace(hour=target_hour, minute=target_minute, second=target_second, microsecond=0)
            if target_dt <= now:
                target_dt += timedelta(days=1)

            target_ts = target_dt.timestamp()
            pre_check_minutes = max(1, self.cfg.scheduler.pre_check_minutes)
            pre_check_dt = target_dt - timedelta(minutes=pre_check_minutes)
            
            logger.info(f"📅 下一个目标抢票时刻: {target_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"⏱️ 提前自检预热时刻: {pre_check_dt.strftime('%Y-%m-%d %H:%M:%S')} (提前 {pre_check_minutes} 分钟)")
            if self.status_callback:
                self.status_callback(f"定时守护中：目标抢票时刻 {target_dt.strftime('%m-%d %H:%M:%S')}，将在 {pre_check_dt.strftime('%H:%M:%S')} 预检凭据")

            # 1. 如果当前距离预检时间尚早，进入纯静默休眠（免打扰，不发心跳、不弹微信、不改代理）
            if datetime.now() < pre_check_dt:
                total_wait = (pre_check_dt - datetime.now()).total_seconds()
                hours = int(total_wait // 3600)
                mins = int((total_wait % 3600) // 60)
                logger.info(f"💤 进入静默休眠等待模式 (距离预检还有 {hours} 小时 {mins} 分钟)")
                logger.info("ℹ️ 等待期间保持免打扰静默状态，不发送心跳，不拉起微信，直至预检时刻准时唤醒。")

                last_report_time = time.time()
                while datetime.now() < pre_check_dt:
                    if self._stop_event.is_set():
                        logger.info("🛑 接收到终止信号，退出定时守护模式")
                        return {"success": False, "info": "定时任务已被手动终止"}
                    wait_secs = (pre_check_dt - datetime.now()).total_seconds()
                    if wait_secs <= 0:
                        break
                    # 若等待时间较长，每 30 分钟在控制台输出一次状态
                    if time.time() - last_report_time >= 1800 and wait_secs > 600:
                        logger.info(f"⏳ 静默守护中... 距离预检自愈还有 {int(wait_secs // 60)} 分钟 (目标预检时刻: {pre_check_dt.strftime('%H:%M:%S')})")
                        last_report_time = time.time()
                    if self.status_callback:
                        self.status_callback(f"静默休眠中，将在 {pre_check_dt.strftime('%H:%M:%S')} 进行预检自愈 (距抢票 {int((target_ts - datetime.now().timestamp()) // 60)} 分钟)")
                    sleep_step = min(10.0, max(0.5, wait_secs))
                    if self._stop_event.wait(sleep_step):
                        return {"success": False, "info": "定时任务已被手动终止"}

            if self._stop_event.is_set():
                return {"success": False, "info": "定时任务已被手动终止"}

            # 2. 到达预检时刻：仅在此刻全面执行 Session 存活探测与失效自愈 (此时捕获的凭证最新鲜有效)
            logger.info(f"🔍 到达抢票前预检时刻 ({datetime.now().strftime('%H:%M:%S')})，检查凭证有效性...")
            if self.status_callback:
                self.status_callback("到达抢票前预检时刻，正在检查并自愈 Session 凭据...")
            valid = self.ensure_valid_session()
            if not valid:
                logger.error("⚠️ 提前预检自愈未成功，抢票将按当前状态继续尝试")

            # 3. 冲刺等待期：在准点前 30 秒进行高精度服务端毫秒时间差校准
            while (target_ts - datetime.now().timestamp()) > 35.0:
                if self._stop_event.wait(1.0):
                    return {"success": False, "info": "定时任务已被手动终止"}

            if self._stop_event.is_set():
                return {"success": False, "info": "定时任务已被手动终止"}

            logger.info("正在与厦大体育馆服务器校准高精度时间差...")
            if self.status_callback:
                self.status_callback("正在与厦大体育馆服务器进行毫秒级高精度对时...")
            time_offset = TimeSync.get_server_time_offset(self.cfg.base_url)

            # 4. 高精度等待直至准点时刻 (提前 advance_ms 毫秒)
            remaining = target_ts - datetime.now().timestamp()
            logger.info(f"距离准点放票还剩 {remaining:.2f} 秒，进入毫秒级高精度等待...")
            if self.status_callback:
                self.status_callback(f"距离放票还剩 {remaining:.1f} 秒，进入突发就绪状态...")
            TimeSync.wait_until(target_ts, offset=time_offset, advance_ms=self.cfg.scheduler.advance_ms)

            if self._stop_event.is_set():
                return {"success": False, "info": "定时任务已被手动终止"}

            # 5. 准点瞬间：极速并发抢票！
            logger.info(f"⚡ [准点] {datetime.now().strftime('%H:%M:%S')} 到达放号时刻！立即执行极速抢票！")
            if self.status_callback:
                self.status_callback("⚡ 到达放票时刻！正在极速提交预约订单...")
            engine = BookingEngine(
                api=self.api,
                captcha_solver=self.solver,
                config=self.cfg,
                notifier=self.notifier,
                on_session_expired=self.ensure_valid_session
            )
            res = engine.execute_booking(
                fallback_nearest=self.cfg.scheduler.fallback_nearest,
                mode="早7点准点抢票"
            )
            
            if res.get("success"):
                logger.info(f"🎉 准点抢票大获全胜: {res.get('info')}")
                if self.status_callback:
                    self.status_callback(f"🎉 准点抢票成功！{res.get('info')}")
            else:
                logger.error(f"准点抢票结果: {res.get('info')}")
                if self.status_callback:
                    self.status_callback(f"⚠️ 准点抢票结束: {res.get('info')}")

            return res
        finally:
            set_windows_keep_awake(False)
