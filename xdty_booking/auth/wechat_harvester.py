import os
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class WeChatHarvester:
    """
    落地方案 2：全自动定时唤醒与静默截取兜底机制。
    在指定抢票前或发现 Token 失效时，可自动调用 Windows 微信核心进程 (WeChatAppEx.exe)
    加载对应的小程序 (AppID)，并触发静默登录。
    """
    DEFAULT_APPID = "wx81a2b2fa90759cb7"

    def __init__(self, appid: str = DEFAULT_APPID):
        self.appid = appid

    def find_wechat_appex(self) -> Optional[str]:
        """
        自动扫描 Windows 系统微信小程序核心进程 WeChatAppEx.exe 路径。
        全面适配旧版微信 (WeChat 3.x) 与新版微信 (WeChat 4.0 / Weixin NT)。
        优先级：
        1. 活跃进程扫描 (若微信正在运行，直接提取真实路径)
        2. 注册表安装路径推导
        3. AppData / Program Files 常见路径智能遍历
        """
        # 1. 优先从当前运行中的进程直接获取 WeChatAppEx.exe 路径
        try:
            import psutil
            for p in psutil.process_iter(['name', 'exe']):
                try:
                    name = p.info.get('name')
                    if name and name.lower() == 'wechatappex.exe':
                        exe = p.info.get('exe')
                        if exe and os.path.isfile(exe):
                            logger.info(f"从运行中进程检测到 WeChatAppEx.exe: {exe}")
                            return exe
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            logger.debug(f"进程扫描跳过: {e}")

        # 2. 尝试从 Windows 注册表查找微信安装目录并推导
        try:
            import winreg
            reg_queries = [
                (winreg.HKEY_CLASSES_ROOT, r"weixin\shell\open\command", ""),
                (winreg.HKEY_CURRENT_USER, r"Software\Tencent\Weixin", "InstallPath"),
                (winreg.HKEY_CURRENT_USER, r"Software\Tencent\WeChat", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Tencent\Weixin", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Tencent\WeChat", "InstallPath"),
            ]
            for root_hkey, sub_key, val_name in reg_queries:
                try:
                    with winreg.OpenKey(root_hkey, sub_key) as key:
                        raw_val, _ = winreg.QueryValueEx(key, val_name)
                        if raw_val:
                            clean_val = raw_val.strip('"').split('"')[0].strip()
                            base_dir = os.path.dirname(clean_val) if os.path.isfile(clean_val) else clean_val
                            if os.path.isdir(base_dir):
                                for root, _, files in os.walk(base_dir):
                                    if "WeChatAppEx.exe" in files:
                                        found = os.path.join(root, "WeChatAppEx.exe")
                                        logger.info(f"通过注册表推导找到 WeChatAppEx.exe: {found}")
                                        return found
                except OSError:
                    pass
        except Exception as e:
            logger.debug(f"注册表扫描跳过: {e}")

        # 3. 常见默认目录遍历（覆盖 WeChat 4.0 / xwechat 和 WeChat 3.x）
        appdata = os.getenv("APPDATA", "")
        localappdata = os.getenv("LOCALAPPDATA", "")

        possible_paths = [
            # 微信 4.0 / Weixin NT (xwechat / RadiumWMPF)
            os.path.join(appdata, r"Tencent\xwechat\xplugin\Plugins\RadiumWMPF"),
            os.path.join(appdata, r"Tencent\xwechat"),
            # 微信 3.x (WeChat / WMPF)
            os.path.join(appdata, r"Tencent\WeChat\XPlugin\Plugins\WMPF"),
            os.path.join(appdata, r"Tencent\WeChat\XPlugin\Plugins\RadiumWMPF"),
            os.path.join(localappdata, r"Tencent\WeChatAppEx"),
            os.path.join(localappdata, r"Tencent\xwechat"),
            r"C:\Program Files\Tencent\Weixin",
            r"C:\Program Files (x86)\Tencent\Weixin",
            r"C:\Program Files\Tencent\WeChat",
            r"C:\Program Files (x86)\Tencent\WeChat",
            r"D:\Tencent\Weixin",
            r"D:\Tencent\WeChat",
            r"D:\Program Files\Tencent\Weixin",
            r"D:\Program Files\Tencent\WeChat",
        ]

        for p in possible_paths:
            if p and os.path.exists(p):
                if os.path.isfile(p):
                    if os.path.basename(p).lower() == "wechatappex.exe":
                        logger.info(f"找到 WeChatAppEx.exe: {p}")
                        return p
                else:
                    for root, dirs, files in os.walk(p):
                        if "WeChatAppEx.exe" in files:
                            found = os.path.join(root, "WeChatAppEx.exe")
                            logger.info(f"找到 WeChatAppEx.exe: {found}")
                            return found
        return None

    def find_and_activate_window(self, titles: tuple = ("厦大体育",)) -> bool:
        """
        若小程序窗口已经在后台运行或最小化，将其还原并激活置顶
        """
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            # 连接用户交互桌面会话
            winsta = user32.OpenWindowStationW('WinSta0', False, 0x037F)
            if winsta:
                user32.SetProcessWindowStation(winsta)
            desk = user32.OpenDesktopW('default', 0, False, 0x01FF)

            activated = False
            def callback(hwnd, lparam):
                nonlocal activated
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    if any(t in title for t in titles):
                        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        user32.SetForegroundWindow(hwnd)
                        logger.info(f"成功激活并置顶已有小程序窗口: '{title}' (HWND: {hwnd})")
                        activated = True
                        return False
                return True

            cb = WNDENUMPROC(callback)
            if desk:
                user32.EnumDesktopWindows(desk, cb, 0)
            else:
                user32.EnumWindows(cb, 0)
            return activated
        except Exception as e:
            logger.debug(f"窗口激活异常: {e}")
            return False

    def find_desktop_shortcut(self, keywords: tuple = ("场馆预约", "健身房", "爱秋", "厦大体育", "体育馆", "体育")) -> Optional[str]:
        """
        检索桌面是否存在小程序快捷方式 (.lnk)
        优先匹配场馆/健身房直达快捷方式，其次匹配小程序通用快捷方式
        """
        desktop_dirs = [
            os.path.join(os.path.expanduser("~"), "Desktop"),
            r"D:\桌面",
        ]
        userprofile = os.getenv("USERPROFILE")
        if userprofile:
            desktop_dirs.append(os.path.join(userprofile, "Desktop"))
            desktop_dirs.append(os.path.join(userprofile, "桌面"))

        candidates = []
        for d in set(desktop_dirs):
            if os.path.exists(d):
                for f in os.listdir(d):
                    if f.lower().endswith(".lnk"):
                        for idx, kw in enumerate(keywords):
                            if kw in f:
                                candidates.append((idx, os.path.join(d, f)))
                                break
        if candidates:
            candidates.sort(key=lambda x: x[0])
            best_shortcut = candidates[0][1]
            logger.info(f"找到桌面小程序快捷方式 (优先级匹配): {best_shortcut}")
            return best_shortcut
        return None

    def launch_by_shortcut(self, shortcut_path: str) -> bool:
        """
        使用 Windows ShellExecute 启动桌面快捷方式（对微信 4.0 最稳定可靠的方式）
        """
        try:
            logger.info(f"正在通过桌面快捷方式启动小程序: {shortcut_path}")
            os.startfile(shortcut_path)
            return True
        except Exception as e:
            logger.error(f"启动快捷方式失败: {e}")
            return False

    def launch_by_protocol(self) -> bool:
        """
        通过微信注册的 URL 协议 (weixin://launchapplet/?app_id=...) 唤起小程序
        """
        try:
            url = f"weixin://launchapplet/?app_id={self.appid}"
            logger.info(f"正在通过微信 URL 协议唤起小程序: {url}")
            os.startfile(url)
            return True
        except Exception as e:
            logger.debug(f"通过 URL 协议唤起小程序失败: {e}")
            return False

    @staticmethod
    def kill_miniprogram() -> bool:
        """
        强制终止所有微信小程序进程 (WeChatAppEx.exe)
        """
        killed = False
        try:
            res = subprocess.run(
                ["taskkill", "/f", "/im", "WeChatAppEx.exe"],
                capture_output=True,
                text=True
            )
            if res.returncode == 0:
                logger.info("已通过 taskkill 成功终止 WeChatAppEx.exe 进程")
                killed = True
            else:
                logger.debug(f"taskkill 输出: {res.stderr.strip() or res.stdout.strip()}")
        except Exception as e:
            logger.debug(f"taskkill 执行异常: {e}")

        try:
            import psutil
            for p in psutil.process_iter(['name']):
                try:
                    if p.info.get('name', '').lower() == 'wechatappex.exe':
                        p.kill()
                        killed = True
                        logger.info(f"已通过 psutil 终止 WeChatAppEx.exe (PID: {p.pid})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

        return killed

    def launch_miniprogram(
        self,
        executable_path: Optional[str] = None,
        extra_args: Optional[list] = None,
        force_cold_start: bool = False
    ) -> bool:
        """
        通过多重策略唤醒/打开微信小程序：
        1. 若显式指定 executable_path，则直接通过命令行启动
        2. 策略 1 (窗口激活)：非冷启动模式下，检测后台是否已有小程序窗口，若有则直接还原置顶
        3. 策略 2 (快捷方式)：若桌面存在“添加到桌面”生成的快捷方式，通过 Shell 唤起
        4. 策略 3 (命令行)：扫描定位 WeChatAppEx.exe 并带 --app_id 参数启动
        """
        args_to_add = extra_args or []

        # 显式指定路径时直接调用
        if executable_path:
            if not os.path.exists(executable_path):
                logger.warning(f"指定的路径不存在: {executable_path}")
                return False
            cmd = [executable_path, f"--app_id={self.appid}"] + args_to_add
            try:
                logger.info(f"执行唤醒命令: {' '.join(cmd)}")
                subprocess.Popen(cmd)
                logger.info(f"小程序唤醒指令已发送 (AppID: {self.appid})")
                return True
            except Exception as e:
                logger.error(f"唤醒小程序失败: {e}")
                return False

        # 策略 1: 非强制冷启动模式下，检查是否已有运行中的小程序窗口，直接唤醒置顶
        if not force_cold_start and self.find_and_activate_window():
            logger.info("已成功激活正在运行的小程序窗口。")
            return True

        # 策略 2: 优先使用桌面快捷方式 (.lnk) 唤起（对微信 4.0 / Weixin NT 体系最稳定有效）
        shortcut = self.find_desktop_shortcut()
        if shortcut and self.launch_by_shortcut(shortcut):
            return True

        # 策略 3: 使用微信官方注册 URL 协议 (weixin://launchapplet/?app_id=...) 唤起
        if self.launch_by_protocol():
            return True

        # 策略 4: 扫描 WeChatAppEx.exe 并通过命令行启动（适用于旧版微信 3.x 或备选方案）
        path = executable_path or self.find_wechat_appex()
        if path and os.path.exists(path):
            cmd = [path, f"--app_id={self.appid}"] + args_to_add
            try:
                logger.info(f"执行唤醒命令: {' '.join(cmd)}")
                subprocess.Popen(cmd)
                logger.info(f"小程序唤醒指令已发送 (AppID: {self.appid})")
                return True
            except Exception as e:
                logger.error(f"唤醒小程序失败: {e}")

        logger.warning("未定位到有效的 WeChatAppEx.exe 路径或快捷方式，请在配置文件中明确指定或确认微信已安装")
        return False
