from unittest.mock import patch, MagicMock
from xdty_booking.config import NotifyConfig, EmailConfig, PushPlusConfig, ServerChanConfig, BarkConfig
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
            "area_name": "爱秋体育馆",
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
