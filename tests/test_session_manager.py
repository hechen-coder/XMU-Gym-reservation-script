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
