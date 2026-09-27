import sys
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable

from xdty_booking.config import AppConfig, load_config
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.auth.session_manager import SessionManager
from xdty_booking.auth.harvester_service import HarvestService
from xdty_booking.solver.captcha_solver import CaptchaSolver
from xdty_booking.core.time_sync import TimeSync
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.notify.notifier import Notifier

logger = logging.getLogger(__name__)

# execute_booking 返回这些 reason 时，准点后宽限期内视为“尚未放票”而非最终失败
_NOT_RELEASED_REASONS = ("course_occupied", "slot_missing", "query_failed")

def planned_slots(cfg: AppConfig, visit_date: str) -> List[str]:
    """某入场日期应预约的时段，按优先级从高到低：特例表优先，其次每周计划（按星期），非每周模式用固定时段。"""
    override = cfg.scheduler.date_overrides.get(visit_date)
    if override:
        return override
    if cfg.scheduler.weekly_enabled:
        return cfg.scheduler.weekly_plan.get(str(datetime.fromisoformat(visit_date).isoweekday()), [])
    return [cfg.target.preferred_time]


def slots_text(slots: List[str], brief: bool = False) -> str:
    """把优先级时段拼成可读文本；brief 供通知标题使用，只显示首选与总数"""
    if brief and len(slots) > 1:
        return f"{slots[0]} 等 {len(slots)} 个时段"
    return " > ".join(slots)


def next_scheduled_booking(cfg: AppConfig, now: datetime, target_time: Optional[str] = None):
    """返回下次开抢时间、入场日期和按优先级排序的时段列表；星期按入场日期计算。"""
    hour, minute, second = map(int, (target_time or cfg.scheduler.target_time).split(":"))
    run_at = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if run_at <= now:
        run_at += timedelta(days=1)
    for _ in range(7):
        visit_date = (run_at + timedelta(days=cfg.target.target_date_offset)).date().isoformat()
        slots = planned_slots(cfg, visit_date)
        if slots:
            return run_at, visit_date, slots
        run_at += timedelta(days=1)
    raise ValueError("每周计划至少需要设置一天")

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


# 失败原因关键字 -> 通知标题分类（按顺序匹配，第一条命中为准）
_FAILURE_KINDS = (
    (("登录", "失效", "PHPSESSID", "token", "未授权"), "登录失效"),
    (("满", "超额", "名额"), "名额已满"),
    (("验证码",), "验证码错误"),
    (("网络", "超时", "timeout"), "网络异常"),
    (("未找到",), "未找到场次"),
)


def classify_failure(res: Dict[str, Any]) -> str:
    """把 execute_booking 的失败结果归类为便于一眼识别的标题"""
    if res.get("full") or res.get("capacity_full"):
        return "名额已满"
    info = str(res.get("info", ""))
    for keywords, kind in _FAILURE_KINDS:
        if any(k in info for k in keywords):
            return kind
    return "预约失败"


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
        self.next_booking = None
        self.last_result = None

    def _notify(self, title: str, content: str) -> Dict[str, bool]:
        """发送通知；任何异常只记日志，绝不中断预约流程"""
        try:
            result = self.notifier.send(title=title, content=content)
            if not any(result.values()):
                logger.warning(f"通知未送达 [{title}]，请检查通知配置或网络")
            return result
        except Exception as e:
            logger.error("通知发送异常 [%s]: %s", title, type(e).__name__)
            return {"error": False}

    def _plan_context(self, visit_date: str, preferred_times: List[str]) -> str:
        return (f"场馆：{self.cfg.target.stadium_name}\n"
                f"入场日期：{visit_date}\n计划时段：{slots_text(preferred_times)}\n")

    def _missed_window(self, visit_date: str, preferred_times: List[str]) -> Dict[str, Any]:
        info = "已错过本次开抢时间，继续等待下一个计划日"
        self._notify(title=f"错过开抢时间 {visit_date} {slots_text(preferred_times, brief=True)}",
                     content=self._plan_context(visit_date, preferred_times)
                     + f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                     "原因：到达开抢时刻时服务未在运行或被阻塞，本次未提交预约。")
        return {"success": False, "info": info}

    def stop(self):
        """手动取消/停止定时调度守护"""
        logger.info("🛑 收到手动停止定时预约请求...")
        self._stop_event.set()
        set_windows_keep_awake(False)
        if self.status_callback:
            self.status_callback("已手动停止定时任务")

    def _adopt_file_credentials(self):
        """网页登录可能发生在调度器启动之后，预检时以配置文件中的 PHPSESSID / auth_params 为准"""
        try:
            auth = load_config(self.config_path).auth
        except Exception as e:
            logger.debug(f"读取配置文件凭据失败，沿用内存配置: {e}")
            return
        if auth.phpsessid and auth.phpsessid != self.cfg.auth.phpsessid:
            logger.info(f"🔁 检测到配置文件中有更新的 PHPSESSID ({auth.phpsessid[:8]}***)，采用之")
            self.cfg.auth.phpsessid = auth.phpsessid
            self.session_mgr.update_token(auth.phpsessid)
            self.client.set_session_token(auth.phpsessid)
        if auth.auth_params:
            self.cfg.auth.auth_params = auth.auth_params
            self.session_mgr.set_auth_params(auth.auth_params)

    def _slots_reachable(self) -> bool:
        """场次查询接口探测：仅“我的预约”查询成功不足以证明预约链路可用"""
        t = self.cfg.target
        try:
            res = self.api.get_intervals(t.venue_id, t.stadium_id, t.category_id, t.user_range)
        except Exception as e:
            logger.warning(f"场次查询接口探测异常: {e}")
            return False
        if res.status != 1:
            logger.warning(f"场次查询接口探测未通过: {res.info}")
            return False
        return True

    def ensure_valid_session(self, timeout: float = 30.0) -> bool:
        """
        预检自愈：配置了账号密码时，无条件先用账号密码重新登录（不信任隔夜会话）；
        未配置或登录失败时回退：以配置文件凭据为准，探测“我的预约”与场次查询接口，
        失效再依次尝试纯 HTTP 续登 -> 微信小程序嗅探捕获
        """
        self._adopt_file_credentials()

        # 0. 每日强制账号密码重新登录
        new_token = self.session_mgr.refresh_session_via_password()
        if new_token:
            self.client.set_session_token(new_token)
            self.cfg.auth.phpsessid = new_token
            logger.info(f"✅ 已按计划使用账号密码重新登录！新 PHPSESSID: {str(new_token)[:8]}***")
            # 新会话首次 getInterval 会报“参数错误”，此处预热场馆上下文，避免准点时多花一个来回
            self._slots_reachable()
            return True
        logger.warning("账号密码重新登录未执行或未成功（未配置 / CAS 异常），回退检查现有会话...")

        is_missing = not bool(self.cfg.auth.phpsessid)
        is_alive = (not is_missing) and self.session_mgr.check_alive() and self._slots_reachable()
        if is_alive:
            logger.info("✅ 登录凭证与场次查询接口均正常，无需自愈")
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

        logger.info(f"启动微信小程序代理嗅探自愈闭环...")
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
        after = datetime.now()
        while not self._stop_event.is_set():
            self.next_booking = next_scheduled_booking(self.cfg, after, target_time)
            try:
                self.last_result = self._run_once(target_time)
            except Exception as e:
                if not self.cfg.scheduler.weekly_enabled:
                    raise
                logger.exception("本次每周计划预约异常，将继续下一个计划日")
                self.last_result = {"success": False, "info": str(e)}
                _, visit_date, slots = self.next_booking
                self._notify(title=f"预约流程异常 {visit_date} {slots_text(slots, brief=True)}",
                             content=self._plan_context(visit_date, slots)
                             + f"异常：{type(e).__name__}: {e}\n系统将继续执行下一个计划日，请检查服务器日志。")
            if not self.cfg.scheduler.weekly_enabled:
                return self.last_result
            # 提前毫秒提交或失败重试结束时，不能再次选中同一开抢时刻。
            after = max(datetime.now(), self.next_booking[0])
        return {"success": False, "info": "定时任务已被手动终止"}

    def _run_once(self, target_time: Optional[str] = None) -> Dict[str, Any]:
        if self._stop_event.is_set():
            return {"success": False, "info": "定时任务已被手动终止"}
        target_time_str = target_time or self.cfg.scheduler.target_time or "07:00:00"
        logger.info(f"🚀 启动早间高精度定时抢票守护服务，目标时刻: 每日 [{target_time_str}]")

        # 启动 Windows 原生防睡眠守护，允许锁屏/息屏下维持后台执行
        set_windows_keep_awake(True)

        try:
            # 计算目标时间
            target_dt, visit_date, preferred_times = self.next_booking or next_scheduled_booking(self.cfg, datetime.now(), target_time)

            target_ts = target_dt.timestamp()
            pre_check_minutes = max(1, self.cfg.scheduler.pre_check_minutes)
            pre_check_dt = target_dt - timedelta(minutes=pre_check_minutes)
            
            logger.info(f"📅 下一个目标抢票时刻: {target_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"⏱️ 提前自检预热时刻: {pre_check_dt.strftime('%Y-%m-%d %H:%M:%S')} (提前 {pre_check_minutes} 分钟)")
            if self.status_callback:
                self.status_callback(f"等待 {target_dt.strftime('%m-%d %H:%M:%S')} 开抢，预约 {visit_date} {slots_text(preferred_times)}")

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

            if self.cfg.scheduler.weekly_enabled and datetime.now() > target_dt + timedelta(minutes=1):
                return self._missed_window(visit_date, preferred_times)

            # 2. 到达预检时刻：仅在此刻全面执行 Session 存活探测与失效自愈 (此时捕获的凭证最新鲜有效)
            logger.info(f"🔍 到达抢票前预检时刻 ({datetime.now().strftime('%H:%M:%S')})，检查凭证有效性...")
            if self.status_callback:
                self.status_callback("到达抢票前预检时刻，正在检查并自愈 Session 凭据...")
            valid = self.ensure_valid_session()
            if not valid:
                logger.error("⚠️ 提前预检自愈未成功，抢票将按当前状态继续尝试")
                self._notify(title=f"预检登录失败 {visit_date} {slots_text(preferred_times, brief=True)}",
                             content=self._plan_context(visit_date, preferred_times)
                             + f"账号密码重新登录与会话续登均失败，{target_dt.strftime('%H:%M')} 抢票大概率失败。\n"
                             "请立即打开控制台登录页手动登录，服务会在开抢时自动采用新凭据。")

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
            if self.cfg.scheduler.weekly_enabled and datetime.now() > target_dt + timedelta(minutes=1):
                return self._missed_window(visit_date, preferred_times)

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
            # 服务端放票不是准点瞬间完成：日期先挂出、时段稍后才从 locked 翻成可约。
            # 宽限期内时段缺失 / 仍锁定 / 查询失败都视为“尚未放票”继续轮询，超时仍锁定才算排课占用。
            # 每一轮按优先级从高到低依次尝试：明确失败（名额已满等）的时段立刻让位给下一优先级，
            # 仍属“尚未放票”的留在队列里下一轮再试，全部时段都已定论或超过宽限期才收尾。
            # ponytail: 优先级 1 还没挂出、优先级 2 已可约时会订到 2；要严格优先可加一个“放票等待窗”再降级。
            deadline = time.time() + self.cfg.scheduler.release_grace_seconds
            results: Dict[str, Dict[str, Any]] = {}
            pending = list(preferred_times)
            while True:
                for slot_time in list(pending):
                    res = results[slot_time] = engine.execute_booking(
                        target_date=visit_date,
                        preferred_time=slot_time,
                        fallback_nearest=False if self.cfg.scheduler.weekly_enabled else self.cfg.scheduler.fallback_nearest,
                        mode="早7点准点抢票" if len(preferred_times) == 1 else f"早7点准点抢票(优先级{preferred_times.index(slot_time) + 1})"
                    )
                    if res.get("success"):
                        break
                    if res.get("reason") in ("outcome_unknown", "booking_in_progress"):
                        pending.clear()
                        break
                    if res.get("reason") not in _NOT_RELEASED_REASONS:
                        pending.remove(slot_time)
                        logger.warning(f"时段 [{slot_time}] 无法预约（{res.get('info')}），尝试下一优先级")
                if res.get("success") or not pending or time.time() >= deadline:
                    break
                if self.status_callback:
                    self.status_callback(f"⏳ 时段尚未放出 ({res.get('info')})，{int(deadline - time.time())} 秒内持续轮询...")
                if self._stop_event.wait(2.0):
                    return {"success": False, "info": "定时任务已被手动终止"}

            tail = "系统将继续执行下一个计划日。" if self.cfg.scheduler.weekly_enabled else "本次定时任务已结束。"
            detail = "".join(f"· {t}：{results[t].get('info')}\n" for t in preferred_times if t in results)
            if res.get("success"):
                logger.info(f"🎉 准点抢票大获全胜: {res.get('info')}")
                if self.status_callback:
                    self.status_callback(f"🎉 准点抢票成功！{res.get('info')}")
            elif all(r.get("reason") == "course_occupied" for r in results.values()):
                message = (self._plan_context(visit_date, preferred_times) + detail
                           + "当天不再预约，也不改约计划外的其他时段。" + tail)
                try:
                    res["notification"] = self.notifier.send(
                        title=f"课程占用，已跳过 {visit_date} {slots_text(preferred_times, brief=True)} 的预约",
                        content=message)
                    if not any(res["notification"].values()):
                        logger.warning("课程占用跳过通知未送达，请检查通知配置或网络")
                except Exception as e:
                    logger.error("课程占用通知发送异常: %s", type(e).__name__)
                    res["notification"] = {"error": False}
                logger.info(res["info"])
                if self.status_callback:
                    self.status_callback(res["info"])
            else:
                logger.error(f"准点抢票结果: {res.get('info')}")
                if self.status_callback:
                    self.status_callback(f"⚠️ 准点抢票结束: {res.get('info')}")
                kind = classify_failure(res)
                res["notification"] = self._notify(
                    title=f"{kind} {visit_date} {slots_text(preferred_times, brief=True)}",
                    content=self._plan_context(visit_date, preferred_times)
                    + f"各优先级结果：\n{detail}" + tail)

            return res
        finally:
            set_windows_keep_awake(False)
