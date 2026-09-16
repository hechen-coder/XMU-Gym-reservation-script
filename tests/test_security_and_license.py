# -*- coding: utf-8 -*-
"""
一机一码授权防护与安全验签单元测试
覆盖：
1. 硬件指纹 (HWID) 采集与格式化校验
2. 源码开发模式免密全功能放行
3. RSA-2048 非对称数字签名与防伪造检测
4. 机器码不匹配、过期授权、内容篡改拦截
5. 授权激活接口与状态持久化
"""

import os
import sys
import json
import pytest
from datetime import datetime, timedelta

from xdty_booking.security.hwid import get_hwid, get_hardware_info
from xdty_booking.security.auth import (
    is_dev_mode,
    check_license,
    activate_license,
    get_auth_status,
    verify_license_object,
    parse_license_data
)
from tools.keygen import sign_license, format_license_code, ensure_keypair


def test_hwid_generation():
    """测试机器识别码采集与格式规范"""
    hwid = get_hwid()
    assert hwid.startswith("XMU-")
    parts = hwid.split("-")
    assert len(parts) == 5  # XMU-XXXX-XXXX-XXXX-XXXX
    for p in parts[1:]:
        assert len(p) == 4
        assert p.isalnum()

    # 验证多次调用指纹稳定性 (幂等性)
    assert get_hwid() == hwid


def test_dev_mode_bypass():
    """测试源码开发环境下的 100% 免密放行通道"""
    # 确保未开启强制模式
    old_val = os.environ.pop("FORCE_LICENSE_CHECK", None)
    try:
        assert is_dev_mode() is True
        status = check_license(force_refresh=True)
        assert status.is_licensed is True
        assert status.is_dev is True
        assert "开发调试模式" in status.message

        api_status = get_auth_status()
        assert api_status["licensed"] is True
        assert api_status["is_dev"] is True
    finally:
        if old_val is not None:
            os.environ["FORCE_LICENSE_CHECK"] = old_val


def test_rsa_signature_verification_success():
    """测试合法授权签发与验签成功"""
    current_hwid = get_hwid()
    lic = sign_license(hwid=current_hwid, days=30, remark="测试买家张三")

    ok, msg, payload = verify_license_object(lic)
    assert ok is True
    assert "授权验证通过" in msg
    assert payload["hwid"] == current_hwid
    assert payload["remark"] == "测试买家张三"


def test_tamper_signature_rejection():
    """测试授权文件被篡改时签名校验立即拒绝"""
    current_hwid = get_hwid()
    lic = sign_license(hwid=current_hwid, days=30, remark="原版合法授权")

    # 恶意篡改有效期至 2099 年
    lic["payload"]["expire_at"] = "2099-12-31 23:59:59"
    ok, msg, _ = verify_license_object(lic)
    assert ok is False
    assert "签名验证失败" in msg

    # 恶意伪造签名
    lic["signature"] = "SGVsbG9Xb3JsZFNpZ25hdHVyZUZha2U="
    ok2, msg2, _ = verify_license_object(lic)
    assert ok2 is False


def test_cross_machine_hwid_rejection():
    """测试跨机转卖行为（室友运行别人的授权）立即拦截"""
    other_hwid = "XMU-FFFF-EEEE-DDDD-CCCC"
    lic = sign_license(hwid=other_hwid, days=30, remark="买家 A")

    ok, msg, _ = verify_license_object(lic)
    assert ok is False
    assert "机器码不匹配" in msg


def test_expired_license_rejection():
    """测试过期授权拦截"""
    current_hwid = get_hwid()
    past_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    lic = sign_license(hwid=current_hwid, expire_at=past_date, remark="过期测试")

    ok, msg, _ = verify_license_object(lic)
    assert ok is False
    assert "到期" in msg


def test_compact_license_code_format_and_parse():
    """测试单行 Base64 文本激活码的压缩打包与还原解析"""
    current_hwid = get_hwid()
    lic = sign_license(hwid=current_hwid, days=15, remark="微信文本激活码")
    b64_code = format_license_code(lic)
    assert isinstance(b64_code, str)
    assert len(b64_code) > 50

    parsed = parse_license_data(b64_code)
    assert parsed is not None
    assert parsed["payload"]["hwid"] == current_hwid


def test_activate_license_and_status_refresh(tmp_path):
    """测试激活函数及其在模拟打包环境下的生效表现"""
    os.environ["FORCE_LICENSE_CHECK"] = "1"
    try:
        # 未激活状态检测
        # 确保无残留 license.lic
        lic_file = os.path.join(os.getcwd(), "license.lic")
        if os.path.exists(lic_file):
            os.remove(lic_file)

        unauth_status = check_license(force_refresh=True)
        assert unauth_status.is_licensed is False
        assert unauth_status.is_dev is False

        # 生成并执行激活
        current_hwid = get_hwid()
        lic = sign_license(hwid=current_hwid, days=30, remark="新用户激活")
        code = format_license_code(lic)

        ok, msg = activate_license(code)
        assert ok is True
        assert "激活成功" in msg

        # 验证激活后状态
        auth_status = check_license(force_refresh=True)
        assert auth_status.is_licensed is True
        assert auth_status.is_dev is False
        assert auth_status.remark == "新用户激活"

    finally:
        os.environ.pop("FORCE_LICENSE_CHECK", None)
        lic_file = os.path.join(os.getcwd(), "license.lic")
        if os.path.exists(lic_file):
            try:
                os.remove(lic_file)
            except Exception:
                pass
