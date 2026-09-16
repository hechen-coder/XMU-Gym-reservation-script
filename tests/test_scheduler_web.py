import os
import json
import yaml
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from xdty_booking.config import save_target_and_scheduler_config, load_config
from xdty_booking.core.scheduler import BookingScheduler
from xdty_booking.web.server import GymStatusHandler, SchedulerManager, SnipeManager
from xdty_booking.web.template import render_dashboard

class TestSchedulerWeb(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "config.yaml")
        initial_yaml = {
            "base_url": "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test",
            "auth": {
                "phpsessid": "dummy_phpsessid_123456",
                "auth_params": {"token": "test_token"}
            },
            "target": {
                "stadium_name": "翔安校区健身房",
                "area_name": "爱秋体育馆健身房",
                "stadium_id": 16,
                "venue_id": 14,
                "area_id": 67,
                "user_range": "[67]",
                "preferred_time": "19:30-21:00",
                "target_date_offset": 1
            },
            "scheduler": {
                "target_time": "07:00:00",
                "fallback_nearest": True,
                "pre_check_minutes": 5
            }
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(initial_yaml, f, allow_unicode=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_target_and_scheduler_config(self):
        target_updates = {
            "stadium_name": "思明校区健身房",
            "area_name": "思明校区健身房",
            "stadium_id": 6,
            "venue_id": 6,
            "area_id": 0,
            "user_range": "[]",
            "preferred_time": "18:00-19:30"
        }
        scheduler_updates = {
            "target_time": "07:05:00",
            "fallback_nearest": False
        }

        ok = save_target_and_scheduler_config(self.config_path, target_updates, scheduler_updates)
        self.assertTrue(ok)

        cfg = load_config(self.config_path)
        self.assertEqual(cfg.target.stadium_name, "思明校区健身房")
        self.assertEqual(cfg.target.stadium_id, 6)
        self.assertEqual(cfg.target.preferred_time, "18:00-19:30")
        self.assertEqual(cfg.scheduler.target_time, "07:05:00")
        self.assertFalse(cfg.scheduler.fallback_nearest)

    def test_booking_scheduler_stop(self):
        cfg = load_config(self.config_path)
        session_mgr = MagicMock()
        client = MagicMock()
        api = MagicMock()
        solver = MagicMock()

        scheduler = BookingScheduler(
            config=cfg,
            session_mgr=session_mgr,
            client=client,
            api=api,
            solver=solver,
            config_path=self.config_path
        )
        self.assertFalse(scheduler._stop_event.is_set())

        scheduler.stop()
        self.assertTrue(scheduler._stop_event.is_set())

        res = scheduler.run()
        self.assertFalse(res["success"])
        self.assertIn("手动", res["info"])

    def test_scheduler_manager_lifecycle(self):
        mgr = SchedulerManager()
        status = mgr.get_status()
        self.assertFalse(status["running"])

        with patch("xdty_booking.web.server.BookingScheduler") as mock_sched_cls, \
             patch("xdty_booking.web.server.CaptchaSolver"):
            import threading
            stop_evt = threading.Event()
            mock_sched_inst = MagicMock()
            mock_sched_inst.run.side_effect = lambda: stop_evt.wait(5)
            def _fake_stop():
                stop_evt.set()
            mock_sched_inst.stop.side_effect = _fake_stop
            mock_sched_cls.return_value = mock_sched_inst

            start_res = mgr.start(self.config_path)
            self.assertTrue(start_res["success"])
            self.assertTrue(mgr.get_status()["running"])

            stop_res = mgr.stop()
            self.assertTrue(stop_res["success"])
            self.assertFalse(mgr.get_status()["running"])
            mock_sched_inst.stop.assert_called_once()

    def test_handle_scheduler_api(self):
        handler = GymStatusHandler.__new__(GymStatusHandler)
        handler._send_json = MagicMock()

        # 1. GET config
        with patch("xdty_booking.web.server._GLOBAL_CONFIG_PATH", self.config_path):
            handler._handle_scheduler_config_get()
            handler._send_json.assert_called_once()
            code, body = handler._send_json.call_args[0]
            self.assertEqual(code, 200)
            self.assertEqual(body["target"]["stadium_id"], 16)
            self.assertEqual(body["scheduler"]["target_time"], "07:00:00")

        # 2. POST config
        handler._send_json.reset_mock()
        payload = {
            "target": {"preferred_time": "16:30-18:00"},
            "scheduler": {"target_time": "07:00:00"}
        }
        with patch("xdty_booking.web.server._GLOBAL_CONFIG_PATH", self.config_path):
            handler._handle_scheduler_config_save(payload, {})
            handler._send_json.assert_called_once()
            code, body = handler._send_json.call_args[0]
            self.assertEqual(code, 200)
            self.assertTrue(body["success"])

        cfg = load_config(self.config_path)
        self.assertEqual(cfg.target.preferred_time, "16:30-18:00")

        # 3. GET status
        handler._send_json.reset_mock()
        handler._handle_scheduler_status()
        handler._send_json.assert_called_once()
        code, body = handler._send_json.call_args[0]
        self.assertEqual(code, 200)
        self.assertIn("running", body)

    def test_render_dashboard_scheduler_elements(self):
        # 1. Normal not running
        data = {
            "stadium_name": "翔安校区健身房",
            "area_name": "爱秋体育馆健身房",
            "query_time": "2026-09-12 10:00:00",
            "session_valid": True,
            "groups": [],
            "scheduler_status": {"running": False},
            "snipe_status": {"running": False},
            "target_config": {"stadium_id": 16, "preferred_time": "19:30-21:00"},
            "scheduler_config": {"target_time": "07:00:00"}
        }
        html = render_dashboard(data)
        self.assertIn("定时预约", html)
        self.assertIn("捡漏监听", html)
        self.assertIn("feature-bar", html)
        self.assertIn("featureSchedBtn", html)
        self.assertIn("featureSnipeBtn", html)
        self.assertIn("schedulerModal", html)
        self.assertIn("snipeModal", html)
        self.assertIn("● 登录有效", html)
        self.assertIn("自动刷新(30s)", html)
        self.assertIn("重新登录", html)
        self.assertIn("默认定时预约当天早上 07:00:00 开放的第二天的健身房名额", html)
        self.assertNotIn("系统将在抢票前 5 分钟", html)
        self.assertNotIn("防休眠守护", html)
        self.assertIn("翔安校区健身房", html)
        self.assertIn("思明校区健身房", html)
        self.assertIn("19:30-21:00", html)
        self.assertIn("openSchedulerModal", html)
        self.assertIn("openSnipeModal", html)
        self.assertIn("startSchedulerTask", html)
        self.assertIn("startSnipeTask", html)
        self.assertIn("campus-switch-container", html)
        self.assertIn("switchCampus", html)
        self.assertIn("🏢 翔安校区", html)
        self.assertIn("🏛️ 思明校区", html)

        # 1.1 Siming campus dashboard rendering
        data_siming = dict(data)
        data_siming["stadium_name"] = "思明校区健身房"
        data_siming["area_name"] = "思明校区健身房"
        data_siming["target_config"] = {"stadium_id": 6, "preferred_time": "19:30-21:00"}
        html_siming = render_dashboard(data_siming)
        self.assertIn("思明校区健身房", html_siming)
        self.assertIn("14:30-16:10", html_siming)

        # 1.2 Locked / course occupied slot rendering
        data_locked = dict(data)
        data_locked["groups"] = [
            {
                "date": "2026-09-17",
                "week_name": "周四",
                "time_range": "15:00-16:30",
                "is_preferred": False,
                "slots": [
                    {
                        "area_name": "爱秋体育馆健身房",
                        "interval_id": "3070",
                        "selected": 0,
                        "max_count": 95,
                        "remaining": 0,
                        "is_available": False,
                        "is_locked": True,
                        "status": "locked"
                    }
                ]
            }
        ]
        html_locked = render_dashboard(data_locked)
        self.assertIn("课程占用", html_locked)
        self.assertIn("教学课程占用", html_locked)
        self.assertNotIn('<span class="badge full">已约满</span>', html_locked)
        self.assertNotIn("0 / 95 (0%)", html_locked)

        # 2. Running state for scheduler
        data_running = dict(data)
        data_running["scheduler_status"] = {"running": True, "status_text": "正在静默休眠等待"}
        html_running = render_dashboard(data_running)
        self.assertIn("定时预约中", html_running)
        self.assertIn("bookingInfoCard", html_running)

        # 3. Running state for snipe
        data_snipe = dict(data)
        data_snipe["snipe_status"] = {"running": True, "status_text": "正在高频轮询探测", "poll_count": 42}
        html_snipe = render_dashboard(data_snipe)
        self.assertIn("正在捡漏中", html_snipe)
        self.assertIn("snipeInfoCard", html_snipe)
        self.assertIn("42 次", html_snipe)

    def test_snipe_manager_lifecycle(self):
        mgr = SnipeManager()
        status = mgr.get_status()
        self.assertFalse(status["running"])

        with patch("xdty_booking.web.server.BookingEngine") as mock_engine_cls, \
             patch("xdty_booking.web.server.CaptchaSolver"):
            import threading
            stop_evt = threading.Event()
            mock_engine_inst = MagicMock()
            mock_engine_inst.resolve_target_date.return_value = "2026-09-17"
            def _fake_snipe(**kwargs):
                stop_event = kwargs.get("stop_event")
                if stop_event:
                    stop_event.wait(5)
                return {"success": True, "info": "捡漏成功"}
            mock_engine_inst.snipe_booking.side_effect = _fake_snipe
            mock_engine_cls.return_value = mock_engine_inst

            start_res = mgr.start(
                self.config_path,
                target_date="2026-09-17",
                preferred_time="19:30-21:00",
                poll_interval=1.0,
                fallback_nearest=True
            )
            self.assertTrue(start_res["success"])
            self.assertTrue(mgr.get_status()["running"])
            self.assertEqual(mgr.get_status()["target_date"], "2026-09-17")

            stop_res = mgr.stop()
            self.assertTrue(stop_res["success"])
            self.assertFalse(mgr.get_status()["running"])

    def test_handle_snipe_api(self):
        handler = GymStatusHandler.__new__(GymStatusHandler)
        handler._send_json = MagicMock()

        # 1. GET snipe status
        handler._handle_snipe_status()
        handler._send_json.assert_called_once()
        code, body = handler._send_json.call_args[0]
        self.assertEqual(code, 200)
        self.assertIn("running", body)
        self.assertIn("poll_count", body)

        # 2. POST snipe start (mocking snipe_manager)
        handler._send_json.reset_mock()
        with patch("xdty_booking.web.server._snipe_manager.start") as mock_start:
            mock_start.return_value = {"success": True, "info": "启动成功"}
            handler._handle_snipe_start({"target_date": "2026-09-17", "preferred_time": "19:30-21:00"}, {})
            handler._send_json.assert_called_once()
            code, body = handler._send_json.call_args[0]
            self.assertEqual(code, 200)
            self.assertTrue(body["success"])

        # 3. POST snipe stop (mocking snipe_manager)
        handler._send_json.reset_mock()
        with patch("xdty_booking.web.server._snipe_manager.stop") as mock_stop:
            mock_stop.return_value = {"success": True, "info": "停止成功"}
            handler._handle_snipe_stop()
            handler._send_json.assert_called_once()
            code, body = handler._send_json.call_args[0]
            self.assertEqual(code, 200)
            self.assertTrue(body["success"])

    def test_handle_campus_switch_api(self):
        handler = GymStatusHandler.__new__(GymStatusHandler)
        handler._send_json = MagicMock()

        with patch("xdty_booking.web.server._GLOBAL_CONFIG_PATH", self.config_path):
            # 1. POST switch to Siming
            handler._handle_campus_switch({"campus": "siming"}, {})
            handler._send_json.assert_called_once()
            code, body = handler._send_json.call_args[0]
            self.assertEqual(code, 200)
            self.assertTrue(body["success"])
            self.assertEqual(body["campus"], "siming")
            self.assertEqual(body["target"]["stadium_id"], 6)

            cfg = load_config(self.config_path)
            self.assertEqual(cfg.target.stadium_id, 6)
            self.assertEqual(cfg.target.stadium_name, "思明校区健身房")

            # 2. POST switch back to Xiang'an
            handler._send_json.reset_mock()
            handler._handle_campus_switch({"campus": "xiangan"}, {})
            handler._send_json.assert_called_once()
            code, body = handler._send_json.call_args[0]
            self.assertEqual(code, 200)
            self.assertTrue(body["success"])
            self.assertEqual(body["campus"], "xiangan")
            self.assertEqual(body["target"]["stadium_id"], 16)

            cfg = load_config(self.config_path)
            self.assertEqual(cfg.target.stadium_id, 16)
            self.assertEqual(cfg.target.stadium_name, "翔安校区健身房")
