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
        自动扫描 Windows 系统常见微信小程序核心进程 WeChatAppEx.exe 路径
        """
        possible_paths = [
            os.path.expandvars(r"%APPDATA%\Tencent\WeChat\XPlugin\Plugins\WMPF"),
            os.path.expandvars(r"%LOCALAPPDATA%\Tencent\WeChatAppEx"),
            r"C:\Program Files\Tencent\WeChat\WeChatAppEx.exe",
            r"C:\Program Files (x86)\Tencent\WeChat\WeChatAppEx.exe",
            r"D:\Tencent\WeChat\WeChatAppEx.exe"
        ]
        for p in possible_paths:
            if os.path.exists(p):
                if os.path.isfile(p):
                    return p
                for root, dirs, files in os.walk(p):
                    if "WeChatAppEx.exe" in files:
                        found = os.path.join(root, "WeChatAppEx.exe")
                        logger.info(f"找到 WeChatAppEx.exe: {found}")
                        return found
        return None

    def launch_miniprogram(self, executable_path: Optional[str] = None) -> bool:
        """
        通过命令行直接唤醒微信小程序
        """
        path = executable_path or self.find_wechat_appex()
        if not path or not os.path.exists(path):
            logger.warning("未定位到有效的 WeChatAppEx.exe 路径，请在配置文件中明确指定或确认微信已安装")
            return False

        cmd = [path, f"--app_id={self.appid}"]
        try:
            logger.info(f"执行唤醒命令: {' '.join(cmd)}")
            subprocess.Popen(cmd)
            logger.info(f"小程序唤醒指令已发送 (AppID: {self.appid})")
            return True
        except Exception as e:
            logger.error(f"唤醒小程序失败: {e}")
            return False
