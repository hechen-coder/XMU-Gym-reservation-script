#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
厦大体育馆自动预约工具 (XMU Gym Booking) - 独立发布包主启动器
此文件负责：
1. 自动校准运行目录（确保无论从快捷方式还是命令行启动，都能准确定位配置文件与数据）；
2. 兼容命令行参数调用（支持与 main.py 相同的全部 CLI 指令）；
3. 默认在应用内打开；组件缺失时原生修复，浏览器仅由用户主动选择。
"""

import os
import sys
import types
import time
import webbrowser
import threading
import atexit

# 瘦身关键优化：注入 Mock cv2 模块，避免 ddddocr 强依赖 136MB 的 OpenCV 庞大二进制库
if "cv2" not in sys.modules:
    sys.modules["cv2"] = types.ModuleType("cv2")

# 1. 确保工作目录锁定在可执行程序（或工程根目录）同级，避免快捷方式启动路径漂移
if getattr(sys, 'frozen', False):
    # 打包运行环境 (PyInstaller)
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    sys.path.insert(0, APP_DIR)
    os.chdir(APP_DIR)
else:
    # 源码开发运行环境
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, APP_DIR)
    os.chdir(APP_DIR)

# 确保在 Windows GUI (console=False) 模式下，sys.stdout/stderr 始终安全可用
class _SafeStreamWriter:
    def write(self, text):
        pass
    def flush(self):
        pass
    def isatty(self):
        return False

if sys.platform == "win32" and len(sys.argv) > 1:
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            try:
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            except Exception:
                pass
            try:
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            except Exception:
                pass
    except Exception:
        pass

if sys.stdout is None:
    sys.stdout = _SafeStreamWriter()
if sys.stderr is None:
    sys.stderr = _SafeStreamWriter()

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def cli_main():
    # GUI 诊断就绪之前不加载网络、OCR、授权等业务依赖。
    from main import main
    return main()


def _bootstrap():
    import logging
    from logging.handlers import RotatingFileHandler
    from xdty_booking.runtime.paths import prepare_data_dir, log_dir
    logs = log_dir()
    handler = RotatingFileHandler(str(logs / "startup.log"), maxBytes=2 * 1024 * 1024,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    def unhandled(kind, value, tb):
        logging.getLogger("startup").error("启动或运行异常", exc_info=(kind, value, tb))

    sys.excepthook = unhandled
    threading.excepthook = lambda args: unhandled(args.exc_type, args.exc_value, args.exc_traceback)
    logging.getLogger("startup").info("BOOTSTRAP python=%s frozen=%s", sys.version, getattr(sys, "frozen", False))
    target = prepare_data_dir()
    os.chdir(str(target))


def interactive_menu():
    """双击 exe 启动时的交互式控制台导航界面"""
    while True:
        print("\n" + "=" * 66)
        print("       厦大体育馆自动预约工具 (XMU Gym Booking)")
        print("          面向厦大师生的极速预约与定时秒杀神器")
        print("=" * 66)
        print(" 请选择您要执行的功能操作 (输入数字后按回车)：\n")
        print("   [1] 🌐 启动网页预约控制台 (最直观推荐，自动打开浏览器)")
        print("   [2] ⏰ 启动早 7 点准点抢票 (次日票秒杀，提前自检+自动降级)")
        print("   [3] 🔑 微信免抓包凭证截取 (自动唤醒小程序截取凭据)")
        print("   [4] 📊 查询场馆实时余票状态 (表格打印当前名额)")
        print("   [5] 🔍 检测当前登录凭证有效性 (失效自动尝试自愈)")
        print("   [6] 🔄 开启退票捡漏秒杀监控 (持续监听，出票瞬间毫秒秒抢)")
        print("   [7] 📱 测试微信/邮件通知推送")
        print("   [8] 🧪 测试验证码识别 (ddddocr 离线引擎)")
        print("   [0] 🚪 退出程序")
        print("=" * 66)

        try:
            choice = input("请输入选项代号 [默认 1]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n程序已退出。")
            break

        if not choice or choice == "1":
            try:
                launch_desktop_window(browser_mode=True)
            except KeyboardInterrupt:
                print("\nWeb 服务已停止。")
            continue

        elif choice == "2":
            print("\n>>> 正在启动早 7 点定时抢票任务 (睡前挂机，07:00 准点秒杀)...")
            sys.argv = [sys.argv[0], "schedule"]
            try:
                cli_main()
            except KeyboardInterrupt:
                print("\n定时任务已取消。")
            except SystemExit:
                input("\n按回车键返回主菜单...")
            continue

        elif choice == "3":
            print("\n>>> 正在调起微信小程序截取登录凭证...")
            sys.argv = [sys.argv[0], "harvest"]
            try:
                cli_main()
            except SystemExit:
                pass
            except Exception as e:
                print(f"执行出错: {e}")
            input("\n按回车键返回主菜单...")

        elif choice == "4":
            print("\n>>> 正在查询场馆余票信息...")
            sys.argv = [sys.argv[0], "query"]
            try:
                cli_main()
            except SystemExit:
                pass
            except Exception as e:
                print(f"查询出错: {e}")
            input("\n按回车键返回主菜单...")

        elif choice == "5":
            print("\n>>> 正在检测 Session 有效性...")
            sys.argv = [sys.argv[0], "check"]
            try:
                cli_main()
            except SystemExit:
                pass
            except Exception as e:
                print(f"检测出错: {e}")
            input("\n按回车键返回主菜单...")

        elif choice == "6":
            print("\n>>> 正在启动捡漏监听模式...")
            sys.argv = [sys.argv[0], "snipe"]
            try:
                cli_main()
            except KeyboardInterrupt:
                print("\n捡漏已停止。")
            except SystemExit:
                pass
            input("\n按回车键返回主菜单...")

        elif choice == "7":
            print("\n>>> 正在发送测试通知...")
            sys.argv = [sys.argv[0], "test-notify"]
            try:
                cli_main()
            except Exception as e:
                print(f"发送出错: {e}")
            input("\n按回车键返回主菜单...")

        elif choice == "8":
            print("\n>>> 正在测试验证码识别...")
            sys.argv = [sys.argv[0], "test-captcha"]
            try:
                cli_main()
            except Exception as e:
                print(f"测试出错: {e}")
            input("\n按回车键返回主菜单...")

        elif choice == "0":
            print("感谢使用，再见！")
            break
        else:
            print("❌ 无效的选项，请重新输入！")


def _attach_console_for_cli():
    """如果是 CLI 命令行模式且处于无控制台 GUI 编译模式下，附着父进程控制台以输出终端日志"""
    if sys.platform == "win32":
        try:
            import ctypes
            # ATTACH_PARENT_PROCESS = -1
            if ctypes.windll.kernel32.AttachConsole(-1):
                for stream_name in ("stdout", "stderr"):
                    try:
                        setattr(sys, stream_name, open("CONOUT$", "w", encoding="utf-8", errors="replace"))
                    except Exception:
                        pass
        except Exception:
            pass


def _log_gui_msg(msg: str):
    """记录 GUI 运行及异常信息到 logs/gui_error.log"""
    try:
        from datetime import datetime
        from xdty_booking.runtime.paths import log_dir
        logs_dir = str(log_dir())
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "gui_error.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _setup_system_tray(window, url: str, tray_holder: dict):
    """
    在 WinForms 原生 UI 线程 (STA) 上配置系统托盘 (NotifyIcon) 与上下文菜单。
    注意：NotifyIcon 必须挂载在具有激活消息循环 (Application.Run) 的 UI 线程上，
    否则将脱离 Windows 消息循环导致托盘图标的鼠标左键/右键/双击点击全部完全失效！
    """
    try:
        import clr
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Windows.Forms import (
            NotifyIcon, ContextMenuStrip, ToolStripMenuItem, ToolStripSeparator,
            FormWindowState, MouseButtons
        )
        from System.Drawing import Icon, SystemIcons
        from System import Func, Type
        import webview.platforms.winforms as wf

        form = getattr(window, "native", None) or wf.BrowserView.instances.get(window.uid)
        if form is None:
            _log_gui_msg("form is None in _setup_system_tray")
            return

        def _create_tray_on_ui_thread():
            try:
                tray = NotifyIcon()

                # 1. 寻找应用图标
                icon_set = False
                icon_paths = [
                    os.path.join(APP_DIR, "app_icon.ico"),
                    os.path.join(APP_DIR, "packaging", "app_icon.ico"),
                ]
                for p in icon_paths:
                    if os.path.exists(p):
                        try:
                            tray.Icon = Icon(p)
                            icon_set = True
                            break
                        except Exception:
                            pass

                if not icon_set:
                    try:
                        tray.Icon = Icon.ExtractAssociatedIcon(sys.executable)
                    except Exception:
                        tray.Icon = SystemIcons.Application

                tray.Text = "厦大体育馆自动预约工具 (后台运行中)"

                # 核心：无论处于最小化、隐藏还是后台锁定状态，全方位穿透并置顶唤起窗口
                def do_show_window(*args, **kwargs):
                    try:
                        # 1. 尝试 pywebview 原生显示与恢复
                        try:
                            window.show()
                            window.restore()
                        except Exception as e:
                            _log_gui_msg(f"pywebview show/restore error: {e}")

                        # 2. 穿透至底层 WinForms Form 句柄进行强行恢复与前台焦点激活
                        try:
                            form.Visible = True
                            if form.WindowState == FormWindowState.Minimized:
                                form.WindowState = FormWindowState.Normal
                            form.WindowState = FormWindowState.Normal
                            form.Show()
                            form.BringToFront()
                            form.Activate()
                            form.Focus()
                            # 技巧：临时开启置顶再关闭，穿透 Windows 前台窗口激活锁定 (ASFW)
                            form.TopMost = True
                            form.TopMost = False
                        except Exception as e:
                            _log_gui_msg(f"winforms direct restore error: {e}")

                        # 3. 使用 Win32 API 绝对保证还原并置顶 (SW_RESTORE = 9)
                        try:
                            import ctypes
                            hwnd = form.Handle.ToInt64()
                            user32 = ctypes.windll.user32
                            user32.ShowWindow(hwnd, 9)
                            user32.SetForegroundWindow(hwnd)
                            user32.BringWindowToTop(hwnd)
                        except Exception:
                            pass
                    except Exception as e:
                        _log_gui_msg(f"do_show_window fatal error: {e}")

                # 2. 构建托盘右键菜单
                menu = ContextMenuStrip()

                def on_browser_clicked(sender, args):
                    try:
                        import webbrowser
                        webbrowser.open(url)
                    except Exception as e:
                        _log_gui_msg(f"on_browser_clicked error: {e}")

                def on_log_clicked(sender, args):
                    try:
                        from System.Windows.Forms import MessageBox, MessageBoxButtons, MessageBoxIcon
                        from xdty_booking.runtime.paths import data_dir
                        log_file = str(data_dir() / "logs" / "booking.log")
                        logs_dir = str(data_dir() / "logs")
                        if os.path.exists(log_file):
                            os.startfile(log_file)
                        elif os.path.exists(os.path.join(APP_DIR, "booking.log")):
                            os.startfile(os.path.join(APP_DIR, "booking.log"))
                        elif os.path.exists(logs_dir):
                            os.startfile(logs_dir)
                        else:
                            MessageBox.Show("暂未生成运行日志文件 (logs/booking.log)", "提示", MessageBoxButtons.OK, MessageBoxIcon.Information)
                    except Exception as e:
                        _log_gui_msg(f"on_log_clicked error: {e}")

                def on_quit_clicked(sender, args):
                    try:
                        tray.Visible = False
                        tray.Dispose()
                    except Exception:
                        pass
                    try:
                        window._force_close = True
                        window.destroy()
                    except Exception:
                        pass
                    return

                item_show = ToolStripMenuItem("🖥️ 显示主界面")
                item_show.Click += do_show_window
                item_browser = ToolStripMenuItem("🌐 在浏览器中打开")
                item_browser.Click += on_browser_clicked
                item_log = ToolStripMenuItem("📄 查看运行日志")
                item_log.Click += on_log_clicked
                sep = ToolStripSeparator()
                item_quit = ToolStripMenuItem("🚪 彻底退出程序")
                item_quit.Click += on_quit_clicked

                menu.Items.Add(item_show)
                menu.Items.Add(item_browser)
                menu.Items.Add(item_log)
                menu.Items.Add(sep)
                menu.Items.Add(item_quit)

                tray.ContextMenuStrip = menu

                # 响应鼠标左键单击托盘图标直接呼出主界面
                def on_tray_mouse_click(sender, e):
                    try:
                        if e.Button == MouseButtons.Left:
                            do_show_window()
                    except Exception as ex:
                        _log_gui_msg(f"on_tray_mouse_click error: {ex}")

                tray.MouseClick += on_tray_mouse_click
                tray.DoubleClick += do_show_window
                tray.BalloonTipClicked += do_show_window
                tray.Visible = True

                tray_holder["tray"] = tray
                _log_gui_msg("System tray NotifyIcon successfully initialized on WinForms UI thread!")
            except Exception as e:
                _log_gui_msg(f"_create_tray_on_ui_thread error: {e}")

        if form.InvokeRequired:
            form.Invoke(Func[Type](_create_tray_on_ui_thread))
        else:
            _create_tray_on_ui_thread()
    except Exception as e:
        _log_gui_msg(f"_setup_system_tray init error: {e}")


_SINGLE_INSTANCE_MUTEX = None


def check_single_instance(app_title: str = "厦大体育馆自动预约工具", show_dialog: bool = True) -> bool:
    """
    使用 Windows 原生命名互斥体 (Named Mutex) 实现严格的单实例互斥检测。
    如果检测到已有实例在运行：
    1. 自动查找首个实例的主窗口并将其恢复/置顶至屏幕最前端；
    2. 弹出系统级置顶提示框提醒用户“程序已在运行中（已打开）”；
    3. 返回 False 通知调用方立即退出，彻底杜绝重复进程多开。
    """
    global _SINGLE_INSTANCE_MUTEX
    if sys.platform != "win32":
        return True

    try:
        import ctypes

        ERROR_ALREADY_EXISTS = 183
        MUTEX_NAME = "Local\\XMU_Gym_Booking_Desktop_SingleInstance_Mutex"

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        from ctypes import wintypes
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]

        # 尝试创建命名互斥体
        mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        last_error = kernel32.GetLastError()
        if not mutex:
            raise OSError(last_error, "无法创建单实例互斥体")

        if last_error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(mutex)
            # 尝试查找已运行的前台窗口并唤醒恢复
            try:
                hwnd = user32.FindWindowW(None, app_title)
                if not hwnd:
                    for title in ("无法打开应用内界面", "预约工具 — 应急浏览器模式"):
                        hwnd = user32.FindWindowW(None, title)
                        if hwnd:
                            break
                if hwnd:
                    # SW_RESTORE = 9
                    user32.ShowWindow(hwnd, 9)
                    user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

            if show_dialog:
                # 弹出系统级置顶提示框 (MB_OK | MB_ICONINFORMATION | MB_TOPMOST)
                MB_OK = 0x00000000
                MB_ICONINFORMATION = 0x00000040
                MB_TOPMOST = 0x00040000
                user32.MessageBoxW(
                    None,
                    f"【{app_title}】已在运行中（已打开或正在启动）！\n\n请查看已有窗口或组件修复窗口，勿重复启动。",
                    f"{app_title} - 运行提示",
                    MB_OK | MB_ICONINFORMATION | MB_TOPMOST
                )
            return False

        _SINGLE_INSTANCE_MUTEX = mutex
        atexit.register(release_single_instance)
        return True
    except Exception as e:
        _log_gui_msg(f"check_single_instance exception: {e}")
        raise


def release_single_instance():
    """显式释放当前进程持有的互斥体句柄"""
    global _SINGLE_INSTANCE_MUTEX
    if _SINGLE_INSTANCE_MUTEX and sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(_SINGLE_INSTANCE_MUTEX)
        except Exception:
            pass
        _SINGLE_INSTANCE_MUTEX = None


def _browser_session(service):
    """Only entered by an explicit user choice; keep a native exit control."""
    from xdty_booking.runtime.windows import choose, message
    while service.thread.is_alive():
        if not webbrowser.open(service.url):
            message("Unable to open the browser. Local address: " + service.url)
        action = choose("预约工具 — 应急浏览器模式",
                        "关闭浏览器标签页后本地服务仍在运行。退出程序将停止已开启的任务。",
                        [("retry", "重新打开浏览器"), ("exit", "退出程序")])
        if action != "retry":
            return
    raise RuntimeError("Local HTTP service stopped unexpectedly") from service.error


def _run_gui(service):
    import webview
    from xdty_booking.runtime.windows import choose
    from xdty_booking.runtime.paths import data_dir
    loaded = threading.Event()
    finished = threading.Event()
    failed = threading.Event()
    tray_holder = {"tray": None, "initialized": False}
    window = webview.create_window(title="厦大体育馆自动预约工具", url=service.url,
                                   width=1120, height=820, min_size=(900, 650))

    def on_closing():
        if failed.is_set() or getattr(window, "_force_close", False):
            return True
        action = choose("关闭预约工具", "已开启的任务仅在程序运行期间继续执行。",
                        [("hide", "最小化到托盘"), ("exit", "退出程序"), ("cancel", "取消")])
        if action == "hide":
            if tray_holder["tray"] is not None:
                window.hide()
            else:
                from xdty_booking.runtime.windows import message
                message("托盘未创建成功，窗口将保持显示。")
            return False
        return action == "exit"

    window.events.closing += on_closing
    window.events.loaded += lambda: loaded.set()
    def on_shown():
        import webview.platforms.winforms as wf
        if wf.renderer != "edgechromium":
            failed.set()
            window.destroy()
            return
        if not tray_holder["initialized"]:
            tray_holder["initialized"] = True
            _setup_system_tray(window, service.url, tray_holder)

    window.events.shown += on_shown

    def watch():
        deadline = time.monotonic() + 30
        while not finished.wait(0.25):
            if not service.thread.is_alive() or (not loaded.is_set() and time.monotonic() >= deadline):
                failed.set()
                _log_gui_msg("GUI initialization timeout or local service stopped")
                window.destroy()
                return

    try:
        threading.Thread(target=watch, name="DesktopWatchdog", daemon=True).start()
        webview.start(gui="edgechromium", storage_path=str(data_dir() / "webview-cache"))
        if failed.is_set() or not loaded.is_set():
            raise RuntimeError("应用内页面未能完成加载，请查看启动日志后修复组件或重试")
    finally:
        finished.set()
        tray = tray_holder.get("tray")
        if tray is not None:
            tray.Visible = False
            tray.Dispose()


def _restart_application():
    import subprocess
    count = int(os.environ.get("XMU_REPAIR_RESTARTS", "0"))
    if count >= 2:
        raise RuntimeError("组件修复重启次数已达上限，请查看日志，关闭程序后手动重试")
    env = os.environ.copy()
    env["XMU_REPAIR_RESTARTS"] = str(count + 1)
    command = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, __file__]
    subprocess.Popen(command + sys.argv[1:], cwd=APP_DIR, env=env)


def launch_desktop_window(port: int = 8080, browser_mode=False):
    """应用内打开；GUI 失败先修复，不自动启动浏览器。"""
    from xdty_booking.runtime.windows import runtime_version, repair_choice, install_runtime, message
    if not check_single_instance():
        return
    service = None
    restart = False
    try:
        for attempt in range(3):
            if not browser_mode and not runtime_version():
                action = repair_choice("未检测到可用的 WebView2 Runtime。")
            else:
                if service is None:
                    from xdty_booking.web.server import create_web_service
                    service = create_web_service(port=port, auto_port=not browser_mode)
                    service.start()
                    service.start_monitor()
                    _log_gui_msg("HTTP_READY " + service.url)
                if browser_mode:
                    _browser_session(service)
                    return
                try:
                    _run_gui(service)
                    return
                except Exception:
                    import traceback
                    _log_gui_msg(traceback.format_exc())
                    if not service.thread.is_alive():
                        raise RuntimeError("本地服务已停止，请查看启动日志") from service.error
                    action = repair_choice("独立窗口初始化失败。详情见 logs/startup.log 和 gui_error.log。")
            if action == "install":
                try:
                    install_runtime(APP_DIR)
                    restart = True
                    break
                except Exception as exc:
                    _log_gui_msg("Runtime repair failed: " + str(exc))
                    message(str(exc))
            elif action == "browser":
                browser_mode = True
            elif action == "retry" and service is not None:
                # CLR / GUI 已初始化后不在同一进程重建消息循环。
                restart = True
                break
            elif action != "retry":
                return
        else:
            message("重试次数已达上限。请查看启动日志后重新启动程序。")
    finally:
        if service:
            service.close()
        release_single_instance()
    if restart:
        _restart_application()


def entry_point():
    """程序总入口"""
    if len(sys.argv) > 1:
        arg1 = sys.argv[1].lower()
        if arg1 == "self-test":
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument("action")
            parser.add_argument("--output", required=True)
            args = parser.parse_args()
            from xdty_booking.runtime.diagnostics import run_self_test
            raise SystemExit(run_self_test(args.output))
        if arg1 in ("gui", "desktop"):
            launch_desktop_window()
            return
        elif arg1 in ("menu", "console"):
            interactive_menu()
            return

        # 挂载控制台并分发给 CLI 命令行执行
        _attach_console_for_cli()
        if arg1 == "web":
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument("action")
            parser.add_argument("--port", type=int, default=8080)
            parser.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
            args = parser.parse_args()
            launch_desktop_window(port=args.port, browser_mode=True)
            return
        cli_main()
    else:
        # 无参数双击启动：直接打开现代独立原生窗口
        launch_desktop_window()


if __name__ == "__main__":
    try:
        _bootstrap()
        entry_point()
    except Exception as exc:
        import traceback
        _log_gui_msg(traceback.format_exc())
        from xdty_booking.runtime.windows import message
        message("启动失败：{}\n\n请查看 logs/startup.log 或 gui_error.log。".format(exc))
        sys.exit(1)
