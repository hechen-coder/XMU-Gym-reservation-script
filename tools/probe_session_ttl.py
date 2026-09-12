"""
Session 过期时间与存活机制探测工具
用于科学探究服务端 PHPSESSID 的闲置过期时间 (Idle Timeout) 与心跳延期能力。

【实测权威基准结论 (2026-09-12)】:
  - 纯静置 15 分钟: ✅ 存活
  - 纯静置 30 分钟: ✅ 存活
  - 纯静置  1 小时: ✅ 存活
  - 纯静置  2 小时: ❌ 失效 (Expired)
  => 结论：服务端 Redis 纯闲置过期时间精准定格在 1小时 ~ 2小时 之间 (推测 session.gc_maxlifetime = 7200秒/2小时)。
"""

import time
import sys
import os
from typing import List, Dict, Any

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

def get_fresh_session(api: XdtyApi, auth_params: Dict[str, Any]) -> str:
    """申请一个全新的独立 PHPSESSID"""
    success, token, _ = api.check_login(auth_params)
    if not success or not token:
        raise RuntimeError("无法通过 checkLogin 获取新 Session，请检查 auth_params 配置")
    return token

def probe_token_alive(base_url: str, token: str) -> bool:
    """对指定 token 发起一次轻量 probe 请求验证存活"""
    client = ApiClient(base_url=base_url)
    client.set_session_token(token)
    api = XdtyApi(client)
    try:
        res = api.my_subscribe(page=1)
        return isinstance(res, dict) and res.get("status") == 1
    except Exception:
        return False

def format_duration(minutes: int) -> str:
    """格式化分钟为易读字符串"""
    if minutes >= 1440 and minutes % 1440 == 0:
        return f"{minutes // 1440}天"
    if minutes >= 60 and minutes % 60 == 0:
        return f"{minutes // 60}小时"
    if minutes >= 60:
        return f"{minutes / 60:.1f}小时"
    return f"{minutes}分钟"

def parse_time_intervals(intervals_str: str) -> List[int]:
    """解析如 '15m, 30m, 1h, 2h, 4h' 或 '15, 30, 60, 120' 为分钟整数列表"""
    res = []
    for item in intervals_str.replace("，", ",").split(","):
        item = item.strip().lower()
        if not item:
            continue
        if item.endswith("h"):
            res.append(int(float(item[:-1]) * 60))
        elif item.endswith("m"):
            res.append(int(item[:-1]))
        elif item.endswith("d"):
            res.append(int(float(item[:-1]) * 1440))
        else:
            res.append(int(item))
    return sorted(list(set(res)))

def run_idle_matrix_probe(checkpoints_minutes: List[int] = [15, 30, 60, 120, 240, 480, 720, 1440]):
    """
    多样本静置法 (Idle Timeout Probe)
    核心原理：
    1. 在 T0 时刻一次性获取 N 个全新的 PHPSESSID；
    2. 每个 PHPSESSID 在测试前【绝不发任何请求】，彻底静置；
    3. 到达指定时间点时，只用对应的 Session 发送 1 次请求探测是否存活。
    这样可以彻底排除'每次探测给 Redis 重置 TTL 续期'的干扰，测出真实的闲置消亡时间！
    """
    cfg = load_config("config/config.yaml")
    if not getattr(cfg.auth, "auth_params", None) or not cfg.auth.auth_params.get("token"):
        print("❌ config.yaml 中缺少 auth_params，无法批量申请全新测试 Session！")
        return

    base_url = cfg.base_url
    client = ApiClient(base_url=base_url)
    api = XdtyApi(client)

    chk_desc = [format_duration(m) for m in sorted(checkpoints_minutes)]
    print("==================================================================")
    print("🔬 正在启动【PHPSESSID 纯静置闲置过期时间 (Idle Timeout) 平行测定】")
    print(f"🎯 探测检查点: {chk_desc}")
    print("💡 彻底解决'测它就给它续期'悖论：所有样本在 T0 申请后彻底静置，到点只发 1 枪验证！")
    print("==================================================================\n")

    sample_sessions = {}
    print("⏳ 正在为各个检查点一次性批量申请独立的干净会话...")
    for m in sorted(checkpoints_minutes):
        tok = get_fresh_session(api, cfg.auth.auth_params)
        sample_sessions[m] = tok
        print(f"  - [{format_duration(m):>6s} 样本] 获得独立 PHPSESSID: {tok[:8]}***")
        time.sleep(0.3)

    start_time = time.time()
    print(f"\n🚀 样本已全部就绪！基准起始时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")
    print("☕ 脚本后台静默计时中，期间不对服务器产生任何网络请求，直到检查点到达...\n")

    results = {}
    try:
        for m in sorted(checkpoints_minutes):
            target_time = start_time + m * 60
            sleep_needed = target_time - time.time()
            if sleep_needed > 0:
                print(f"[{time.strftime('%H:%M:%S')}] 距离下个检查点 ({format_duration(m)}) 还有 {int(sleep_needed)} 秒，静默等待中...")
                time.sleep(sleep_needed)

            now_str = time.strftime('%H:%M:%S')
            tok = sample_sessions[m]
            alive = probe_token_alive(base_url, tok)
            status_symbol = "✅ 依然存活" if alive else "❌ 已失效 (Expired)"
            results[m] = alive
            print(f"[{now_str}] ⏱️ 【第 {format_duration(m)} 测试】 Session: {tok[:8]}*** -> {status_symbol}")

            if not alive and all(results.get(prev, True) for prev in checkpoints_minutes if prev < m):
                print(f"\n🚨 关键发现：Session 在静置【{format_duration(m)}】时已死亡！")

    except KeyboardInterrupt:
        print("\n⚠️ 测试被人为中断。")

    print("\n================== 📊 探测结果汇总 ==================")
    for m, alive in sorted(results.items()):
        print(f"纯静置 {format_duration(m):>6s}: {'✅ 存活' if alive else '❌ 失效'}")
    print("====================================================\n")

def run_sliding_heartbeat_probe(interval_seconds: int = 120):
    """
    持续心跳测定法 (Sliding Window / Absolute Timeout Probe)
    原理：
    每隔 interval_seconds (默认 120 秒) 发送一次请求维持活跃。
    若连续维持很长时间依然存活，说明属于纯滑动窗口 (只要有请求就能无限续命)；
    若在特定时间点 (例如第 24 小时整) 即使持续心跳也突然失效，说明存在绝对最大生存周期。
    """
    cfg = load_config("config/config.yaml")
    if not getattr(cfg.auth, "auth_params", None) or not cfg.auth.auth_params.get("token"):
        print("❌ config.yaml 中缺少 auth_params！")
        return

    base_url = cfg.base_url
    client = ApiClient(base_url=base_url)
    api = XdtyApi(client)

    print("==================================================================")
    print("💓 正在启动【持续心跳滑动保活上限测试 (Absolute Lifetime)】")
    print(f"⏱️ 心跳间隔: 每 {interval_seconds} 秒发送一次探活请求")
    print("💡 目的：测试在持续活跃的情况下，是否存在服务端绝对过期上限 (如 24h/7天 强制失效)")
    print("==================================================================\n")

    token = get_fresh_session(api, cfg.auth.auth_params)
    print(f"✅ 获取全新测试 Session: {token[:8]}***")
    start_time = time.time()
    count = 0

    try:
        while True:
            count += 1
            now = time.time()
            elapsed_min = (now - start_time) / 60.0
            alive = probe_token_alive(base_url, token)
            now_str = time.strftime('%Y-%m-%d %H:%M:%S')

            if alive:
                print(f"[{now_str}] 💓 心跳 #{count:03d} 成功 | 已经累计持续存活: {elapsed_min:.1f} 分钟 ({elapsed_min/60:.2f} 小时)")
            else:
                print(f"\n🚨 [{now_str}] Session 死亡！在持续心跳下，于累计 {elapsed_min:.1f} 分钟后被强制失效！")
                break

            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        elapsed_min = (time.time() - start_time) / 60.0
        print(f"\n⚠️ 测试被人工中断。当前 Session 已成功持续活跃了 {elapsed_min:.1f} 分钟。")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("heartbeat", "hb", "pulse"):
        interval = 120
        if len(sys.argv) > 2:
            try:
                interval = int(sys.argv[2])
            except Exception:
                pass
        run_sliding_heartbeat_probe(interval)
    else:
        checkpoints = [15, 30, 60, 120, 240, 480, 720, 1440]
        param = None
        for arg in sys.argv[1:]:
            if arg.lower() not in ("idle",):
                param = arg
                break
        if param:
            try:
                checkpoints = parse_time_intervals(param)
            except Exception as e:
                print(f"⚠️ 参数解析异常 ({e})，使用默认检查点: {checkpoints}")
        run_idle_matrix_probe(checkpoints)

