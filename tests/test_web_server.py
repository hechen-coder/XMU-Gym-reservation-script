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

