import os
import json
import logging
import threading
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any

from xdty_booking.config import (
    load_config,
    save_phpsessid,
    save_auth_params,
    save_target_and_scheduler_config
)
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.auth.session_manager import SessionManager
from xdty_booking.auth.harvester_service import HarvestService
from xdty_booking.solver.captcha_solver import CaptchaSolver
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.core.scheduler import BookingScheduler
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
                import shutil
                try:
                    shutil.copy(example_path, path)
                    logger.info(f"💡 首次运行检测：已自动为您生成配置文件 '{path}'")
                    return path
                except Exception:
                    return example_path
            return example_path
    return path

def ensure_session(cfg, session_mgr, client, config_path: str, timeout: float = 30.0) -> bool:
    """Session 有效性预检与双阶自动自愈核心工具"""
    has_token = bool(getattr(cfg.auth, "auth_params", None) and cfg.auth.auth_params.get("token"))
    has_php = bool(cfg.auth.phpsessid)

    # 若没有任何凭据（未登录状态），无需启动自愈，直接返回 False
    if not has_php and not has_token:
        return False

    if has_php and session_mgr.check_alive():
        return True

    logger.warning("检测到 Session 无效或已过期，启动双阶自愈策略...")
    new_token = session_mgr.renew_or_fallback()
    if new_token:
        client.set_session_token(new_token)
        cfg.auth.phpsessid = new_token
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

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            if self._is_running and self._thread and not self._thread.is_alive():
                self._is_running = False
                if not self._last_result and self._status_text.startswith("正在启动"):
                    self._status_text = "定时任务已结束"
            return {
                "running": self._is_running,
                "status_text": self._status_text,
                "target_time": self._target_time,
                "next_run_dt": self._next_run_dt,
                "stadium_name": self._stadium_name,
                "preferred_time": self._preferred_time,
                "last_result": self._last_result
            }

    def start(self, config_path: str = _GLOBAL_CONFIG_PATH) -> Dict[str, Any]:
        with self._lock:
            if self._is_running and self._thread and self._thread.is_alive():
                return {"success": False, "info": "定时任务已在运行中，请勿重复启动"}

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

            now = datetime.now()
            target_hour, target_minute, target_second = map(int, self._target_time.split(":"))
            target_dt = now.replace(hour=target_hour, minute=target_minute, second=target_second, microsecond=0)
            if target_dt <= now:
                target_dt += timedelta(days=1)
            self._next_run_dt = target_dt.strftime("%Y-%m-%d %H:%M:%S")

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
            "pre_check_minutes": cfg.scheduler.pre_check_minutes
        }
    }

    if intervals and hasattr(intervals, "time_slot_list"):
        data["date_list"] = [{"date": d.date, "week": d.week} for d in getattr(intervals, "date_list", [])]
        for g in intervals.time_slot_list:
            group_data = {
                "date": g.date,
                "week_name": g.week_name,
                "time_range": g.time_range,
                "is_preferred": (g.time_range == cfg.target.preferred_time),
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

    def _send_json(self, status_code: int, data: Any):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        payload = json.dumps(data, ensure_ascii=False, default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o)).encode("utf-8")
        self.wfile.write(payload)

    def _send_html(self, status_code: int, html_str: str):
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html_str.encode("utf-8"))

    def _handle_book(self, params: Dict[str, Any]):
        interval_id = params.get("interval_id", [None])[0]
        date = params.get("date", [None])[0]
        time_slot = params.get("time", [None])[0]
        try:
            res = book_gym_slot(
                interval_id=interval_id,
                date=date,
                time_slot=time_slot,
                config_path=_GLOBAL_CONFIG_PATH,
                auto_heal=True
            )
            self._send_json(200, res)
        except Exception as e:
            logger.error(f"预约处理异常: {e}")
            self._send_json(500, {"success": False, "info": f"服务器内部错误: {e}"})

    def _handle_set_token(self, params: Dict[str, Any]):
        token = params.get("token", [None])[0]
        if not token or not str(token).strip():
            self._send_json(400, {"success": False, "info": "Token 不能为空"})
            return
        token = str(token).strip()
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            save_phpsessid(c_path, token)
            cfg = load_config(c_path)
            client = ApiClient(base_url=cfg.base_url)
            client.set_session_token(token)
            api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)
            mgr = SessionManager(api, phpsessid=token)
            alive = mgr.check_alive()
            self._send_json(200, {
                "success": True,
                "alive": alive,
                "phpsessid": f"{token[:8]}***",
                "info": "🎉 Token 保存成功且存活有效！" if alive else "⚠️ Token 已保存至配置文件，但在服务端校验未通过 (可能过期或复制有误)"
            })
        except Exception as e:
            logger.error(f"保存 Token 异常: {e}")
            self._send_json(500, {"success": False, "info": f"服务器内部错误: {e}"})

    def _handle_relogin(self):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            cfg = load_config(c_path)
            client = ApiClient(base_url=cfg.base_url)
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
                    "token": new_token,
                    "phpsessid": f"{new_token[:8]}***",
                    "info": f"🎉 纯 HTTP 自动续登成功！最新 PHPSESSID: {new_token[:8]}*** 已生效并持久化。"
                })
            else:
                self._send_json(200, {
                    "success": False,
                    "info": "❌ checkLogin 纯 HTTP 续登未成功，可能长效 Token 已过期，请尝试微信小程序嗅探兜底。"
                })
        except Exception as e:
            logger.error(f"HTTP 自动续登异常: {e}")
            self._send_json(500, {"success": False, "info": f"服务器内部错误: {e}"})

    def do_POST(self):
        parsed = urlparse(self.path)
        content_len = int(self.headers.get('Content-Length', 0))
        params = {}
        if content_len > 0:
            try:
                body = self.rfile.read(content_len).decode('utf-8')
                body_json = json.loads(body)
                for k, v in body_json.items():
                    params[k] = [v]
            except Exception:
                pass
        if not params:
            params = parse_qs(parsed.query)

        # 0. 授权激活专属 API (免拦截)
        if parsed.path.startswith("/api/license/activate"):
            key_data = (
                body_json.get("license_key")
                or body_json.get("code")
                or (params.get("license_key", [None])[0] if params.get("license_key") else None)
            )
            if not key_data and content_len > 0:
                try:
                    key_data = body
                except Exception:
                    pass
            ok, msg = activate_license(key_data)
            self._send_json(200, {
                "success": ok,
                "info": msg,
                "status": get_auth_status()
            })
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
        else:
            self._send_json(404, {"error": "Not Found"})

    def _handle_scheduler_config_save(self, body_json: dict, params: dict):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            target = body_json.get("target") or {}
            scheduler = body_json.get("scheduler") or {}

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

            save_target_and_scheduler_config(c_path, target_updates=target, scheduler_updates=scheduler)
            self._send_json(200, {"success": True, "info": "定时预约配置已保存成功！"})
        except Exception as e:
            logger.error(f"保存定时配置异常: {e}", exc_info=True)
            self._send_json(500, {"success": False, "info": str(e)})

    def _handle_scheduler_start(self, body_json: dict, params: dict):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            target = body_json.get("target")
            scheduler = body_json.get("scheduler")
            if target or scheduler:
                save_target_and_scheduler_config(c_path, target_updates=target, scheduler_updates=scheduler)

            res = _scheduler_manager.start(c_path)
            self._send_json(200, res)
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
                    "pre_check_minutes": cfg.scheduler.pre_check_minutes
                }
            })
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
            fallback_nearest = bool(body_json.get("fallback_nearest", False) or (params.get("fallback_nearest", [False])[0] if params.get("fallback_nearest") else False))

            res = _snipe_manager.start(
                config_path=c_path,
                target_date=target_date,
                preferred_time=preferred_time,
                poll_interval=poll_interval,
                fallback_nearest=fallback_nearest
            )
            self._send_json(200, res)
        except Exception as e:
            logger.error(f"启动捡漏监听异常: {e}", exc_info=True)
            self._send_json(500, {"success": False, "info": str(e)})

    def _handle_snipe_stop(self):
        try:
            res = _snipe_manager.stop()
            self._send_json(200, res)
        except Exception as e:
            logger.error(f"停止捡漏监听异常: {e}", exc_info=True)
            self._send_json(500, {"success": False, "info": str(e)})

    def _handle_campus_switch(self, body_json: dict, params: dict):
        try:
            c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
            campus = body_json.get("campus") or (params.get("campus", [None])[0] if params.get("campus") else None)
            if not campus:
                stadium_id = body_json.get("stadium_id") or (params.get("stadium_id", [None])[0] if params.get("stadium_id") else None)
                if stadium_id and str(stadium_id) == "6":
                    campus = "siming"
                else:
                    campus = "xiangan"

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
        except Exception as e:
            logger.error(f"切换校区异常: {e}", exc_info=True)
            self._send_json(500, {"success": False, "info": str(e)})

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
        parsed = urlparse(self.path)
        path = parsed.path

        # 0. 授权状态查询专属 API
        if path.startswith("/api/license/status"):
            self._send_json(200, get_auth_status())
            return

        # 针对会产生预约或续登行为的 GET API 进行客户端未激活拦截
        if any(path.startswith(prefix) for prefix in ("/api/book", "/api/relogin", "/api/harvest")):
            auth_res = check_license()
            if not auth_res.is_licensed:
                self._send_json(403, {
                    "success": False,
                    "error": "LICENSE_REQUIRED",
                    "info": f"当前软件未激活或授权已到期！请先在界面完成激活。本机机器码: {auth_res.hwid}",
                    "hwid": auth_res.hwid
                })
                return

        # 1. 一键预约 API
        if path.startswith("/api/book"):
            params = parse_qs(parsed.query)
            self._handle_book(params)

        # 2. 纯 HTTP 自动续登 API
        elif path.startswith("/api/relogin"):
            self._handle_relogin()

        # 3. 扫码登录：初始化获取二维码 API
        elif path.startswith("/api/qr") and not path.startswith("/api/qr_status") and not path.startswith("/api/qr/status"):
            self._handle_qr_init()

        # 4. 扫码登录：轮询认证状态 API
        elif path.startswith("/api/qr_status") or path.startswith("/api/qr/status"):
            self._handle_qr_status()

        # 5. 企业微信扫码登录页面
        elif path == "/login" or path == "/login.html" or path == "/qr_login":
            self._handle_login_page()

        # 6. 查询余量 JSON API
        elif path.startswith("/api/status") or path.startswith("/status.json"):
            try:
                data = query_gym_status(_GLOBAL_CONFIG_PATH)
                self._send_json(200, data)
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        # 7. 登录态探测 API
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
                self._send_json(500, {"error": str(e)})

        # 8. 手动设置/保存 PHPSESSID
        elif path.startswith("/api/set_token"):
            params = parse_qs(parsed.query)
            self._handle_set_token(params)

        # 9. 手动触发微信自愈嗅探 API
        elif path.startswith("/api/harvest"):
            try:
                c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
                cfg = load_config(c_path)
                service = HarvestService(cfg, config_path=c_path)
                token = service.harvest(timeout=60.0)
                if token:
                    self._send_json(200, {"success": True, "token": token, "info": "凭证已成功获取并更新"})
                else:
                    self._send_json(200, {"success": False, "info": "未能成功从微信小程序获取凭证"})
            except Exception as e:
                self._send_json(500, {"success": False, "info": str(e)})

        # 10. 定时预约守护任务状态与配置 API
        elif path.startswith("/api/scheduler/status"):
            self._handle_scheduler_status()
        elif path.startswith("/api/scheduler/config"):
            self._handle_scheduler_config_get()

        # 11. 捡漏监听任务状态 API
        elif path.startswith("/api/snipe/status"):
            self._handle_snipe_status()

        # 11.1 校区切换 GET API
        elif path.startswith("/api/campus/switch"):
            params = parse_qs(parsed.query)
            self._handle_campus_switch({}, params)

        # 12. Web 仪表板首页 (体育馆场次查询与预约大厅)
        else:
            try:
                # 支持通过 ?campus=siming 或 ?campus=xiangan 或 ?stadium_id=6 在 URL 直接访问并切换校区
                params = parse_qs(parsed.query)
                if "campus" in params or "stadium_id" in params:
                    c_val = params.get("campus", [""])[0]
                    s_val = params.get("stadium_id", [""])[0]
                    if c_val.lower() in ("siming", "6", "思明") or s_val == "6":
                        t_updates = {
                            "stadium_id": 6,
                            "stadium_name": "思明校区健身房",
                            "area_name": "思明校区健身房",
                            "venue_id": 6,
                            "area_id": 0,
                            "user_range": "[]"
                        }
                    else:
                        t_updates = {
                            "stadium_id": 16,
                            "stadium_name": "翔安校区健身房",
                            "area_name": "爱秋体育馆健身房",
                            "venue_id": 14,
                            "area_id": 67,
                            "user_range": "[67]"
                        }
                    save_target_and_scheduler_config(_GLOBAL_CONFIG_PATH, target_updates=t_updates)

                data = query_gym_status(_GLOBAL_CONFIG_PATH)
                html = render_dashboard(data)
                self._send_html(200, html)
            except Exception as e:
                logger.error(f"加载页面异常: {e}", exc_info=True)
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
                    "info": f"系统连接或数据解析异常: {e}",
                    "groups": []
                }
                self._send_html(200, render_dashboard(fallback_data))

def run_server(port: int = 8080, config_path: str = "config/config.yaml"):
    global _GLOBAL_CONFIG_PATH
    _GLOBAL_CONFIG_PATH = config_path

    server = HTTPServer(("0.0.0.0", port), GymStatusHandler)
    logger.info(f"🚀 健身房实时监控与预约 Web 服务已启动: http://localhost:{port}")
    logger.info(f"👉 网页一键预约与监控大厅: http://localhost:{port}/")
    logger.info(f"👉 企业微信扫码登录直达: http://localhost:{port}/login")
    logger.info(f"👉 实时 JSON API: http://localhost:{port}/api/status")
    logger.info(f"👉 凭证自愈 API: http://localhost:{port}/api/harvest")
    print(f"\n服务启动成功！浏览器访问: http://localhost:{port} (扫码登录: http://localhost:{port}/login)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("已停止 Web 服务。")
        server.server_close()
