# -*- coding: utf-8 -*-
"""
安全与授权防护核心模块 (Security & License Guard)
提供硬件指纹计算 (HWID)、非对称加密签名鉴权与热激活支持。
"""

from .hwid import get_hwid, get_hardware_info, copy_hwid_to_clipboard
from .auth import check_license, activate_license, get_auth_status, is_dev_mode

__all__ = [
    "get_hwid",
    "get_hardware_info",
    "copy_hwid_to_clipboard",
    "check_license",
    "activate_license",
    "get_auth_status",
    "is_dev_mode"
]
