import time
import logging
from typing import Optional

from xdty_booking.config import AppConfig, save_phpsessid
from xdty_booking.auth.wechat_harvester import WeChatHarvester
from xdty_booking.auth.proxy_manager import WindowsProxyManager
from xdty_booking.auth.sniffer_proxy import SnifferProxy

logger = logging.getLogger(__name__)

class HarvestService:
    """
    方案 A：WeChatHarvester + 本地透明轻量代理自动嗅探闭环调度引擎
    负责整体业务编排：
    1. 检测缺失/失效后触发；
    2. 启动后台极简 HTTP/HTTPS 嗅探代理；
    3. 修改 Windows 注册表临时生效系统代理；
    4. 唤醒并冷启动微信小程序 WeChatAppEx.exe；
    5. 捕获 /v3/api.php/WpLogin/loginByCode 返回的 PHPSESSID；
    6. 截获后立即复原 Windows 注册表代理、杀掉小程序进程、回写 config.yaml。
    """
    def __init__(self, config: AppConfig, config_path: str = "config/config.yaml", proxy_port: int = 8889):
        self.config = config
        self.config_path = config_path
        self.proxy_port = proxy_port

    def harvest(self, timeout: float = 30.0) -> Optional[str]:
        """
        执行一次完整的自动化嗅探捕获闭环
        """
        logger.info("=" * 60)
        logger.info("🚀 正在启动 方案 A：WeChatHarvester + 本地透明代理自动捕获流程")
        logger.info("=" * 60)

        # 1. 预先清理可能已经闲置或挂起的旧小程序进程，确保冷启动触发 loginByCode
        logger.info("步骤 1/5: 清理可能残留的微信小程序旧进程...")
        WeChatHarvester.kill_miniprogram()
        time.sleep(0.5)

        # 2. 启动本地轻量嗅探代理
        logger.info(f"步骤 2/5: 启动本地轻量嗅探代理 (127.0.0.1:{self.proxy_port})...")
        proxy = SnifferProxy(host="127.0.0.1", port=self.proxy_port)
        try:
            proxy.start()
        except Exception as e:
            logger.error(f"启动本地嗅探代理失败: {e}")
            return None

        captured_token = None
        proxy_manager = WindowsProxyManager(proxy_server=f"127.0.0.1:{self.proxy_port}")

        try:
            # 3. 切换 Windows 系统网络代理
            logger.info("步骤 3/5: 配置 Windows 注册表临时网络代理...")
            with proxy_manager:
                # 4. 唤醒小程序
                logger.info("步骤 4/5: 正在静默唤醒微信小程序并注入代理参数...")
                harvester = WeChatHarvester(appid=self.config.auth.wechat_appid)
                extra_args = [
                    f"--proxy-server=http://127.0.0.1:{self.proxy_port}",
                    "--ignore-certificate-errors",
                ]
                launched = harvester.launch_miniprogram(
                    executable_path=self.config.auth.wechat_appex_path or None,
                    extra_args=extra_args,
                    force_cold_start=True
                )
                if not launched:
                    logger.warning("未能成功唤醒小程序，等待桌面手动打开或观察嗅探...")

                # 5. 等待代理截获 loginByCode
                logger.info(f"步骤 5/5: 正在监听网络报文，等待截获 PHPSESSID (最长等待 {timeout} 秒)...")
                captured_token = proxy.wait_for_token(timeout=timeout)

        except Exception as e:
            logger.error(f"嗅探捕获流程发生异常: {e}")
        finally:
            # 6. 收尾工作：无论成功失败，必须确保还原 Windows 代理并关闭代理服务
            proxy.stop()
            logger.info("收尾: 立即终止微信小程序进程...")
            WeChatHarvester.kill_miniprogram()

        # 7. 处理截获成果并持久化
        if captured_token:
            logger.info(f"✨ 凭证捕获成功: {captured_token}")
            self.config.auth.phpsessid = captured_token
            # 回写配置文件
            saved = save_phpsessid(self.config_path, captured_token)
            if saved:
                logger.info(f"💾 已成功将新 PHPSESSID 回写至配置文件: {self.config_path}")
            else:
                logger.warning(f"回写配置文件失败: {self.config_path}")
            return captured_token
        else:
            logger.error("❌ 自动捕获超时或未能获取到有效的 PHPSESSID")
            return None
