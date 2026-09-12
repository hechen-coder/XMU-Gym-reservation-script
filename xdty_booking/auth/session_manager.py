import time
import threading
import logging
from typing import Optional, Callable, Dict, Any
from xdty_booking.api.endpoints import XdtyApi

logger = logging.getLogger(__name__)

class SessionManager:
    """
    会话状态管理器与保活引擎：
    1. 提供实时存活探测 (check_alive)；
    2. 支持全 HTTP 自动续登 (refresh_session_via_check_login)；
    3. 支持双阶自愈策略 (renew_or_fallback: 先 HTTP 续登，失败后再走小程序兜底)；
    4. 心跳保活守护循环 (heartbeat_loop)。
    """
    def __init__(
        self,
        api: XdtyApi,
        phpsessid: str = "",
        auth_params: Optional[Dict[str, Any]] = None,
        config_path: str = "config/config.yaml",
        on_expired: Optional[Callable[[], None]] = None
    ):
        self.api = api
        self.phpsessid = phpsessid
        self.auth_params = auth_params or {}
        self.config_path = config_path
        self.on_expired = on_expired
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def set_auth_params(self, auth_params: Dict[str, Any]):
        """设置或更新 checkLogin 认证参数上下文"""
        if auth_params:
            self.auth_params = auth_params

    def update_token(self, new_token: str):
        self.phpsessid = new_token
        self.api.client.set_session_token(new_token)
        logger.info(f"已更新 Session Token: {new_token[:8]}***")

    def refresh_session_via_check_login(self) -> Optional[str]:
        """
        方案 A：优先通过 checkLogin 纯 HTTP 接口换取新的 PHPSESSID。
        成功后自动更新会话 Token，校验存活性，并持久化回写至配置文件。
        """
        if not self.auth_params or not self.auth_params.get("token"):
            logger.warning("未配置 auth_params 或缺少 token，无法执行 checkLogin 自动续登")
            return None

        logger.info("🔄 正在通过 checkLogin 执行纯 HTTP 自动续登...")
        success, new_phpsessid, res = self.api.check_login(self.auth_params)
        if success and new_phpsessid:
            self.update_token(new_phpsessid)
            # 使用 my_subscribe 进行二重确认
            try:
                sub_res = self.api.my_subscribe(page=1)
                if isinstance(sub_res, dict) and sub_res.get("status") == 1:
                    logger.info(f"🎉 纯 HTTP 自动续登成功且 mySubscribe 验证通过！新 Session: {new_phpsessid[:8]}***")
                else:
                    logger.warning(f"⚠️ checkLogin 换票成功但 mySubscribe 验证未通过: {sub_res}")
            except Exception as e:
                logger.warning(f"mySubscribe 验证异常: {e}")

            # 持久化回写 config
            if self.config_path:
                try:
                    from xdty_booking.config import save_phpsessid
                    save_phpsessid(self.config_path, new_phpsessid)
                except Exception as e:
                    logger.warning(f"持久化新 PHPSESSID 异常: {e}")

            return new_phpsessid
        else:
            info = res.get("info", "未知") if isinstance(res, dict) else str(res)
            logger.warning(f"checkLogin 续登失败: {info}")
            return None

    def renew_or_fallback(self) -> Optional[str]:
        """
        双阶自愈策略：
        第 1 阶：优先调用 checkLogin 进行纯 HTTP 自动续登；
        第 2 阶：若失败或凭据过期，回退调用 on_expired 回调（微信小程序冷启动兜底截取）。
        """
        new_token = self.refresh_session_via_check_login()
        if new_token:
            return new_token
        if self.on_expired:
            logger.info("checkLogin 续登未成功，启动兜底机制 (WeChatHarvester)...")
            fallback_token = self.on_expired()
            if fallback_token:
                self.update_token(fallback_token)
                return fallback_token
        return None

    def check_alive(self) -> bool:
        """
        探测 Session 存活状态：
        返回 True 表示当前 Session 有效且能正常获取预约数据；
        返回 False 表示已失效或网络不可达。
        """
        if not self.phpsessid:
            logger.warning("Session Token 为空，判定为未登录或失效状态")
            return False

        try:
            resp = self.api.my_subscribe(page=1)
            # 接口在有效时返回 {"status": 1, ...}
            # 失效或未登录时通常返回 {"status": -1, "info": "..."} 或 status: 0
            if isinstance(resp, dict) and resp.get("status") == 1:
                return True
            logger.warning(f"Session 存活检测未通过: {resp}")
            return False
        except Exception as e:
            logger.error(f"Session 存活检测异常: {e}")
            return False

    def heartbeat_loop(self, interval_seconds: int = 300):
        """
        阻塞式心跳循环，适于独立作为保活守护进程启动
        """
        logger.info(f"Session 心跳保活守护已启动，保活周期: {interval_seconds} 秒")
        self._running = True
        while self._running:
            alive = self.check_alive()
            current_time = time.strftime("%Y-%m-%d %H:%M:%S")
            if alive:
                logger.info(f"[{current_time}] 心跳发送成功，Session 维持活跃状态 ✅")
            else:
                logger.error(f"[{current_time}] ⚠️ Session 已失效或未能成功保活！尝试自动自愈...")
                self.renew_or_fallback()
            
            # 分段休眠，以便快速响应 stop 信号
            for _ in range(interval_seconds):
                if not self._running:
                    break
                time.sleep(1)

    def start_heartbeat_daemon(self, interval_seconds: int = 300):
        """
        启动后台守护线程运行心跳
        """
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self.heartbeat_loop,
            args=(interval_seconds,),
            daemon=True
        )
        self._thread.start()
        logger.info("心跳守护线程已在后台启动")

    def stop(self):
        """停止心跳保活"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("心跳守护已停止")
