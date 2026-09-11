from unittest.mock import Mock, patch
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.core.models import SlotItem
from xdty_booking.config import AppConfig

def test_booking_engine_full_flow_success():
    api = Mock()
    solver = Mock()
    solver.solve.return_value = "daxs"
    
    # Mock interval response with 1 available slot
    slot = SlotItem(
        column_id="67",
        date="2026-09-12",
        area_name="爱秋体育馆健身房",
        interval_id="3087",
        price=0,
        selected=80,
        max_count=95,
        status="available"
    )
    mock_interval_resp = Mock()
    mock_interval_resp.status = 1
    mock_interval_resp.find_slot.return_value = slot
    api.get_intervals.return_value = mock_interval_resp
    api.choose_verify.return_value = {"status": 1}
    api.get_venue_config.return_value = {"status": 1, "data": {"info": {"needRemark": 0, "isCanAppoint": True}}}
    api.get_captcha.return_value = b"image_bytes"
    api.add_order.return_value = {"status": 1, "info": "预约成功", "data": []}
    
    cfg = AppConfig()
    engine = BookingEngine(api=api, captcha_solver=solver, config=cfg)
    result = engine.execute_booking(target_date="2026-09-12")
    
    assert result["success"] is True
    assert result["info"] == "预约成功"
    assert api.add_order.called
    assert api.choose_verify.called

def test_booking_engine_slot_not_found():
    api = Mock()
    mock_interval_resp = Mock()
    mock_interval_resp.status = 1
    mock_interval_resp.find_slot.return_value = None
    api.get_intervals.return_value = mock_interval_resp
    
    cfg = AppConfig()
    engine = BookingEngine(api=api, captcha_solver=Mock(), config=cfg)
    result = engine.execute_booking(target_date="2026-09-12")
    
    assert result["success"] is False
    assert "未找到指定时段" in result["info"]

def test_booking_engine_retry_on_captcha_error():
    api = Mock()
    solver = Mock()
    solver.solve.side_effect = ["wrong", "daxs"]
    
    slot = SlotItem(
        column_id="67",
        date="2026-09-12",
        area_name="爱秋体育馆健身房",
        interval_id="3087",
        price=0,
        selected=80,
        max_count=95,
        status="available"
    )
    mock_interval_resp = Mock()
    mock_interval_resp.status = 1
    mock_interval_resp.find_slot.return_value = slot
    api.get_intervals.return_value = mock_interval_resp
    api.choose_verify.return_value = {"status": 1}
    api.get_captcha.return_value = b"bytes"
    
    # 第一次失败（验证码错误），第二次成功
    api.add_order.side_effect = [
        {"status": 0, "info": "验证码错误"},
        {"status": 1, "info": "预约成功", "data": []}
    ]
    
    cfg = AppConfig()
    cfg.scheduler.retry_interval_ms = 10
    engine = BookingEngine(api=api, captcha_solver=solver, config=cfg)
    result = engine.execute_booking(target_date="2026-09-12")
    
    assert result["success"] is True
    assert api.add_order.call_count == 2
