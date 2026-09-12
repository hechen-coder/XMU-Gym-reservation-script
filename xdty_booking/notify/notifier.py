import json
import logging
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, Optional
import requests

from xdty_booking.config import NotifyConfig

logger = logging.getLogger(__name__)

class Notifier:
    """
    统一即时通知分发引擎：
    支持 PushPlus (微信推送)、邮件 (SMTP)、Server酱 Turbo、Bark (iOS 锁屏)。
    """
    def __init__(self, config: NotifyConfig):
        self.cfg = config

    def is_enabled(self) -> bool:
        return bool(self.cfg and self.cfg.enabled)

    def send(self, title: str, content: str, html_content: Optional[str] = None) -> Dict[str, bool]:
        """
        向配置的通道分发通知。
        返回各通道发送成功/失败状态字典。
        """
        results = {}
        if not self.is_enabled():
            logger.debug("通知功能未开启 (notify.enabled=false)，跳过推送")
            return results

        full_title = f"{self.cfg.title_prefix} {title}".strip()
        channel = (self.cfg.channel or "pushplus").lower()
        html = html_content or content.replace("\n", "<br>")

        # PushPlus
        if channel in ("pushplus", "all") and self.cfg.pushplus.token:
            results["pushplus"] = self._send_pushplus(full_title, html)

        # 邮件 (Email)
        if channel in ("email", "all") and self.cfg.email.sender and self.cfg.email.to_addrs:
            results["email"] = self._send_email(full_title, content, html)

        # Server酱
        if channel in ("serverchan", "all") and self.cfg.serverchan.sendkey:
            results["serverchan"] = self._send_serverchan(full_title, content)

        # Bark
        if channel in ("bark", "all") and self.cfg.bark.device_key:
            results["bark"] = self._send_bark(full_title, content)

        if not results:
            logger.warning("未配置任何可用的通知通道或凭证为空，请检查 config.yaml 中的 notify 配置")

        return results

    def _send_pushplus(self, title: str, content: str) -> bool:
        """PushPlus 微信推送通道"""
        try:
            url = "http://www.pushplus.plus/send"
            payload = {
                "token": self.cfg.pushplus.token,
                "title": title,
                "content": content,
                "template": "html"
            }
            resp = requests.post(url, json=payload, timeout=10)
            res_json = resp.json()
            if res_json.get("code") == 200:
                logger.info("✅ PushPlus 微信推送成功！")
                return True
            else:
                logger.error(f"❌ PushPlus 推送失败: {res_json.get('msg')}")
                return False
        except Exception as e:
            logger.error(f"❌ PushPlus 推送异常: {e}")
            return False

    def _send_email(self, title: str, text_content: str, html_content: str) -> bool:
        """SMTP 邮件通知通道"""
        ec = self.cfg.email
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = Header(title, "utf-8")
            msg["From"] = ec.sender
            msg["To"] = ",".join(ec.to_addrs)

            part_text = MIMEText(text_content, "plain", "utf-8")
            part_html = MIMEText(html_content, "html", "utf-8")
            msg.attach(part_text)
            msg.attach(part_html)

            if ec.ssl or ec.smtp_port == 465:
                server = smtplib.SMTP_SSL(ec.smtp_host, ec.smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(ec.smtp_host, ec.smtp_port, timeout=10)
                server.starttls()

            server.login(ec.sender, ec.password)
            server.sendmail(ec.sender, ec.to_addrs, msg.as_string())
            server.quit()
            logger.info(f"✅ 邮件通知发送成功！已投递至: {ec.to_addrs}")
            return True
        except Exception as e:
            logger.error(f"❌ 邮件发送失败: {e}")
            return False

    def _send_serverchan(self, title: str, content: str) -> bool:
        """Server酱 Turbo 推送"""
        try:
            url = f"https://sctapi.ftqq.com/{self.cfg.serverchan.sendkey}.send"
            resp = requests.post(url, data={"title": title, "desp": content}, timeout=10)
            res_json = resp.json()
            if res_json.get("code") == 0:
                logger.info("✅ Server酱推送成功！")
                return True
            else:
                logger.error(f"❌ Server酱推送失败: {res_json.get('message')}")
                return False
        except Exception as e:
            logger.error(f"❌ Server酱推送异常: {e}")
            return False

    def _send_bark(self, title: str, content: str) -> bool:
        """Bark iOS 推送"""
        try:
            base_url = self.cfg.bark.server_url.rstrip("/")
            url = f"{base_url}/push"
            payload = {
                "device_key": self.cfg.bark.device_key,
                "title": title,
                "body": content,
                "badge": 1,
                "sound": "alarm.caf"
            }
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("✅ Bark 推送成功！")
                return True
            else:
                logger.error(f"❌ Bark 推送失败: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Bark 推送异常: {e}")
            return False

    def send_booking_success(self, slot_info: Dict[str, Any], order_info: Optional[Dict[str, Any]] = None) -> Dict[str, bool]:
        """
        预约成功专用模板通知
        """
        venue = slot_info.get("stadium_name") or slot_info.get("area_name") or "厦大健身房"
        date = slot_info.get("date", "")
        time_slot = slot_info.get("time_range") or slot_info.get("interval_time", "")
        area_name = slot_info.get("area_name", "")
        mode = slot_info.get("mode", "预约")

        title = f"🎉 抢票成功提醒: {date} {time_slot}"
        
        text = f"""🎉 恭喜！厦大体育馆场地抢票成功！
------------------------------------------------
【预约模式】{mode}
【场馆项目】{venue} ({area_name})
【预约日期】{date}
【预约时段】{time_slot}
【场次 I D】{slot_info.get('interval_id', 'N/A')}
【订单详情】{order_info.get('info', '已成功下单锁定') if order_info else '预约完成'}
------------------------------------------------
请在微信小程序【厦大体育】或系统历史记录中核对。"""

        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 500px; padding: 20px; border-radius: 10px; background: #f0fdf4; border: 1px solid #bbf7d0;">
            <h2 style="color: #166534; margin-top: 0;">🎉 厦大体育馆抢票成功！</h2>
            <p style="color: #374151; font-size: 14px;">您的场地已成功完成预约下单，详细信息如下：</p>
            <table style="width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px;">
                <tr><td style="padding: 6px 0; color: #6b7280;">预约模式:</td><td style="font-weight: bold; color: #1f2937;">{mode}</td></tr>
                <tr><td style="padding: 6px 0; color: #6b7280;">场馆名称:</td><td style="font-weight: bold; color: #1f2937;">{venue} - {area_name}</td></tr>
                <tr><td style="padding: 6px 0; color: #6b7280;">预约日期:</td><td style="font-weight: bold; color: #1f2937;">{date}</td></tr>
                <tr><td style="padding: 6px 0; color: #6b7280;">预约时段:</td><td style="font-weight: bold; color: #15803d; font-size: 16px;">{time_slot}</td></tr>
                <tr><td style="padding: 6px 0; color: #6b7280;">场次 ID:</td><td style="color: #1f2937;">{slot_info.get('interval_id', 'N/A')}</td></tr>
            </table>
            <div style="margin-top: 16px; padding: 10px; background: #ffffff; border-radius: 6px; font-size: 13px; color: #4b5563;">
                💡 提醒：请准时到场锻炼打卡。如计划变动请在规定时间内退票，避免违约。
            </div>
        </div>
        """
        return self.send(title=title, content=text, html_content=html)

    def send_test(self) -> Dict[str, bool]:
        """发送测试消息验证通道是否通畅"""
        title = "系统通知测试"
        text = "您好！这是一条来自【厦大体育馆自动预约系统】的测试通知。如果您收到了这条消息，说明通知功能已配置就绪！"
        html = f"""
        <div style="font-family: sans-serif; padding: 16px; border-radius: 8px; background: #eff6ff; border: 1px solid #bfdbfe;">
            <h3 style="color: #1e40af; margin-top: 0;">🚀 厦大体育馆自动预约 - 通知通道测试</h3>
            <p style="color: #1f2937; font-size: 14px;">{text}</p>
            <p style="color: #6b7280; font-size: 12px; margin-bottom: 0;">测试时间: {requests.utils.default_user_agent()}</p>
        </div>
        """
        return self.send(title=title, content=text, html_content=html)
