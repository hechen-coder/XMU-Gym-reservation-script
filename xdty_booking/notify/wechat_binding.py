"""Background QR login and single-owner context refresh for the local dashboard."""
import base64
import io
import logging
import threading
import time
from datetime import datetime, timezone

from .wechat import (BASE_URL, WeChatClient, WeChatError, SessionExpired,
                     invalidate, load_json, save_json, trusted_base_url, _STORE_LOCK)

logger = logging.getLogger(__name__)
_BINDINGS = {}
_BINDINGS_LOCK = threading.RLock()


def binding_for(config):
    key = (config.cred_path, config.state_path)
    with _BINDINGS_LOCK:
        if key not in _BINDINGS:
            _BINDINGS[key] = WeChatBinding(config)
        return _BINDINGS[key]


def close_bindings():
    with _BINDINGS_LOCK:
        for binding in _BINDINGS.values():
            binding.close()


class WeChatBinding:
    def __init__(self, config):
        self.config = config
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._verify = ""
        self._status = {"phase": "idle", "info": "尚未连接微信 bot", "qr_image": ""}

    def status(self):
        with self._lock:
            result = dict(self._status)
        try:
            creds, state = load_json(self.config.cred_path), load_json(self.config.state_path)
            result["logged_in"] = bool(creds.get("token"))
            owner = creds.get("user_id") or creds.get("userId")
            result["bound"] = bool(creds.get("token") and state.get("target_user_id") and state.get("context_token")
                                   and (not owner or owner == state.get("target_user_id")))
            if not result["logged_in"] and result["phase"] in ("bound", "binding", "retrying"):
                result.update(phase="expired", info="微信登录已过期，请重新连接", qr_image="")
            elif result["logged_in"] and result["phase"] == "idle":
                result["info"] = "已保存微信绑定，点击恢复连接" if result["bound"] else "已登录，点击恢复连接后向 bot 发一条消息"
        except WeChatError:
            result.update(logged_in=False, bound=False)
        return result

    def _set(self, phase, info, qr_image=None):
        with self._lock:
            self._status.update(phase=phase, info=info)
            if qr_image is not None:
                self._status["qr_image"] = qr_image

    def start(self, login=False):
        with self._lock:
            if self._thread and self._thread.is_alive():
                if login:
                    raise WeChatError("微信连接仍在运行，请先断开再重新连接")
                if self._stop.is_set():
                    raise WeChatError("微信连接正在停止，请稍后点击恢复连接")
                return
            if not login and not load_json(self.config.cred_path).get("token"):
                self._set("idle", "请先扫码连接微信 bot", "")
                return
            self._stop = threading.Event()
            self._verify = ""
            self._set("starting", "正在连接微信 bot…", "")
            self._thread = threading.Thread(target=self._run, args=(login,), name="WeChatBot", daemon=True)
            self._thread.start()

    def verify(self, code):
        if not isinstance(code, str) or not code.isascii() or not code.isdigit() or not 4 <= len(code) <= 12:
            raise WeChatError("请输入手机微信显示的配对码")
        with self._lock:
            if self._status["phase"] != "need_verifycode":
                raise WeChatError("当前无需输入配对码")
            self._verify = code

    def close(self):
        with self._lock:
            self._stop.set()
            self._set("idle", "微信监听已停止，绑定保留；可点击恢复连接", "")

    def disconnect(self):
        # Do not allow an in-flight long poll to restore deleted credentials.
        with self._lock, _STORE_LOCK:
            self.close()
            save_json(self.config.cred_path, {})
            save_json(self.config.state_path, {})
            self._set("idle", "已断开微信 bot", "")

    def _login(self):
        import qrcode
        existing = load_json(self.config.cred_path)
        client = WeChatClient(use_env_proxy=self.config.use_env_proxy)
        qr = client.request("get_bot_qrcode", {"local_token_list": [existing["token"]] if existing.get("token") else []},
                            params={"bot_type": "3"}, auth=False)
        code, url = qr.get("qrcode"), qr.get("qrcode_img_content")
        if not isinstance(code, str) or not isinstance(url, str) or not code or not url or len(url) > 4096:
            raise WeChatError("微信二维码加载失败，请重试")
        image = io.BytesIO()
        qrcode.make(url).save(image, format="PNG")
        self._set("wait", "用手机微信扫码并确认连接", "data:image/png;base64," + base64.b64encode(image.getvalue()).decode())
        deadline, base, verify = time.monotonic() + 300, BASE_URL, ""
        while not self._stop.is_set() and time.monotonic() < deadline:
            with self._lock:
                if self._verify:
                    verify, self._verify = self._verify, ""
            try:
                result = client.request("get_qrcode_status", base_url=base,
                                        params={"qrcode": code, **({"verify_code": verify} if verify else {})},
                                        timeout=35, auth=False)
            except WeChatError as exc:
                if not self._stop.is_set():
                    logger.warning("微信扫码状态查询失败：%s", exc)
                    self._set("retrying", str(exc) + "；正在重试")
                if self._stop.wait(2):
                    return None
                continue
            if self._stop.is_set():
                return None
            phase = result.get("status")
            if phase == "confirmed":
                creds = {"token": result.get("bot_token"), "base_url": trusted_base_url(result.get("baseurl") or BASE_URL),
                         "account_id": result.get("ilink_bot_id"), "user_id": result.get("ilink_user_id")}
                if not all(creds.values()):
                    raise WeChatError("微信登录返回缺少凭据，请重试")
                with self._lock, _STORE_LOCK:
                    if self._stop.is_set():
                        return None
                    save_json(self.config.state_path, {})
                    save_json(self.config.cred_path, creds)
                return creds
            if phase == "binded_redirect":
                if existing.get("token"):
                    return existing
                raise WeChatError("此 bot 已绑定但本机缺少凭据，请在微信中解绑后重试")
            if phase == "scaned_but_redirect":
                base = trusted_base_url("https://" + str(result.get("redirect_host", "")))
            elif phase == "wait":
                self._set("wait", "用手机微信扫码并确认连接")
            elif phase == "scaned":
                verify = ""
                self._set("scaned", "已扫码，请在手机微信确认")
            elif phase == "need_verifycode":
                self._set("need_verifycode", "请输入手机微信显示的配对码；若不匹配，请重新输入")
                verify = ""
                while not self._stop.is_set() and time.monotonic() < deadline:
                    with self._lock:
                        if self._verify:
                            break
                    self._stop.wait(0.3)
            elif phase in ("expired", "verify_code_blocked"):
                raise WeChatError("二维码已过期或配对被锁定，请重新连接")
            if self._stop.wait(1):
                return None
        if not self._stop.is_set():
            raise WeChatError("连接超时，请重新扫码")
        return None

    def _accept_updates(self, credentials, result):
        owner = credentials.get("user_id") or credentials.get("userId")
        with self._lock, _STORE_LOCK:
            if self._stop.is_set() or load_json(self.config.cred_path).get("token") != credentials.get("token"):
                return
            state = load_json(self.config.state_path)
            target = state.get("target_user_id") or owner
            messages = result.get("msgs", [])
            cursor = result.get("get_updates_buf", state.get("get_updates_buf", ""))
            if not isinstance(messages, list) or not isinstance(cursor, str):
                raise WeChatError("微信消息返回格式异常")
            for msg in messages:
                if not isinstance(msg, dict) or msg.get("message_type") != 1:
                    continue
                user, token = msg.get("from_user_id"), msg.get("context_token")
                # A different sender cannot silently take over the notification target.
                if isinstance(user, str) and isinstance(token, str) and user and token and target and user == target:
                    state.update(target_user_id=user, context_token=token,
                                 updated_at=datetime.now(timezone.utc).isoformat())
            state["get_updates_buf"] = cursor
            save_json(self.config.state_path, state)
            bound = bool(state.get("target_user_id") and state.get("context_token"))
            self._set("bound" if bound else "binding", "已绑定，可发送测试通知" if bound else "请用扫码账号向微信 bot 发一条消息以完成绑定", "")

    def _run(self, login):
        credentials = {}
        try:
            credentials = self._login() if login else load_json(self.config.cred_path)
            if not credentials or self._stop.is_set():
                return
            client = WeChatClient(credentials, use_env_proxy=self.config.use_env_proxy)
            try:
                client.request("msg/notifystart", {})
            except SessionExpired:
                raise
            except WeChatError:
                pass
            self._set("binding", "请向微信 bot 发一条消息以完成绑定", "")
            while not self._stop.is_set():
                try:
                    state = load_json(self.config.state_path)
                    result = client.request("getupdates", {"get_updates_buf": state.get("get_updates_buf", "")}, timeout=35)
                    self._accept_updates(credentials, result)
                except SessionExpired:
                    raise
                except WeChatError as exc:
                    if self._stop.is_set():
                        break
                    logger.warning("微信消息监听失败：%s", exc)
                    self._set("retrying", str(exc) + "；正在重试")
                    if self._stop.wait(5):
                        break
                if self._stop.wait(1):
                    break
        except SessionExpired:
            invalidate(self.config, credentials.get("token"))
            if not self._stop.is_set():
                self._set("expired", "微信登录已过期，请重新连接", "")
        except Exception as exc:
            reason = str(exc) if isinstance(exc, WeChatError) else type(exc).__name__
            logger.warning("微信连接失败：%s", reason)
            if not self._stop.is_set():
                self._set("error", str(exc) if isinstance(exc, WeChatError) else "微信连接失败，请检查网络和依赖后重试", "")
