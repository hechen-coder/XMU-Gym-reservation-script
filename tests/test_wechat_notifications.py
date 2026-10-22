"""iLink wire contract, local binding lifecycle, and mixed delivery regressions."""
import json
import threading
from unittest.mock import Mock, patch

import pytest
import requests

from xdty_booking.config import EmailConfig, NotifyConfig, WeChatConfig, load_config, save_notify_config
from xdty_booking.notify.notifier import Notifier
from xdty_booking.notify.wechat import (WeChatClient, WeChatError, SessionExpired,
                                       load_json, save_json, send_wechat, trusted_base_url)
from xdty_booking.notify.wechat_binding import WeChatBinding
from xdty_booking.web.server import GymStatusHandler


@pytest.fixture
def configured(tmp_path):
    cfg = WeChatConfig(enabled=True, cred_path=str(tmp_path / "wechatbot-credentials.json"),
                       state_path=str(tmp_path / "wechat_state.json"))
    save_json(cfg.cred_path, {"token": "private-token", "base_url": "https://ilinkai.weixin.qq.com", "user_id": "owner"})
    save_json(cfg.state_path, {"target_user_id": "owner", "context_token": "private-context"})
    return cfg


def response(payload, status=200):
    res = Mock(status_code=status)
    res.json.return_value = payload
    return res


def test_mixed_delivery_is_concurrent_and_independent(configured):
    notifier = Notifier(NotifyConfig(enabled=True, wechat=configured, email=EmailConfig(to_addrs=["test@example.com"])))
    reached = threading.Event()

    def mail(*args):
        reached.set()
        return True

    def bot(*args):
        assert reached.wait(2), "email should proceed while bot is busy"
        raise requests.Timeout("private-token")

    with patch.object(notifier, "_send_email", side_effect=mail), patch.object(notifier, "_send_wechat", side_effect=bot):
        assert notifier.send_test() == {"email": True, "wechat": False}


def test_email_failure_does_not_block_bot(configured):
    notifier = Notifier(NotifyConfig(enabled=True, wechat=configured, email=EmailConfig(to_addrs=["test@example.com"])))
    with patch.object(notifier, "_send_email", return_value=False), patch.object(notifier, "_send_wechat", return_value=True):
        assert notifier.send_test() == {"email": False, "wechat": True}


def test_wechat_only_and_global_off(configured):
    cfg = NotifyConfig(enabled=True, wechat=configured)
    with patch("xdty_booking.notify.notifier.Notifier._send_wechat", return_value=True) as send:
        assert Notifier(cfg).send_test() == {"wechat": True}
        cfg.enabled = False
        assert Notifier(cfg).send_test() == {}
        assert send.call_count == 1


def test_actual_send_wire_format_and_unique_ids(configured):
    with patch("xdty_booking.notify.wechat.requests.post", return_value=response({"ret": 0})) as post:
        assert send_wechat(configured, "预约成功", "场馆\n日期 时段")
        assert send_wechat(configured, "测试", "内容")
    calls = post.call_args_list
    first = calls[0].kwargs
    assert calls[0].args[0].endswith("/ilink/bot/sendmessage")
    assert first["headers"]["Authorization"] == "Bearer private-token"
    assert first["allow_redirects"] is False
    assert first["proxies"] == {"http": "", "https": "", "all": ""}
    assert first["timeout"] == (5, 15)
    msg = first["json"]["msg"]
    assert msg["from_user_id"] == ""
    assert msg["to_user_id"] == "owner"
    assert msg["context_token"] == "private-context"
    assert msg["message_type"] == msg["message_state"] == 2
    assert msg["item_list"] == [{"type": 1, "text_item": {"text": "预约成功\n场馆\n日期 时段"}}]
    assert msg["client_id"] != calls[1].kwargs["json"]["msg"]["client_id"]
    assert first["json"]["base_info"]["channel_version"]


@pytest.mark.parametrize("payload", [{"ret": -2, "errmsg": "private-token"}, {"errcode": 9}, [], "bad", {"ret": "0"}])
def test_http_200_is_not_enough_and_logs_redact(configured, payload, caplog):
    with patch("xdty_booking.notify.wechat.requests.post", return_value=response(payload)):
        assert not send_wechat(configured, "测试", "内容")
    assert "private-token" not in caplog.text
    assert "private-context" not in caplog.text


def test_expiry_clears_credentials_and_context(configured):
    with patch("xdty_booking.notify.wechat.requests.post", return_value=response({"errcode": -14})):
        assert not send_wechat(configured, "测试", "内容")
    assert load_json(configured.cred_path) == load_json(configured.state_path) == {}


@pytest.mark.parametrize("error", [requests.Timeout("private-token"), requests.HTTPError("private-token"), ValueError("private-token")])
def test_transport_failures_are_redacted(configured, caplog, error):
    with patch("xdty_booking.notify.wechat.requests.post", side_effect=error):
        assert not send_wechat(configured, "测试", "内容")
    assert "private-token" not in caplog.text


def test_missing_binding_or_wrong_owner_never_sends(configured):
    for state in ({}, {"target_user_id": "stranger", "context_token": "private-context"}):
        save_json(configured.state_path, state)
        with patch("xdty_booking.notify.wechat.requests.post") as post:
            assert not send_wechat(configured, "测试", "内容")
            post.assert_not_called()


@pytest.mark.parametrize("url", ["http://ilinkai.weixin.qq.com", "https://weixin.qq.com.evil.com", "https://evil.com", "https://ilinkai.weixin.qq.com@evil.com", "https://ilinkai.weixin.qq.com/path"])
def test_credentials_cannot_be_redirected_to_foreign_hosts(url):
    with pytest.raises(WeChatError):
        trusted_base_url(url)


def test_config_round_trip_preserves_other_channels_and_resolves_paths(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("notify:\n  channel: feishu\n  feishu:\n    webhook_url: https://example.com/hook\n  wechat:\n    send_timeout: 8\n", encoding="utf-8")
    save_notify_config(str(path), enabled=True, email="test@example.com", wechat_enabled=True)
    cfg = load_config(str(path)).notify
    assert cfg.channel == "feishu"
    assert cfg.wechat.enabled and cfg.wechat.send_timeout == 8
    assert cfg.wechat.cred_path == str(tmp_path / "wechatbot-credentials.json")
    assert cfg.email.to_addrs == ["test@example.com"]
    assert cfg.feishu.webhook_url == "https://example.com/hook"
    save_notify_config(str(path), wechat_enabled=False)
    assert not load_config(str(path)).notify.wechat.enabled


def test_context_refresh_ignores_other_senders_and_survives_restart(configured):
    credentials = load_json(configured.cred_path)
    binding = WeChatBinding(configured)
    binding._accept_updates(credentials, {"get_updates_buf": "cursor", "msgs": [
        {"message_type": 1, "from_user_id": "stranger", "context_token": "stolen"},
        {"message_type": 2, "from_user_id": "owner", "context_token": "outbound"},
        {"message_type": 1, "from_user_id": "owner", "context_token": "fresh"},
    ]})
    state = load_json(configured.state_path)
    assert state["target_user_id"] == "owner" and state["context_token"] == "fresh"
    assert state["get_updates_buf"] == "cursor"
    restored = WeChatBinding(configured).status()
    assert restored["bound"] and restored["logged_in"]
    assert "fresh" not in json.dumps(restored)
    assert "private-token" not in json.dumps(restored)


def test_disconnect_cannot_be_undone_by_inflight_poll(configured):
    binding = WeChatBinding(configured)
    credentials = load_json(configured.cred_path)
    binding.disconnect()
    binding._accept_updates(credentials, {"msgs": [{"message_type": 1, "from_user_id": "owner", "context_token": "late"}]})
    assert load_json(configured.cred_path) == load_json(configured.state_path) == {}
    assert binding.status()["phase"] == "idle"


def test_qr_pairing_redirect_and_login_clear_old_context(configured):
    binding = WeChatBinding(configured)
    calls = []
    statuses = iter([
        {"status": "scaned_but_redirect", "redirect_host": "node.weixin.qq.com"},
        {"status": "need_verifycode"},
        {"status": "confirmed", "bot_token": "new-token", "ilink_bot_id": "bot-id", "ilink_user_id": "owner", "baseurl": "https://node.weixin.qq.com"},
    ])

    def request(client, endpoint, payload=None, **kwargs):
        calls.append((endpoint, payload, kwargs))
        if endpoint == "get_bot_qrcode":
            return {"qrcode": "qr", "qrcode_img_content": "https://example.com/login"}
        value = next(statuses)
        if value["status"] == "confirmed":
            assert kwargs["params"]["verify_code"] == "123456"
            assert kwargs["base_url"] == "https://node.weixin.qq.com"
        return value

    original_set = binding._set

    def state(phase, info, qr_image=None):
        original_set(phase, info, qr_image)
        if phase == "need_verifycode":
            binding.verify("123456")

    with patch.object(WeChatClient, "request", request), patch.object(binding, "_set", side_effect=state), patch.object(binding._stop, "wait", return_value=False):
        credentials = binding._login()
    assert credentials["token"] == "new-token"
    assert calls[0][1] == {"local_token_list": ["private-token"]}
    assert load_json(configured.state_path) == {}
    assert binding.status()["qr_image"].startswith("data:image/png;base64,")


def test_api_partial_delivery_and_wechat_only(configured, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("notify:\n  enabled: true\n  wechat:\n    enabled: true\n", encoding="utf-8")
    handler = GymStatusHandler.__new__(GymStatusHandler)
    handler._send_json = Mock()
    with patch("xdty_booking.web.server._GLOBAL_CONFIG_PATH", str(config_path)), patch.object(Notifier, "send_test", return_value={"email": True, "wechat": False}):
        handler._handle_notify_test({"email": "test@example.com", "wechat_enabled": True})
    code, body = handler._send_json.call_args.args
    assert code == 200 and body["status"] == "partial" and not body["success"]
    assert body["results"] == {"email": True, "wechat": False}
    with patch("xdty_booking.web.server._GLOBAL_CONFIG_PATH", str(config_path)), patch.object(Notifier, "_send_wechat", return_value=True):
        handler._handle_notify_test({"email": "", "wechat_enabled": True})
    assert handler._send_json.call_args.args[1]["results"] == {"wechat": True}


@pytest.mark.parametrize("body", [{"wechat_enabled": "false"}, {"email": "bad"}, {"enabled": "false"}])
def test_bad_api_config_never_persists(body, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("notify: {}\n", encoding="utf-8")
    handler = GymStatusHandler.__new__(GymStatusHandler)
    handler._send_json = Mock()
    with patch("xdty_booking.web.server._GLOBAL_CONFIG_PATH", str(path)):
        handler._handle_notify_config_post(body)
    assert handler._send_json.call_args.args[0] == 400
    assert path.read_text(encoding="utf-8") == "notify: {}\n"


def test_windows_proxy_is_overridden_only_for_wechat():
    res = requests.Response()
    res.status_code = 200
    res._content = b'{"ret":0,"qrcode":"qr","qrcode_img_content":"url"}'
    broken_proxy = {"http": "https://127.0.0.1:7890", "https": "https://127.0.0.1:7890", "all": "https://127.0.0.1:7890"}
    with patch("requests.sessions.get_environ_proxies", return_value=broken_proxy.copy()), patch("requests.sessions.Session.send", return_value=res) as send:
        assert WeChatClient().request("get_bot_qrcode", {}, auth=False)["qrcode"] == "qr"
        assert not any(send.call_args.kwargs["proxies"].values())
        # Other clients continue to inherit their configured proxies.
        requests.get("https://example.com")
        assert send.call_args.kwargs["proxies"]["https"] == broken_proxy["https"]


def test_proxy_opt_in_applies_to_post_and_qr_poll():
    client = WeChatClient(use_env_proxy=True)
    with patch("xdty_booking.notify.wechat.requests.post", return_value=response({"ret": 0})) as post:
        client.request("get_bot_qrcode", {}, auth=False)
        assert "proxies" not in post.call_args.kwargs
    with patch("xdty_booking.notify.wechat.requests.get", return_value=response({"status": "wait"})) as get:
        client.request("get_qrcode_status", params={"qrcode": "private-qr"}, auth=False)
        assert "proxies" not in get.call_args.kwargs


def test_legacy_tls_proxy_error_explains_failure_without_secrets():
    error = ValueError("check_hostname requires server_hostname private-token")
    with patch("xdty_booking.notify.wechat.requests.post", side_effect=error):
        with pytest.raises(WeChatError, match="get_bot_qrcode.*代理 TLS") as raised:
            WeChatClient(use_env_proxy=True).request("get_bot_qrcode", {}, auth=False)
    assert "private-token" not in str(raised.value)


def test_http_and_json_failures_identify_endpoint_without_server_text():
    res = response({"errmsg": "private-token"}, 403)
    res.raise_for_status.side_effect = requests.HTTPError("private-token", response=res)
    with patch("xdty_booking.notify.wechat.requests.post", return_value=res):
        with pytest.raises(WeChatError, match="get_bot_qrcode.*HTTP 403") as raised:
            WeChatClient().request("get_bot_qrcode", {}, auth=False)
        assert "private-token" not in str(raised.value)
    res = response({}, 200)
    res.json.side_effect = ValueError("private-token")
    with patch("xdty_booking.notify.wechat.requests.get", return_value=res):
        with pytest.raises(WeChatError, match="get_qrcode_status.*非 JSON"):
            WeChatClient().request("get_qrcode_status", auth=False)


def test_binding_logs_actionable_sanitized_failure(configured, caplog):
    binding = WeChatBinding(configured)
    with patch.object(binding, "_login", side_effect=WeChatError("微信接口 get_bot_qrcode：请求超时")):
        binding._run(login=True)
    assert "get_bot_qrcode" in caplog.text and "请求超时" in caplog.text
    assert binding.status()["phase"] == "error"
    assert "private-token" not in caplog.text


def test_proxy_config_accepts_only_boolean(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("notify:\n  wechat:\n    use_env_proxy: true\n", encoding="utf-8")
    assert load_config(str(path)).notify.wechat.use_env_proxy is True
    path.write_text("notify:\n  wechat:\n    use_env_proxy: 'false'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="use_env_proxy"):
        load_config(str(path))


@pytest.mark.parametrize("payload", [{}, {"message_id": ""}, {"message_id": []}, {"unrelated": "private-token"}])
def test_send_without_acknowledgement_is_not_success(configured, payload, caplog):
    with patch("xdty_booking.notify.wechat.requests.post", return_value=response(payload)):
        assert not send_wechat(configured, "测试", "内容")
    assert "未确认发送结果" in caplog.text
    assert "private-token" not in caplog.text


@pytest.mark.parametrize("payload", [{"ret": 0}, {"errcode": 0}, {"message_id": "accepted-id"}])
def test_explicit_send_acknowledgement_is_accepted(configured, payload):
    with patch("xdty_booking.notify.wechat.requests.post", return_value=response(payload)):
        assert send_wechat(configured, "测试", "内容")


def test_rapid_disable_enable_resumes_after_old_poll_exits(configured):
    binding = WeChatBinding(configured)
    old_poll, release_old, new_poll = threading.Event(), threading.Event(), threading.Event()
    count = []

    def request(client, endpoint, *args, **kwargs):
        if endpoint == "getupdates":
            count.append(endpoint)
            if len(count) == 1:
                old_poll.set()
                assert release_old.wait(3)
            else:
                new_poll.set()
                binding._stop.wait(3)
        return {"ret": 0}

    with patch.object(WeChatClient, "request", request):
        try:
            binding.start()
            assert old_poll.wait(3)
            old_thread = binding._thread
            binding.close()
            binding.start()
            assert binding.status()["phase"] == "stopping"
            release_old.set()
            assert new_poll.wait(3)
            assert binding._thread is not old_thread
            old_thread.join(3)
            assert not old_thread.is_alive()
        finally:
            binding.close()
            release_old.set()
            if binding._thread:
                binding._thread.join(3)
    assert not binding._thread.is_alive()


def test_closing_again_cancels_pending_resume(configured):
    binding = WeChatBinding(configured)
    old_poll, release_old = threading.Event(), threading.Event()

    def request(client, endpoint, *args, **kwargs):
        if endpoint == "getupdates":
            old_poll.set()
            assert release_old.wait(3)
        return {"ret": 0}

    with patch.object(WeChatClient, "request", request):
        try:
            binding.start()
            assert old_poll.wait(3)
            old_thread = binding._thread
            binding.close()
            binding.start()
            binding.close()
            release_old.set()
            old_thread.join(3)
            assert not old_thread.is_alive()
            assert binding._thread is old_thread
            assert not binding._resume_requested
        finally:
            binding.close()
            release_old.set()
            if binding._thread:
                binding._thread.join(3)
