import json
import unittest
from unittest.mock import patch, MagicMock
from xdty_booking.web.server import GymStatusHandler, query_gym_status
from xdty_booking.web.template import render_dashboard

class TestWebServer(unittest.TestCase):
    def test_render_dashboard_expired_session(self):
        data = {
            "stadium_name": "测试健身房",
            "area_name": "二楼力量区",
            "query_time": "2026-09-12 10:00:00",
            "session_valid": False,
            "info": "登录信息失效,请退出重新登录",
            "groups": []
        }
        html = render_dashboard(data)
        self.assertIn("当前登录凭证已失效", html)
        self.assertIn("手动输入 Token", html)
        self.assertIn("setManualToken", html)

    @patch("xdty_booking.web.server.save_phpsessid")
    @patch("xdty_booking.web.server.load_config")
    @patch("xdty_booking.web.server.SessionManager.check_alive")
    def test_handle_set_token(self, mock_alive, mock_load, mock_save):
        mock_save.return_value = True
        cfg = MagicMock()
        cfg.base_url = "http://fake"
        cfg.auth.phpsessid = "new_token_12345678"
        cfg.auth.uid = None
        mock_load.return_value = cfg
        mock_alive.return_value = True

        handler = GymStatusHandler.__new__(GymStatusHandler)
        handler._send_json = MagicMock()

        handler._handle_set_token({"token": ["new_token_12345678"]})
        handler._send_json.assert_called_once()
        code, body = handler._send_json.call_args[0]
        self.assertEqual(code, 200)
        self.assertTrue(body["success"])
        self.assertTrue(body["alive"])

    def test_render_dashboard_with_auth_params(self):
        data = {
            "stadium_name": "测试健身房",
            "area_name": "二楼力量区",
            "query_time": "2026-09-12 10:00:00",
            "session_valid": False,
            "has_auth_params": True,
            "info": "登录信息失效,请退出重新登录",
            "groups": []
        }
        html = render_dashboard(data)
        self.assertIn("当前登录凭证已失效", html)
        self.assertIn("HTTP 自动续登", html)
        self.assertIn("reloginSession", html)

    @patch("xdty_booking.web.server.load_config")
    @patch("xdty_booking.web.server.SessionManager.refresh_session_via_check_login")
    def test_handle_relogin_success(self, mock_refresh, mock_load):
        mock_refresh.return_value = "new_phpsessid_abcdef123456"
        cfg = MagicMock()
        cfg.base_url = "http://fake"
        cfg.auth.phpsessid = "old"
        cfg.auth.uid = None
        cfg.auth.auth_params = {"token": "tok"}
        mock_load.return_value = cfg

        handler = GymStatusHandler.__new__(GymStatusHandler)
        handler._send_json = MagicMock()

        handler._handle_relogin()
        handler._send_json.assert_called_once()
        code, body = handler._send_json.call_args[0]
        self.assertEqual(code, 200)
        self.assertTrue(body["success"])
        self.assertEqual(body["token"], "new_phpsessid_abcdef123456")

    @patch("xdty_booking.web.server.load_config")
    @patch("xdty_booking.web.server.SessionManager.refresh_session_via_check_login")
    def test_handle_relogin_failure(self, mock_refresh, mock_load):
        mock_refresh.return_value = None
        cfg = MagicMock()
        cfg.base_url = "http://fake"
        cfg.auth.phpsessid = "old"
        cfg.auth.uid = None
        cfg.auth.auth_params = {}
        mock_load.return_value = cfg

        handler = GymStatusHandler.__new__(GymStatusHandler)
        handler._send_json = MagicMock()

        handler._handle_relogin()
        handler._send_json.assert_called_once()
        code, body = handler._send_json.call_args[0]
        self.assertEqual(code, 200)
        self.assertFalse(body["success"])

    def test_ensure_session_unlogged_no_credentials(self):
        from xdty_booking.web.server import ensure_session
        cfg = MagicMock()
        cfg.auth.phpsessid = ""
        cfg.auth.auth_params = {}
        session_mgr = MagicMock()
        client = MagicMock()

        res = ensure_session(cfg, session_mgr, client, "fake.yaml")
        self.assertFalse(res)
        session_mgr.renew_or_fallback.assert_not_called()

    def test_render_dashboard_unlogged_script_and_prompt(self):
        data = {
            "stadium_name": "测试健身房",
            "area_name": "二楼力量区",
            "query_time": "2026-09-12 10:00:00",
            "session_valid": False,
            "info": "未登录",
            "groups": []
        }
        html = render_dashboard(data)
        self.assertIn("const IS_SESSION_VALID = false;", html)
        self.assertIn("🔑 手动登录", html)
        self.assertIn(".lnk", html)
        self.assertIn("场馆预约", html)
    def test_render_dashboard_modal_and_book_slot_safeguards(self):
        data = {
            "stadium_name": "测试健身房",
            "area_name": "二楼力量区",
            "query_time": "2026-09-12 10:00:00",
            "session_valid": True,
            "info": "正常",
            "groups": [
                {
                    "date": "2026-09-20",
                    "week_name": "周日",
                    "time_range": "19:30-21:00",
                    "is_preferred": True,
                    "slots": [
                        {
                            "interval_id": "9999",
                            "selected": 5,
                            "max_count": 50,
                            "remaining": 45,
                            "is_available": True,
                            "is_locked": False
                        }
                    ]
                }
            ]
        }
        html = render_dashboard(data)

        # 1. 验证预约按钮传参包含 this，不依赖易受污染的 window.event
        self.assertIn("bookSlot('9999', '2026-09-20', '19:30-21:00', this)", html)

        # 2. 验证弹窗具备右上角关闭按钮
        self.assertIn('id="customDialogCloseBtn"', html)

        # 3. 验证 customAlert / confirm / prompt 及 _closeCustomDialog 具有 disabled = false 复位保护
        self.assertIn("confirmBtn.disabled = false;", html)
        self.assertIn("cancelBtn.disabled = false;", html)

        # 4. 验证 CSS 包含 .dialog-btn:disabled 规范
        self.assertIn(".dialog-btn:disabled", html)

        # 5. 验证全局支持 Backdrop 遮罩点击关闭与 Esc/Enter 按键响应
        self.assertIn('e.target === customModal', html)
        self.assertIn('e.key === "Escape"', html)
        self.assertIn('e.key === "Enter"', html)

    def test_render_dashboard_notification_ui(self):
        data = {
            "stadium_name": "测试健身房",
            "area_name": "二楼力量区",
            "query_time": "2026-09-12 10:00:00",
            "session_valid": True,
            "info": "正常",
            "groups": [],
            "notify_config": {
                "enabled": True,
                "email": "user@qq.com",
                "channel": "email"
            }
        }
        html = render_dashboard(data)
        self.assertIn('id="featureNotifyBtn"', html)
        self.assertIn('id="notifyModal"', html)
        self.assertIn('id="notifySwitch"', html)
        self.assertIn('id="notifyEmailInput"', html)
        self.assertIn('sendTestNotification()', html)
        self.assertIn('saveNotificationSettings()', html)
        self.assertIn('openNotifyModal()', html)
        self.assertIn('user@qq.com', html)

    @patch("xdty_booking.web.server.load_config")
    def test_handle_notify_config_get(self, mock_load):
        cfg = MagicMock()
        cfg.notify.enabled = True
        cfg.notify.email.to_addrs = ["user123@qq.com"]
        cfg.notify.channel = "email"
        mock_load.return_value = cfg

        handler = GymStatusHandler.__new__(GymStatusHandler)
        handler._send_json = MagicMock()

        handler._handle_notify_config_get()
        handler._send_json.assert_called_once()
        code, body = handler._send_json.call_args[0]
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["enabled"])
        self.assertEqual(body["email"], "user123@qq.com")

    @patch("xdty_booking.web.server.save_notify_config")
    def test_handle_notify_config_post(self, mock_save):
        handler = GymStatusHandler.__new__(GymStatusHandler)
        handler._send_json = MagicMock()

        payload = {"enabled": True, "email": "test@qq.com"}
        handler._handle_notify_config_post(payload)

        mock_save.assert_called_once_with(unittest.mock.ANY, enabled=True, email="test@qq.com", channel="email")
        handler._send_json.assert_called_once()
        code, body = handler._send_json.call_args[0]
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "ok")

    @patch("xdty_booking.web.server.load_config")
    @patch("xdty_booking.web.server.Notifier")
    def test_handle_notify_test(self, mock_notifier_cls, mock_load):
        cfg = MagicMock()
        mock_load.return_value = cfg
        mock_notifier = MagicMock()
        mock_notifier.send_test.return_value = {"email": True}
        mock_notifier_cls.return_value = mock_notifier

        handler = GymStatusHandler.__new__(GymStatusHandler)
        handler._send_json = MagicMock()

        payload = {"email": "tester@qq.com"}
        handler._handle_notify_test(payload)

        self.assertEqual(cfg.notify.email.to_addrs, ["tester@qq.com"])
        mock_notifier.send_test.assert_called_once()
        handler._send_json.assert_called_once()
        code, body = handler._send_json.call_args[0]
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "ok")

    def test_render_dashboard_my_orders_ui(self):
        data = {
            "stadium_name": "测试健身房",
            "area_name": "二楼力量区",
            "query_time": "2026-09-12 10:00:00",
            "session_valid": True,
            "info": "正常",
            "groups": []
        }
        html = render_dashboard(data)
        self.assertIn('id="featureMyOrdersBtn"', html)
        self.assertIn('id="myOrdersModal"', html)
        self.assertIn('openMyOrdersModal()', html)
        self.assertIn('fetchMyOrders()', html)
        self.assertIn('filterMyOrders(', html)

    @patch("xdty_booking.web.server.load_config")
    @patch("xdty_booking.web.server.ensure_session")
    @patch("xdty_booking.web.server.XdtyApi")
    def test_handle_my_orders_success(self, mock_api_cls, mock_ensure, mock_load):
        mock_ensure.return_value = True
        cfg = MagicMock()
        mock_load.return_value = cfg

        mock_api = MagicMock()
        mock_api.my_subscribe.return_value = {
            "status": 1,
            "data": [
                {
                    "order_id": 711681,
                    "order_num": "B091916380301732651",
                    "stadium_name": "翔安校区健身房",
                    "audit_status": 1,
                    "audit_status_text": "已预约"
                },
                {
                    "order_id": 711666,
                    "order_num": "B091916244242540244",
                    "stadium_name": "翔安校区健身房",
                    "audit_status": 3,
                    "audit_status_text": "已取消"
                }
            ]
        }
        mock_api.order_details.return_value = {
            "status": 1,
            "data": {
                "order_id": 711681,
                "venue_name": "爱秋体育馆健身房",
                "details": [
                    {
                        "date": "2026-09-19",
                        "week": "周六",
                        "interval_time": "19:30-21:00",
                        "area_name": "爱秋体育馆健身房"
                    }
                ]
            }
        }
        mock_api_cls.return_value = mock_api

        handler = GymStatusHandler.__new__(GymStatusHandler)
        handler._send_json = MagicMock()

        handler._handle_my_orders()
        handler._send_json.assert_called_once()
        code, body = handler._send_json.call_args[0]
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["success"])
        self.assertEqual(len(body["orders"]), 2)
        self.assertEqual(body["active_count"], 1)
        # 验证有效订单已被富化时段信息
        active_order = body["orders"][0]
        self.assertEqual(active_order["date"], "2026-09-19")
        self.assertEqual(active_order["interval_time"], "19:30-21:00")
        self.assertEqual(active_order["venue_name"], "爱秋体育馆健身房")

    @patch("xdty_booking.web.server.load_config")
    @patch("xdty_booking.web.server.ensure_session")
    def test_handle_my_orders_session_invalid(self, mock_ensure, mock_load):
        mock_ensure.return_value = False
        cfg = MagicMock()
        mock_load.return_value = cfg

        handler = GymStatusHandler.__new__(GymStatusHandler)
        handler._send_json = MagicMock()

        handler._handle_my_orders()
        handler._send_json.assert_called_once()
        code, body = handler._send_json.call_args[0]
        self.assertEqual(code, 200)
        self.assertFalse(body["success"])
        self.assertFalse(body["session_valid"])
        self.assertIn("登录凭证已失效", body["info"])


