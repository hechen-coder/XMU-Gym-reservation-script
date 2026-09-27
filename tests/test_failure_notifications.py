"""定时预约链路上每一种失败都必须触发通知（课程占用已有专门通知）。"""
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from xdty_booking.config import AppConfig, SchedulerConfig
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.core.models import IntervalResponse
from xdty_booking.core.scheduler import BookingScheduler


def _scheduler(notifier=None):
    cfg = AppConfig(scheduler=SchedulerConfig(weekly_enabled=True, release_grace_seconds=0, weekly_plan={'6': '16:30-18:00'}))
    cfg.auth.phpsessid = "sess"
    scheduler = BookingScheduler(cfg, Mock(), Mock(), Mock(), Mock(), notifier=notifier or Mock())
    scheduler.next_booking = (datetime(2026, 9, 18, 7), '2026-09-19', ['16:30-18:00'])
    return scheduler


def _run_once_with(scheduler, booking_result, precheck_ok=True, wake_late=False):
    with patch('xdty_booking.core.scheduler.datetime', wraps=datetime) as clock, \
         patch.object(scheduler, 'ensure_valid_session', return_value=precheck_ok), \
         patch('xdty_booking.core.scheduler.TimeSync.get_server_time_offset', return_value=0), \
         patch('xdty_booking.core.scheduler.TimeSync.wait_until') as wait, \
         patch('xdty_booking.core.scheduler.BookingEngine') as engine:
        clock.now.return_value = datetime(2026, 9, 18, 6, 59, 40)
        if wake_late:
            wait.side_effect = lambda *a, **k: setattr(clock.now, "return_value", datetime(2026, 9, 18, 7, 5))
        engine.return_value.execute_booking.return_value = booking_result
        return scheduler._run_once()


def _sent(notifier):
    assert notifier.send.called, "未发送任何通知"
    kwargs = notifier.send.call_args.kwargs
    return kwargs["title"], kwargs["content"]


@pytest.mark.parametrize('result,expected_kind', [
    ({"success": False, "info": "查询场次失败: 登录信息失效,请退出重新登录"}, "登录失效"),
    ({"success": False, "info": "该时段目前无空闲名额 (已约满 3/3)", "full": True}, "名额已满"),
    ({"success": False, "info": "名额已满", "capacity_full": True}, "名额已满"),
    ({"success": False, "info": "验证码错误"}, "验证码"),
    ({"success": False, "info": "查询场次列表网络异常: timeout"}, "网络异常"),
    ({"success": False, "info": "未找到指定时段场次: 日期 2026-09-19, 时段 16:30-18:00"}, "未找到场次"),
    ({"success": False, "info": "该场次当前不可预约"}, "预约失败"),
    ({"success": False, "info": "您已有预约，不能重复预约"}, "预约失败"),
])
def test_every_booking_failure_is_notified_with_context(result, expected_kind):
    notifier = Mock()
    scheduler = _scheduler(notifier)
    _run_once_with(scheduler, result)

    title, content = _sent(notifier)
    assert expected_kind in title
    assert "翔安校区健身房" in content
    assert "2026-09-19" in content
    assert "16:30-18:00" in content
    assert result["info"] in content


def test_success_and_course_occupied_do_not_send_failure_notification():
    notifier = Mock()
    scheduler = _scheduler(notifier)
    _run_once_with(scheduler, {"success": True, "info": "ok"})
    notifier.send.assert_not_called()

    notifier = Mock()
    scheduler = _scheduler(notifier)
    _run_once_with(scheduler, {"success": False, "skipped": True, "reason": "course_occupied", "info": "课程占用"})
    assert notifier.send.call_count == 1  # 仅课程占用专用通知
    assert "课程占用" in notifier.send.call_args.kwargs["title"]


def test_precheck_failure_is_notified_before_booking_and_booking_still_runs():
    notifier = Mock()
    scheduler = _scheduler(notifier)
    with patch('xdty_booking.core.scheduler.datetime', wraps=datetime) as clock, \
         patch.object(scheduler, 'ensure_valid_session', return_value=False), \
         patch('xdty_booking.core.scheduler.TimeSync.get_server_time_offset', return_value=0), \
         patch('xdty_booking.core.scheduler.TimeSync.wait_until'), \
         patch('xdty_booking.core.scheduler.BookingEngine') as engine:
        clock.now.return_value = datetime(2026, 9, 18, 6, 59, 40)

        def booking(*a, **k):
            assert notifier.send.called, "预检失败通知必须在抢票之前发出"
            return {"success": True}
        engine.return_value.execute_booking.side_effect = booking
        scheduler._run_once()

    title, content = _sent(notifier)
    assert "预检" in title and "登录" in content
    engine.return_value.execute_booking.assert_called_once()


def test_missed_booking_window_is_notified():
    notifier = Mock()
    scheduler = _scheduler(notifier)
    result = _run_once_with(scheduler, {"success": True}, wake_late=True)
    assert result["success"] is False
    title, content = _sent(notifier)
    assert "错过" in title
    assert "2026-09-19" in content


def test_unhandled_exception_in_weekly_loop_is_notified():
    notifier = Mock()
    scheduler = _scheduler(notifier)

    def attempt(*a, **k):
        scheduler.stop()
        raise ConnectionError("offline")

    with patch('xdty_booking.core.scheduler.datetime', wraps=datetime) as clock, \
         patch.object(scheduler, '_run_once', side_effect=attempt):
        clock.now.return_value = datetime(2026, 9, 18, 6, 59, 40)
        scheduler.run()

    title, content = _sent(notifier)
    assert "异常" in title
    assert "offline" in content


def test_notification_failure_never_breaks_the_run():
    notifier = Mock()
    notifier.send.side_effect = RuntimeError("feishu down")
    scheduler = _scheduler(notifier)
    result = _run_once_with(scheduler, {"success": False, "info": "该场次当前不可预约"})
    assert result["info"] == "该场次当前不可预约"


def test_engine_reports_real_query_failure_instead_of_slot_not_found():
    """查询接口返回登录失效时，不能误报为「未找到指定时段场次」"""
    api = Mock()
    api.get_intervals.return_value = IntervalResponse(
        status=0, info="登录信息失效,请退出重新登录", venue_id="", date_list=[], time_slot_list=[])
    engine = BookingEngine(api=api, captcha_solver=Mock(), config=AppConfig())

    result = engine.execute_booking(target_date="2026-09-19", preferred_time="16:30-18:00")

    assert result["success"] is False
    assert "登录信息失效" in result["info"]
    assert "未找到指定时段" not in result["info"]
