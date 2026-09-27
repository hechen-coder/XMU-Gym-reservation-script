import http.client
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest
import requests

from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.config import load_config, save_auth_params, save_phpsessid
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.core.models import SlotItem
from xdty_booking.config import AppConfig
from xdty_booking.web.server import GymStatusHandler, ThreadingHTTPServer, run_server
from xdty_booking.web.template import render_dashboard
from cas_qr_login.server import CasQrRequestHandler, HTML_TEMPLATE


def _order(api):
    return api.add_order(
        stadium_id=16, venue_id=14, stadium_name="健身房", project_name="健身房",
        area_name="力量区", date="2026-09-27", week="7", week_msg="周日",
        interval_time="19:30-21:00", interval_id="3087", area_id="67", captcha="abcd"
    )


def test_order_success_is_not_submitted_twice():
    client = ApiClient()
    client.set_session_token("dedupe_success_account")
    api = XdtyApi(client)
    response = Mock(status_code=200)
    response.json.return_value = {"status": 1, "info": "预约成功", "data": {"private": "secret"}}
    with patch.object(client, "post", return_value=response) as post:
        assert _order(api)["status"] == 1
        assert _order(api)["duplicate"] is True
        assert post.call_count == 1


def test_unknown_order_result_is_not_retried():
    client = ApiClient()
    client.set_session_token("dedupe_timeout_account")
    api = XdtyApi(client)
    with patch.object(client, "post", side_effect=requests.Timeout("secret-url")) as post:
        assert _order(api)["outcome_unknown"] is True
        assert _order(api)["outcome_unknown"] is True
        assert post.call_count == 1


def test_concurrent_order_request_is_rejected_while_first_is_running():
    client = ApiClient()
    client.set_session_token("dedupe_parallel_account")
    api = XdtyApi(client)
    started, release = threading.Event(), threading.Event()
    response = Mock(status_code=200)
    response.json.return_value = {"status": 1, "info": "预约成功"}

    def slow_post(*args, **kwargs):
        started.set()
        assert release.wait(2)
        return response

    with patch.object(client, "post", side_effect=slow_post) as post, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_order, api)
        assert started.wait(2)
        second = pool.submit(_order, api)
        assert second.result(timeout=2)["in_progress"] is True
        release.set()
        assert first.result(timeout=2)["status"] == 1
        assert post.call_count == 1


def test_booking_exception_does_not_retry_or_fallback():
    api = Mock()
    slot = SlotItem("67", "2026-09-27", "力量区", "3087", 0, 0, 20, "available")
    intervals = Mock(status=1)
    intervals.find_slot_with_group.return_value = None
    intervals.find_slot.return_value = slot
    api.get_intervals.return_value = intervals
    api.choose_verify.return_value = {"status": 1}
    api.get_captcha.return_value = b"png"
    api.add_order.side_effect = requests.Timeout("lost response")
    solver = Mock()
    solver.solve.return_value = "abcd"
    result = BookingEngine(api, solver, AppConfig()).execute_booking(target_date="2026-09-27")
    assert result["reason"] == "outcome_unknown"
    assert api.add_order.call_count == 1
    intervals.find_nearest_available_slots.assert_not_called()


def test_booking_query_error_does_not_expose_request_url():
    api = Mock()
    api.get_intervals.side_effect = requests.Timeout("https://example.test/?token=private-value")
    result = BookingEngine(api, Mock(), AppConfig()).execute_booking(target_date="2026-09-27")
    assert result["reason"] == "query_failed"
    assert "private-value" not in result["info"]


def test_config_writes_preserve_both_updates_and_private_permissions(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text('auth:\n  phpsessid: "old"\n')
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(save_phpsessid, str(path), "new_session_123456")
        b = pool.submit(save_auth_params, str(path), {"token": "renew_123456"})
        assert a.result() and b.result()
    cfg = load_config(str(path))
    assert cfg.auth.phpsessid == "new_session_123456"
    assert cfg.auth.auth_params["token"] == "renew_123456"
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


def test_null_config_sections_use_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("base_url: null\nauth: null\ntarget: null\nscheduler: null\nnotify: null\n")
    cfg = load_config(str(path))
    assert cfg.auth.auth_params == {}
    assert cfg.target.target_date_offset == 1
    assert cfg.base_url == AppConfig.base_url
    path.write_text("[]")
    with pytest.raises(ValueError):
        load_config(str(path))


def test_dashboard_escapes_untrusted_server_fields():
    payload = "<script>alert(1)</script>"
    html = render_dashboard({
        "stadium_name": payload, "area_name": payload, "session_valid": True,
        "scheduler_status": {"status_text": payload},
        "groups": [{"date": "2026-09-27", "week_name": payload, "time_range": "19:30-21:00",
                    "slots": [{"interval_id": "' onclick='alert(1)", "selected": 0,
                               "max_count": 10, "remaining": 10, "is_available": True}]}]
    })
    assert payload not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert 'data-interval-id="&#x27; onclick=&#x27;alert(1)"' in html


def test_web_rejects_cross_origin_get_mutation_and_invalid_body():
    server = ThreadingHTTPServer(("127.0.0.1", 0), GymStatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/api/book?interval_id=3087&date=2026-09-27&time=19:30-21:00")
        res = conn.getresponse()
        assert res.status == 405
        assert res.getheader("Access-Control-Allow-Origin") is None
        res.read()

        conn.request("POST", "/api/book", body="{}", headers={"Content-Type": "text/plain"})
        assert conn.getresponse().status == 415
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("POST", "/api/book", body="{}", headers={"Content-Type": "application/json", "Origin": "https://evil.example"})
        assert conn.getresponse().status == 403
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("POST", "/api/book", body="[1]", headers={"Content-Type": "application/json"})
        assert conn.getresponse().status == 400
        conn.close()

        with patch("xdty_booking.web.server.book_gym_slot", return_value={"success": True}) as book:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            body = json.dumps({"interval_id": "3087", "date": "2026-09-27", "time": "19:30-21:00"})
            conn.request("POST", "/api/book", body=body, headers={"Content-Type": "application/json"})
            res = conn.getresponse()
            assert res.status == 200
            assert json.load(res)["success"] is True
            book.assert_called_once()
            conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_public_bind_is_rejected_before_starting():
    with pytest.raises(ValueError, match="回环地址"):
        run_server(host="0.0.0.0")


def test_standalone_qr_server_book_and_host_guards():
    import cas_qr_login.server as qr_server
    original_client = qr_server.cas_client
    server = ThreadingHTTPServer(("127.0.0.1", 0), CasQrRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/api/book")
        assert conn.getresponse().status == 405
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/api/qr")
        assert conn.getresponse().status == 405
        conn.close()

        with patch("cas_qr_login.server.CasQrLoginClient") as cas:
            cas.return_value.init_qr_session.return_value = ("test-uuid", b"png")
            cas.return_value.get_qr_image_base64.return_value = "data:image/png;base64,cG5n"
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("POST", "/api/qr", body="{}", headers={"Content-Type": "application/json"})
            res = conn.getresponse()
            assert res.status == 200
            assert json.load(res)["uuid"] == "test-uuid"
            conn.close()

        with patch("cas_qr_login.server.check_license", return_value=Mock(is_licensed=True)), \
             patch("xdty_booking.web.server.book_gym_slot", return_value={"success": True}) as book:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            body = json.dumps({"interval_id": "3087", "date": "2026-09-27", "time": "19:30-21:00"})
            conn.request("POST", "/api/book", body=body, headers={"Content-Type": "application/json"})
            res = conn.getresponse()
            assert res.status == 200
            assert json.load(res)["success"] is True
            book.assert_called_once()
            conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("POST", "/api/book", body="{}", headers={"Content-Type": "application/json", "Host": "evil.example"})
        assert conn.getresponse().status == 403
        conn.close()
    finally:
        qr_server.cas_client = original_client
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_standalone_qr_page_displays_credentials_as_text():
    assert "value.textContent = p[key]" in HTML_TEMPLATE
    assert "${p[key]}" not in HTML_TEMPLATE
