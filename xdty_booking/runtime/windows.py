"""不依赖 WebView2 / CLR 的 Windows 提示与组件修复。"""

import ctypes
import logging
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

logger = logging.getLogger(__name__)
RUNTIME_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
RUNTIME_INSTALLER = "MicrosoftEdgeWebview2Setup.exe"


def message(text, title="厦大体育馆自动预约工具", flags=0x10):
    if sys.platform == "win32":
        return ctypes.windll.user32.MessageBoxW(None, text, title, flags | 0x40000)
    print(title + ": " + text, file=sys.stderr)
    return 2


def choose(title, content, buttons):
    """TaskDialog 自定义按钮；旧系统回退为安装/重试/退出提示。"""
    if sys.platform != "win32":
        return "exit"
    class Button(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("id", ctypes.c_int), ("text", wintypes.LPCWSTR)]

    class Config(ctypes.Structure):
        _pack_ = 1
        _fields_ = [
            ("size", wintypes.UINT), ("parent", wintypes.HWND), ("instance", wintypes.HINSTANCE),
            ("flags", wintypes.UINT), ("common", wintypes.UINT), ("title", wintypes.LPCWSTR),
            ("icon", ctypes.c_void_p), ("instruction", wintypes.LPCWSTR), ("content", wintypes.LPCWSTR),
            ("count", wintypes.UINT), ("buttons", ctypes.POINTER(Button)), ("default", ctypes.c_int),
            ("radio_count", wintypes.UINT), ("radios", ctypes.POINTER(Button)), ("radio_default", ctypes.c_int),
            ("verification", wintypes.LPCWSTR), ("expanded", wintypes.LPCWSTR),
            ("expanded_text", wintypes.LPCWSTR), ("collapsed_text", wintypes.LPCWSTR),
            ("footer_icon", ctypes.c_void_p), ("footer", wintypes.LPCWSTR),
            ("callback", ctypes.c_void_p), ("callback_data", ctypes.c_ssize_t), ("width", wintypes.UINT),
        ]
    try:
        items = (Button * len(buttons))(*[Button(100 + i, label) for i, (_, label) in enumerate(buttons)])
        config = Config()
        config.size = ctypes.sizeof(Config)
        config.flags = 0x8  # 允许关闭窗口；关闭视为退出，不启动浏览器。
        config.title = title
        config.instruction = title
        config.content = content
        config.count = len(buttons)
        config.buttons = items
        config.default = 100
        selected = ctypes.c_int()
        dialog = ctypes.windll.comctl32.TaskDialogIndirect
        dialog.argtypes = [ctypes.POINTER(Config), ctypes.POINTER(ctypes.c_int), ctypes.c_void_p, ctypes.c_void_p]
        dialog.restype = ctypes.c_long
        result = dialog(ctypes.byref(config), ctypes.byref(selected), None, None)
        if result != 0:
            raise OSError("TaskDialog HRESULT: {}".format(result))
        index = selected.value - 100
        return buttons[index][0] if 0 <= index < len(buttons) else "exit"
    except Exception:
        logger.exception("原生 TaskDialog 不可用，使用 MessageBox")
        if any(key == "install" for key, _ in buttons):
            answer = message(content + "\n\n是：安装或修复组件\n否：重试\n取消：退出", title, 0x3)
            return {6: "install", 7: "retry"}.get(answer, "exit")
        answer = message(content + "\n\n是否重试？取消或否将退出。", title, 0x4)
        return "retry" if answer == 6 else "exit"


def runtime_version():
    if sys.platform != "win32":
        return ""
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" + RUNTIME_ID,
                                    0, winreg.KEY_READ | view) as key:
                    value = str(winreg.QueryValueEx(key, "pv")[0])
                    parts = value.split(".")
                    if len(parts) == 4 and all(part.isdigit() for part in parts) and tuple(map(int, parts)) >= (86, 0, 622, 0):
                        return value
            except OSError:
                pass
    return ""


def verify_microsoft_installer(path):
    """执行前检查 Authenticode，不把同名 EXE 当成可信安装器。"""
    if sys.platform != "win32":
        raise RuntimeError("Runtime 安装仅支持 Windows")
    env = os.environ.copy()
    env["XMU_RUNTIME_INSTALLER"] = str(Path(path).resolve())
    # PowerShell 7 父进程可能传入不兼容的 PSModulePath，显式加载目标宿主自带模块。
    script = ("$ErrorActionPreference='Stop'; "
              "Import-Module (Join-Path $PSHOME 'Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop; "
              "$s=Get-AuthenticodeSignature -LiteralPath $env:XMU_RUNTIME_INSTALLER; "
              "if($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match "
              "'(^|,\\s*)O=Microsoft Corporation(,|$)'){exit 0}else{exit 1}")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=0x08000000, timeout=60)
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        logger.error("微软安装器签名验证失败: %s", detail)
        raise RuntimeError("无法验证 WebView2 安装器的微软数字签名，请检查文件及系统验证服务；详情见启动日志")


def install_runtime(app_dir):
    path = Path(app_dir) / "prerequisites" / RUNTIME_INSTALLER
    if not path.is_file():
        raise FileNotFoundError("发布包缺少微软 WebView2 引导安装器：{}".format(path))
    verify_microsoft_installer(path)
    result = subprocess.run([str(path), "/silent", "/install"], timeout=600)
    # 安装器成功仍需验证注册状态；3010 表示需要重启。
    if result.returncode not in (0, 3010) or not runtime_version():
        raise RuntimeError("组件安装未完成（退出码 {}）。引导安装器需要联网，请检查微软下载服务是否可访问、安装权限，或重启 Windows 后重试。".format(result.returncode))


def repair_choice(reason):
    return choose("无法打开应用内界面", reason + "\n\n安装或修复窗口组件需要联网下载 WebView2 Runtime。安装成功后将重新打开应用，不会自动打开默认浏览器。",
                  [("install", "安装 / 修复窗口组件"), ("retry", "重试打开应用"),
                   ("browser", "临时使用浏览器（应急）"), ("exit", "退出程序")])
