import time
import threading
import logging
from typing import Optional, Callable
from xdty_booking.api.endpoints import XdtyApi

logger = logging.getLogger(__name__)

class SessionManager:
    """
    落地方案 1：心跳机制保持 Session/Token 不失效。
    定期发送心跳查询请求（如 mySubscribe），延长服务端 Session 有效期；
    同时提供实时存活探测与失效告警机制。
    """
    def __init__(self, api: XdtyApi, phpsessid: str = "", on_expired: Optional[Callable[[], None]] = None):
        self.api = api
        self.phpsessid = phpsessid
        self.on_expired = on_expired
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def update_token(self, new_token: str):
        self.phpsessid = new_token
        self.api.client.set_session_token(new_token)
        logger.info(f"已更新 Session Token: {new_token[:8]}***")

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
                logger.error(f"[{current_time}] ⚠️ Session 已失效或未能成功保活！")
                if self.on_expired:
                    new_token = self.on_expired()
                    if new_token:
                        self.update_token(new_token)
            
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
