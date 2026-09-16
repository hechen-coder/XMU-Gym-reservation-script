# -*- coding: utf-8 -*-
"""
开发者专属发码与授权签发工具 (Developer Keygen & License Issuer)
注意：此工具及 developer_private_key.pem 仅供软件作者本人使用，严禁分发给买家！

功能：
1. 首次运行自动生成 RSA-2048 密钥对 (私钥 developer_private_key.pem + 公钥 client_public_key.pem)
2. 根据买家机器码 (HWID)、有效期与备注，进行 RSA-SHA256 数字签名
3. 生成标准的 license.lic 文件，并输出便于微信粘贴的 Base64 激活码文本
"""

import os
import sys
import json
import base64
import argparse
from datetime import datetime, timedelta

# 解决 Windows 控制台编码
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import rsa
except ImportError:
    print("[ERROR] 缺失 rsa 库，请先执行: pip install rsa")
    sys.exit(1)

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TOOLS_DIR)
PRIV_KEY_PATH = os.path.join(TOOLS_DIR, "developer_private_key.pem")
PUB_KEY_PATH = os.path.join(TOOLS_DIR, "client_public_key.pem")
AUTH_PY_PATH = os.path.join(PROJECT_ROOT, "xdty_booking", "security", "auth.py")


def ensure_keypair():
    """确保 RSA-2048 密钥对就绪，若不存在则自动生成并同步公钥到 auth.py"""
    if os.path.exists(PRIV_KEY_PATH) and os.path.exists(PUB_KEY_PATH):
        with open(PRIV_KEY_PATH, "rb") as f:
            privkey = rsa.PrivateKey.load_pkcs1(f.read())
        with open(PUB_KEY_PATH, "rb") as f:
            pubkey = rsa.PublicKey.load_pkcs1(f.read())
        return privkey, pubkey

    print("[*] 正在生成全新的 2048 位 RSA 商业级密钥对 (需耗时 1-2 秒)...")
    pubkey, privkey = rsa.newkeys(2048)

    with open(PRIV_KEY_PATH, "wb") as f:
        f.write(privkey.save_pkcs1(format="PEM"))
    with open(PUB_KEY_PATH, "wb") as f:
        f.write(pubkey.save_pkcs1(format="PEM"))

    print(f"[+] 私钥已妥善保存至: {PRIV_KEY_PATH} (⚠️ 必须保密，请勿泄露！)")
    print(f"[+] 公钥已导出至: {PUB_KEY_PATH}")

    # 同步公钥至 auth.py
    pub_pem_str = pubkey.save_pkcs1(format="PEM").decode("utf-8")
    _sync_public_key_to_auth(pub_pem_str)

    return privkey, pubkey


def _sync_public_key_to_auth(pub_pem_str: str):
    """将生成的客户端公钥同步写入 xdty_booking/security/auth.py"""
    if not os.path.exists(AUTH_PY_PATH):
        return
    try:
        with open(AUTH_PY_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        target_marker = 'DEFAULT_PUBLIC_KEY_PEM = """'
        if target_marker in content:
            idx_start = content.find(target_marker) + len(target_marker)
            idx_end = content.find('"""', idx_start)
            if idx_end != -1:
                new_content = content[:idx_start] + "\n" + pub_pem_str.strip() + "\n" + content[idx_end:]
                with open(AUTH_PY_PATH, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"[+] 已将公钥成功固化至客户端模块: {AUTH_PY_PATH}")
    except Exception as e:
        print(f"[!] 同步公钥到 auth.py 时出现警告: {e}")


def calculate_semester_end() -> str:
    """自动推算中国高校当前学期结束日期 (春季学期至 7月31日，秋季学期至次年 1月31日)"""
    now = datetime.now()
    year = now.year
    month = now.month
    if 2 <= month <= 7:
        end_dt = datetime(year, 7, 31, 23, 59, 59)
    elif month >= 8:
        end_dt = datetime(year + 1, 1, 31, 23, 59, 59)
    else:
        end_dt = datetime(year, 1, 31, 23, 59, 59)
    return end_dt.strftime("%Y-%m-%d %H:%M:%S")


def sign_license(
    hwid: str,
    days: int = 0,
    expire_at: str = None,
    remark: str = "客户授权",
    features: list = None
) -> dict:
    """签署授权并生成完整授权包"""
    privkey, _ = ensure_keypair()
    hwid = hwid.strip().upper()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if expire_at is None:
        if days == -1:
            expire_at = "PERMANENT"
        elif days > 0:
            expire_dt = datetime.now() + timedelta(days=days)
            expire_at = expire_dt.strftime("%Y-%m-%d 23:59:59")
        else:
            expire_at = calculate_semester_end()

    payload = {
        "hwid": hwid,
        "remark": remark,
        "issued_at": now_str,
        "expire_at": expire_at,
        "version": "1.0",
        "features": features or ["all"]
    }

    # 规范化排序序列化，确保签名确定性
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig_raw = rsa.sign(canonical_bytes, privkey, "SHA-256")
    sig_b64 = base64.b64encode(sig_raw).decode("utf-8")

    full_license = {
        "payload": payload,
        "signature": sig_b64
    }
    return full_license


def format_license_code(license_dict: dict) -> str:
    """将授权字典打包压缩为单行 Base64 文本激活码 (便于微信/QQ直接发送)"""
    raw_json = json.dumps(license_dict, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw_json).decode("utf-8")


def interactive_issue():
    """交互式发卡控制台"""
    print("\n" + "=" * 64)
    print("      厦大体育馆自动预约项目 - 开发者专属授权签发中心 (Keygen)")
    print("=" * 64)

    privkey, pubkey = ensure_keypair()

    while True:
        try:
            hwid_input = input("\n[1/3] 请输入买家机器码 (HWID，例如 XMU-2883-636D-719B-97CB): ").strip().upper()
        except (KeyboardInterrupt, EOFError):
            print("\n已退出。")
            break

        if not hwid_input:
            print("❌ 机器码不能为空，请重新输入！")
            continue

        print("\n[2/3] 请选择授权时长：")
        print("  [1] 30 天 (月度授权)")
        print("  [2] 90 天 (季度授权)")
        print("  [3] 本学期有效 (自动推算至 1月31日 或 7月31日)")
        print("  [4] 永久买断 (PERMANENT)")
        print("  [5] 自定义天数")

        opt = input("请输入选项数字 [默认 3]: ").strip()
        expire_at = None
        days = 0
        if opt == "1":
            days = 30
        elif opt == "2":
            days = 90
        elif opt == "4":
            days = -1
        elif opt == "5":
            try:
                custom_d = int(input("请输入有效天数: ").strip())
                days = custom_d
            except Exception:
                print("输入无效，默认设为 30 天")
                days = 30
        else:  # 默认 3: 本学期
            expire_at = calculate_semester_end()

        remark = input("\n[3/3] 请输入买家备注 (例如 微信-张三 / 学号2024xxx) [可直接回车]: ").strip()
        if not remark:
            remark = "标准客户授权"

        lic = sign_license(hwid=hwid_input, days=days, expire_at=expire_at, remark=remark)
        b64_code = format_license_code(lic)

        # 保存为 license.lic 文件
        out_file = os.path.join(PROJECT_ROOT, "license.lic")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(lic, f, indent=2, ensure_ascii=False)

        print("\n" + "=" * 64)
        print("🎉 授权凭证签发成功！")
        print(f"  • 绑定机器: {lic['payload']['hwid']}")
        print(f"  • 授权期限: {lic['payload']['expire_at']}")
        print(f"  • 买家备注: {lic['payload']['remark']}")
        print(f"  • 文件导出: {out_file}")
        print("-" * 64)
        print("📋 【方式 A - 授权文件】：已将 'license.lic' 保存在工程根目录，可直接发给买家。")
        print("📋 【方式 B - 文本激活码】：可直接复制下方这一长串文本通过微信发送给买家：\n")
        print(f"{b64_code}\n")
        print("=" * 64)

        cont = input("是否继续签发下一个授权？(y/N): ").strip().lower()
        if cont != "y":
            break


def main():
    parser = argparse.ArgumentParser(description="厦大体育馆自动预约项目 - 授权签发工具 (Keygen)")
    parser.add_argument("--hwid", help="买家机器码 (例如 XMU-2883-636D-719B-97CB)")
    parser.add_argument("--days", type=int, default=0, help="授权天数 (-1 为永久)")
    parser.add_argument("--semester", action="store_true", help="设为本学期期末")
    parser.add_argument("--permanent", action="store_true", help="设为永久授权")
    parser.add_argument("--remark", default="标准客户授权", help="买家备注信息")
    parser.add_argument("--out", default="license.lic", help="输出文件路径")
    args = parser.parse_args()

    if args.hwid:
        days = args.days
        expire_at = None
        if args.permanent:
            days = -1
        elif args.semester:
            expire_at = calculate_semester_end()

        lic = sign_license(hwid=args.hwid, days=days, expire_at=expire_at, remark=args.remark)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(lic, f, indent=2, ensure_ascii=False)
        code = format_license_code(lic)
        print(f"[+] 授权文件已生成: {args.out}")
        print(f"[+] 文本激活码:\n{code}")
    else:
        interactive_issue()


if __name__ == "__main__":
    main()
