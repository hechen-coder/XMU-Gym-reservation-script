"""
长效 Token (auth_params.token) 生命周期与有效性探测工具
用于测定方案 A 中用于换票的 SSO Token 到底能存活多少天/小时。
"""

import time
import datetime
import sys
import os

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

# 首次从抓包捕获到该 Token 的基准时间 (来自抓包中 timestamp: 1789187729)
INITIAL_CAPTURED_TIME = datetime.datetime(2026, 9, 12, 12, 35, 29)

def test_token_validity() -> bool:
    """使用 checkLogin 单独测试 auth_params.token 的有效性"""
    cfg = load_config("config/config.yaml")
    if not getattr(cfg.auth, "auth_params", None) or not cfg.auth.auth_params.get("token"):
        print("❌ config.yaml 中未配置 auth_params！")
        return False

    client = ApiClient(base_url=cfg.base_url)
    api = XdtyApi(client)
    success, _, res = api.check_login(cfg.auth.auth_params)
    return success

def run_once():
    """执行一次即时诊断"""
    cfg = load_config("config/config.yaml")
    token = cfg.auth.auth_params.get("token", "")
    print("==================================================================")
    print("🔍 【长效 Token (auth_params.token) 存活诊断】")
    print(f"🔑 当前 Token: {token[:8]}***{token[-4:]}")
    print(f"📅 初始捕获时间: {INITIAL_CAPTURED_TIME.strftime('%Y-%m-%d %H:%M:%S')}")
    
    now = datetime.datetime.now()
    elapsed = now - INITIAL_CAPTURED_TIME
    hours = elapsed.total_seconds() / 3600.0
    days = hours / 24.0

    print(f"⏱️ 距离捕获已过去: {hours:.2f} 小时 ({days:.2f} 天)")
    print("⏳ 正在向服务端 checkLogin 发起独立无状态鉴权验证...")

    alive = test_token_validity()
    if alive:
        print(f"🎉 状态: 【有效存活中】 (已稳定工作 {hours:.2f} 小时)")
        print("💡 说明: 该 Token 依然可以直接用于秒级换取全新的 PHPSESSID。")
    else:
        print(f"❌ 状态: 【已过期失效】")
        print("💡 说明: 该 Token 已被服务端失效，需重新唤起微信小程序进行一次嗅探更新。")
    print("==================================================================\n")

def run_watch(interval_seconds: int = 3600):
    """守护式周期探活，直至检测到 Token 死亡并输出确切寿命"""
    print("==================================================================")
    print("🔭 【长效 Token (auth_params.token) 寿命追踪挂机探测】")
    print(f"⏱️ 检测周期: 每隔 {interval_seconds} 秒 (即 {interval_seconds/3600:.1f} 小时) 检验一次")
    print("💡 目的: 在 Token 最终失效的那一刻，自动计算出其精准的生命周期 (如 3天/7天/30天)")
    print("==================================================================\n")

    while True:
        now = datetime.datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        elapsed = now - INITIAL_CAPTURED_TIME
        hours = elapsed.total_seconds() / 3600.0
        days = hours / 24.0

        alive = test_token_validity()
        if alive:
            print(f"[{now_str}] ✅ Token 依旧存活 | 累计生存时长: {hours:.2f} 小时 ({days:.2f} 天)")
        else:
            print(f"\n🚨🚨🚨 [{now_str}] 捕获到 Token 失效事件！")
            print(f"📊 该 Token 最终寿命定格为: {hours:.2f} 小时 ({days:.2f} 天)")
            break

        time.sleep(interval_seconds)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("watch", "monitor", "daemon"):
        interval = 3600
        if len(sys.argv) > 2:
            try:
                interval = int(sys.argv[2])
            except Exception:
                pass
        run_watch(interval)
    else:
        run_once()
