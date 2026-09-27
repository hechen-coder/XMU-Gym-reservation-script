from unittest.mock import patch, MagicMock
import pytest
import requests
from xdty_booking.config import NotifyConfig, EmailConfig, PushPlusConfig, ServerChanConfig, BarkConfig, FeishuConfig
from xdty_booking.notify.notifier import Notifier

def test_notifier_disabled():
    cfg = NotifyConfig(enabled=False)
    notifier = Notifier(cfg)
    assert not notifier.is_enabled()
    res = notifier.send("测试标题", "测试内容")
    assert res == {}

def test_notifier_pushplus_success():
    cfg = NotifyConfig(
        enabled=True,
        channel="pushplus",
        pushplus=PushPlusConfig(token="fake_token_123")
    )
    notifier = Notifier(cfg)
    
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"code": 200, "msg": "请求成功"}
    
    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = notifier.send("预约成功", "已锁定场地")
        assert res.get("pushplus") is True
        assert mock_post.called
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["token"] == "fake_token_123"
        assert "预约成功" in kwargs["json"]["title"]

def test_notifier_email_success():
    cfg = NotifyConfig(
        enabled=True,
        channel="email",
        email=EmailConfig(
            smtp_host="smtp.fake.com",
            smtp_port=465,
            ssl=True,
            sender="bot@fake.com",
            password="auth_password",
            to_addrs=["user@fake.com"]
        )
    )
    notifier = Notifier(cfg)
    
    with patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
        mock_server = MagicMock()
        mock_smtp_ssl.return_value = mock_server
        
        res = notifier.send("预约成功", "已锁定场地")
        assert res.get("email") is True
        mock_server.login.assert_called_once_with("bot@fake.com", "auth_password")
        assert mock_server.sendmail.called
        mock_server.quit.assert_called_once()

def test_notifier_booking_success_template():
    cfg = NotifyConfig(
        enabled=True,
        channel="pushplus",
        pushplus=PushPlusConfig(token="fake_token_123")
    )
    notifier = Notifier(cfg)
    
    with patch.object(notifier, "send", return_value={"pushplus": True}) as mock_send:
        slot_info = {
            "stadium_name": "翔安校区健身房",
            "area_name": "<img src=x onerror=alert(1)>",
            "date": "2026-09-12",
            "time_range": "19:30-21:00",
            "interval_id": "3080",
            "mode": "准点抢票"
        }
        res = notifier.send_booking_success(slot_info, {"info": "下单成功"})
        assert res.get("pushplus") is True
        assert mock_send.called
        _, kwargs = mock_send.call_args
        assert "19:30-21:00" in kwargs["title"]
        assert "翔安校区健身房" in kwargs["content"]
        assert "<img src=x onerror=alert(1)>" not in kwargs["html_content"]
        assert "&lt;img src=x onerror=alert(1)&gt;" in kwargs["html_content"]

@pytest.fixture
def feishu_notifier():
    return Notifier(NotifyConfig(
        enabled=True, channel="feishu",
        feishu=FeishuConfig(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test"),
    ))

def test_feishu_booking_success(feishu_notifier):
    with patch("requests.post") as post:
        post.return_value.json.return_value = {"code": 0, "msg": "success"}
        result = feishu_notifier.send_booking_success({
            "stadium_name": "翔安校区健身房", "date": "2026-09-20",
            "time_range": "19:30-21:00", "interval_id": "3080",
        })
    assert result == {"feishu": True}
    args, kwargs = post.call_args
    assert args == (feishu_notifier.cfg.feishu.webhook_url,)
    assert kwargs["timeout"] == 10
    payload = kwargs["json"]
    assert payload["msg_type"] == "text"
    for text in ("【厦大体育馆预约】", "翔安校区健身房", "2026-09-20", "19:30-21:00"):
        assert text in payload["content"]["text"]
    assert "timestamp" not in payload
    assert "sign" not in payload

@pytest.mark.parametrize("response", [{"code": 19024}, {}, [], {"code": 9499, "StatusCode": 0}])
def test_feishu_api_failure(feishu_notifier, response):
    with patch("requests.post") as post:
        post.return_value.json.return_value = response
        assert feishu_notifier.send_test() == {"feishu": False}

def test_feishu_signature(feishu_notifier):
    feishu_notifier.cfg.feishu.secret = "test-secret"
    with patch("xdty_booking.notify.notifier.time.time", return_value=1700000000.9), patch("requests.post") as post:
        post.return_value.json.return_value = {"code": 0}
        assert feishu_notifier.send_test() == {"feishu": True}
    payload = post.call_args.kwargs["json"]
    assert payload["timestamp"] == "1700000000"
    assert payload["sign"] == "mbm4Y4oluIPQ00qlBIhX8vAZ0EKv3nw0LuTb91jPL84="

@pytest.mark.parametrize("error_stage", ["post", "http", "json"])
def test_feishu_request_failure_redacts_credentials(feishu_notifier, caplog, error_stage):
    with patch("requests.post") as post:
        secret_url = feishu_notifier.cfg.feishu.webhook_url
        if error_stage == "post":
            post.side_effect = requests.Timeout(secret_url)
        elif error_stage == "http":
            post.return_value.raise_for_status.side_effect = requests.HTTPError(secret_url)
        else:
            post.return_value.json.side_effect = ValueError(secret_url)
        assert feishu_notifier.send_test() == {"feishu": False}
    assert secret_url not in caplog.text
    assert "飞书推送异常" in caplog.text

@pytest.mark.parametrize("enabled, webhook", [(False, "https://example.com/hook"), (True, "")])
def test_feishu_disabled_or_unconfigured(feishu_notifier, enabled, webhook):
    feishu_notifier.cfg.enabled = enabled
    feishu_notifier.cfg.feishu.webhook_url = webhook
    with patch("requests.post") as post:
        assert feishu_notifier.send_test() == {}
        post.assert_not_called()

def test_all_channels_includes_feishu_after_other_failure(feishu_notifier):
    feishu_notifier.cfg.channel = "all"
    feishu_notifier.cfg.pushplus.token = "test-token"
    with patch.object(feishu_notifier, "_send_pushplus", return_value=False), patch("requests.post") as post:
        post.return_value.json.return_value = {"code": 0}
        assert feishu_notifier.send_test() == {"pushplus": False, "feishu": True}

def test_notifier_developer_unified_sender(tmp_path):
    """测试买家仅填写自己的 QQ 邮箱时，系统自动注入开发者统一发信箱进行投递"""
    from xdty_booking.config import (
        DEFAULT_DEVELOPER_EMAIL_SENDER,
        DEFAULT_DEVELOPER_EMAIL_AUTH,
        save_notify_config,
        load_config
    )

    # 1. 验证 load_config 智能注入
    cfg_file = str(tmp_path / "test_config.yaml")
    with open(cfg_file, "w", encoding="utf-8") as f:
        f.write("notify:\n  enabled: true\n  email:\n    to_addrs: ['customer@qq.com']\n")

    cfg = load_config(cfg_file)
    assert cfg.notify.channel == "email"
    assert cfg.notify.email.sender == DEFAULT_DEVELOPER_EMAIL_SENDER
    assert cfg.notify.email.password == DEFAULT_DEVELOPER_EMAIL_AUTH
    assert cfg.notify.email.to_addrs == ["customer@qq.com"]

    # 2. 验证 Notifier 实际投递调用
    notifier = Notifier(cfg.notify)
    with patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
        mock_server = MagicMock()
        mock_smtp_ssl.return_value = mock_server

        res = notifier.send("抢票提醒", "测试内容")
        assert res.get("email") is True
        mock_server.login.assert_called_once_with(DEFAULT_DEVELOPER_EMAIL_SENDER, DEFAULT_DEVELOPER_EMAIL_AUTH)
        assert mock_server.sendmail.called
        args, _ = mock_server.sendmail.call_args
        assert args[0] == DEFAULT_DEVELOPER_EMAIL_SENDER
        assert args[1] == ["customer@qq.com"]

    # 3. 验证 save_notify_config 持久化
    save_notify_config(cfg_file, enabled=False, email="new_customer@qq.com")
    cfg_after = load_config(cfg_file)
    assert cfg_after.notify.enabled is False
    assert cfg_after.notify.email.to_addrs == ["new_customer@qq.com"]
