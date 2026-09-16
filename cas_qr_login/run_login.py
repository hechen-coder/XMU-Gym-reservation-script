"""
厦门大学统一身份认证 · 纯 Python 企业微信扫码登录工具
脱离微信客户端，通过纯 HTTP/HTTPS 协议链路完成扫码登录与全套凭证提取。
"""

import logging
import os
import sys
import time
import webbrowser

# Windows 控制台 UTF-8 支持
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from cas_qr_login.server import start_cas_qr_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("CasQrMain")

def main():
    port = 8899
    print("=" * 68)
    print("🎯 【厦大体育馆 · 纯 Python 统一身份认证扫码登录工具】")
    print("=" * 68)
    print("💡 特性说明:")
    print("  1. 彻底脱离微信 PC 客户端，无需安装微信，无需开启嗅探代理；")
    print("  2. 直接模拟 CAS 统一身份认证协议，提供可视化二维码页面；")
    print("  3. 手机端企业微信扫码授权后，自动截获并置换最新 PHPSESSID 与 auth_params；")
    print("  4. 自动持久化回写至 config/config.yaml，并支持直接进入预约大厅！")
    print("-" * 68)

    # 启动本地服务
    httpd = start_cas_qr_server(port=port)
    local_url = f"http://127.0.0.1:{port}"
    print(f"\n🌐 扫码登录控制台已启动: {local_url}")
    print(f"🏋️ 体育馆查询预约大厅直达: {local_url}/dashboard")
    print("🚀 正在自动为你打开默认浏览器...")

    try:
        webbrowser.open(local_url)
    except Exception as e:
        print(f"⚠️ 自动打开浏览器失败，请手动访问: {local_url} ({e})")

    print("\n👉 请在弹出的浏览器页面中，使用手机【企业微信】扫描二维码完成登录。")
    print("⏹️ 按 Ctrl + C 可退出本工具。\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 正在关闭扫码登录服务...")
        httpd.shutdown()
        print("✅ 服务已安全停止。")

if __name__ == "__main__":
    main()
