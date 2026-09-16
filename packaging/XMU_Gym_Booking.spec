# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包构建规范 (Spec)
目标：构建独立、免 Python 环境的厦大体育馆自动预约工具 (Windows x64)
特点：
1. 自动定位并打包 ddddocr 的全部 ONNX 模型文件；
2. 排除 Anaconda 环境中无关的巨型机器学习与绘图库，大幅减小打包体积；
3. 注入产品图标与 Windows 元信息。
"""

import os
import sys
import glob

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 动态获取项目根目录
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.abspath(os.path.join(SPEC_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

# 动态探测 ddddocr 所在目录并提取所需模型文件
# 瘦身关键：ddddocr 字母验证码默认仅加载 common_old.onnx (12.98 MB)，
# 排除 common.onnx (51.58 MB) 和 common_det.onnx (19.20 MB) 可立省 70.8 MB 冗余体积
import ddddocr
ddddocr_dir = os.path.dirname(ddddocr.__file__)
onnx_datas = []
target_model = os.path.join(ddddocr_dir, "common_old.onnx")
if os.path.exists(target_model):
    onnx_datas.append((target_model, "ddddocr"))
else:
    for p in glob.glob(os.path.join(ddddocr_dir, "*.onnx")):
        onnx_datas.append((p, "ddddocr"))

print(f"[*] Collected ddddocr models: {[os.path.basename(x[0]) for x in onnx_datas]}")

# 动态收集 pywebview 的 WebView2 与 WinForms 原生库，杜绝打包后找不到 DLL
import webview
webview_datas = []
w_dir = os.path.dirname(webview.__file__)
w_lib = os.path.join(w_dir, "lib")
if os.path.exists(w_lib):
    for f in ["Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebBrowserInterop.x64.dll"]:
        p = os.path.join(w_lib, f)
        if os.path.exists(p):
            webview_datas.append((p, "."))
            webview_datas.append((p, "webview/lib"))
    native_loader = os.path.join(w_lib, "runtimes", "win-x64", "native", "WebView2Loader.dll")
    if os.path.exists(native_loader):
        webview_datas.append((native_loader, "."))
        webview_datas.append((native_loader, "runtimes/win-x64/native"))
        webview_datas.append((native_loader, "webview/lib/runtimes/win-x64/native"))

print(f"[*] Collected pywebview native components: {[os.path.basename(x[0]) for x in webview_datas]}")

# 动态收集 xdty_booking/security 下的原生动态库 (如 pyarmor_runtime.pyd)
sec_binaries = []
sec_path = os.path.join(PROJECT_ROOT, "xdty_booking", "security")
if os.path.exists(sec_path):
    for root, dirs, files in os.walk(sec_path):
        for f in files:
            if f.endswith((".pyd", ".dll")):
                full_p = os.path.join(root, f)
                rel_dir = os.path.relpath(root, PROJECT_ROOT)
                sec_binaries.append((full_p, rel_dir))

# 组装数据文件
datas = [
    (os.path.join(PROJECT_ROOT, "config", "config.example.yaml"), "config"),
    (os.path.join(SPEC_DIR, "app_icon.ico"), "."),
] + onnx_datas + webview_datas + sec_binaries

# 包含的高级配置模板（如果存在）
adv_cfg = os.path.join(PROJECT_ROOT, "config", "config.advanced.example.yaml")
if os.path.exists(adv_cfg):
    datas.append((adv_cfg, "config"))

# 隐式导入清单，防止动态加载丢失
hidden_imports = [
    "xdty_booking",
    "xdty_booking.config",
    "xdty_booking.api",
    "xdty_booking.api.client",
    "xdty_booking.api.endpoints",
    "xdty_booking.auth",
    "xdty_booking.auth.session_manager",
    "xdty_booking.auth.sniffer_proxy",
    "xdty_booking.auth.wechat_harvester",
    "xdty_booking.auth.harvester_service",
    "xdty_booking.auth.cert_generator",
    "xdty_booking.auth.proxy_manager",
    "xdty_booking.core",
    "xdty_booking.core.booking_engine",
    "xdty_booking.core.models",
    "xdty_booking.core.scheduler",
    "xdty_booking.core.time_sync",
    "xdty_booking.notify",
    "xdty_booking.notify.notifier",
    "xdty_booking.notify.channels",
    "xdty_booking.notify.channels.base",
    "xdty_booking.notify.channels.email_smtp",
    "xdty_booking.notify.channels.pushplus",
    "xdty_booking.notify.channels.serverchan",
    "xdty_booking.notify.channels.bark",
    "xdty_booking.solver",
    "xdty_booking.solver.captcha_solver",
    "xdty_booking.utils",
    "xdty_booking.utils.logger",
    "xdty_booking.web",
    "xdty_booking.web.server",
    "xdty_booking.web.template",
    "xdty_booking.security",
    "xdty_booking.security.auth",
    "xdty_booking.security.hwid",
    "cryptography",
    "cryptography.x509",
    "cryptography.x509.oid",
    "cryptography.hazmat",
    "cryptography.hazmat.primitives",
    "cryptography.hazmat.primitives.hashes",
    "cryptography.hazmat.primitives.serialization",
    "cryptography.hazmat.primitives.asymmetric",
    "cryptography.hazmat.primitives.asymmetric.rsa",
    "cryptography.hazmat.backends",
    "cryptography.hazmat.backends.openssl",
    "rsa",
    "ddddocr",
    "onnxruntime",
    "PIL",
    "PIL.Image",
    "yaml",
    "requests",
    "urllib3",
    "psutil",
    "http.server",
    "webbrowser",
    "multiprocessing",
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "clr",
    "pythonnet",
]

# 排除 Anaconda 冗余巨型库与不必要的 OpenCV，使发布包清爽小巧 (省下 136MB)
excludes = [
    "torch", "torchaudio", "torchvision",
    "tensorflow", "tensorboard",
    "scipy", "pandas", "matplotlib", "seaborn", "statsmodels",
    "notebook", "jupyter", "IPython", "ipykernel",
    "spyder", "spyder_kernels",
    "sympy", "sklearn", "pyodbc", "PyQt5", "PyQt6", "PySide2", "PySide6",
    "pytest", "tests",
    "cv2", "_cv2", "opencv", "opencv_python",
]

icon_path = os.path.join(SPEC_DIR, "app_icon.ico")
if not os.path.exists(icon_path):
    icon_path = None

custom_hooks = []
try:
    import webview.__pyinstaller as wp
    custom_hooks.append(os.path.dirname(wp.__file__))
except Exception:
    pass

a = Analysis(
    [os.path.join(SPEC_DIR, "launcher.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=custom_hooks,
    hooksconfig={},
    runtime_hooks=[os.path.join(SPEC_DIR, "hook-cv2-mock.py")],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=None
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="XMU_Gym_Booking",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 彻底消除黑框控制台，直接唤起原生桌面应用窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="XMU_Gym_Booking",
)
