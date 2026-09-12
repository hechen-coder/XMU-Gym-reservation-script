import os
import json
import logging
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any

from xdty_booking.config import load_config, save_phpsessid
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.auth.session_manager import SessionManager
from xdty_booking.auth.harvester_service import HarvestService
from xdty_booking.solver.captcha_solver import CaptchaSolver
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.notify.notifier import Notifier
from xdty_booking.web.template import render_dashboard
from xdty_booking.utils.logger import setup_logger

logger = setup_logger("xdty_web")

_GLOBAL_CONFIG_PATH = "config/config.yaml"

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
    if cfg.auth.phpsessid and session_mgr.check_alive():
        return True

    logger.warning("检测到 Session 无效或已过期，启动双阶自愈策略...")
    new_token = session_mgr.renew_or_fallback()
    if new_token:
        client.set_session_token(new_token)
        cfg.auth.phpsessid = new_token
        logger.info("Session 自愈成功！")
        return True
    return False

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

    if auto_heal:
        ensure_session(cfg, session_mgr, client, c_path)

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
                # 若初次查询提示登录失效且开启了 auto_heal，立即通过 checkLogin 紧急自愈并重试查询
                if auto_heal and ensure_session(cfg, session_mgr, client, c_path):
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
        "groups": []
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
                    "status": s.status
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

        if parsed.path.startswith("/api/book"):
            self._handle_book(params)
        elif parsed.path.startswith("/api/relogin"):
            self._handle_relogin()
        elif parsed.path.startswith("/api/set_token"):
            self._handle_set_token(params)
        else:
            self._send_json(404, {"error": "Not Found"})

    def do_GET(self):
        parsed = urlparse(self.path)
        
        # 1. 一键预约 API
        if parsed.path.startswith("/api/book"):
            params = parse_qs(parsed.query)
            self._handle_book(params)

        # 2. 纯 HTTP 自动续登 API
        elif parsed.path.startswith("/api/relogin"):
            self._handle_relogin()

        # 3. 查询余量 JSON API
        elif parsed.path.startswith("/api/status") or parsed.path.startswith("/status.json"):
            try:
                data = query_gym_status(_GLOBAL_CONFIG_PATH)
                self._send_json(200, data)
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        # 4. 登录态探测 API
        elif parsed.path.startswith("/api/check"):
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

        # 5. 手动设置/保存 PHPSESSID
        elif parsed.path.startswith("/api/set_token"):
            params = parse_qs(parsed.query)
            self._handle_set_token(params)

        # 6. 手动触发微信自愈嗅探 API
        elif parsed.path.startswith("/api/harvest"):
            try:
                c_path = _ensure_config_path(_GLOBAL_CONFIG_PATH)
                cfg = load_config(c_path)
                service = HarvestService(cfg, config_path=c_path)
                token = service.harvest(timeout=60.0)
                if token:
                    self._send_json(200, {"success": True, "token": token, "info": "凭证自动截获并更新成功"})
                else:
                    self._send_json(200, {"success": False, "info": "未能成功从微信小程序截获凭证"})
            except Exception as e:
                self._send_json(500, {"success": False, "info": str(e)})

        # 5. Web 仪表板首页
        else:
            try:
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
    logger.info(f"👉 网页一键预约与监控: http://localhost:{port}/")
    logger.info(f"👉 实时 JSON API: http://localhost:{port}/api/status")
    logger.info(f"👉 凭证自愈 API: http://localhost:{port}/api/harvest")
    print(f"\n服务启动成功！浏览器访问: http://localhost:{port} (按 Ctrl+C 退出)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("已停止 Web 服务。")
        server.server_close()
