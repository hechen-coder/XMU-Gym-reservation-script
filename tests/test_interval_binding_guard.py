from unittest.mock import Mock

from xdty_booking.config import AppConfig
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.core.models import IntervalResponse


def interval_response(date, time_range, interval_id):
    start, end = time_range.split("-")
    return IntervalResponse.from_dict({
        "status": 1,
        "info": "ok",
        "data": {
            "venue_id": "14",
            "date_list": [],
            "time_slot_list": [{
                "date": date,
                "time_range": time_range,
                "start_time": start,
                "end_time": end,
                "week": "3",
                "week_name": "周三",
                "slots": [{
                    "column_id": "67",
                    "date": date,
                    "area_name": "健身房",
                    "interval_id": interval_id,
                    "price": 0,
                    "selected": 10,
                    "max_count": 95,
                    "status": "available",
                    "select_type": 1,
                    "is_lock": 0,
                    "lock_reason": "",
                }],
            }],
        },
    })


def test_rejects_interval_id_remapped_since_initial_query():
    api = Mock()
    api.get_intervals.side_effect = [
        interval_response("2026-11-11", "16:30-18:00", "3063"),
        interval_response("2026-11-11", "15:00-16:30", "3063"),
    ]
    api.choose_verify.return_value = {"status": 1}
    api.get_captcha.return_value = b"image"
    api.add_order.return_value = {"status": 1, "info": "预约成功"}
    solver = Mock()
    solver.solve.return_value = "abcd"

    result = BookingEngine(api, solver, AppConfig()).execute_booking(
        target_date="2026-11-11",
        preferred_time="16:30-18:00",
        fallback_nearest=False,
    )

    assert result["success"] is False
    assert result["reason"] == "slot_mapping_changed"
    api.choose_verify.assert_not_called()
    api.get_captcha.assert_not_called()
    api.add_order.assert_not_called()
