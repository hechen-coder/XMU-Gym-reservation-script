"""
PHPSESSID (会话凭证) 生命周期与有效性探测工具
用于测定与追踪校方系统 Session (PHPSESSID) 的存活周期与失效极限。

【实测权威基准数据 (2026-09-12 平行断网静置实验)】:
  - 纯静置 15 分钟: ✅ 存活
  - 纯静置 30 分钟: ✅ 存活
  - 纯静置  1 小时: ✅ 存活
  - 纯静置  2 小时: ❌ 失效 (Expired)
  => 结论：校方后端 Redis 纯闲置超时时间精准定格在 1小时 ~ 2小时 (推测为 7200 秒 / 2 小时)。

使用方法:
  python tools/probe_phpsessid.py                 # 执行一次即时存活与寿命诊断
  python tools/probe_phpsessid.py watch [秒数]     # 挂机周期探活 (默认每 3600 秒检测一次，直到失效)
  python tools/probe_phpsessid.py idle            # 运行多样本静置闲置测试 (探究无心跳下的绝对超时时间)
"""

import os
import sys
import time
import json
import argparse
import datetime
from typing import Tuple, Dict, Any, Optional

# 适配 Windows 控制台输出编码
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 确保导入路径包含项目根目录
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from xdty_booking.config import load_config
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi

TIMELINE_FILE = os.path.join("data", "phpsessid_timeline.json")

def _get_timeline_data() -> Dict[str, Any]:
    """读取本地寿命追踪记录"""
    if os.path.exists(TIMELINE_FILE):
        try:
            with open(TIMELINE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_timeline_data(data: Dict[str, Any]):
    """持久化保存寿命追踪记录"""
    try:
        os.makedirs(os.path.dirname(TIMELINE_FILE), exist_ok=True)
        with open(TIMELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 保存时间轴异常: {e}")

def get_session_start_time(token: str, config_path: str = "config/config.yaml", custom_since: Optional[str] = None) -> datetime.datetime:
    """获取指定 PHPSESSID 的初始生成/捕获基准时间"""
    timeline = _get_timeline_data()
    if custom_since:
        try:
            dt = datetime.datetime.strptime(custom_since, "%Y-%m-%d %H:%M:%S")
            if token not in timeline:
                timeline[token] = {"token": token}
            timeline[token]["first_seen"] = custom_since
            _save_timeline_data(timeline)
            return dt
        except ValueError:
            pass

    # 1. 优先读取 timeline 历史记录
    if token in timeline and "first_seen" in timeline[token]:
        try:
            return datetime.datetime.strptime(timeline[token]["first_seen"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    # 2. 其次读取 config.yaml 文件的最后修改时间
    now = datetime.datetime.now()
    if os.path.exists(config_path):
        mtime = os.path.getmtime(config_path)
        dt = datetime.datetime.fromtimestamp(mtime)
        if dt <= now:
            first_seen_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            timeline[token] = {
                "token": token,
                "first_seen": first_seen_str,
                "last_alive": first_seen_str,
                "status": "alive"
            }
            _save_timeline_data(timeline)
            return dt

    # 3. 兜底为当前时刻
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    timeline[token] = {
        "token": token,
        "first_seen": now_str,
        "last_alive": now_str,
        "status": "alive"
    }
    _save_timeline_data(timeline)
    return now

def update_session_alive(token: str, is_alive: bool, elapsed_hours: float):
    """更新会话在时间轴中的最新存活状态"""
    timeline = _get_timeline_data()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if token not in timeline:
        timeline[token] = {
            "token": token,
            "first_seen": now_str,
            "status": "alive"
        }

    rec = timeline[token]
    if is_alive:
        rec["last_alive"] = now_str
        rec["status"] = "alive"
        rec["elapsed_hours"] = round(elapsed_hours, 2)
    else:
        if rec.get("status") == "alive":
            rec["died_at"] = now_str
            rec["final_duration_hours"] = round(elapsed_hours, 2)
            rec["final_duration_days"] = round(elapsed_hours / 24.0, 2)
            rec["status"] = "expired"

    _save_timeline_data(timeline)

def check_phpsessid_alive(token: str, base_url: str = "") -> Tuple[bool, str, Dict[str, Any]]:
    """向校方服务端发送轻量 mySubscribe 请求探测 PHPSESSID 存活"""
    if not token:
        return False, "PHPSESSID 为空", {}

    client = ApiClient(base_url=base_url or "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test")
    client.set_session_token(token)
    api = XdtyApi(client)
    try:
        res = api.my_subscribe(page=1)
        if isinstance(res, dict) and res.get("status") == 1:
            return True, "会话正常有效", res
        info = res.get("info", "状态异常") if isinstance(res, dict) else str(res)
        return False, info, res if isinstance(res, dict) else {}
    except Exception as e:
        return False, f"网络请求异常: {e}", {}

def run_once(token: Optional[str] = None, since: Optional[str] = None, config_path: str = "config/config.yaml"):
    """执行一次即时诊断"""
    cfg = load_config(config_path)
    target_token = token or cfg.auth.phpsessid
    if not target_token:
        print("❌ 未在 config.yaml 中找到有效的 phpsessid，且未指定 --token！")
        return

    start_dt = get_session_start_time(target_token, config_path, custom_since=since)
    now = datetime.datetime.now()
    elapsed = now - start_dt
    hours = max(0.0, elapsed.total_seconds() / 3600.0)
    days = hours / 24.0

    print("==================================================================")
    print("🔍 【会话凭证 (PHPSESSID) 存活与寿命即时诊断】")
    print(f"🔑 当前 PHPSESSID : {target_token[:8]}***{target_token[-4:]}")
    print(f"📅 初始生效基准时刻: {start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱️ 距离生效已过去  : {hours:.2f} 小时 ({days:.2f} 天)")
    print("⏳ 正在向校方服务端发起真实性存活检测...")

    alive, info, data = check_phpsessid_alive(target_token, cfg.base_url)
    update_session_alive(target_token, alive, hours)

    if alive:
        order_list = data.get("data", []) if isinstance(data, dict) else []
        uid = order_list[0].get("uid") if order_list and isinstance(order_list[0], dict) else cfg.auth.uid
        print(f"🎉 状态: 【有效存活中】 (已稳定工作 {hours:.2f} 小时 / {days:.2f} 天)")
        if uid:
            print(f"👤 绑定账号 UID  : {uid}")
        print(f"📋 历史订单校验   : 成功返回 {len(order_list)} 条预约记录")
        print("💡 结论: 该 PHPSESSID 状态完好，可直接用于查询余量与准点抢票！")
    else:
        print(f"❌ 状态: 【已过期失效】 (服务端提示: {info})")
        print(f"📊 该凭证总计维持了: {hours:.2f} 小时 ({days:.2f} 天)")
        print("💡 说明: 凭证已死，请使用 main.py harvest 或 Web 端重新截取更新。")
    print("==================================================================\n")

def run_watch(interval_seconds: int = 3600, token: Optional[str] = None, since: Optional[str] = None, config_path: str = "config/config.yaml"):
    """持续周期探活，直到检测到 PHPSESSID 失效并输出确切寿命"""
    cfg = load_config(config_path)
    target_token = token or cfg.auth.phpsessid
    if not target_token:
        print("❌ 未在 config.yaml 中找到有效的 phpsessid，且未指定 --token！")
        return

    start_dt = get_session_start_time(target_token, config_path, custom_since=since)

    print("==================================================================")
    print("🔭 【会话凭证 (PHPSESSID) 寿命追踪挂机探测】")
    print(f"🔑 当前探查 PHPSESSID: {target_token[:8]}***{target_token[-4:]}")
    print(f"📅 初始生效基准时刻: {start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱️ 检测周期: 每隔 {interval_seconds} 秒 (即 {interval_seconds/3600:.1f} 小时) 检验一次")
    print("💡 目的: 在 PHPSESSID 最终失效的那一刻，自动计算出其精准的生命周期 (如 12小时/24小时/7天)")
    print("==================================================================\n")

    count = 0
    try:
        while True:
            count += 1
            now = datetime.datetime.now()
            now_str = now.strftime("%Y-%m-%d %H:%M:%S")
            elapsed = now - start_dt
            hours = max(0.0, elapsed.total_seconds() / 3600.0)
            days = hours / 24.0

            alive, info, _ = check_phpsessid_alive(target_token, cfg.base_url)
            update_session_alive(target_token, alive, hours)

            if alive:
                print(f"[{now_str}] 💓 检查 #{count:03d} | ✅ PHPSESSID 依旧存活 | 累计生存时长: {hours:.2f} 小时 ({days:.2f} 天)")
            else:
                print(f"\n🚨🚨🚨 [{now_str}] 捕获到 PHPSESSID 失效事件！")
                print(f"⚠️ 服务端响应提示: {info}")
                print(f"📊 该 PHPSESSID 最终寿命定格为: {hours:.2f} 小时 ({days:.2f} 天)")
                print(f"💾 诊断记录已写入: {TIMELINE_FILE}")
                break

            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        now = datetime.datetime.now()
        elapsed = now - start_dt
        hours = max(0.0, elapsed.total_seconds() / 3600.0)
        days = hours / 24.0
        print(f"\n⚠️ 探测被人为中断 (Ctrl+C)。当前 PHPSESSID 已累计存活 {hours:.2f} 小时 ({days:.2f} 天)。")

def run_idle_probe(checkpoints_str: Optional[str] = None):
    """桥接调用多样本静置闲置超时探针 (probe_session_ttl.py)"""
    from tools.probe_session_ttl import run_idle_matrix_probe, parse_time_intervals
    if checkpoints_str:
        try:
            checkpoints = parse_time_intervals(checkpoints_str)
        except Exception:
            checkpoints = [15, 30, 60, 120, 240, 480, 720, 1440]
    else:
        checkpoints = [15, 30, 60, 120, 240, 480, 720, 1440]
    run_idle_matrix_probe(checkpoints)

def main():
    parser = argparse.ArgumentParser(
        description="PHPSESSID 生命周期与有效性探测工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
常用示例:
  python tools/probe_phpsessid.py                    # 即时诊断当前 Session 存活与已运行天数
  python tools/probe_phpsessid.py watch 3600         # 每隔 1 小时检测一次，测【带心跳保活下的绝对硬上限 (Hard Lifetime)】
  python tools/probe_phpsessid.py idle               # 运行多样本平行静置测定，测【完全无操作下的纯静默闲置超时 (Idle Timeout)】
  python tools/probe_phpsessid.py idle 30m,1h,2h,4h  # 自定义静置检查点
  python tools/probe_phpsessid.py --since "2026-09-12 09:30:00"  # 手动指定生成时间
"""
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="once",
        choices=["once", "watch", "monitor", "daemon", "idle"],
        help="执行模式: once (单次诊断, 默认), watch (挂机追踪绝对硬寿命), idle (多样本平行静置测闲置超时)"
    )
    parser.add_argument(
        "interval",
        nargs="?",
        default="3600",
        help="watch 模式下的间隔秒数 (默认 3600)，或 idle 模式下的检查点列表 (如 '30m,1h,2h')"
    )
    parser.add_argument(
        "--token",
        default=None,
        help="指定待检测的 PHPSESSID (留空则默认读取 config/config.yaml)"
    )
    parser.add_argument(
        "--since",
        default=None,
        help="指定该 Token 初始获取时间 (格式: 'YYYY-MM-DD HH:MM:SS')"
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="配置文件路径 (默认: config/config.yaml)"
    )

    args = parser.parse_args()

    if args.action in ("watch", "monitor", "daemon"):
        try:
            sec = int(args.interval)
        except ValueError:
            sec = 3600
        run_watch(interval_seconds=sec, token=args.token, since=args.since, config_path=args.config)
    elif args.action == "idle":
        run_idle_probe(checkpoints_str=args.interval if args.interval != "3600" else None)
    else:
        run_once(token=args.token, since=args.since, config_path=args.config)

if __name__ == "__main__":
    main()
