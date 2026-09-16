#!/usr/bin/env python3
"""
厦大健身房空闲状态查询与 8080 Web 即时预约工具 (已整合至 xdty_booking.web)
"""
import sys
import json
import argparse

from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.web.server import (
    query_gym_status,
    book_gym_slot as _server_book_gym_slot,
    run_server as _server_run_server,
    GymStatusHandler as BaseGymStatusHandler,
    logger,
    _GLOBAL_CONFIG_PATH
)

def book_gym_slot(interval_id=None, date=None, time_slot=None, config_path="config/config.yaml"):
    """在当前模块命名空间下封装 book_gym_slot，确保单元测试 patch 生效"""
    return _server_book_gym_slot(interval_id=interval_id, date=date, time_slot=time_slot, config_path=config_path)

class GymStatusHandler(BaseGymStatusHandler):
    """重载 _handle_book 确保调用当前模块的 book_gym_slot"""
    def _handle_book(self, params):
        interval_id = params.get("interval_id", [None])[0]
        date = params.get("date", [None])[0]
        time_slot = params.get("time", [None])[0]
        try:
            res = book_gym_slot(
                interval_id=interval_id,
                date=date,
                time_slot=time_slot,
                config_path=_GLOBAL_CONFIG_PATH
            )
            self._send_json(200, res)
        except Exception as e:
            logger.error(f"预约处理异常: {e}")
            self._send_json(500, {"success": False, "info": f"服务器内部错误: {e}"})

def run_server(port=8080, config_path="config/config.yaml"):
    return _server_run_server(port=port, config_path=config_path)

def print_gym_status(data):
    """在终端格式化输出空闲状态"""
    print("\n" + "=" * 76)
    print(f"[场馆查询] {data.get('stadium_name', '')}（{data.get('area_name', '')}）实时空闲状态查询")
    print(f"[查询时间] {data.get('query_time', '')}")
    dates_str = ", ".join([f"{d.get('date', '')}({d.get('week', '')})" for d in data.get('date_list', [])])
    print(f"[开放日期] {dates_str}")
    print("=" * 76)

    current_date = None
    for g in data.get("groups", []):
        if g["date"] != current_date:
            current_date = g["date"]
            print(f"\n[日期] {g['date']} {g['week_name']}")
            print("-" * 76)

        for s in g.get("slots", []):
            if s.get("is_available"):
                badge = "[空闲充足]" if s.get("remaining", 0) > 10 else "[剩余紧张]"
                rem_text = f"剩余: {s.get('remaining', 0):>2}人 (已约 {s.get('selected', 0):>2}/{s.get('max_count', 0):<2})"
            elif s.get("is_locked") or s.get("status") == "locked" or (s.get("selected", 0) == 0 and not s.get("is_available")):
                badge = "[课程占用]"
                rem_text = f"教学课程占用 · 暂不开放个人预约 (0/{s.get('max_count', 0):<2})"
            else:
                badge = "[已经约满]"
                rem_text = f"名额已约满 (已约 {s.get('selected', 0):>2}/{s.get('max_count', 0):<2})"

            pref = " *【目标时段】" if g.get("is_preferred") else ""
            status_text = f"时段: {g['time_range']:<13} | {badge} | {rem_text}{pref}"
            print(f"  {status_text}")

    print("\n" + "=" * 76 + "\n")

def main():
    parser = argparse.ArgumentParser(description="厦大健身房空闲状态查询与即时预约工具")
    parser.add_argument("--serve", action="store_true", help="启动本地 HTTP Web 服务与预约 API (默认: 8080)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP 服务监听端口 (默认: 8080)")
    parser.add_argument("--json", action="store_true", help="直接输出 JSON 格式结果")
    parser.add_argument("--book", action="store_true", help="立刻执行一次预约")
    parser.add_argument("--date", help="指定预约日期 (YYYY-MM-DD)")
    parser.add_argument("--time", help="指定预约时段 (如 19:30-21:00)")
    parser.add_argument("--interval-id", help="指定场次 ID")
    parser.add_argument("--config", default="config/config.yaml", help="配置文件路径")
    args = parser.parse_args()

    if args.serve:
        run_server(port=args.port, config_path=args.config)
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
