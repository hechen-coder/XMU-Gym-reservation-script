# -*- coding: utf-8 -*-
"""
授权守护核心与非对称签名鉴权引擎 (AuthGuard & RSA Verification)
实现：
1. 源码端 vs 打包端智能分流 (源码开发环境 100% 免密放行，打包客户端硬核拦截)
2. RSA-2048 非对称数字签名验签 (防伪造、防修改、防注册机)
3. 机器码 HWID 强绑定 (防跨机复制、防二次分发)
4. 有效期与系统时间防回拨校验 (Anti-Time-Rollback)
5. 支持拖入 license.lic 或直接在 Web 界面粘贴文本激活码
"""

import os
import sys
import json
import base64
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

try:
    import rsa
except ImportError:
    rsa = None

try:
    from .hwid import get_hwid
except (ImportError, ValueError):
    from hwid import get_hwid


# 固化的客户端验证公钥 (RSA-2048 Public Key)
# 仅用于验签，绝无法用于倒推私钥生成授权！
DEFAULT_PUBLIC_KEY_PEM = """
-----BEGIN RSA PUBLIC KEY-----
MIIBCgKCAQEAtgUfUzBYVNaeQySfsLcB3rLdDyjTrUKIIPCeImc7Oh7YqX58qF14
swoeOiTrJtQ5qNxNS7MJyAasI9D8rXMLu+nf8jgAyI+J50SVkjoklJtRHZqAo5ij
jOFbLp83WSO7fDxakpfwWMYOV1jpG2PnWRu2uMi4Rxc20ckrzs78v+Zg6qsPtaO2
44raXFb8QoopqMW0RYz+oVVCUvb0bUbvWWjGq8Wn0lZZM4BXlGFfKZClmfJ4z0yr
DbQLNpaR1TjJ5SOifbhY/0BmhrjBsAzsvYsctAQC/ztMiIUpanWpNva9AXjX4O1s
7ugVcetYxSgyv20Et5/qgXQORMZBiGv2+QIDAQAB
-----END RSA PUBLIC KEY-----
"""


def is_dev_mode() -> bool:
    """
    判断当前是否处于源码开发模式。
    如果是在 IDE / 命令行以 python 脚本方式直接启动，则 sys.frozen 为 False；
    如果是经 PyInstaller 打包构建的独立 EXE，则 sys.frozen 为 True。
    支持通过环境变量 FORCE_LICENSE_CHECK=1 强制在源码下模拟打包客户端拦截。
    """
    if os.environ.get("FORCE_LICENSE_CHECK") == "1":
        return False
    return not getattr(sys, "frozen", False)


def get_app_dir() -> str:
    """获取程序运行工作根目录"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # 源码环境下，定位到项目根目录
    cur = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(cur))


class AuthResult:
    def __init__(
        self,
        is_licensed: bool,
        message: str = "",
        is_dev: bool = False,
        hwid: str = "",
        expire_at: str = "",
        remark: str = ""
    ):
        self.is_licensed = is_licensed
        self.message = message
        self.is_dev = is_dev
        self.hwid = hwid or get_hwid()
        self.expire_at = expire_at
        self.remark = remark

    def to_dict(self) -> Dict[str, Any]:
        return {
            "licensed": self.is_licensed,
            "is_dev": self.is_dev,
            "hwid": self.hwid,
            "expire_at": self.expire_at,
            "remark": self.remark,
            "info": self.message
        }

    def __repr__(self):
        return f"<AuthResult licensed={self.is_licensed} is_dev={self.is_dev} expire={self.expire_at}>"


_CACHED_AUTH_RESULT: Optional[AuthResult] = None


def get_public_key() -> Optional[Any]:
    """加载 RSA 验签公钥"""
    if rsa is None:
        return None
    try:
        return rsa.PublicKey.load_pkcs1(DEFAULT_PUBLIC_KEY_PEM.strip().encode("utf-8"))
    except Exception:
        # 兼容备用路径
        pub_path = os.path.join(get_app_dir(), "tools", "client_public_key.pem")
        if os.path.exists(pub_path):
            try:
                with open(pub_path, "rb") as f:
                    return rsa.PublicKey.load_pkcs1(f.read())
            except Exception:
                pass
    return None


def _get_time_guard_path() -> str:
    """防系统时钟回拨隐藏记录文件"""
    data_dir = os.path.join(get_app_dir(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, ".auth_state")


def _check_and_update_clock() -> bool:
    """
    系统时钟防回拨校验 (Anti-Time-Rollback)
    记录每次程序运行的最大时间戳，若检测到系统时间倒退超过 24 小时，判定为恶意篡改时钟。
    """
    state_file = _get_time_guard_path()
    now_ts = datetime.now().timestamp()
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                # 简单 Base64 编码的时间戳
                last_ts = float(base64.b64decode(content.encode("utf-8")).decode("utf-8"))
                if now_ts < last_ts - 86400:  # 允许 1 天合理夏令时/误差
                    return False
        except Exception:
            pass

    # 更新最新时间戳
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            b64_val = base64.b64encode(str(now_ts).encode("utf-8")).decode("utf-8")
            f.write(b64_val)
    except Exception:
        pass
    return True


def parse_license_data(raw_data: Any) -> Optional[dict]:
    """
    智能解析授权数据 (支持 JSON 字符串、Base64 编码单行激活码、字典对象)
    """
    if isinstance(raw_data, dict):
        return raw_data

    if isinstance(raw_data, bytes):
        try:
            raw_data = raw_data.decode("utf-8")
        except Exception:
            return None

    if not isinstance(raw_data, str):
        return None

    raw_str = raw_data.strip()

    # 1. 尝试直接作为 JSON 解析
    try:
        obj = json.loads(raw_str)
        if isinstance(obj, dict) and "payload" in obj and "signature" in obj:
            return obj
    except Exception:
        pass

    # 2. 尝试作为 Base64 编码的文本激活码解析
    try:
        decoded_bytes = base64.b64decode(raw_str.encode("utf-8"))
        obj = json.loads(decoded_bytes.decode("utf-8"))
        if isinstance(obj, dict) and "payload" in obj and "signature" in obj:
            return obj
    except Exception:
        pass

    return None


def verify_license_object(lic_obj: dict) -> Tuple[bool, str, Optional[dict]]:
    """
    底层核心：验证授权数据对象的合法性
    返回：(是否合法, 说明消息, payload内容)
    """
    if not lic_obj or "payload" not in lic_obj or "signature" not in lic_obj:
        return False, "授权文件格式损坏或不完整", None

    payload = lic_obj["payload"]
    sig_b64 = lic_obj["signature"]

    # 1. 校验公钥是否存在
    pubkey = get_public_key()
    if pubkey is None or rsa is None:
        return False, "客户端验签引擎未就绪 (缺失公钥或 rsa 模块)", None

    # 2. 验证 RSA-2048 数字签名 (绝对防伪)
    try:
        canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        sig_raw = base64.b64decode(sig_b64.encode("utf-8"))
        rsa.verify(canonical_bytes, sig_raw, pubkey)
    except rsa.VerificationError:
        return False, "数字签名验证失败！授权文件可能已被篡改或非官方签发。", None
    except Exception as e:
        return False, f"签名解析异常: {e}", None

    # 3. 校验机器识别码 (HWID)
    lic_hwid = str(payload.get("hwid", "")).strip().upper()
    current_hwid = get_hwid().strip().upper()
    if lic_hwid != current_hwid:
        return False, f"机器码不匹配！该授权绑定机器为 [{lic_hwid}]，本机为 [{current_hwid}]", None

    # 4. 校验时钟防回拨
    if not _check_and_update_clock():
        return False, "检测到系统时钟发生异常回拨，请同步正确的北京时间后再试！", None

    # 5. 校验授权有效期 (expire_at)
    expire_at = str(payload.get("expire_at", "")).strip()
    if expire_at != "PERMANENT":
        try:
            exp_dt = datetime.strptime(expire_at, "%Y-%m-%d %H:%M:%S")
            if datetime.now() > exp_dt:
                return False, f"该授权已于 {expire_at} 到期，请联系作者续期！", None
        except Exception:
            return False, "授权文件中的到期时间格式无效", None

    return True, "授权验证通过", payload


def find_local_license_file() -> Optional[str]:
    """全盘搜索可能存在的本地 license.lic 文件"""
    candidates = [
        os.path.join(get_app_dir(), "license.lic"),
        os.path.join(get_app_dir(), "config", "license.lic"),
        os.path.join(get_app_dir(), "data", "license.lic"),
        os.path.join(os.getcwd(), "license.lic"),
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.isfile(p):
            return p
    return None


def check_license(force_refresh: bool = False) -> AuthResult:
    """
    检查当前环境授权状态（高频调用带缓存）。
    若处于源码开发模式，直接无感放行；
    若处于打包客户端模式，执行严格验签与机器码匹配。
    """
    global _CACHED_AUTH_RESULT
    if not force_refresh and _CACHED_AUTH_RESULT is not None:
        return _CACHED_AUTH_RESULT

    current_hwid = get_hwid()

    # 模式 A: 源码开发环境 -> 直接免密放行
    if is_dev_mode():
        res = AuthResult(
            is_licensed=True,
            message="开发调试模式 · 免激活放行",
            is_dev=True,
            hwid=current_hwid,
            expire_at="永久 (开发者模式)",
            remark="本地源码运行环境"
        )
        _CACHED_AUTH_RESULT = res
        return res

    # 模式 B: 打包客户端发布版 -> 检查本地 license.lic
    lic_file = find_local_license_file()
    if not lic_file:
        res = AuthResult(
            is_licensed=False,
            message=f"未找到授权文件 (license.lic)。本机机器码: {current_hwid}，请联系作者获取授权。",
            is_dev=False,
            hwid=current_hwid,
            expire_at="",
            remark=""
        )
        _CACHED_AUTH_RESULT = res
        return res

    try:
        with open(lic_file, "r", encoding="utf-8") as f:
            raw_content = f.read()
        lic_obj = parse_license_data(raw_content)
        if not lic_obj:
            res = AuthResult(
                is_licensed=False,
                message="本地 license.lic 文件格式无效",
                is_dev=False,
                hwid=current_hwid
            )
            _CACHED_AUTH_RESULT = res
            return res

        ok, msg, payload = verify_license_object(lic_obj)
        if ok and payload:
            res = AuthResult(
                is_licensed=True,
                message="授权有效",
                is_dev=False,
                hwid=current_hwid,
                expire_at=payload.get("expire_at", "永久"),
                remark=payload.get("remark", "")
            )
        else:
            res = AuthResult(
                is_licensed=False,
                message=msg,
                is_dev=False,
                hwid=current_hwid
            )
        _CACHED_AUTH_RESULT = res
        return res
    except Exception as e:
        res = AuthResult(
            is_licensed=False,
            message=f"读取授权文件异常: {e}",
            is_dev=False,
            hwid=current_hwid
        )
        _CACHED_AUTH_RESULT = res
        return res


def activate_license(raw_data: Any) -> Tuple[bool, str]:
    """
    执行授权激活 (支持传入 Base64 文本激活码或 license.lic 内容)
    校验合法后自动回写到程序根目录 license.lic，并即时刷新内存授权状态。
    """
    global _CACHED_AUTH_RESULT
    lic_obj = parse_license_data(raw_data)
    if not lic_obj:
        return False, "激活码或授权文件格式解析失败，请检查是否完整复制！"

    ok, msg, payload = verify_license_object(lic_obj)
    if not ok:
        return False, msg

    # 验签通过，持久化保存至主程序同级目录
    target_path = os.path.join(get_app_dir(), "license.lic")
    try:
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(lic_obj, f, indent=2, ensure_ascii=False)
    except Exception as e:
        return False, f"写入授权文件失败: {e}"

    # 强制刷新缓存
    check_license(force_refresh=True)
    exp_str = payload.get("expire_at", "永久")
    return True, f"🎉 激活成功！授权有效期至: {exp_str}"


def get_auth_status() -> Dict[str, Any]:
    """获取格式化的授权状态字典，供 Web API 直接输出"""
    res = check_license()
    return res.to_dict()


if __name__ == "__main__":
    print("=" * 60)
    print("      厦大体育馆自动预约项目 - 授权守护诊断")
    print("=" * 60)
    status = get_auth_status()
    for k, v in status.items():
        print(f"  [{k}]: {v}")
    print("=" * 60)
