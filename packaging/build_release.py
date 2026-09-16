#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自动化构建与发布包生成器 (Build Release)
一键完成：
1. 依赖检测与 PyInstaller 自动安装
2. 缓存清理与独立二进制编译 (PyInstaller spec)
3. 绿色免安装版 (Portable Zip) 自动组装与压缩
4. Inno Setup 安装包 (Setup.exe) 智能探测与编译
5. SHA256 校验和清单生成
"""

import os
import sys
import shutil
import zipfile
import hashlib
import subprocess

# Windows 控制台字符编码兼容配置，防止 emoji 抛出 UnicodeEncodeError
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 消除代理导致的 pip 或 urllib 异常
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

VERSION = "1.0.0"
APP_NAME = "XMU_Gym_Booking"
PACKAGING_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGING_DIR)
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
TARGET_DIR = os.path.join(DIST_DIR, APP_NAME)


def log(msg: str):
    print(f"[BUILD] {msg}")


def check_and_install_dependencies():
    """检查并确保 PyInstaller 等核心打包工具就绪"""
    log("正在检查编译依赖...")
    # 确保 backports.tarfile 存在，防止 setuptools 报错
    try:
        import backports.tarfile
    except ImportError:
        log("检测到缺失 backports.tarfile，正在自动安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "backports.tarfile", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"])

    try:
        import PyInstaller
        log(f"已检测到 PyInstaller 版本: {PyInstaller.__version__}")
    except ImportError:
        log("未检测到 PyInstaller，正在通过清华镜像自动安装...")
        cmd = [sys.executable, "-m", "pip", "install", "pyinstaller", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
        subprocess.check_call(cmd)
        log("PyInstaller 安装成功！")

    # 确保 pywebview 存在 (桌面原生无黑框窗口依赖)
    try:
        import webview
        log("已检测到 pywebview 桌面原生窗口库")
    except ImportError:
        log("未检测到 pywebview，正在自动安装...")
        cmd = [sys.executable, "-m", "pip", "install", "pywebview", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
        subprocess.check_call(cmd)
        log("pywebview 安装成功！")


def clean_build_artifacts():
    """清理历史构建缓存与目录"""
    log("正在清理历史构建缓存...")
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/F", "/IM", f"{APP_NAME}.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    for d in [BUILD_DIR, TARGET_DIR]:
        if os.path.exists(d):
            try:
                shutil.rmtree(d)
                log(f"已清理目录: {d}")
            except Exception as e:
                log(f"清理 {d} 时出现警告: {e}")


def run_pyinstaller():
    """执行 PyInstaller 核心编译"""
    spec_file = os.path.join(PACKAGING_DIR, "XMU_Gym_Booking.spec")
    if not os.path.exists(spec_file):
        raise FileNotFoundError(f"未找到 Spec 文件: {spec_file}")

    log(f"开始执行 PyInstaller 编译 (读取 {spec_file})...")
    cmd = [
        "pyinstaller",
        "--clean",
        "--noconfirm",
        f"--distpath={DIST_DIR}",
        f"--workpath={BUILD_DIR}",
        spec_file
    ]
    subprocess.check_call(cmd, cwd=PROJECT_ROOT)
    log("PyInstaller 编译完成！")


def post_process_portable_distribution():
    """完善免安装便携版目录，写入快捷批处理启动器"""
    log("正在后处理便携版分发目录...")
    exe_file = os.path.join(TARGET_DIR, f"{APP_NAME}.exe")
    if not os.path.exists(exe_file):
        raise FileNotFoundError(f"编译产物缺失: 未找到 {exe_file}")

    # 1. 确保 config 模板齐全
    cfg_dir = os.path.join(TARGET_DIR, "config")
    os.makedirs(cfg_dir, exist_ok=True)
    src_example = os.path.join(PROJECT_ROOT, "config", "config.example.yaml")
    if os.path.exists(src_example):
        shutil.copy(src_example, os.path.join(cfg_dir, "config.example.yaml"))

    # 2. 预创建日志目录 logs/
    logs_dir = os.path.join(TARGET_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # 3. 复制 WebView2 核心运行时 DLL 到 EXE 根目录（确保 Windows 各路径模式下 100% 成功加载 WebView2 窗口）
    w_lib = os.path.join(TARGET_DIR, "_internal", "webview", "lib")
    if os.path.exists(w_lib):
        for f in ["Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll"]:
            src = os.path.join(w_lib, f)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(TARGET_DIR, f))
        native_loader = os.path.join(w_lib, "runtimes", "win-x64", "native", "WebView2Loader.dll")
        if os.path.exists(native_loader):
            shutil.copy2(native_loader, os.path.join(TARGET_DIR, "WebView2Loader.dll"))

    # 4. 复制应用高清图标
    icon_src = os.path.join(PACKAGING_DIR, "app_icon.ico")
    if os.path.exists(icon_src):
        shutil.copy2(icon_src, os.path.join(TARGET_DIR, "app_icon.ico"))

    log(f"便携版目录就绪 (已完成极简精简): {TARGET_DIR}")


def make_portable_zip() -> str:
    """将便携版目录打包为 Zip 压缩包"""
    zip_filename = f"{APP_NAME}_v{VERSION}_Portable_Windows_x64.zip"
    zip_path = os.path.join(DIST_DIR, zip_filename)
    if os.path.exists(zip_path):
        os.remove(zip_path)

    log(f"正在压缩生成绿色便携版: {zip_filename}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(TARGET_DIR):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, DIST_DIR)
                zf.write(abs_path, rel_path)

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    log(f"✅ 绿色便携版压缩完成: {zip_path} ({size_mb:.2f} MB)")
    return zip_path


def find_iscc() -> str:
    """寻找本地 Inno Setup 编译器 ISCC.exe"""
    candidates = [
        shutil.which("iscc"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        r"C:\Program Files\Inno Setup 5\ISCC.exe",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def build_installer_if_possible() -> str:
    """如果存在 Inno Setup，则编译 Windows 安装向导 EXE"""
    iscc = find_iscc()
    iss_file = os.path.join(PACKAGING_DIR, "installer.iss")

    if not iscc:
        log("⚠️ 本地未检测到 Inno Setup 编译器 (ISCC.exe)。")
        log("   - 若需要本地生成 Setup 安装包，可从官网下载安装 Inno Setup 6: https://jrsoftware.org/isdl.php")
        log("   - 本项目已配置 GitHub Actions CI/CD 流水线，推送 Tag 后云端会自动编译 Setup 安装包！")
        return None

    log(f"检测到 Inno Setup 编译器: {iscc}，正在编译安装包向导...")
    cmd = [iscc, iss_file]
    subprocess.check_call(cmd, cwd=PACKAGING_DIR)

    setup_exe = os.path.join(DIST_DIR, f"{APP_NAME}_Setup_v{VERSION}.exe")
    if os.path.exists(setup_exe):
        size_mb = os.path.getsize(setup_exe) / (1024 * 1024)
        log(f"🎉 [成功] Windows 安装向导包已生成: {setup_exe} ({size_mb:.2f} MB)")
        return setup_exe
    return None


def generate_sha256sums():
    """生成发布文件的 SHA256 校验清单"""
    log("正在计算发布文件 SHA256 校验和...")
    sums_file = os.path.join(DIST_DIR, "SHA256SUMS.txt")
    lines = []

    for name in os.listdir(DIST_DIR):
        if name.endswith((".zip", ".exe")) and name != "SHA256SUMS.txt":
            fp = os.path.join(DIST_DIR, name)
            if os.path.isfile(fp):
                h = hashlib.sha256()
                with open(fp, "rb") as f:
                    while chunk := f.read(8192 * 1024):
                        h.update(chunk)
                sha = h.hexdigest()
                lines.append(f"{sha}  {name}")
                log(f"  {name}: {sha}")

    if lines:
        with open(sums_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log(f"校验清单已保存至: {sums_file}")


def main():
    print("=" * 72)
    print(f"       厦大体育馆自动预约工具 v{VERSION} - 独立发布包自动化构建")
    print("=" * 72)

    try:
        check_and_install_dependencies()
        clean_build_artifacts()
        run_pyinstaller()
        post_process_portable_distribution()
        make_portable_zip()
        build_installer_if_possible()
        generate_sha256sums()

        print("\n" + "=" * 72)
        print("🎉 全部构建流程顺利完成！产物位于 dist/ 目录：")
        print(f"📁 便携解压版目录: {TARGET_DIR}")
        print(f"📦 便携版压缩包:   dist/{APP_NAME}_v{VERSION}_Portable_Windows_x64.zip")
        setup_file = os.path.join(DIST_DIR, f"{APP_NAME}_Setup_v{VERSION}.exe")
        if os.path.exists(setup_file):
            print(f"💿 Windows 安装向导: dist/{APP_NAME}_Setup_v{VERSION}.exe")
        print("=" * 72 + "\n")

    except Exception as e:
        print(f"\n❌ 构建过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
