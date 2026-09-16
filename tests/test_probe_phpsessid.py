import unittest
from unittest.mock import patch, MagicMock
from tools.probe_phpsessid import check_phpsessid_alive, get_session_start_time, update_session_alive

class TestProbePhpsessid(unittest.TestCase):
    @patch("tools.probe_phpsessid.ApiClient")
    @patch("tools.probe_phpsessid.XdtyApi")
    def test_phpsessid_validity_alive(self, mock_api_cls, mock_client_cls):
        mock_api = MagicMock()
        mock_api.my_subscribe.return_value = {"status": 1, "info": "查询成功", "data": [{"uid": "1073507"}]}
        mock_api_cls.return_value = mock_api

        alive, info, data = check_phpsessid_alive("fake_token_123")
        self.assertTrue(alive)
        self.assertEqual(info, "会话正常有效")
        self.assertEqual(data["data"][0]["uid"], "1073507")

    @patch("tools.probe_phpsessid.ApiClient")
    @patch("tools.probe_phpsessid.XdtyApi")
    def test_phpsessid_validity_expired(self, mock_api_cls, mock_client_cls):
        mock_api = MagicMock()
        mock_api.my_subscribe.return_value = {"status": 0, "info": "登录信息失效,请退出重新登录"}
        mock_api_cls.return_value = mock_api

        alive, info, _ = check_phpsessid_alive("fake_token_expired")
        self.assertFalse(alive)
        self.assertIn("失效", info)

    def test_get_session_start_time_custom(self):
        dt = get_session_start_time("test_token", custom_since="2026-09-12 10:00:00")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 9)
        self.assertEqual(dt.day, 12)
        self.assertEqual(dt.hour, 10)
