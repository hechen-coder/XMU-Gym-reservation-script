import os
import json
import logging
import threading
import time
import re
import math
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlsplit
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any

from xdty_booking.config import (
    load_config,
    ensure_config_file,
    save_phpsessid,
    save_auth_params,
    save_cas_credentials,
    save_target_and_scheduler_config,
    save_notify_config
)
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.auth.session_manager import SessionManager
from xdty_booking.auth.harvester_service import HarvestService
from xdty_booking.solver.captcha_solver import CaptchaSolver
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.core.scheduler import BookingScheduler, next_scheduled_booking, planned_slots, slots_text
from xdty_booking.notify.notifier import Notifier
from xdty_booking.web.template import render_dashboard, render_qr_login_page
from xdty_booking.utils.logger import setup_logger
from cas_qr_login.cas_client import CasQrLoginClient
from xdty_booking.security.auth import (
    check_license,
    activate_license,
    get_auth_status,
    is_dev_mode
)

logger = setup_logger("xdty_web")

_GLOBAL_CONFIG_PATH = "config/config.yaml"

# 统一身份认证扫码登录全局状态管理
_state_lock = threading.Lock()
_cas_client: Optional[CasQrLoginClient] = None
_qr_login_result: Optional[Dict[str, Any]] = None
_is_logging_in = False
_has_login_failed = False

def _ensure_config_path(config_path: Optional[str] = None) -> str:
    path = config_path or _GLOBAL_CONFIG_PATH
    if not os.path.exists(path):
        dir_name = os.path.dirname(path)
        example_path = os.path.join(dir_name, "config.example.yaml") if dir_name else "config/config.example.yaml"
        if not os.path.exists(example_path):
            example_path = "config/config.example.yaml"
        if os.path.exists(example_path):
            if os.path.basename(path) == "config.yaml":
                try:
                    ensure_config_file(path, example_path)
                    logger.info(f"💡 首次运行检测：已自动为您生成配置文件 '{path}'")
                    return path
                except Exception:
                    return example_path
            return example_path
    return path

_SESSION_ENSURE_LOCK = threading.Lock()
_LAST_SESSION_VALID_TIME = 0.0
_LAST_SESSION_VALID_TOKEN = ""

def ensure_session(cfg, session_mgr, client, config_path: str, timeout: float = 30.0) -> bool:
    """Session 有效性预检与双阶自动自愈核心工具，支持并发互斥与短时健康缓存，防止频发重复续登"""
    global _LAST_SESSION_VALID_TIME, _LAST_SESSION_VALID_TOKEN

    has_token = bool(getattr(cfg.auth, "auth_params", None) and cfg.auth.auth_params.get("token"))
    has_php = bool(cfg.auth.phpsessid)

    # 若没有任何凭据（未登录状态），无需启动自愈，直接返回 False
    if not has_php and not has_token:
        return False

    now = time.time()
    # 快速短路缓存：若当前 Token 与上次成功校验/自愈的 Token 一致，且距上次检验不足 15 秒，直接判定为有效
    if has_php and cfg.auth.phpsessid == _LAST_SESSION_VALID_TOKEN and (now - _LAST_SESSION_VALID_TIME < 15.0):
        if client:
            client.set_session_token(cfg.auth.phpsessid)
        return True

    with _SESSION_ENSURE_LOCK:
        now = time.time()
        # 进入互斥锁后再次检查（可能前一个获取锁的线程刚自愈完成并更新了配置文件）
        c_path = _ensure_config_path(config_path)
        try:
            latest_cfg = load_config(c_path)
            if latest_cfg.auth.phpsessid and latest_cfg.auth.phpsessid != cfg.auth.phpsessid:
                cfg.auth.phpsessid = latest_cfg.auth.phpsessid
                if client:
                    client.set_session_token(latest_cfg.auth.phpsessid)
                session_mgr.update_token(latest_cfg.auth.phpsessid)
            if getattr(latest_cfg.auth, "auth_params", None):
                cfg.auth.auth_params = latest_cfg.auth.auth_params
                session_mgr.set_auth_params(latest_cfg.auth.auth_params)
        except Exception:
            pass

        has_php = bool(cfg.auth.phpsessid)
        has_token = bool(getattr(cfg.auth, "auth_params", None) and cfg.auth.auth_params.get("token"))
        if not has_php and not has_token:
            return False

        if has_php and cfg.auth.phpsessid == _LAST_SESSION_VALID_TOKEN and (time.time() - _LAST_SESSION_VALID_TIME < 15.0):
            if client:
                client.set_session_token(cfg.auth.phpsessid)
            return True

        if has_php and session_mgr.check_alive():
            _LAST_SESSION_VALID_TIME = time.time()
            _LAST_SESSION_VALID_TOKEN = cfg.auth.phpsessid
            return True

        logger.warning("检测到 Session 无效或已过期，启动双阶自愈策略...")
        new_token = session_mgr.renew_or_fallback()
        if new_token:
            if client:
                client.set_session_token(new_token)
            cfg.auth.phpsessid = new_token
            _LAST_SESSION_VALID_TIME = time.time()
            _LAST_SESSION_VALID_TOKEN = new_token
            logger.info("Session 自愈成功！")
            return True
        return False

class SchedulerManager:
    """Web 服务后台定时预约任务管理器"""
    def __init__(self):
        self._lock = threading.RLock()
        self._scheduler: Optional[BookingScheduler] = None
        self._thread: Optional[threading.Thread] = None
        self._is_running = False
        self._status_text = "未启动定时任务"
        self._target_time = "07:00:00"
        self._next_run_dt = ""
        self._stadium_name = ""
        self._preferred_time = ""
        self._last_result: Optional[Dict[str, Any]] = None

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._is_running and self._thread and self._thread.is_alive())

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            if self._is_running and self._thread and not self._thread.is_alive():
                self._is_running = False
                if not self._last_result and self._status_text.startswith("正在启动"):
                    self._status_text = "定时任务已结束"
            upcoming = getattr(self._scheduler, "next_booking", None)
            if isinstance(upcoming, tuple):
                self._next_run_dt = upcoming[0].strftime("%Y-%m-%d %H:%M:%S")
                self._preferred_time = slots_text(upcoming[2])
            return {
                "running": self._is_running,
                "status_text": self._status_text,
                "target_time": self._target_time,
                "next_run_dt": self._next_run_dt,
                "stadium_name": self._stadium_name,
                "preferred_time": self._preferred_time,
                "target_date": upcoming[1] if isinstance(upcoming, tuple) else "",
                "last_result": (getattr(self._scheduler, "last_result", None) or self._last_result)
            }

    def start(self, config_path: str = _GLOBAL_CONFIG_PATH) -> Dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"success": False, "info": "定时任务仍在运行或停止中，请停止并等待结束后再修改计划"}

            c_path = _ensure_config_path(config_path)
            cfg = load_config(c_path)
            client = ApiClient(base_url=cfg.base_url)
            if cfg.auth.phpsessid:
                client.set_session_token(cfg.auth.phpsessid)
            api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)
            session_mgr = SessionManager(
                api,
                phpsessid=cfg.auth.phpsessid,
                auth_params=cfg.auth.auth_params,
                config_path=c_path
            )
            solver = CaptchaSolver()
            notifier = Notifier(cfg.notify)

            scheduler = BookingScheduler(
                config=cfg,
                session_mgr=session_mgr,
                client=client,
                api=api,
                solver=solver,
                config_path=c_path,
                notifier=notifier
            )

            self._scheduler = scheduler
            self._target_time = cfg.scheduler.target_time or "07:00:00"
            self._stadium_name = cfg.target.stadium_name
            self._preferred_time = cfg.target.preferred_time
            self._status_text = f"定时守护中：将在早 {self._target_time} 执行准点抢票"
            self._last_result = None
            scheduler.next_booking = next_scheduled_booking(cfg, datetime.now())
            self._next_run_dt = scheduler.next_booking[0].strftime("%Y-%m-%d %H:%M:%S")
            self._preferred_time = slots_text(scheduler.next_booking[2])

            def _status_cb(msg: str):
                with self._lock:
                    self._status_text = msg

            scheduler.status_callback = _status_cb

            def _worker():
                try:
                    res = scheduler.run()
                    with self._lock:
                        self._last_result = res
                        self._is_running = False
                        if isinstance(res, dict) and res.get("success"):
                            self._status_text = f"🎉 预约成功: {res.get('info')}"
                        elif isinstance(res, dict) and res.get("info"):
                            self._status_text = f"预约结束: {res.get('info')}"
                except Exception as e:
                    logger.error(f"后台定时预约异常: {e}", exc_info=True)
                    with self._lock:
                        self._status_text = f"运行异常: {e}"
                        self._is_running = False

            t = threading.Thread(target=_worker, daemon=True, name="BookingSchedulerWorker")
            self._thread = t
            self._is_running = True
            t.start()

            return {
                "success": True,
                "info": f"定时预约已在后台启动，目标时刻: {self._next_run_dt}",
                "status": self.get_status()
            }

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            if not self._is_running and (not self._thread or not self._thread.is_alive()):
                return {"success": True, "info": "定时任务未在运行"}

            if self._scheduler:
                self._scheduler.stop()
            self._is_running = False
            self._status_text = "定时任务已手动停止"
            return {"success": True, "info": "定时任务已成功停止"}

_scheduler_manager = SchedulerManager()

class SnipeManager:
    """Web 服务后台实时捡漏监听任务管理器"""
    def __init__(self):
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._is_running = False
        self._status_text = "未启动捡漏监听"
        self._target_date = ""
        self._preferred_time = ""
        self._stadium_name = ""
        self._poll_count = 0
        self._last_result: Optional[Dict[str, Any]] = None

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            if self._is_running and self._thread and not self._thread.is_alive():
                self._is_running = False
                if not self._last_result and self._status_text.startswith("正在"):
                    self._status_text = "捡漏监听已结束"
            return {
                "running": self._is_running,
                "status_text": self._status_text,
                "target_date": self._target_date,
                "preferred_time": self._preferred_time,
                "stadium_name": self._stadium_name,
                "poll_count": self._poll_count,
                "last_result": self._last_result
            }

    def start(
        self,
        config_path: str = _GLOBAL_CONFIG_PATH,
        target_date: Optional[str] = None,
        preferred_time: Optional[str] = None,
        poll_interval: float = 2.0,
        fallback_nearest: bool = False
    ) -> Dict[str, Any]:
        with self._lock:
            if self._is_running and self._thread and self._thread.is_alive():
                return {"success": False, "info": "捡漏监听任务已在运行中，请勿重复启动"}

            c_path = _ensure_config_path(config_path)
            cfg = load_config(c_path)
            client = ApiClient(base_url=cfg.base_url)
            if cfg.auth.phpsessid:
                client.set_session_token(cfg.auth.phpsessid)
            api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)
            session_mgr = SessionManager(
                api,
                phpsessid=cfg.auth.phpsessid,
                auth_params=cfg.auth.auth_params,
                config_path=c_path
            )
            solver = CaptchaSolver()
            notifier = Notifier(cfg.notify)

            engine = BookingEngine(
                api=api,
                captcha_solver=solver,
                config=cfg,
                notifier=notifier,
                on_session_expired=lambda: ensure_session(cfg, session_mgr, client, c_path)
            )

            self._stop_event.clear()
            self._stadium_name = cfg.target.stadium_name
            self._preferred_time = preferred_time or cfg.target.preferred_time
            self._target_date = target_date or engine.resolve_target_date()
            self._poll_count = 0
            self._last_result = None
            self._status_text = f"正在监听 [{self._target_date} {self._preferred_time}] 退票名额..."

            def _status_cb(count: int, msg: str):
                with self._lock:
                    self._poll_count = count
                    self._status_text = msg

            def _worker():
                try:
                    res = engine.snipe_booking(
                        target_date=self._target_date,
                        preferred_time=self._preferred_time,
                        poll_interval=poll_interval,
                        fallback_nearest=fallback_nearest,
                        stop_event=self._stop_event,
                        status_callback=_status_cb
                    )
                    with self._lock:
                        self._last_result = res
                        self._is_running = False
                        if isinstance(res, dict) and res.get("success"):
                            self._status_text = f"🎉 捡漏成功: {res.get('info')}"
                        elif isinstance(res, dict) and res.get("info"):
                            self._status_text = f"捡漏结束: {res.get('info')}"
                except Exception as e:
                    logger.error(f"后台捡漏监听异常: {e}", exc_info=True)
                    with self._lock:
                        self._status_text = f"运行异常: {e}"
                        self._is_running = False

            t = threading.Thread(target=_worker, daemon=True, name="SnipeWorker")
            self._thread = t
            self._is_running = True
            t.start()

            return {
                "success": True,
                "info": f"已启动对 [{self._target_date} {self._preferred_time}] 的实时退票捡漏监听",
                "status": self.get_status()
            }

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            if not self._is_running and (not self._thread or not self._thread.is_alive()):
                return {"success": True, "info": "捡漏监听未在运行"}
            self._stop_event.set()
            self._is_running = False
            self._status_text = "捡漏监听已手动停止"
            return {"success": True, "info": "已成功停止捡漏监听任务"}

_snipe_manager = SnipeManager()

def book_gym_slot(
    interval_id: Optional[str] = None,
    date: Optional[str] = None,
    time_slot: Optional[str] = None,
    config_path: Optional[str] = None,
    auto_heal: bool = False
) -> Dict[str, Any]:
    """执行预约指定场次"""
    c_path = _ensure_config_path(config_path)
    cfg = load_config(c_path)
    client = ApiClient(base_url=cfg.base_url)
    if cfg.auth.phpsessid:
        client.set_session_token(cfg.auth.phpsessid)
    api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)
    session_mgr = SessionManager(
        api,
        phpsessid=cfg.auth.phpsessid,
        auth_params=cfg.auth.auth_params,
        config_path=c_path
    )
    solver = CaptchaSolver()
    notifier = Notifier(cfg.notify)

    if auto_heal:
        ensure_session(cfg, session_mgr, client, c_path)

    engine = BookingEngine(
        api=api,
        captcha_solver=solver,
        config=cfg,
        notifier=notifier,
        on_session_expired=lambda: ensure_session(cfg, session_mgr, client, c_path)
    )

    res = engine.execute_booking(
        target_date=date,
        preferred_time=time_slot,
        interval_id=interval_id
    )

    # 若预约响应判定登录失效且启用了 auto_heal，自动自愈重试
    info_msg = str(res.get("info", "")) if isinstance(res, dict) else ""
    if auto_heal and any(k in info_msg for k in ("登录", "失效", "PHPSESSID", "token", "401")):
        logger.warning(f"预约响应判定登录失效 ({info_msg})，触发紧急自愈并重试...")
        if ensure_session(cfg, session_mgr, client, c_path):
            res = engine.execute_booking(
                target_date=date,
                preferred_time=time_slot,
                interval_id=interval_id
            )
    return res

def query_gym_status(config_path: Optional[str] = None, auto_heal: bool = True) -> Dict[str, Any]:
    """查询健身房空闲状态数据，默认开启自动自愈"""
    c_path = _ensure_config_path(config_path)
    cfg = load_config(c_path)
    client = ApiClient(base_url=cfg.base_url)
    if cfg.auth.phpsessid:
        client.set_session_token(cfg.auth.phpsessid)
    api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)
    session_mgr = SessionManager(
        api,
        phpsessid=cfg.auth.phpsessid,
        auth_params=cfg.auth.auth_params,
        config_path=c_path
    )

    healed = False
    if auto_heal:
        healed = ensure_session(cfg, session_mgr, client, c_path)

    try:
        intervals = api.get_intervals(
            venue_id=cfg.target.venue_id,
            stadium_id=cfg.target.stadium_id,
            category_id=cfg.target.category_id,
            user_range=cfg.target.user_range
        )
    except Exception as e:
        logger.warning(f"获取场馆空闲数据异常: {e}")
        intervals = None

    is_session_valid = bool(cfg.auth.phpsessid)
    info_msg = ""
    if intervals:
        info_msg = getattr(intervals, "info", "")
        if getattr(intervals, "status", 1) == 0:
            if any(k in info_msg for k in ("登录", "失效", "重新登录", "过期", "token", "PHPSESSID")):
                # 若初次未执行过自愈且开启了 auto_heal，才尝试紧急自愈并重试一次
                if auto_heal and not healed and ensure_session(cfg, session_mgr, client, c_path):
                    try:
                        intervals = api.get_intervals(
                            venue_id=cfg.target.venue_id,
                            stadium_id=cfg.target.stadium_id,
                            category_id=cfg.target.category_id,
                            user_range=cfg.target.user_range
                        )
                        info_msg = getattr(intervals, "info", "")
                        is_session_valid = (getattr(intervals, "status", 1) == 1)
                    except Exception:
                        is_session_valid = False
                else:
                    is_session_valid = False
            else:
                is_session_valid = session_mgr.check_alive()
        else:
            is_session_valid = True
    else:
        is_session_valid = False

    has_auth_params = bool(getattr(cfg.auth, "auth_params", None) and cfg.auth.auth_params.get("token"))

    data = {
        "stadium_name": cfg.target.stadium_name,
        "area_name": cfg.target.area_name,
        "preferred_time": cfg.target.preferred_time,
        "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session_valid": is_session_valid,
        "has_auth_params": has_auth_params,
        "phpsessid": f"{cfg.auth.phpsessid[:8]}***" if cfg.auth.phpsessid else "",
        "info": info_msg,
        "date_list": [],
        "groups": [],
        "scheduler_status": _scheduler_manager.get_status(),
        "snipe_status": _snipe_manager.get_status(),
        "auth_status": get_auth_status(),
        "target_config": {
            "stadium_name": cfg.target.stadium_name,
            "stadium_id": cfg.target.stadium_id,
            "venue_id": cfg.target.venue_id,
            "area_name": cfg.target.area_name,
            "area_id": cfg.target.area_id,
            "user_range": cfg.target.user_range,
            "preferred_time": cfg.target.preferred_time,
            "target_date_offset": cfg.target.target_date_offset
        },
        "scheduler_config": {
            "target_time": cfg.scheduler.target_time,
            "fallback_nearest": cfg.scheduler.fallback_nearest,
            "pre_check_minutes": cfg.scheduler.pre_check_minutes,
            "weekly_enabled": cfg.scheduler.weekly_enabled,
            "weekly_plan": cfg.scheduler.weekly_plan,
            "date_overrides": cfg.scheduler.date_overrides
        },
        "notify_config": {
            "enabled": cfg.notify.enabled,
            "channel": cfg.notify.channel,
            "email": cfg.notify.email.to_addrs[0] if cfg.notify.email.to_addrs else ""
        }
    }

    if intervals and hasattr(intervals, "time_slot_list"):
        data["date_list"] = [{"date": d.date, "week": d.week} for d in getattr(intervals, "date_list", [])]
        for g in intervals.time_slot_list:
            preferred_times = planned_slots(cfg, g.date)
            group_data = {
                "date": g.date,
                "week_name": g.week_name,
                "time_range": g.time_range,
                "is_preferred": (g.time_range in preferred_times),
                "slots": []
            }
            for s in g.slots:
                group_data["slots"].append({
                    "area_name": s.area_name,
                    "interval_id": s.interval_id,
                    "selected": s.selected,
                    "max_count": s.max_count,
                    "remaining": s.remaining_capacity,
                    "is_available": s.is_available,
                    "is_locked": getattr(s, "is_locked", False),
                    "status": s.status,
                    "select_type": getattr(s, "select_type", 1),
                    "lock_reason": getattr(s, "lock_reason", "")
                })
            data["groups"].append(group_data)

    return data

class GymStatusHandler(BaseHTTPRequestHandler):
    """8080 端口 HTTP 核心请求处理器"""

    def log_message(self, format, *args):
        # 默认访问日志会写入包含凭据的 URL 查询串。
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def _local_request(self) -> bool:
        host = self.headers.get("Host", "")
        try:
            host_name = urlsplit(f"http://{host}").hostname
            if host_name not in ("localhost", "127.0.0.1", "::1"):
                return False
            for header in ("Origin", "Referer"):
                value = self.headers.get(header)
                if value and urlsplit(value).netloc.lower() != host.lower():
                    return False
        except ValueError:
            return False
        return True

    def _reject_foreign_request(self) -> bool:
        if self._local_request():
            return False
        self._send_json(403, {"success": False, "info": "请求来源无效"})
        return True

    def _send_json(self, status_code: int, data: Any):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        payload = json.dumps(data, ensure_ascii=False, default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o)).encode("utf-8")
        self.wfile.write(payload)

    def _send_html(self, status_code: int, html_str: str):
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html_str.encode("utf-8"))

    def _handle_book(self, params: Dict[str, Any]):
        interval_id = params.get("interval_id", [None])[0]
        date = params.get("date", [None])[0]
        time_slot = params.get("time", [None])[0]
        if not isinstance(interval_id, str) or not interval_id.strip() or not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not isinstance(time_slot, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d", time_slot) or time_slot[:5] >= time_slot[6:]:
            self._send_json(400, {"success": False, "info": "预约场次、日期或时段无效"})
            return
        try:
            datetime.fromisoformat(date)
            res = book_gym_slot(
                interval_id=interval_id,
                date=date,
                time_slot=time_slot,
                config_path=getattr(self, "booking_config_path", _GLOBAL_CONFIG_PATH),
                auto_heal=True
            )
            self._send_json(200, res)
        except ValueError:
            self._send_json(400, {"success": False, "info": "预约日期无效"})
        except Exception as e:
            logger.error("预约处理异常: %s", type(e).__name__)
            self._send_json(500, {"success": False, "info": "服务器内部错误"})

    def _handle_set_token(self, params: Dict[str, Any]):
        token = params.get("token", [None])[0]
        if not token:
            self._send_json(400, {"success": False, "info": "Token 不能为空"})
            return
        token = str(token).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token):
            self._send_json(400, {"success": False, "info": "Token 格式无效"})
            return
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            cfg = load_config(c_path)
            client = ApiClient(base_url=cfg.base_url)
            client.set_session_token(token)
            api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)
            mgr = SessionManager(api, phpsessid=token)
            alive = mgr.check_alive()
            if not alive:
                self._send_json(400, {"success": False, "alive": False, "info": "Token 校验未通过，原配置未修改"})
                return
            save_phpsessid(c_path, token)
            self._send_json(200, {
                "success": True,
                "alive": alive,
                "phpsessid": f"{token[:8]}***",
                "info": "🎉 Token 保存成功且存活有效！"
            })
        except Exception as e:
            logger.error("保存 Token 异常: %s", type(e).__name__)
            self._send_json(500, {"success": False, "info": "服务器内部错误"})

    def _handle_relogin(self):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            cfg = load_config(c_path)
            client = ApiClient(base_url=cfg.base_url)
            if cfg.auth.phpsessid:
                client.set_session_token(cfg.auth.phpsessid)
            api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)
            session_mgr = SessionManager(
                api,
                phpsessid=cfg.auth.phpsessid,
                auth_params=cfg.auth.auth_params,
                config_path=c_path
            )
            new_token = session_mgr.refresh_session_via_check_login()
            if new_token:
                self._send_json(200, {
                    "success": True,
                    "phpsessid": f"{new_token[:8]}***",
                    "info": f"🎉 纯 HTTP 自动续登成功！最新 PHPSESSID: {new_token[:8]}*** 已生效并持久化。"
                })
            else:
                self._send_json(200, {
                    "success": False,
                    "info": "❌ checkLogin 纯 HTTP 续登未成功，可能长效 Token 已过期，请尝试微信小程序嗅探兜底。"
                })
        except Exception as e:
            logger.error("HTTP 自动续登异常: %s", type(e).__name__)
            self._send_json(500, {"success": False, "info": "服务器内部错误"})

    def do_POST(self):
        if self._reject_foreign_request():
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._send_json(415, {"success": False, "info": "仅接受 JSON 请求"})
            return
        parsed = urlparse(self.path)
        try:
            content_len = int(self.headers.get("Content-Length", "0"))
            if content_len < 0 or content_len > 65536:
                self._send_json(413, {"success": False, "info": "请求内容过大"})
                return
            body_json = json.loads(self.rfile.read(content_len)) if content_len else {}
            if not isinstance(body_json, dict):
                raise ValueError("JSON object required")
        except (ValueError, UnicodeDecodeError, TimeoutError):
            self._send_json(400, {"success": False, "info": "请求 JSON 格式无效"})
            return
        params = {k: [v] for k, v in body_json.items()}

        # 0. 授权激活专属 API (免拦截)
        if parsed.path.startswith("/api/license/activate"):
            key_data = body_json.get("license_key") or body_json.get("code")
            ok, msg = activate_license(key_data)
            self._send_json(200, {
                "success": ok,
                "info": msg,
                "status": get_auth_status()
            })
            return

        if parsed.path == "/api/qr":
            self._handle_qr_init()
            return
        if parsed.path in ("/api/qr_status", "/api/qr/status"):
            self._handle_qr_status()
            return

        # 针对打包客户端发布版的业务 API 强控守卫拦截 (开发模式自动放行)
        auth_res = check_license()
        if not auth_res.is_licensed:
            self._send_json(403, {
                "success": False,
                "error": "LICENSE_REQUIRED",
                "info": f"当前软件未激活或授权已到期！请先在界面完成激活。本机机器码: {auth_res.hwid}",
                "hwid": auth_res.hwid
            })
            return

        if parsed.path.startswith("/api/book"):
            self._handle_book(params)
        elif parsed.path.startswith("/api/relogin"):
            self._handle_relogin()
        elif parsed.path.startswith("/api/pw_login"):
            self._handle_pw_login(body_json)
        elif parsed.path.startswith("/api/set_token"):
            self._handle_set_token(params)
        elif parsed.path.startswith("/api/scheduler/start"):
            self._handle_scheduler_start(body_json, params)
        elif parsed.path.startswith("/api/scheduler/stop"):
            self._handle_scheduler_stop()
        elif parsed.path.startswith("/api/scheduler/config"):
            self._handle_scheduler_config_save(body_json, params)
        elif parsed.path.startswith("/api/snipe/start"):
            self._handle_snipe_start(body_json, params)
        elif parsed.path.startswith("/api/snipe/stop"):
            self._handle_snipe_stop()
        elif parsed.path.startswith("/api/campus/switch"):
            self._handle_campus_switch(body_json, params)
        elif parsed.path.startswith("/api/notify/config"):
            self._handle_notify_config_post(body_json, params)
        elif parsed.path.startswith("/api/notify/test"):
            self._handle_notify_test(body_json, params)
        elif parsed.path.startswith("/api/orders/my") or parsed.path.startswith("/api/my_orders"):
            self._handle_my_orders()
        elif parsed.path == "/api/harvest":
            self._handle_harvest()
        else:
            self._send_json(404, {"error": "Not Found"})

    def _handle_pw_login(self, body: dict):
        """统一身份认证账号密码登录；remember=true 时保存账号密码供失效后自动重新登录"""
        username = body.get("username")
        password = body.get("password")
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 128 or len(password) > 256:
            self._send_json(400, {"success": False, "error": "账号或密码格式无效"})
            return
        username = username.strip()
        if not username or not password:
            self._send_json(400, {"success": False, "error": "请填写账号和密码"})
            return
        try:
            res = CasQrLoginClient().password_login(username, password)
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            if res.get("phpsessid"):
                save_phpsessid(c_path, res["phpsessid"])
            if res.get("auth_params"):
                save_auth_params(c_path, res["auth_params"])
            if body.get("remember"):
                save_cas_credentials(c_path, username, password)
            logger.info(f"💾 账号密码登录凭据已持久化回写至配置文件: {c_path}")
            self._send_json(200, {"success": True, "logged_in": True})
        except Exception as e:
            logger.error("账号密码登录失败: %s", type(e).__name__)
            message = "用户名或者密码有误" if "用户名或者密码有误" in str(e) else "登录失败，请检查账号、验证码或网络后重试"
            self._send_json(200, {"success": False, "logged_in": False, "error": message})

    def _handle_harvest(self):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            cfg = load_config(c_path)
            token = HarvestService(cfg, config_path=c_path).harvest(timeout=60.0)
            self._send_json(200, {"success": bool(token), "info": "凭证已成功获取并更新" if token else "未能成功从微信小程序获取凭证"})
        except Exception as e:
            logger.error("微信嗅探异常: %s", type(e).__name__)
            self._send_json(500, {"success": False, "info": "服务器内部错误"})

    def _handle_scheduler_config_save(self, body_json: dict, params: dict):
        try:
            if _scheduler_manager._thread and _scheduler_manager._thread.is_alive():
                self._send_json(409, {"success": False, "info": "请先停止正在运行的定时任务，再修改计划并重新开启"})
                return
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            target = body_json.get("target") or {}
            scheduler = body_json.get("scheduler") or {}
            if not isinstance(target, dict) or not isinstance(scheduler, dict):
                raise ValueError("目标与定时配置必须是映射")

            # 也支持扁平参数传入
            target_keys = ["stadium_id", "venue_id", "stadium_name", "area_name", "area_id", "preferred_time", "target_date_offset", "user_range"]
            for k in target_keys:
                if k in params and k not in target:
                    val = params[k][0]
                    if k in ("stadium_id", "venue_id", "area_id", "target_date_offset"):
                        try:
                            val = int(val)
                        except Exception:
                            pass
                    target[k] = val

            sched_keys = ["target_time", "fallback_nearest", "pre_check_minutes"]
            for k in sched_keys:
                if k in params and k not in scheduler:
                    val = params[k][0]
                    if k == "fallback_nearest":
                        val = (val is True or val == "true" or val == "1")
                    elif k == "pre_check_minutes":
                        try:
                            val = int(val)
                        except Exception:
                            pass
                    scheduler[k] = val

            if isinstance(scheduler.get("date_overrides"), dict):
                today = datetime.now().date().isoformat()  # 已过期的特例日期自动清理
                scheduler["date_overrides"] = {d: t for d, t in scheduler["date_overrides"].items() if str(d) >= today}

            save_target_and_scheduler_config(c_path, target_updates=target, scheduler_updates=scheduler)
            self._send_json(200, {"success": True, "info": "定时预约配置已保存成功！"})
        except ValueError as e:
            self._send_json(400, {"success": False, "info": str(e)})
        except Exception as e:
            logger.error(f"保存定时配置异常: {e}", exc_info=True)
            self._send_json(500, {"success": False, "info": str(e)})

    def _handle_scheduler_start(self, body_json: dict, params: dict):
        try:
            if _scheduler_manager._thread and _scheduler_manager._thread.is_alive():
                self._send_json(409, {"success": False, "info": "定时任务仍在运行或停止中，请等待结束后再开启"})
                return
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            target = body_json.get("target")
            scheduler = body_json.get("scheduler")
            if target or scheduler:
                save_target_and_scheduler_config(c_path, target_updates=target, scheduler_updates=scheduler)

            res = _scheduler_manager.start(c_path)
            self._send_json(200, res)
        except ValueError as e:
            self._send_json(400, {"success": False, "info": str(e)})
        except Exception as e:
            logger.error(f"启动定时任务异常: {e}", exc_info=True)
            self._send_json(500, {"success": False, "info": str(e)})

    def _handle_scheduler_stop(self):
        try:
            res = _scheduler_manager.stop()
            self._send_json(200, res)
        except Exception as e:
            logger.error(f"停止定时任务异常: {e}", exc_info=True)
            self._send_json(500, {"success": False, "info": str(e)})

    def _handle_scheduler_config_get(self):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            cfg = load_config(c_path)
            self._send_json(200, {
                "success": True,
                "target": {
                    "stadium_name": cfg.target.stadium_name,
                    "stadium_id": cfg.target.stadium_id,
                    "venue_id": cfg.target.venue_id,
                    "area_name": cfg.target.area_name,
                    "area_id": cfg.target.area_id,
                    "user_range": cfg.target.user_range,
                    "preferred_time": cfg.target.preferred_time,
                    "target_date_offset": cfg.target.target_date_offset
                },
                "scheduler": {
                    "target_time": cfg.scheduler.target_time,
                    "fallback_nearest": cfg.scheduler.fallback_nearest,
                    "pre_check_minutes": cfg.scheduler.pre_check_minutes,
                    "weekly_enabled": cfg.scheduler.weekly_enabled,
                    "weekly_plan": cfg.scheduler.weekly_plan,
                    "date_overrides": cfg.scheduler.date_overrides
                }
            })
        except Exception as e:
            logger.error(f"获取定时配置异常: {e}", exc_info=True)
            self._send_json(500, {"success": False, "info": str(e)})
        except Exception as e:
            logger.error(f"获取定时配置异常: {e}", exc_info=True)
            self._send_json(500, {"success": False, "info": str(e)})

    def _handle_scheduler_status(self):
        try:
            status = _scheduler_manager.get_status()
            self._send_json(200, {"success": True, **status})
        except Exception as e:
            logger.error(f"获取定时任务状态异常: {e}", exc_info=True)
            self._send_json(500, {"success": False, "info": str(e)})

    def _handle_snipe_status(self):
        try:
            status = _snipe_manager.get_status()
            self._send_json(200, {"success": True, **status})
        except Exception as e:
            logger.error(f"获取捡漏任务状态异常: {e}", exc_info=True)
            self._send_json(500, {"success": False, "info": str(e)})

    def _handle_snipe_start(self, body_json: dict, params: dict):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            target_date = body_json.get("target_date") or (params.get("target_date", [None])[0] if params.get("target_date") else None)
            preferred_time = body_json.get("preferred_time") or (params.get("preferred_time", [None])[0] if params.get("preferred_time") else None)
            poll_interval = float(body_json.get("poll_interval") or (params.get("poll_interval", [2.0])[0] if params.get("poll_interval") else 2.0))
            fallback_nearest = body_json.get("fallback_nearest", False)
            if target_date:
                datetime.strptime(target_date, "%Y-%m-%d")
            if preferred_time:
                from xdty_booking.config import SchedulerConfig
                SchedulerConfig._check_slot(preferred_time)
            if not math.isfinite(poll_interval) or not 1.0 <= poll_interval <= 60.0:
                raise ValueError("捡漏轮询间隔须在 1 到 60 秒之间")
            if not isinstance(fallback_nearest, bool):
                raise ValueError("就近降级参数必须是布尔值")

            res = _snipe_manager.start(
                config_path=c_path,
                target_date=target_date,
                preferred_time=preferred_time,
                poll_interval=poll_interval,
                fallback_nearest=fallback_nearest
            )
            self._send_json(200, res)
        except (TypeError, ValueError) as e:
            self._send_json(400, {"success": False, "info": str(e)})
        except Exception as e:
            logger.error("启动捡漏监听异常: %s", type(e).__name__)
            self._send_json(500, {"success": False, "info": "服务器内部错误"})

    def _handle_snipe_stop(self):
        try:
            res = _snipe_manager.stop()
            self._send_json(200, res)
        except Exception as e:
            logger.error("停止捡漏监听异常: %s", type(e).__name__)
            self._send_json(500, {"success": False, "info": "服务器内部错误"})

    def _handle_campus_switch(self, body_json: dict, params: dict):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            campus = body_json.get("campus") or (params.get("campus", [None])[0] if params.get("campus") else None)
            if not campus:
                stadium_id = body_json.get("stadium_id") or (params.get("stadium_id", [None])[0] if params.get("stadium_id") else None)
                campus = "siming" if str(stadium_id) == "6" else "xiangan" if str(stadium_id) == "16" else None
            if not isinstance(campus, str) or campus.lower() not in ("siming", "6", "思明", "xiangan", "16", "翔安"):
                raise ValueError("请选择有效校区")

            if str(campus).lower() in ("siming", "6", "思明"):
                target_updates = {
                    "stadium_id": 6,
                    "stadium_name": "思明校区健身房",
                    "area_name": "思明校区健身房",
                    "venue_id": 6,
                    "area_id": 0,
                    "user_range": "[]"
                }
                campus_name = "思明校区健身房"
            else:
                target_updates = {
                    "stadium_id": 16,
                    "stadium_name": "翔安校区健身房",
                    "area_name": "爱秋体育馆健身房",
                    "venue_id": 14,
                    "area_id": 67,
                    "user_range": "[67]"
                }
                campus_name = "翔安校区健身房"

            save_target_and_scheduler_config(c_path, target_updates=target_updates)
            self._send_json(200, {
                "success": True,
                "campus": "siming" if target_updates["stadium_id"] == 6 else "xiangan",
                "target": target_updates,
                "info": f"已成功切换至{campus_name}！"
            })
        except ValueError as e:
            self._send_json(400, {"success": False, "info": str(e)})
        except Exception as e:
            logger.error("切换校区异常: %s", type(e).__name__)
            self._send_json(500, {"success": False, "info": "服务器内部错误"})

    def _handle_notify_config_get(self):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            cfg = load_config(c_path)
            to_email = cfg.notify.email.to_addrs[0] if cfg.notify.email.to_addrs else ""
            self._send_json(200, {
                "status": "ok",
                "success": True,
                "enabled": cfg.notify.enabled,
                "channel": cfg.notify.channel,
                "email": to_email
            })
        except Exception as e:
            logger.error(f"获取通知配置异常: {e}", exc_info=True)
            self._send_json(200, {
                "status": "error",
                "success": False,
                "enabled": False,
                "channel": "email",
                "email": "",
                "info": str(e)
            })

    def _handle_notify_config_post(self, body_json: Optional[dict] = None, params: Optional[dict] = None):
        try:
            body_json = body_json or {}
            params = params or {}
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            enabled = body_json.get("enabled")
            if enabled is None and "enabled" in params:
                enabled = str(params["enabled"][0]).lower() in ("true", "1", "yes")

            email = body_json.get("email")
            if email is None and "email" in params:
                email = params["email"][0]

            channel = body_json.get("channel")
            if channel is None and "channel" in params:
                channel = params["channel"][0]
            if channel is None and email:
                channel = "email"

            save_notify_config(c_path, enabled=enabled, email=email, channel=channel)
            cfg = load_config(c_path)
            to_email = cfg.notify.email.to_addrs[0] if cfg.notify.email.to_addrs else ""
            self._send_json(200, {
                "status": "ok",
                "success": True,
                "enabled": cfg.notify.enabled,
                "channel": cfg.notify.channel,
                "email": to_email,
                "info": "通知设置已成功保存！"
            })
        except Exception as e:
            logger.error(f"保存通知配置异常: {e}", exc_info=True)
            self._send_json(500, {"status": "error", "success": False, "info": str(e), "message": str(e)})

    def _handle_notify_test(self, body_json: Optional[dict] = None, params: Optional[dict] = None):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            cfg = load_config(c_path)

            temp_email = None
            if body_json and body_json.get("email"):
                temp_email = str(body_json["email"]).strip()
            elif params and params.get("email"):
                temp_email = str(params["email"][0]).strip()

            if temp_email:
                cfg.notify.email.to_addrs = [temp_email]
                cfg.notify.channel = "email"
                cfg.notify.enabled = True

            if not cfg.notify.email.to_addrs:
                self._send_json(400, {
                    "status": "error",
                    "success": False,
                    "info": "请先输入接收通知的 QQ 邮箱地址！",
                    "message": "请先输入接收通知的 QQ 邮箱地址！"
                })
                return

            if not cfg.notify.email.sender:
                from xdty_booking.config import (
                    DEFAULT_DEVELOPER_EMAIL_SENDER,
                    DEFAULT_DEVELOPER_EMAIL_AUTH,
                    DEFAULT_DEVELOPER_SMTP_HOST,
                    DEFAULT_DEVELOPER_SMTP_PORT,
                    DEFAULT_DEVELOPER_SMTP_SSL
                )
                cfg.notify.email.sender = DEFAULT_DEVELOPER_EMAIL_SENDER
                cfg.notify.email.password = DEFAULT_DEVELOPER_EMAIL_AUTH
                cfg.notify.email.smtp_host = DEFAULT_DEVELOPER_SMTP_HOST
                cfg.notify.email.smtp_port = DEFAULT_DEVELOPER_SMTP_PORT
                cfg.notify.email.ssl = DEFAULT_DEVELOPER_SMTP_SSL

            cfg.notify.enabled = True
            notifier = Notifier(cfg.notify)
            results = notifier.send_test()
            ok = results.get("email", False) or results.get("pushplus", False) or any(results.values())
            if ok:
                self._send_json(200, {
                    "status": "ok",
                    "success": True,
                    "info": f"🎉 测试通知已成功投递至 {cfg.notify.email.to_addrs[0]}！请检查邮箱收信及手机微信【QQ邮箱提醒】大卡片。"
                })
            else:
                self._send_json(500, {
                    "status": "error",
                    "success": False,
                    "info": "❌ 发送测试通知失败，请检查网络或确认邮箱地址是否正确。",
                    "message": "❌ 发送测试通知失败，请检查网络或确认邮箱地址是否正确。"
                })
        except Exception as e:
            logger.error(f"发送测试通知异常: {e}", exc_info=True)
            self._send_json(500, {"status": "error", "success": False, "info": f"测试发送异常: {e}", "message": str(e)})

    def _handle_my_orders(self):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            cfg = load_config(c_path)
            client = ApiClient(base_url=cfg.base_url)
            if cfg.auth.phpsessid:
                client.set_session_token(cfg.auth.phpsessid)
            api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)
            session_mgr = SessionManager(
                api,
                phpsessid=cfg.auth.phpsessid,
                auth_params=cfg.auth.auth_params,
                config_path=c_path
            )
            is_valid = ensure_session(cfg, session_mgr, client, c_path)
            if not is_valid:
                self._send_json(200, {
                    "status": "error",
                    "success": False,
                    "info": "当前登录凭证已失效，请先登录后再查看我的预约！",
                    "orders": [],
                    "session_valid": False
                })
                return

            sub_res = api.my_subscribe(page=1)
            raw_orders = sub_res.get("data", []) if isinstance(sub_res, dict) else []
            if not isinstance(raw_orders, list):
                raw_orders = []

            orders = []
            for item in raw_orders:
                order = dict(item)
                # 若为有效预约(audit_status == 1)，自动查询订单详情获取时段
                if order.get("audit_status") == 1 and order.get("order_id"):
                    try:
                        detail_res = api.order_details(order["order_id"], order.get("order_num", ""))
                        if isinstance(detail_res, dict) and detail_res.get("status") == 1:
                            d_data = detail_res.get("data", {})
                            if isinstance(d_data, dict):
                                details_list = d_data.get("details", [])
                                if details_list and isinstance(details_list, list):
                                    f_det = details_list[0]
                                    order["date"] = f_det.get("date", "")
                                    order["week"] = f_det.get("week", "")
                                    order["interval_time"] = f_det.get("interval_time", "")
                                    order["area_name"] = f_det.get("area_name", "")
                                if d_data.get("venue_name"):
                                    order["venue_name"] = d_data.get("venue_name")
                                if d_data.get("name"):
                                    order["user_name"] = d_data.get("name")
                    except Exception as det_err:
                        logger.warning(f"获取订单 {order.get('order_id')} 详情异常: {det_err}")

                orders.append(order)

            active_orders = [o for o in orders if o.get("audit_status") == 1]
            self._send_json(200, {
                "status": "ok",
                "success": True,
                "orders": orders,
                "active_count": len(active_orders),
                "session_valid": True,
                "info": f"查询成功，共拉取到 {len(orders)} 条记录（其中有效预约 {len(active_orders)} 场）"
            })
        except Exception as e:
            logger.error(f"查询我的预约异常: {e}", exc_info=True)
            self._send_json(200, {
                "status": "error",
                "success": False,
                "info": f"查询我的预约异常: {e}",
                "orders": []
            })

    def _handle_qr_init(self):
        global _cas_client, _qr_login_result, _is_logging_in, _has_login_failed
        with _state_lock:
            try:
                _cas_client = CasQrLoginClient()
                _qr_login_result = None
                _is_logging_in = False
                _has_login_failed = False
                uuid, _ = _cas_client.init_qr_session()
                b64_img = _cas_client.get_qr_image_base64()
                data = {
                    "success": True,
                    "uuid": uuid,
                    "qr_image": b64_img
                }
            except Exception as e:
                logger.error(f"初始化二维码失败: {e}", exc_info=True)
                data = {"success": False, "error": str(e)}
        self._send_json(200, data)

    def _handle_qr_status(self):
        global _cas_client, _qr_login_result, _is_logging_in, _has_login_failed
        with _state_lock:
            if _qr_login_result:
                data = {
                    "code": "1",
                    "desc": "登录成功！",
                    "logged_in": True,
                    "data": _qr_login_result
                }
            elif _has_login_failed:
                data = {
                    "code": "error",
                    "desc": "凭证置换异常，请点击刷新重新扫码",
                    "logged_in": False,
                    "data": None
                }
            elif _cas_client is None:
                data = {
                    "code": "-1",
                    "desc": "会话尚未初始化，请刷新",
                    "logged_in": False,
                    "data": None
                }
            else:
                code, desc = _cas_client.check_status()
                logged_in = False

                # 只有手机端点击了【确认登录】(code == "1") 时，才触发后台表单提交与凭据换发！
                if code == "1" and not _is_logging_in:
                    _is_logging_in = True
                    logger.info("🎯 检测到手机端扫码确认授权完成 (code=1)，开始触发 CAS 票据提交与 Token 置换...")
                    try:
                        res = _cas_client.exchange_and_login()
                        _qr_login_result = res
                        logged_in = True

                        c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
                        phpsessid = res.get("phpsessid")
                        auth_params = res.get("auth_params", {})

                        if phpsessid:
                            save_phpsessid(c_path, phpsessid)
                        if auth_params:
                            save_auth_params(c_path, auth_params)
                        logger.info(f"💾 凭据已成功自动持久化回写至配置文件: {c_path}")
                    except Exception as e:
                        logger.error(f"换发登录凭据异常: {e}", exc_info=True)
                        _qr_login_result = None
                        _has_login_failed = True
                        desc = f"凭据换发异常: {e}"

                data = {
                    "code": code,
                    "desc": desc,
                    "logged_in": logged_in,
                    "data": _qr_login_result
                }
        self._send_json(200, data)

    def _handle_login_page(self):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            cfg = load_config(c_path)
            client = ApiClient(base_url=cfg.base_url)
            if cfg.auth.phpsessid:
                client.set_session_token(cfg.auth.phpsessid)
            api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)
            mgr = SessionManager(
                api,
                phpsessid=cfg.auth.phpsessid,
                auth_params=cfg.auth.auth_params,
                config_path=c_path
            )
            alive = mgr.check_alive() if cfg.auth.phpsessid else False
            masked = f"{cfg.auth.phpsessid[:8]}***" if cfg.auth.phpsessid else ""
            html = render_qr_login_page(is_already_logged_in=alive, phpsessid_masked=masked)
            self._send_html(200, html)
        except Exception as e:
            logger.error(f"渲染登录页面异常: {e}")
            self._send_html(200, render_qr_login_page(is_already_logged_in=False, phpsessid_masked=""))

    def do_GET(self):
        if self._reject_foreign_request():
            return
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/api/book", "/api/relogin", "/api/set_token", "/api/harvest", "/api/campus/switch", "/api/qr", "/api/qr_status", "/api/qr/status", "/api/pw_login"):
            self._send_json(405, {"success": False, "info": "请使用 POST"})
            return

        # 0. 授权状态查询专属 API
        if path.startswith("/api/license/status"):
            self._send_json(200, get_auth_status())
            return

        # 企业微信扫码登录页面
        if path in ("/login", "/login.html", "/qr_login"):
            self._handle_login_page()

        # 查询余量 JSON API
        elif path.startswith("/api/status") or path.startswith("/status.json") or path in ("/api/gym/status", "/api/gym"):
            try:
                data = query_gym_status(_GLOBAL_CONFIG_PATH)
                self._send_json(200, data)
            except Exception as e:
                logger.error("查询状态异常: %s", type(e).__name__)
                self._send_json(500, {"error": "服务器内部错误"})

        # 登录态探测 API
        elif path.startswith("/api/check"):
            try:
                c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
                cfg = load_config(c_path)
                client = ApiClient(base_url=cfg.base_url)
                if cfg.auth.phpsessid:
                    client.set_session_token(cfg.auth.phpsessid)
                api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)
                mgr = SessionManager(
                    api,
                    phpsessid=cfg.auth.phpsessid,
                    auth_params=cfg.auth.auth_params,
                    config_path=c_path
                )
                alive = mgr.check_alive()
                has_auth = bool(getattr(cfg.auth, "auth_params", None) and cfg.auth.auth_params.get("token"))
                self._send_json(200, {
                    "alive": alive,
                    "phpsessid": f"{cfg.auth.phpsessid[:8]}***" if cfg.auth.phpsessid else "",
                    "has_auth_params": has_auth
                })
            except Exception as e:
                logger.error("登录态探测异常: %s", type(e).__name__)
                self._send_json(500, {"error": "服务器内部错误"})

        # 定时预约守护任务状态与配置 API
        elif path.startswith("/api/scheduler/status"):
            self._handle_scheduler_status()
        elif path.startswith("/api/scheduler/config"):
            self._handle_scheduler_config_get()

        # 捡漏监听任务状态 API
        elif path.startswith("/api/snipe/status"):
            self._handle_snipe_status()

        # 获取通知设置 API
        elif path.startswith("/api/notify/config"):
            self._handle_notify_config_get()

        # 查看我的预约记录 API
        elif path.startswith("/api/orders/my") or path.startswith("/api/my_orders"):
            self._handle_my_orders()

        # Web 仪表板首页 (体育馆场次查询与预约大厅)
        elif path in ("/", "/index.html", "/dashboard", "/gym"):
            try:
                data = query_gym_status(_GLOBAL_CONFIG_PATH)
                html = render_dashboard(data)
                self._send_html(200, html)
            except Exception as e:
                logger.error("加载页面异常: %s", type(e).__name__)
                has_auth = False
                try:
                    c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
                    c = load_config(c_path)
                    has_auth = bool(getattr(c.auth, "auth_params", None) and c.auth.auth_params.get("token"))
                except Exception:
                    pass
                fallback_data = {
                    "stadium_name": "厦大体育馆",
                    "area_name": "",
                    "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "session_valid": False,
                    "has_auth_params": has_auth,
                    "info": "系统连接或数据解析异常",
                    "groups": [],
                    "notify_config": {
                        "enabled": False,
                        "channel": "email",
                        "email": ""
                    }
                }
                self._send_html(200, render_dashboard(fallback_data))
        else:
            self._send_json(404, {"error": "Not Found"})

def start_login_monitor(config_path: str) -> Optional[SessionManager]:
    """
    后台登录状态监控：按 auth.heartbeat_interval_seconds 周期探活，失效时自动自愈并通知。
    周期 <= 0 时关闭。凭据每轮从配置文件重新读取，因此网页登录 / 调度器重登后无需重启。
    """
    try:
        c_path = _ensure_config_path(config_path)
        cfg = load_config(c_path)
    except Exception as e:
        logger.warning(f"登录状态监控未启动（读取配置失败）: {e}")
        return None
    interval = int(cfg.auth.heartbeat_interval_seconds or 0)
    if interval <= 0:
        logger.info("登录状态监控已关闭 (auth.heartbeat_interval_seconds <= 0)")
        return None
    client = ApiClient(base_url=cfg.base_url)
    if cfg.auth.phpsessid:
        client.set_session_token(cfg.auth.phpsessid)
    api = XdtyApi(client, uid=cfg.auth.uid or None)
    mgr = SessionManager(api, phpsessid=cfg.auth.phpsessid, auth_params=cfg.auth.auth_params, config_path=c_path)
    mgr.start_heartbeat_daemon(interval_seconds=interval, notifier=Notifier(cfg.notify))
    logger.info(f"🩺 登录状态监控已启动，每 {interval} 秒探活一次，失效将自动重登并通知")
    return mgr


def run_server(port: int = 8080, config_path: str = "config/config.yaml", host: str = "127.0.0.1"):
    global _GLOBAL_CONFIG_PATH
    _GLOBAL_CONFIG_PATH = config_path

    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Web 控制台只允许监听本机回环地址；远程访问请使用 SSH 隧道")

    try:
        server = ThreadingHTTPServer((host, port), GymStatusHandler)
    except OSError as e:
        logger.warning(f"本地 Web 服务端口 {port} 已被占用，服务已处于运行中: {e}")
        print(f"\n⚠️ 本地 Web 服务端口 {port} 已被占用，服务已在运行中。\n")
        return

    logger.info(f"🚀 健身房实时监控与预约 Web 服务已启动: http://{host}:{port}")
    logger.info(f"👉 网页一键预约与监控大厅: http://{host}:{port}/")
    logger.info(f"👉 企业微信扫码登录直达: http://{host}:{port}/login")
    logger.info(f"👉 实时 JSON API: http://{host}:{port}/api/status")
    logger.info(f"👉 凭证自愈 API: http://{host}:{port}/api/harvest")
    print(f"\n服务启动成功！浏览器访问: http://{host}:{port} (扫码登录: http://{host}:{port}/login)\n")
    start_login_monitor(config_path)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("已停止 Web 服务。")
        server.server_close()
