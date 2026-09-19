#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
厦大体育馆自动预约工具 (XMU Gym Booking) - 独立发布包主启动器
此文件负责：
1. 自动校准运行目录（确保无论从快捷方式还是命令行启动，都能准确定位配置文件与数据）；
2. 兼容命令行参数调用（支持与 main.py 相同的全部 CLI 指令）；
3. 提供小白双击交互控制台（直接双击 exe 时提供优雅的快捷菜单，不闪退并支持自动打开网页版）。
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

# 导入主程序模块
from main import main as cli_main


def _open_browser_delayed(url: str, delay_seconds: float = 1.0):
    """延时自动打开默认浏览器访问 Web 页面"""
    def _task():
        time.sleep(delay_seconds)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    t = threading.Thread(target=_task, daemon=True)
    t.start()


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
            if not check_single_instance():
                input("\n按回车键返回主菜单...")
                continue
            print("\n>>> 正在启动 Web 控制台 (http://localhost:8080)...")
            _open_browser_delayed("http://localhost:8080", delay_seconds=0.8)
            sys.argv = [sys.argv[0], "web"]
            try:
                cli_main()
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
        logs_dir = os.path.join(APP_DIR, "logs")
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
                            hwnd = form.Handle.ToInt32()
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
                        log_file = os.path.join(APP_DIR, "logs", "booking.log")
                        logs_dir = os.path.join(APP_DIR, "logs")
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
                        window.destroy()
                    except Exception:
                        pass
                    os._exit(0)

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


def _patch_pywebview_frozen_loader():
    """
    修复 pywebview 在 PyInstaller 打包环境 (onedir/frozen) 下无法定位 WebView2 DLL 和运行时的官方问题。
    """
    try:
        import webview.util
        _orig_interop_dll_path = webview.util.interop_dll_path

        def _patched_interop(dll_name: str) -> str:
            # 1. 优先尝试原逻辑查找
            try:
                p = _orig_interop_dll_path(dll_name)
                if os.path.exists(p):
                    return p
            except Exception:
                pass

            # 2. 在 PyInstaller 展开目录全面扫描
            candidates_dirs = [
                APP_DIR,
                os.path.join(APP_DIR, "_internal"),
                os.path.join(APP_DIR, "_internal", "webview", "lib"),
                os.path.join(APP_DIR, "webview", "lib"),
            ]
            if hasattr(sys, "_MEIPASS"):
                candidates_dirs.insert(0, sys._MEIPASS)
                candidates_dirs.insert(1, os.path.join(sys._MEIPASS, "webview", "lib"))

            # 如果是平台架构名 (win-arm64, win-x64, win-x86)
            if dll_name in ("win-arm64", "win-x64", "win-x86"):
                for cd in candidates_dirs:
                    target = os.path.join(cd, "runtimes", dll_name, "native")
                    if os.path.exists(target):
                        return target
                    target2 = os.path.join(cd, dll_name)
                    if os.path.exists(target2):
                        return target2
                # 若无非必要架构（如 win-arm64），回退至本机 x64 路径，避免抛出 FileNotFoundError
                for cd in candidates_dirs:
                    target = os.path.join(cd, "runtimes", "win-x64", "native")
                    if os.path.exists(target):
                        return target
                return APP_DIR

            # 如果是具体 DLL 文件名
            for cd in candidates_dirs:
                target = os.path.join(cd, dll_name)
                if os.path.exists(target):
                    return target
                target_sub = os.path.join(cd, "runtimes", "win-x64", "native", dll_name)
                if os.path.exists(target_sub):
                    return target_sub

            # 最终尝试原函数
            return _orig_interop_dll_path(dll_name)

        webview.util.interop_dll_path = _patched_interop
    except Exception:
        pass


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
        MUTEX_NAME = "Global\\XMU_Gym_Booking_Desktop_SingleInstance_Mutex"

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        # 尝试创建命名互斥体
        mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        last_error = kernel32.GetLastError()

        if last_error == ERROR_ALREADY_EXISTS:
            # 尝试查找已运行的前台窗口并唤醒恢复
            try:
                hwnd = user32.FindWindowW(None, app_title)
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
                    f"【{app_title}】已在运行中（已打开）！\n\n已为您自动切换至已打开的窗口，请勿重复运行多个实例。",
                    f"{app_title} - 运行提示",
                    MB_OK | MB_ICONINFORMATION | MB_TOPMOST
                )
            return False

        _SINGLE_INSTANCE_MUTEX = mutex
        atexit.register(release_single_instance)
        return True
    except Exception as e:
        _log_gui_msg(f"check_single_instance exception: {e}")
        return True


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


def launch_desktop_window(port: int = 8080):
    """启动本地 Web 服务并在前台唤起无黑框独立桌面原生窗口"""
    if not check_single_instance():
        sys.exit(0)

    from xdty_booking.web.server import run_server

    # 1. 在后台守护线程启动 Web 核心服务
    server_thread = threading.Thread(
        target=run_server,
        kwargs={"port": port, "config_path": "config/config.yaml"},
        daemon=True,
    )
    server_thread.start()

    # 稍等片刻等待端口启动
    time.sleep(0.3)
    url = f"http://127.0.0.1:{port}"

    # 2. 尝试使用 pywebview 唤起 Windows 原生独立客户端窗口 (Edge WebView2)
    use_gui = False
    tray_holder = {"tray": None}
    try:
        _patch_pywebview_frozen_loader()
        import webview
        try:
            import webview.platforms.winforms as wf
            wf.setup_app()
        except Exception:
            pass

        window = webview.create_window(
            title="厦大体育馆自动预约工具",
            url=url,
            width=1120,
            height=820,
            min_size=(900, 650),
            confirm_close=False,  # 由托盘系统的 on_closing 优雅接管
        )

        # 3. 拦截右上角 [X] 关闭事件，弹出三选对话框（缩小至托盘 / 彻底退出 / 取消）
        def on_closing():
            try:
                import clr
                clr.AddReference("System.Windows.Forms")
                from System.Windows.Forms import MessageBox, MessageBoxButtons, MessageBoxIcon, DialogResult, ToolTipIcon
                res = MessageBox.Show(
                    "是否缩小至系统托盘并在后台保持待命？\n\n"
                    "【是 (Yes)】：缩小至托盘（推荐，后台早 7 点抢票与捡漏服务继续运行）\n"
                    "【否 (No)】 ：彻底退出程序（终止所有后台守护服务）\n"
                    "【取消】    ：取消本次操作，继续留在主界面",
                    "厦大体育馆自动预约工具",
                    MessageBoxButtons.YesNoCancel,
                    MessageBoxIcon.Question
                )
                if res == DialogResult.Yes:
                    window.hide()
                    tray = tray_holder.get("tray")
                    if tray is not None:
                        try:
                            tray.ShowBalloonTip(
                                3000,
                                "厦大体育馆预约助手",
                                "已缩小至系统托盘待命，后台抢票与捡漏服务将继续生效。\n左键单击或双击托盘图标可重新呼出主界面。",
                                ToolTipIcon.Info
                            )
                        except Exception:
                            pass
                    return False  # 取消关闭窗口，保持后台运行
                elif res == DialogResult.Cancel:
                    return False  # 取消操作，停留在当前窗口
                else:  # DialogResult.No
                    tray = tray_holder.get("tray")
                    if tray is not None:
                        try:
                            tray.Visible = False
                            tray.Dispose()
                        except Exception:
                            pass
                    return True   # 允许窗口正常关闭退出
            except Exception as e:
                _log_gui_msg(f"on_closing error: {e}")
                return True

        window.events.closing += on_closing

        # 核心关键：必须在窗口就绪且进入 WinForms UI STA 线程后挂载系统托盘，保证消息泵通畅
        _tray_initialized = False
        def on_window_shown():
            nonlocal _tray_initialized
            if _tray_initialized:
                return
            _tray_initialized = True
            _setup_system_tray(window, url, tray_holder)

        window.events.shown += on_window_shown

        use_gui = True
        webview.start()
    except Exception as e:
        import traceback
        _log_gui_msg(f"launch_desktop_window error: {traceback.format_exc()}")
        use_gui = False
    finally:
        tray = tray_holder.get("tray")
        if tray is not None:
            try:
                tray.Visible = False
                tray.Dispose()
            except Exception:
                pass

    # 3. 容灾降级：若系统缺少 WebView2 或 pywebview 初始化异常，平滑降级为浏览器访问
    if not use_gui:
        _open_browser_delayed(url, delay_seconds=0.5)
        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            pass


def entry_point():
    """程序总入口"""
    if len(sys.argv) > 1:
        arg1 = sys.argv[1].lower()
        if arg1 in ("gui", "desktop"):
            launch_desktop_window()
            return
        elif arg1 in ("menu", "console"):
            interactive_menu()
            return

        # 挂载控制台并分发给 CLI 命令行执行
        _attach_console_for_cli()
        if "web" in sys.argv:
            _open_browser_delayed("http://localhost:8080", delay_seconds=0.8)
        cli_main()
    else:
        # 无参数双击启动：直接打开现代独立原生窗口
        launch_desktop_window()


if __name__ == "__main__":
    entry_point()
