import pytest
from unittest.mock import Mock
from xdty_booking.auth.session_manager import SessionManager

def test_session_check_alive_success():
    api = Mock()
    api.my_subscribe.return_value = {"status": 1, "info": "查询成功", "data": []}
    mgr = SessionManager(api, phpsessid="valid_token")
    assert mgr.check_alive() is True

def test_session_check_alive_failure_status():
    api = Mock()
    api.my_subscribe.return_value = {"status": -1, "info": "登录过期"}
    mgr = SessionManager(api, phpsessid="expired_token")
    assert mgr.check_alive() is False

def test_session_check_alive_exception():
    api = Mock()
    api.my_subscribe.side_effect = Exception("Network error")
    mgr = SessionManager(api, phpsessid="token")
    assert mgr.check_alive() is False

def test_session_heartbeat_daemon():
    api = Mock()
    api.my_subscribe.return_value = {"status": 1, "info": "查询成功"}
    mgr = SessionManager(api, phpsessid="token")
    mgr.start_heartbeat_daemon(interval_seconds=1)
    assert mgr._running is True
    mgr.stop()
    assert mgr._running is False

def test_session_manager_auto_syncs_client_token_on_init():
    api = Mock()
    client = Mock()
    api.client = client
    mgr = SessionManager(api, phpsessid="token_abc_123")
    client.set_session_token.assert_called_with("token_abc_123")

def test_session_manager_check_alive_syncs_client_token():
    api = Mock()
    client = Mock()
    api.client = client
    api.my_subscribe.return_value = {"status": 1, "info": "ok"}
    mgr = SessionManager(api, phpsessid="token_xyz_456")
    client.set_session_token.reset_mock()
    assert mgr.check_alive() is True
    client.set_session_token.assert_called_with("token_xyz_456")

def test_ensure_session_short_circuit_cache(monkeypatch):
    import time
    from xdty_booking.web.server import ensure_session
    import xdty_booking.web.server as srv

    cfg = Mock()
    cfg.auth.phpsessid = "cached_token_123"
    cfg.auth.auth_params = {"token": "t"}
    session_mgr = Mock()
    session_mgr.check_alive.return_value = True
    client = Mock()

    # Reset cache
    srv._LAST_SESSION_VALID_TIME = 0.0
    srv._LAST_SESSION_VALID_TOKEN = ""

    # First call: performs check_alive
    res1 = ensure_session(cfg, session_mgr, client, "fake_path.yaml")
    assert res1 is True
    assert session_mgr.check_alive.call_count == 1

    # Second call within 15 seconds: should use short-circuit cache without check_alive
    res2 = ensure_session(cfg, session_mgr, client, "fake_path.yaml")
    assert res2 is True
    assert session_mgr.check_alive.call_count == 1  # No extra call!

def test_ensure_session_adopts_concurrently_renewed_token(monkeypatch):
    from xdty_booking.web.server import ensure_session
    import xdty_booking.web.server as srv
    from unittest.mock import patch, MagicMock

    cfg = Mock()
    cfg.auth.phpsessid = "old_token_111"
    cfg.auth.auth_params = {"token": "t"}
    session_mgr = Mock()
    client = Mock()

    # Reset cache
    srv._LAST_SESSION_VALID_TIME = 0.0
    srv._LAST_SESSION_VALID_TOKEN = ""

    # Mock load_config to return a newer token that another thread wrote to disk
    newer_cfg = Mock()
    newer_cfg.auth.phpsessid = "new_token_999"
    newer_cfg.auth.auth_params = {"token": "t"}
    session_mgr.check_alive.return_value = True

    with patch("xdty_booking.web.server.load_config", return_value=newer_cfg):
        res = ensure_session(cfg, session_mgr, client, "fake_path.yaml")
        assert res is True
        assert cfg.auth.phpsessid == "new_token_999"
        session_mgr.update_token.assert_called_with("new_token_999")
        client.set_session_token.assert_called_with("new_token_999")

def test_handle_my_orders_sets_client_token(monkeypatch):
    from xdty_booking.web.server import GymStatusHandler
    from unittest.mock import patch, MagicMock

    handler = GymStatusHandler.__new__(GymStatusHandler)
    handler._send_json = MagicMock()

    cfg = MagicMock()
    cfg.base_url = "http://fake"
    cfg.auth.phpsessid = "my_token_888"
    cfg.auth.uid = "12345"

    with patch("xdty_booking.web.server.load_config", return_value=cfg), \
         patch("xdty_booking.web.server.ApiClient") as MockClient, \
         patch("xdty_booking.web.server.ensure_session", return_value=True), \
         patch("xdty_booking.web.server.XdtyApi") as MockApi:
        mock_client_instance = MockClient.return_value
        mock_api_instance = MockApi.return_value
        mock_api_instance.my_subscribe.return_value = {"status": 1, "data": []}

        handler._handle_my_orders()
        mock_client_instance.set_session_token.assert_called_with("my_token_888")


