"""Small synchronous iLink text client, compatible with the Python 3.8 release."""
import base64
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import requests

logger = logging.getLogger(__name__)
BASE_URL = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "2.4.10"
_STORE_LOCK = threading.RLock()


class WeChatError(RuntimeError):
    pass


class SessionExpired(WeChatError):
    pass


def trusted_base_url(value):
    """Only send bot credentials to HTTPS WeChat API nodes, including IDC redirects."""
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or not host.endswith(".weixin.qq.com")
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise WeChatError("微信接口地址无效")
    return value.rstrip("/")


def load_json(path):
    with _STORE_LOCK:
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (ValueError, OSError):
            raise WeChatError("微信配置文件无法读取，请重新连接") from None
        if not isinstance(value, dict):
            raise WeChatError("微信配置文件格式无效，请重新连接")
        return value


def save_json(path, value):
    with _STORE_LOCK:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
            os.chmod(name, 0o600)
            os.replace(name, str(target))
        finally:
            if os.path.exists(name):
                os.unlink(name)


def invalidate(config, token):
    # An old in-flight request must not erase a newer login.
    with _STORE_LOCK:
        if load_json(config.cred_path).get("token") == token:
            save_json(config.cred_path, {})
            save_json(config.state_path, {})


class WeChatClient:
    def __init__(self, credentials=None, *, use_env_proxy=False):
        self.credentials = credentials or {}
        self.use_env_proxy = use_env_proxy
        self.base_url = trusted_base_url(
            self.credentials.get("base_url") or self.credentials.get("baseUrl") or BASE_URL)

    def request(self, endpoint, payload=None, *, base_url=None, params=None, timeout=15, auth=True):
        base = trusted_base_url(base_url or self.base_url)
        headers = {"iLink-App-Id": "bot", "iLink-App-ClientVersion": "132106"}
        if auth:
            token = self.credentials.get("token")
            if not token:
                raise WeChatError("请先连接微信 bot")
            headers.update({
                "Content-Type": "application/json", "AuthorizationType": "ilink_bot_token",
                "Authorization": "Bearer " + token,
                "X-WECHAT-UIN": base64.b64encode(str(int.from_bytes(os.urandom(4), "big")).encode()).decode(),
            })
        kwargs = {"headers": headers, "timeout": (5, timeout), "allow_redirects": False}
        if not self.use_env_proxy:
            # Explicit empty routes override Windows/system/ALL_PROXY settings locally.
            # Keep TLS certificate verification enabled and leave other clients untouched.
            kwargs["proxies"] = {"http": "", "https": "", "all": ""}
        url = base + "/ilink/bot/" + endpoint
        try:
            if payload is None:
                response = requests.get(url, params=params, **kwargs)
            else:
                body = dict(payload)
                if auth:
                    body["base_info"] = {"channel_version": CHANNEL_VERSION, "bot_agent": "XMU-Gym/1.0"}
                response = requests.post(url, params=params, json=body, **kwargs)
            if 300 <= response.status_code < 400:
                raise WeChatError(f"微信接口 {endpoint} 重定向异常 (HTTP {response.status_code})")
            response.raise_for_status()
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            raise WeChatError(f"微信接口 {endpoint} 请求失败 (HTTP {status})") from None
        except (requests.RequestException, ValueError) as exc:
            # Never echo raw exceptions: they may include credentials or QR query strings.
            if isinstance(exc, ValueError) and "check_hostname requires server_hostname" in str(exc):
                reason = "代理 TLS 初始化失败，请关闭 wechat.use_env_proxy 或修正系统代理"
            elif isinstance(exc, requests.exceptions.ProxyError):
                reason = "代理连接失败，请检查代理或关闭 wechat.use_env_proxy"
            elif isinstance(exc, requests.exceptions.SSLError):
                reason = "TLS 证书验证失败，请检查证书和网络"
            elif isinstance(exc, requests.Timeout):
                reason = "请求超时"
            else:
                reason = f"网络连接失败 ({type(exc).__name__})"
            raise WeChatError(f"微信接口 {endpoint}：{reason}") from None
        try:
            result = response.json()
        except ValueError:
            raise WeChatError(f"微信接口 {endpoint} 返回了非 JSON 内容 (HTTP {response.status_code})") from None
        if not isinstance(result, dict):
            raise WeChatError(f"微信接口 {endpoint} 返回格式异常")
        codes = (result.get("ret", 0), result.get("errcode", 0))
        if -14 in codes:
            raise SessionExpired("微信登录已过期，请重新连接")
        if any(code != 0 for code in codes):
            # Only numeric business codes are safe to expose; exclude server text.
            safe_codes = ", ".join(f"{key}={value}" for key, value in zip(("ret", "errcode"), codes) if isinstance(value, int))
            raise WeChatError(f"微信接口 {endpoint} 拒绝请求 ({safe_codes or '业务码格式异常'})，请重新连接或向 bot 发一条消息后重试")
        return result

    def send(self, state, text, timeout=15):
        user = state.get("target_user_id")
        context = state.get("context_token")
        if not user or not context:
            raise WeChatError("请先向微信 bot 发送一条消息以完成绑定")
        owner = self.credentials.get("user_id") or self.credentials.get("userId")
        if owner and owner != user:
            raise WeChatError("微信会话与登录账号不一致，请重新绑定")
        self.request("sendmessage", {
            "msg": {"from_user_id": "", "to_user_id": user,
                    "client_id": "openclaw-weixin-" + uuid4().hex,
                    "message_type": 2, "message_state": 2, "context_token": context,
                    "item_list": [{"type": 1, "text_item": {"text": text}}]},
        }, timeout=timeout)


def send_wechat(config, title, content):
    credentials = {}
    try:
        credentials = load_json(config.cred_path)
        state = load_json(config.state_path)
        WeChatClient(credentials, use_env_proxy=config.use_env_proxy).send(state, title + "\n" + content, config.send_timeout)
        logger.info("微信 bot 通知已提交")
        return True
    except SessionExpired:
        invalidate(config, credentials.get("token"))
        logger.warning("微信 bot 登录已过期，请重新连接")
    except Exception as exc:
        reason = str(exc) if isinstance(exc, WeChatError) else type(exc).__name__
        logger.warning("微信 bot 通知失败：%s", reason)
    return False
