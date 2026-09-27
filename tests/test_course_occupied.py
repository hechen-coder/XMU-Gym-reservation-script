from datetime import datetime
from unittest.mock import Mock, patch
import pytest

from xdty_booking.config import AppConfig, SchedulerConfig, NotifyConfig, TargetConfig
from xdty_booking.core.models import IntervalResponse
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.core.scheduler import BookingScheduler
from xdty_booking.notify.notifier import Notifier


def intervals(status="locked", select_type=0, selected=0):
    return IntervalResponse.from_dict({
        "status": 1,
        "info": "ok",
        "data": {
            "venue_id": "14",
            "date_list": [],
            "time_slot_list": [{
                "date": "2026-09-20",
                "time_range": "16:30-18:00",
                "start_time": "16:30",
                "end_time": "18:00",
                "week": "7",
                "week_name": "周日",
                "slots": [{
                    "column_id": "67",
                    "date": "2026-09-20",
                    "area_name": "健身房",
                    "interval_id": "123",
                    "price": 0,
                    "selected": selected,
                    "max_count": 95,
                    "status": status,
                    "select_type": select_type,
                    "is_lock": 0,
                    "lock_reason": ""
                }],
            }],
        }
    })


def test_numeric_zero_select_type_remains_unbookable():
    slot = intervals("available").time_slot_list[0].slots[0]
    assert slot.select_type == 0
    assert slot.is_course_occupied is True
    assert slot.is_locked is True
    assert slot.is_available is False


@pytest.mark.parametrize("by_id,fallback", [(False, False), (False, True), (True, True)])
def test_occupied_slot_skips_without_verification_captcha_order_or_fallback(by_id, fallback):
    api = Mock()
    api.get_intervals.return_value = intervals()
    engine = BookingEngine(api, Mock(), AppConfig())
    with patch.object(api.get_intervals.return_value, "find_nearest_available_slots") as nearest:
        result = engine.execute_booking(
            target_date="2026-09-20",
            preferred_time="16:30-18:00",
            interval_id="123" if by_id else None,
            fallback_nearest=fallback
        )
    assert result["skipped"] is True
    assert result["reason"] == "course_occupied"
    api.choose_verify.assert_not_called()
    api.get_captcha.assert_not_called()
    api.add_order.assert_not_called()
    nearest.assert_not_called()


@pytest.mark.parametrize("stage", ["verify", "order"])
def test_late_course_occupation_response_stops_retrying(stage):
    api = Mock()
    api.get_intervals.return_value = intervals("available", 1)
    api.choose_verify.return_value = {"status": 0 if stage == "verify" else 1, "info": "该时段课程占用"}
    api.get_captcha.return_value = b"image"
    api.add_order.return_value = {"status": 0, "info": "该时段教学排课占用"}
    solver = Mock()
    solver.solve.return_value = "abcd"
    result = BookingEngine(api, solver, AppConfig()).execute_booking(
        target_date="2026-09-20",
        preferred_time="16:30-18:00",
        fallback_nearest=True
    )
    assert result["reason"] == "course_occupied"
    assert result["skipped"] is True
    assert api.add_order.call_count == (0 if stage == "verify" else 1)
    assert api.get_captcha.call_count == (0 if stage == "verify" else 1)


def test_full_slot_is_not_misreported_as_course_occupation():
    api = Mock()
    api.get_intervals.return_value = intervals("available", 1, 95)
    result = BookingEngine(api, Mock(), AppConfig()).execute_booking(
        target_date="2026-09-20",
        preferred_time="16:30-18:00",
        fallback_nearest=False
    )
    assert not result.get("skipped")
    assert result.get("reason") != "course_occupied"


def test_unknown_unavailable_status_is_not_misreported_as_course_occupation():
    api = Mock()
    api.get_intervals.return_value = intervals("unavailable", 1)
    result = BookingEngine(api, Mock(), AppConfig()).execute_booking(
        target_date="2026-09-20",
        preferred_time="16:30-18:00",
        fallback_nearest=False
    )
    assert result.get("reason") != "course_occupied"
    api.add_order.assert_not_called()


def test_snipe_booking_stops_on_course_occupied():
    api = Mock()
    api.get_intervals.return_value = intervals()
    engine = BookingEngine(api, Mock(), AppConfig())
    res = engine.snipe_booking(
        target_date="2026-09-20",
        preferred_time="16:30-18:00",
        poll_interval=0.1,
        max_duration_seconds=5
    )
    assert res.get("skipped") is True
    assert res.get("reason") == "course_occupied"
    # Should exit immediately on first check without infinite looping
    assert api.get_intervals.call_count == 1


def test_scheduler_notifies_when_course_occupied():
    cfg = AppConfig(
        target=TargetConfig(stadium_name="翔安校区健身房", preferred_time="16:30-18:00"),
        scheduler=SchedulerConfig(target_time="07:00:00", pre_check_minutes=5, release_grace_seconds=0),
        notify=NotifyConfig(enabled=True)
    )
    api = Mock()
    api.get_intervals.return_value = intervals()
    notifier = Mock()
    notifier.is_enabled.return_value = True

    scheduler = BookingScheduler(
        config=cfg,
        session_mgr=Mock(),
        client=Mock(),
        api=api,
        solver=Mock(),
        notifier=notifier
    )

    with patch("xdty_booking.core.scheduler.datetime") as mock_dt, \
         patch("xdty_booking.core.scheduler.time.sleep"), \
         patch.object(scheduler, "ensure_valid_session", return_value=True), \
         patch("xdty_booking.core.scheduler.BookingEngine.resolve_target_date", return_value="2026-09-20"), \
         patch("xdty_booking.core.scheduler.TimeSync.get_server_time_offset", return_value=0), \
         patch("xdty_booking.core.scheduler.TimeSync.wait_until"):
        # 设定当前时间为 06:59:59，使得目标时刻为当天的 07:00:00，跳过预检休眠直接进入抢票
        now_time = datetime(2026, 9, 19, 6, 59, 59)
        mock_dt.now.return_value = now_time
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        res = scheduler.run(target_time="07:00:00")

    assert res.get("skipped") is True
    assert res.get("reason") == "course_occupied"
    assert notifier.send.call_count == 1
    call_kwargs = notifier.send.call_args.kwargs
    assert "课程占用" in call_kwargs["title"]
    assert "翔安校区健身房" in call_kwargs["content"]
    assert "排课占用" in call_kwargs["content"]
