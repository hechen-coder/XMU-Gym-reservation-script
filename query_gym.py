import os
import sys
import json
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import argparse

from xdty_booking.config import load_config
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.solver.captcha_solver import CaptchaSolver
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.utils.logger import setup_logger

logger = setup_logger("query_gym")

def book_gym_slot(interval_id=None, date=None, time_slot=None, config_path="config/config.yaml"):
    """执行立刻预约指定场次"""
    if not os.path.exists(config_path):
        config_path = "config/config.example.yaml"
    cfg = load_config(config_path)
    client = ApiClient(base_url=cfg.base_url)
    if cfg.auth.phpsessid:
        client.set_session_token(cfg.auth.phpsessid)
    api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)
    solver = CaptchaSolver()
    engine = BookingEngine(api, solver, cfg)
    return engine.execute_booking(target_date=date, preferred_time=time_slot, interval_id=interval_id)

def query_gym_status(config_path="config/config.yaml"):
    """执行 HTTP 请求查询健身房空闲状态数据"""
    if not os.path.exists(config_path):
        config_path = "config/config.example.yaml"
    cfg = load_config(config_path)
    client = ApiClient(base_url=cfg.base_url)
    if cfg.auth.phpsessid:
        client.set_session_token(cfg.auth.phpsessid)
    api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)

    intervals = api.get_intervals(
        venue_id=cfg.target.venue_id,
        stadium_id=cfg.target.stadium_id,
        category_id=cfg.target.category_id,
        user_range=cfg.target.user_range
    )

    data = {
        "stadium_name": cfg.target.stadium_name,
        "area_name": cfg.target.area_name,
        "preferred_time": cfg.target.preferred_time,
        "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date_list": [{"date": d.date, "week": d.week} for d in intervals.date_list],
        "groups": []
    }

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

def print_gym_status(data):
    """在终端格式化输出空闲状态"""
    print("\n" + "=" * 76)
    print(f"[场馆查询] {data['stadium_name']}（{data['area_name']}）实时空闲状态查询")
    print(f"[查询时间] {data['query_time']}")
    dates_str = ", ".join([f"{d['date']}({d['week']})" for d in data['date_list']])
    print(f"[开放日期] {dates_str}")
    print("=" * 76)

    current_date = None
    for g in data["groups"]:
        if g["date"] != current_date:
            current_date = g["date"]
            print(f"\n[日期] {g['date']} {g['week_name']}")
            print("-" * 76)

        for s in g["slots"]:
            if s["is_available"]:
                badge = "[空闲充足]" if s["remaining"] > 10 else "[剩余紧张]"
            else:
                badge = "[已经约满]"

            pref = " *【目标时段】" if g["is_preferred"] else ""
            status_text = f"时段: {g['time_range']:<13} | {badge} | 剩余: {s['remaining']:>2}人 (已约 {s['selected']:>2}/{s['max_count']:<2}){pref}"
            print(f"  {status_text}")

    print("\n" + "=" * 76 + "\n")

class GymStatusHandler(BaseHTTPRequestHandler):
    """轻量 HTTP 服务处理器，支持状态查询与立刻预约 API"""

    def _handle_book(self, params):
        interval_id = params.get("interval_id", [None])[0]
        date = params.get("date", [None])[0]
        time_slot = params.get("time", [None])[0]
        try:
            res = book_gym_slot(interval_id=interval_id, date=date, time_slot=time_slot)
            payload = json.dumps(res, ensure_ascii=False, default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            err_resp = {"success": False, "info": f"服务器内部错误: {e}"}
            self.wfile.write(json.dumps(err_resp, ensure_ascii=False).encode("utf-8"))

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/book"):
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
            self._handle_book(params)
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/book"):
            params = parse_qs(parsed.query)
            self._handle_book(params)
        elif parsed.path.startswith("/api/status") or parsed.path.startswith("/status.json"):
            try:
                data = query_gym_status()
                payload = json.dumps(data, ensure_ascii=False, default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(payload)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            try:
                data = query_gym_status()
                # 动态生成响应式美观 HTML
                rows_html = ""
                for g in data["groups"]:
                    for s in g["slots"]:
                        avail_cls = "avail" if s["is_available"] else "full"
                        avail_txt = f"剩余 {s['remaining']} 人" if s["is_available"] else "已约满"
                        pref_tag = "<span class='pref'>⭐目标时段</span>" if g["is_preferred"] else ""
                        rows_html += f"""
                        <tr class="{avail_cls}">
                            <td>{g['date']} {g['week_name']}</td>
                            <td><strong>{g['time_range']}</strong> {pref_tag}</td>
                            <td>{s['selected']} / {s['max_count']}</td>
                            <td><span class="badge {avail_cls}">{avail_txt}</span></td>
                            <td>
                                <button class="btn-book" onclick="bookSlot('{s['interval_id']}', '{g['date']}', '{g['time_range']}')">⚡ 立刻预约</button>
                            </td>
                        </tr>
                        """
                html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{data['stadium_name']} - 实时查询与预约</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f4f6f9; margin: 0; padding: 20px; }}
        .card {{ max-width: 860px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.06); padding: 24px; }}
        h1 {{ margin-top: 0; color: #1e293b; font-size: 22px; display: flex; align-items: center; justify-content: space-between; }}
        .time {{ color: #64748b; font-size: 13px; font-weight: normal; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 18px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #f1f5f9; font-size: 14px; vertical-align: middle; }}
        th {{ background: #f8fafc; color: #475569; font-weight: 600; }}
        .badge {{ padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }}
        .badge.avail {{ background: #dcfce7; color: #15803d; }}
        .badge.full {{ background: #fee2e2; color: #b91c1c; }}
        .pref {{ background: #fef3c7; color: #b45309; padding: 2px 6px; border-radius: 4px; font-size: 11px; margin-left: 6px; }}
        tr.avail {{ background: #f0fdf4; }}
        .btn {{ background: #2563eb; color: white; text-decoration: none; padding: 8px 16px; border-radius: 6px; font-size: 13px; display: inline-block; }}
        .btn-book {{ background: #059669; color: white; border: none; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s; }}
        .btn-book:hover {{ background: #047857; }}
        .btn-book:disabled {{ background: #9ca3af; cursor: not-allowed; opacity: 0.7; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>
            <span>🏋️ {data['stadium_name']}</span>
            <span class="time">更新时间: {data['query_time']}</span>
        </h1>
        <p style="color: #64748b; margin: 4px 0 16px 0;">{data['area_name']} | 数据实时直连校内预约系统，点击右侧按钮可直接发起极速预约</p>
        <table>
            <thead>
                <tr>
                    <th>日期</th>
                    <th>预约时段</th>
                    <th>已约 / 总容量</th>
                    <th>空闲状态</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        <div style="margin-top: 20px; text-align: right;">
            <a href="javascript:location.reload()" class="btn">🔄 刷新数据</a>
            <a href="/api/status" style="margin-left: 10px; font-size: 13px; color: #64748b;">查看 JSON API</a>
        </div>
    </div>
    <script>
        function bookSlot(intervalId, date, timeRange) {{
            if (!confirm(`确认立刻发起预约【${{date}} ${{timeRange}}】吗？`)) return;
            const btn = event.target;
            btn.disabled = true;
            const originalText = btn.innerText;
            btn.innerText = "预约提交中...";
            fetch(`/api/book?interval_id=${{intervalId}}&date=${{date}}&time=${{encodeURIComponent(timeRange)}}`)
                .then(r => r.json())
                .then(res => {{
                    if (res.success) {{
                        alert(`🎉 预约成功！\\n${{res.info || '恭喜您预约成功！'}}`);
                        location.reload();
                    }} else {{
                        alert(`⚠️ 预约未成功: ${{res.info || '网络或场次异常'}}`);
                        btn.disabled = false;
                        btn.innerText = originalText;
                    }}
                }})
                .catch(err => {{
                    alert(`请求出错: ${{err}}`);
                    btn.disabled = false;
                    btn.innerText = originalText;
                }});
        }}
    </script>
</body>
</html>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error querying gym status: {e}".encode())

def run_server(port=8080):
    server = HTTPServer(("0.0.0.0", port), GymStatusHandler)
    logger.info(f"🚀 健身房空闲状态与即时预约 HTTP 服务已启动: http://localhost:{port}")
    logger.info(f"👉 网页查看与一键预约: http://localhost:{port}/")
    logger.info(f"👉 状态 JSON API: http://localhost:{port}/api/status")
    logger.info(f"👉 即时预约 API: http://localhost:{port}/api/book?date=YYYY-MM-DD&time=HH:MM-HH:MM")
    print(f"\n服务已启动！按 Ctrl+C 退出。\n访问地址: http://localhost:{port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("已停止 HTTP 服务。")
        server.server_close()

def main():
    parser = argparse.ArgumentParser(description="厦大健身房空闲状态查询与即时预约工具")
    parser.add_argument("--serve", action="store_true", help="启动本地 HTTP Web 服务与预约 API")
    parser.add_argument("--port", type=int, default=8080, help="HTTP 服务监听端口 (默认: 8080)")
    parser.add_argument("--json", action="store_true", help="直接输出 JSON 格式结果")
    parser.add_argument("--book", action="store_true", help="立刻执行一次预约")
    parser.add_argument("--date", help="指定预约日期 (YYYY-MM-DD)")
    parser.add_argument("--time", help="指定预约时段 (如 19:30-21:00)")
    parser.add_argument("--interval-id", help="指定场次 ID")
    parser.add_argument("--config", default="config/config.yaml", help="配置文件路径")
    args = parser.parse_args()

    if args.serve:
        run_server(port=args.port)
    elif args.book:
        logger.info("正在执行立刻预约...")
        res = book_gym_slot(interval_id=args.interval_id, date=args.date, time_slot=args.time, config_path=args.config)
        if res.get("success"):
            logger.info(f"[成功] 预约成功: {res.get('info')}")
        else:
            logger.error(f"[失败] 预约未完成: {res.get('info')}")
    else:
        try:
            data = query_gym_status(config_path=args.config)
            if args.json:
                print(json.dumps(data, ensure_ascii=False, indent=2, default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o)))
            else:
                print_gym_status(data)
        except Exception as e:
            logger.error(f"查询失败: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
