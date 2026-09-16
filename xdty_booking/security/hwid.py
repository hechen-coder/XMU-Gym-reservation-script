# -*- coding: utf-8 -*-
"""
硬件设备指纹采集器 (Hardware Identification / HWID)
基于物理主板 UUID、CPU 硬件标识、系统盘出厂序列号生成全球唯一机器码。
专为 Windows 环境打造，兼容 Win10/Win11 及精简版系统，具备高容错与防漂移机制。
"""

import os
import sys
import hashlib
import subprocess
import winreg
from typing import Dict, Optional, Tuple

_CACHED_HWID: Optional[str] = None
_CACHED_DETAILS: Optional[Dict[str, str]] = None


def _clean_str(val: Optional[str]) -> str:
    """清理并规范化硬件字符串"""
    if not val:
        return ""
    val = val.strip().replace("\r", "").replace("\n", "").replace(" ", "").replace("-", "")
    val = val.upper()
    # 过滤虚拟机或劣质驱动中的无效占位字符串
    invalid_tokens = (
        "NONE", "DEFAULTSTRING", "TOBEFILLEDBYOEM", "SYSTEMSERIALNUMBER",
        "00000000", "FFFFFFFF", "UNKNOWN", "NOTAPPLICABLE"
    )
    for token in invalid_tokens:
        if token in val:
            return ""
    return val


def _get_registry_value(root_key, sub_key: str, value_name: str) -> str:
    """从 Windows 注册表快速静默读取键值"""
    try:
        with winreg.OpenKey(root_key, sub_key) as k:
            val, _ = winreg.QueryValueEx(k, value_name)
            return str(val).strip()
    except Exception:
        return ""


def _get_c_volume_serial() -> str:
    """通过 Windows 原生 API 极速获取 C 盘卷序列号 (微秒级兜底)"""
    try:
        import ctypes
        vol_serial = ctypes.c_ulong()
        res = ctypes.windll.kernel32.GetVolumeInformationW(
            "C:\\", None, 0, ctypes.byref(vol_serial), None, None, None, 0
        )
        if res != 0 and vol_serial.value != 0:
            return hex(vol_serial.value).upper().replace("0X", "")
    except Exception:
        pass
    return ""


def _query_powershell_hardware() -> Tuple[str, str, str]:
    """
    通过 PowerShell CIM 接口一次性静默提取核心物理特征
    (无控制台黑框弹出，针对 Win11 24H2 废弃 WMIC 做了完全适配)
    """
    script = (
        "$mb=''; try { $mb = (Get-CimInstance Win32_ComputerSystemProduct).UUID } catch {}; "
        "$cpu=''; try { $cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).ProcessorId } catch {}; "
        "$disk=''; try { $disk = (Get-CimInstance Win32_DiskDrive | Select-Object -First 1).SerialNumber } catch {}; "
        "Write-Output ($mb + '|||' + $cpu + '|||' + $disk)"
    )
    creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            creationflags=creationflags,
            timeout=4.0
        )
        if proc.returncode == 0 and proc.stdout:
            parts = proc.stdout.strip().split("|||")
            if len(parts) == 3:
                return parts[0].strip(), parts[1].strip(), parts[2].strip()
    except Exception:
        pass
    return "", "", ""


def _query_wmic_hardware() -> Tuple[str, str, str]:
    """针对旧版 Windows (Win7/Win10旧版) 的 WMIC 兼容回退方案"""
    creationflags = 0x08000000 if sys.platform == "win32" else 0
    mb, cpu, disk = "", "", ""
    try:
        r = subprocess.run(["wmic", "csproduct", "get", "uuid"], capture_output=True, text=True, creationflags=creationflags, timeout=2.0)
        lines = [line.strip() for line in r.stdout.splitlines() if line.strip() and "UUID" not in line]
        if lines:
            mb = lines[0]
    except Exception:
        pass

    try:
        r = subprocess.run(["wmic", "cpu", "get", "processorid"], capture_output=True, text=True, creationflags=creationflags, timeout=2.0)
        lines = [line.strip() for line in r.stdout.splitlines() if line.strip() and "ProcessorId" not in line]
        if lines:
            cpu = lines[0]
    except Exception:
        pass

    try:
        r = subprocess.run(["wmic", "diskdrive", "get", "serialnumber"], capture_output=True, text=True, creationflags=creationflags, timeout=2.0)
        lines = [line.strip() for line in r.stdout.splitlines() if line.strip() and "SerialNumber" not in line]
        if lines:
            disk = lines[0]
    except Exception:
        pass

    return mb, cpu, disk


def get_hardware_info() -> Dict[str, str]:
    """采集原始硬件标识明细字典"""
    global _CACHED_DETAILS
    if _CACHED_DETAILS is not None:
        return _CACHED_DETAILS

    mb, cpu, disk = _query_powershell_hardware()

    # 如果 PowerShell 读取不全，尝试 WMIC 补充
    if not (mb and cpu and disk):
        w_mb, w_cpu, w_disk = _query_wmic_hardware()
        mb = mb or w_mb
        cpu = cpu or w_cpu
        disk = disk or w_disk

    # 注册表与系统底层 API 终极兜底
    if not mb:
        mb = _get_registry_value(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", "MachineGuid")
    if not cpu:
        cpu = _get_registry_value(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "Identifier")
    if not disk:
        disk = _get_c_volume_serial()

    details = {
        "motherboard_uuid": mb or "UNKNOWN_MB",
        "cpu_id": cpu or "UNKNOWN_CPU",
        "disk_serial": disk or "UNKNOWN_DISK"
    }
    _CACHED_DETAILS = details
    return details


def get_hwid() -> str:
    """
    计算当前电脑的唯一机器识别码 (HWID)
    输出格式为便于阅读与发送的标准格式：XMU-XXXX-XXXX-XXXX-XXXX (16位哈希)
    """
    global _CACHED_HWID
    if _CACHED_HWID is not None:
        return _CACHED_HWID

    info = get_hardware_info()
    c_mb = _clean_str(info["motherboard_uuid"]) or "DEFAULT_MB"
    c_cpu = _clean_str(info["cpu_id"]) or "DEFAULT_CPU"
    c_disk = _clean_str(info["disk_serial"]) or "DEFAULT_DISK"

    # 固定加盐拼接硬件物理指纹
    raw = f"HWID::MB={c_mb}::CPU={c_cpu}::DISK={c_disk}::SALT=XMU_GYM_2026_SEC"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()

    # 格式化为 4x4 的标准商业序列号格式: XMU-XXXX-XXXX-XXXX-XXXX
    hwid = f"XMU-{digest[0:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:16]}"
    _CACHED_HWID = hwid
    return hwid


def copy_hwid_to_clipboard() -> bool:
    """将本机机器码自动复制到 Windows 系统剪贴板"""
    hwid = get_hwid()
    # 方案 1: pywin32 clipboard
    try:
        import win32clipboard
        import win32con
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, hwid)
        win32clipboard.CloseClipboard()
        return True
    except Exception:
        pass

    # 方案 2: clip.exe 系统原生命令
    try:
        creationflags = 0x08000000 if sys.platform == "win32" else 0
        p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, creationflags=creationflags)
        p.communicate(hwid.encode("utf-16le"))
        return True
    except Exception:
        pass

    return False


if __name__ == "__main__":
    print("=" * 60)
    print("     厦门大学体育馆预约助手 - 本机硬件指纹检测")
    print("=" * 60)
    info = get_hardware_info()
    for k, v in info.items():
        print(f"  [{k}]: {v}")
    code = get_hwid()
    print("-" * 60)
    print(f"  >> 本机唯一机器码 (HWID): {code}")
    if copy_hwid_to_clipboard():
        print("  >> (已自动复制到剪贴板！)")
    print("=" * 60)
