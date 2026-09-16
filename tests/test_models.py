import pytest
from xdty_booking.core.models import IntervalResponse, SlotItem, TimeSlotGroup, DateItem

def test_slot_item_properties():
    slot = SlotItem(
        column_id="67",
        date="2026-09-11",
        area_name="爱秋体育馆健身房",
        interval_id="3080",
        price=0,
        selected=94,
        max_count=95,
        status="available",
        is_lock=1,
        lock_reason=""
    )
    assert slot.is_available is True
    assert slot.remaining_capacity == 1

    # Full slot
    full_slot = SlotItem(
        column_id="67",
        date="2026-09-11",
        area_name="爱秋体育馆健身房",
        interval_id="3079",
        price=0,
        selected=95,
        max_count=95,
        status="available"
    )
    assert full_slot.is_available is False
    assert full_slot.remaining_capacity == 0

    # Locked / course-occupied slot (e.g. 0/95 on Thursday 15:00-16:30)
    locked_slot = SlotItem(
        column_id="67",
        date="2026-09-17",
        area_name="爱秋体育馆健身房",
        interval_id="3070",
        price=0,
        selected=0,
        max_count=95,
        status="locked",
        select_type=0,
        is_lock=0,
        lock_reason=""
    )
    assert locked_slot.is_available is False
    assert locked_slot.is_locked is True
    assert locked_slot.remaining_capacity == 0

def test_parse_interval_response():
    sample_json = {
        "status": 1,
        "info": "查询成功",
        "data": {
            "venue_id": "14",
            "date_list": [
                {"date_int": "2026-09-11", "date": "09月11日", "week_int": "5", "week": "今天"},
                {"date_int": "2026-09-12", "date": "09月12日", "week_int": "6", "week": "周六"}
            ],
            "column_list": [{"column_id": "67", "name": "爱秋体育馆健身房"}],
            "time_slot_list": [
                {
                    "time_range": "19:30-21:00",
                    "start_time": "19:30",
                    "end_time": "21:00",
                    "date": "2026-09-11",
                    "week": "5",
                    "week_name": "周五",
                    "slots": [
                        {
                            "column_id": "67",
                            "date": "2026-09-11",
                            "area_name": "爱秋体育馆健身房",
                            "interval_id": "3080",
                            "price": 0,
                            "selected": 94,
                            "select_type": 1,
                            "max_count": 95,
                            "is_lock": 1,
                            "lock_reason": "",
                            "status": "available"
                        }
                    ]
                },
                {
                    "time_range": "19:30-21:00",
                    "start_time": "19:30",
                    "end_time": "21:00",
                    "date": "2026-09-12",
                    "week": "6",
                    "week_name": "周六",
                    "slots": [
                        {
                            "column_id": "67",
                            "date": "2026-09-12",
                            "area_name": "爱秋体育馆健身房",
                            "interval_id": "3087",
                            "price": 0,
                            "selected": 81,
                            "select_type": 1,
                            "max_count": 95,
                            "is_lock": 1,
                            "lock_reason": "",
                            "status": "available"
                        }
                    ]
                }
            ]
        }
    }
    resp = IntervalResponse.from_dict(sample_json)
    assert resp.status == 1
    assert resp.venue_id == "14"
    assert len(resp.date_list) == 2
    
    # Check find_slot for 2026-09-11
    slot_11 = resp.find_slot(date="2026-09-11", time_range="19:30-21:00", column_id="67")
    assert slot_11 is not None
    assert slot_11.interval_id == "3080"
    assert slot_11.remaining_capacity == 1

    # Check find_slot for 2026-09-12
    slot_12 = resp.find_slot(date="2026-09-12", time_range="19:30-21:00")
    assert slot_12 is not None
    assert slot_12.interval_id == "3087"
    assert slot_12.remaining_capacity == 14

    # Non-existent slot
    none_slot = resp.find_slot(date="2026-09-13", time_range="19:30-21:00")
    assert none_slot is None

def test_parse_interval_response_when_data_is_list_or_invalid():
    # 模拟服务端 Session 失效时返回的典型响应 (data 为 list [])
    expired_json = {
        "status": 0,
        "info": "登录信息失效,请退出重新登录",
        "data": []
    }
    resp = IntervalResponse.from_dict(expired_json)
    assert resp.status == 0
    assert resp.info == "登录信息失效,请退出重新登录"
    assert resp.date_list == []
    assert resp.time_slot_list == []

    # 模拟 data 为 None 或非字典
    invalid_json = {"status": -1, "info": "未知错误", "data": None}
    resp_invalid = IntervalResponse.from_dict(invalid_json)
    assert resp_invalid.status == -1
    assert resp_invalid.date_list == []
    assert resp_invalid.time_slot_list == []
