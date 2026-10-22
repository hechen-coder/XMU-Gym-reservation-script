import base64
import hashlib
import hmac
import json
import logging
import smtplib
import time
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional
import requests

from xdty_booking.config import (
    NotifyConfig,
    DEFAULT_DEVELOPER_EMAIL_SENDER,
    DEFAULT_DEVELOPER_EMAIL_AUTH,
    DEFAULT_DEVELOPER_SMTP_HOST,
    DEFAULT_DEVELOPER_SMTP_PORT,
    DEFAULT_DEVELOPER_SMTP_SSL,
)

logger = logging.getLogger(__name__)

class Notifier:
    """
    统一即时通知分发引擎：
    支持 PushPlus (微信推送)、邮件 (SMTP)、Server酱 Turbo、Bark (iOS 锁屏)、飞书自定义机器人。
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
        channel = (self.cfg.channel or "email").lower()
        html = html_content or escape(content).replace("\n", "<br>")

        # Run independently so a slow/broken bot cannot prevent email delivery.
        if self.cfg.wechat.enabled:
            with ThreadPoolExecutor(max_workers=2) as pool:
                wechat = pool.submit(self._send_wechat, full_title, content)
                remaining = pool.submit(self._send_channels, channel, full_title, content, html)
                for name, future in (("channels", remaining), ("wechat", wechat)):
                    try:
                        value = future.result()
                        if name == "channels":
                            results.update(value)
                        else:
                            results[name] = value
                    except Exception as exc:
                        logger.warning("通知通道失败 (%s): %s", name, type(exc).__name__)
                        results[name] = False
            return results
        return self._send_channels(channel, full_title, content, html)

    def _send_wechat(self, title, content):
        from .wechat import send_wechat
        return send_wechat(self.cfg.wechat, title, content)

    def _send_channels(self, channel, full_title, content, html):
        results = {}

        # PushPlus
        if channel in ("pushplus", "all") and self.cfg.pushplus.token:
            results["pushplus"] = self._send_pushplus(full_title, html)

        # 邮件 (Email - 支持开发者统一内置发信箱，用户仅需配置接收邮箱)
        if channel in ("email", "all") and self.cfg.email and self.cfg.email.to_addrs:
            results["email"] = self._send_email(full_title, content, html)

        # Server酱
        if channel in ("serverchan", "all") and self.cfg.serverchan.sendkey:
            results["serverchan"] = self._send_serverchan(full_title, content)

        # Bark
        if channel in ("bark", "all") and self.cfg.bark.device_key:
            results["bark"] = self._send_bark(full_title, content)

        # 飞书 (Feishu 自定义群机器人，支持签名校验)
        if channel in ("feishu", "all") and self.cfg.feishu and self.cfg.feishu.webhook_url:
            results["feishu"] = self._send_feishu(full_title, content)

        if not results and not self.cfg.wechat.enabled:
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
        """SMTP 邮件通知通道 (支持开发者统一发件箱与自定义发件箱)"""
        ec = self.cfg.email
        sender = ec.sender or DEFAULT_DEVELOPER_EMAIL_SENDER
        password = ec.password or DEFAULT_DEVELOPER_EMAIL_AUTH
        smtp_host = ec.smtp_host or DEFAULT_DEVELOPER_SMTP_HOST
        smtp_port = ec.smtp_port or DEFAULT_DEVELOPER_SMTP_PORT
        use_ssl = ec.ssl if ec.ssl is not None else DEFAULT_DEVELOPER_SMTP_SSL
        to_addrs = ec.to_addrs

        if not to_addrs:
            logger.warning("未指定邮件接收人列表 (to_addrs 为空)，跳过邮件发送")
            return False

        try:
            from email.utils import formataddr
            msg = MIMEMultipart("alternative")
            msg["Subject"] = Header(title, "utf-8")
            msg["From"] = formataddr(("厦大体育馆预约助手", sender))
            msg["To"] = ",".join(to_addrs)

            part_text = MIMEText(text_content, "plain", "utf-8")
            part_html = MIMEText(html_content, "html", "utf-8")
            msg.attach(part_text)
            msg.attach(part_html)

            if use_ssl or smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
                server.starttls()

            server.login(sender, password)
            server.sendmail(sender, to_addrs, msg.as_string())
            server.quit()
            logger.info(f"✅ 邮件通知发送成功！已投递至: {to_addrs}")
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

    def _send_feishu(self, title: str, content: str) -> bool:
        """飞书自定义机器人文本推送，支持可选的签名校验。"""
        try:
            payload = {
                "msg_type": "text",
                "content": {"text": f"{title}\n\n{content}"},
            }
            if self.cfg.feishu.secret:
                timestamp = str(int(time.time()))
                # 飞书使用「秒级时间戳 + 换行 + 密钥」作为 HMAC key，消息为空。
                key = f"{timestamp}\n{self.cfg.feishu.secret}".encode("utf-8")
                payload["timestamp"] = timestamp
                payload["sign"] = base64.b64encode(
                    hmac.new(key, b"", hashlib.sha256).digest()
                ).decode("ascii")
            resp = requests.post(self.cfg.feishu.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            if isinstance(result, dict) and result.get("code") == 0:
                logger.info("✅ 飞书推送成功！")
                return True
            code = result.get("code") if isinstance(result, dict) else None
            logger.error("❌ 飞书推送失败，错误码: %s（请检查机器人安全设置及配置）", code)
        except Exception as e:
            # requests 的异常可能含完整 Webhook URL，避免将机器人凭证写入日志。
            logger.error("❌ 飞书推送异常: %s", type(e).__name__)
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

        title = f"预约成功 · {date} {time_slot}"
        location = venue if not area_name or area_name == venue else f"{venue} · {area_name}"
        text = f"{location}\n{date} {time_slot}\n请在「厦大体育」核对预约，按时到场。"
        html = (f"<h3>{escape(title)}</h3><p>{escape(location)}</p>"
                f"<p>{escape(str(date))} {escape(str(time_slot))}</p>"
                "<p>请在「厦大体育」核对预约，按时到场。</p>")
        return self.send(title=title, content=text, html_content=html)

    def send_test(self) -> Dict[str, bool]:
        """发送测试消息验证通道是否通畅"""
        title = "系统通知测试"
        text = "通知通道测试，请检查是否收到。"
        return self.send(title=title, content=text)
