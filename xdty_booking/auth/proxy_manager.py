import sys
import atexit
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Windows WinINet 常量
INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_REFRESH = 37

class WindowsProxyManager:
    """
    Windows 系统网络代理管理器：
    1. 修改 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings 临时生效本地代理
    2. 调用 WinINet API 立即无缝刷新系统代理，无需重启应用
    3. 支持 Python 上下文管理器 (Context Manager) 和 atexit 钩子，保证 100% 自动还原原始网络状态
    """
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

    def __init__(self, proxy_server: str = "127.0.0.1:8889", proxy_override: str = "<local>;<-loopback>"):
        self.proxy_server = proxy_server
        self.proxy_override = proxy_override
        self.original_settings: Optional[Dict[str, Any]] = None
        self._is_applied = False
        atexit.register(self.restore)

    @staticmethod
    def _notify_system_settings_changed():
        """通知 Windows 系统网络配置已更新，WinINet 立即刷新"""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            wininet = ctypes.windll.wininet
            # 刷新设置通知
            wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
            wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
            logger.debug("已通过 WinINet 发送系统代理刷新通知")
        except Exception as e:
            logger.warning(f"WinINet 刷新通知调用异常: {e}")

    def backup(self) -> Dict[str, Any]:
        """备份当前 Windows 系统代理配置"""
        settings = {
            "ProxyEnable": 0,
            "ProxyServer": "",
            "ProxyOverride": "",
            "AutoConfigURL": ""
        }
        if sys.platform != "win32":
            self.original_settings = settings
            return settings

        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_READ) as key:
                for sub in ["ProxyEnable", "ProxyServer", "ProxyOverride", "AutoConfigURL"]:
                    try:
                        val, _ = winreg.QueryValueEx(key, sub)
                        settings[sub] = val
                    except OSError:
                        settings[sub] = None
        except Exception as e:
            logger.warning(f"备份 Windows 代理设置失败: {e}")

        self.original_settings = settings
        logger.debug(f"已备份原始 Windows 代理设置: {settings}")
        return settings

    def apply(self) -> bool:
        """应用临时代理设置"""
        if self._is_applied:
            return True

        self.backup()

        if sys.platform != "win32":
            logger.info(f"[Mock] 已应用系统代理: {self.proxy_server}")
            self._is_applied = True
            return True

        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                server_val = self.proxy_server
                if "=" not in server_val:
                    server_val = f"http={server_val};https={server_val}"
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server_val)
                if self.proxy_override:
                    winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, self.proxy_override)

            self._notify_system_settings_changed()
            self._is_applied = True
            logger.info(f"已将 Windows 临时系统代理切换至: {self.proxy_server}")
            return True
        except Exception as e:
            logger.error(f"修改 Windows 代理注册表异常: {e}")
            return False

    def restore(self) -> bool:
        """完整还原原始 Windows 系统代理设置"""
        if not self._is_applied or not self.original_settings:
            return True

        if sys.platform != "win32":
            logger.info("[Mock] 已复原原始系统代理配置")
            self._is_applied = False
            return True

        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
                # 恢复 ProxyEnable
                orig_enable = self.original_settings.get("ProxyEnable")
                if orig_enable is not None:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, int(orig_enable))
                else:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)

                # 恢复 ProxyServer
                orig_server = self.original_settings.get("ProxyServer")
                if orig_server is not None:
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, str(orig_server))
                else:
                    try:
                        winreg.DeleteValue(key, "ProxyServer")
                    except OSError:
                        pass

                # 恢复 ProxyOverride
                orig_override = self.original_settings.get("ProxyOverride")
                if orig_override is not None:
                    winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, str(orig_override))
                else:
                    try:
                        winreg.DeleteValue(key, "ProxyOverride")
                    except OSError:
                        pass

                # 恢复 AutoConfigURL (若存在)
                orig_pac = self.original_settings.get("AutoConfigURL")
                if orig_pac is not None:
                    winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, str(orig_pac))

            self._notify_system_settings_changed()
            self._is_applied = False
            logger.info("已成功复原 Windows 原始系统代理设置 ✅")
            return True
        except Exception as e:
            logger.error(f"复原 Windows 代理设置异常: {e}")
            return False

    def __enter__(self):
        self.apply()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.restore()
