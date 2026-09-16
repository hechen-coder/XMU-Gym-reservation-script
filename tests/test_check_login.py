import pytest
from unittest.mock import MagicMock, patch
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.auth.session_manager import SessionManager
from xdty_booking.config import load_config, save_auth_params, AuthConfig
from xdty_booking.auth.sniffer_proxy import SnifferProxy

def test_api_check_login_success():
    client = ApiClient(base_url="https://test.edu.cn")
    api = XdtyApi(client)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": 1, "info": "验证成功", "data": []}
    mock_resp.cookies.get.return_value = "new_sess_12345"
    mock_resp.headers = {"Set-Cookie": "PHPSESSID=new_sess_12345; path=/"}

    with patch.object(client, "post", return_value=mock_resp) as mock_post:
        success, phpsessid, data = api.check_login({
            "token": "TEST_TOKEN_12345678",
            "sign": "TEST_SIGN",
            "uid": "1001",
            "card_id": "369000",
            "student_num": "369000",
            "school_id": 788,
        })

        assert success is True
        assert phpsessid == "new_sess_12345"
        assert data.get("status") == 1
        assert client.session.cookies.get("PHPSESSID") == "new_sess_12345"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "public/index.php/index/Index/checkLogin"
        assert kwargs["data"]["token"] == "TEST_TOKEN_12345678"
        assert kwargs["data"]["uid"] == "1001"
        assert "referer" in kwargs

def test_api_check_login_missing_token():
    client = ApiClient(base_url="https://test.edu.cn")
    api = XdtyApi(client)

    success, phpsessid, data = api.check_login({"uid": "1001"})
    assert success is False
    assert "缺少 token" in data.get("info", "")

def test_api_check_login_failure_response():
    client = ApiClient(base_url="https://test.edu.cn")
    api = XdtyApi(client)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": 0, "info": "登录信息失效,请退出重新登录", "data": []}
    mock_resp.cookies.get.return_value = None
    mock_resp.headers = {}

    with patch.object(client, "post", return_value=mock_resp):
        success, phpsessid, data = api.check_login({"token": "INVALID_TOKEN"})
        assert success is False
        assert phpsessid == ""
        assert "登录信息失效" in data.get("info", "")

def test_session_manager_refresh_via_check_login_success(tmp_path):
    client = ApiClient(base_url="https://test.edu.cn")
    api = XdtyApi(client)

    fake_config = tmp_path / "config.yaml"
    fake_config.write_text('auth:\n  phpsessid: "old_sess"\n', encoding="utf-8")

    mgr = SessionManager(
        api=api,
        phpsessid="old_sess",
        auth_params={"token": "VALID_TOKEN", "uid": "1001"},
        config_path=str(fake_config)
    )

    with patch.object(api, "check_login", return_value=(True, "brand_new_cookie", {"status": 1})), \
         patch.object(api, "my_subscribe", return_value={"status": 1, "data": []}):
        token = mgr.refresh_session_via_check_login()
        assert token == "brand_new_cookie"
        assert mgr.phpsessid == "brand_new_cookie"
        assert "brand_new_cookie" in fake_config.read_text(encoding="utf-8")

def test_session_manager_renew_or_fallback():
    client = ApiClient(base_url="https://test.edu.cn")
    api = XdtyApi(client)
    mock_fallback = MagicMock(return_value="harvester_cookie_999")

    # 1. When check_login succeeds, fallback is NOT called
    mgr = SessionManager(
        api=api,
        phpsessid="expired_sess",
        auth_params={"token": "VALID_TOKEN"},
        on_expired=mock_fallback
    )
    with patch.object(mgr, "refresh_session_via_check_login", return_value="http_new_cookie"):
        res = mgr.renew_or_fallback()
        assert res == "http_new_cookie"
        mock_fallback.assert_not_called()

    # 2. When check_login fails, fallback IS called
    with patch.object(mgr, "refresh_session_via_check_login", return_value=None):
        res = mgr.renew_or_fallback()
        assert res == "harvester_cookie_999"
        mock_fallback.assert_called_once()

def test_config_save_auth_params(tmp_path):
    fake_config = tmp_path / "config.yaml"
    fake_config.write_text("auth:\n  phpsessid: \"test\"\n", encoding="utf-8")

    saved = save_auth_params(str(fake_config), {
        "token": "NEW_TOKEN_XYZ",
        "sign": "NEW_SIGN",
        "uid": "1073507"
    })
    assert saved is True
    cfg = load_config(str(fake_config))
    assert cfg.auth.auth_params.get("token") == "NEW_TOKEN_XYZ"
    assert cfg.auth.uid == "1073507"

def test_sniffer_proxy_extract_auth_params():
    captured = {}
    def on_captured(params):
        captured.update(params)

    proxy = SnifferProxy(on_auth_params_captured=on_captured)

    sample_req = (
        b"POST /bdlp_h5_fitness_test/public/index.php/index/Index/checkLogin HTTP/1.1\r\n"
        b"Host: xdty.xmu.edu.cn\r\n"
        b"Referer: https://xdty.xmu.edu.cn/bdlp_h5_fitness_test/view/stadium/home.html?token=SNIFFED_TOKEN_123456&sign=SNIFFED_SIGN\r\n"
        b"\r\n"
        b"uid=1073507&token=SNIFFED_TOKEN_123456&sign=SNIFFED_SIGN&card_id=36920261153318"
    )

    proxy._inspect_and_extract_auth_params(sample_req)
    assert proxy.captured_auth_params is not None
    assert proxy.captured_auth_params.get("token") == "SNIFFED_TOKEN_123456"
    assert proxy.captured_auth_params.get("uid") == "1073507"
    assert captured.get("token") == "SNIFFED_TOKEN_123456"
