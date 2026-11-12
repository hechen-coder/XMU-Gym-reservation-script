from unittest.mock import Mock

import pytest
from requests.exceptions import Timeout

from xdty_booking.config import AppConfig
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.core.models import IntervalResponse, SlotItem, TimeSlotGroup


DATE = "2026-09-23"
PREFERRED = "16:30-18:00"


def _group(time_range, interval_id, selected=0):
    start, end = time_range.split("-")
    slot = SlotItem("67", DATE, "健身房", interval_id, 0, selected, 95, "available")
    return TimeSlotGroup(time_range, start, end, DATE, "3", "周三", [slot])


@pytest.mark.parametrize("preferred_full", [False, True], ids=["preferred", "fallback"])
@pytest.mark.parametrize("reason", ["slot_mapping_changed", "query_failed"])
def test_recheck_failure_stops_current_attempt(preferred_full, reason):
    first = IntervalResponse(1, "", "14", [], [
        _group(PREFERRED, "1000", selected=95 if preferred_full else 94),
        _group("18:00-19:30", "1001", selected=94),
        _group("19:30-21:00", "1002"),
    ])
    checked_id = "1001" if preferred_full else "1000"
    if reason == "slot_mapping_changed":
        recheck = IntervalResponse(1, "", "14", [], [_group("13:30-15:00", checked_id)])
    else:
        recheck = Timeout("simulated timeout")

    api = Mock()
    api.get_intervals.side_effect = [first, recheck]
    result = BookingEngine(api, Mock(), AppConfig()).execute_booking(
        target_date=DATE, preferred_time=PREFERRED, fallback_nearest=True,
    )

    assert result["success"] is False
    assert result["reason"] == reason
    assert not result.get("full")
    assert not result.get("capacity_full")
    assert api.get_intervals.call_count == 2
    api.choose_verify.assert_not_called()
    api.get_captcha.assert_not_called()
    api.add_order.assert_not_called()
