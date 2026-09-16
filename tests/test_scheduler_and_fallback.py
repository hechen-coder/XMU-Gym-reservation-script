from unittest.mock import Mock, MagicMock, patch
from xdty_booking.core.models import IntervalResponse, SlotItem, TimeSlotGroup, parse_time_to_minutes
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.core.scheduler import BookingScheduler
from xdty_booking.config import AppConfig

def test_parse_time_to_minutes():
    assert parse_time_to_minutes("07:00") == 420
    assert parse_time_to_minutes("19:30-21:00") == 1170
    assert parse_time_to_minutes("18:00") == 1080
    assert parse_time_to_minutes("") == 0

def test_find_nearest_available_slots_ordering():
    # 模拟包含 3 个时段的数据：16:30(满), 18:00(有余量), 21:00(有余量), 22:30(有余量)
    # 首选为 19:30-21:00 (1170 分钟)
    # 18:00 距离 |1080 - 1170| = 90
    # 21:00 距离 |1260 - 1170| = 90
    # 22:30 距离 |1350 - 1170| = 180
    slot_18 = SlotItem(column_id="67", date="2026-09-12", area_name="健身房", interval_id="101", price=0, selected=10, max_count=90, status="available")
    slot_21 = SlotItem(column_id="67", date="2026-09-12", area_name="健身房", interval_id="102", price=0, selected=20, max_count=90, status="available")
    slot_22 = SlotItem(column_id="67", date="2026-09-12", area_name="健身房", interval_id="103", price=0, selected=30, max_count=90, status="available")
    slot_full = SlotItem(column_id="67", date="2026-09-12", area_name="健身房", interval_id="100", price=0, selected=90, max_count=90, status="available")

    group_full = TimeSlotGroup(time_range="16:30-18:00", start_time="16:30", end_time="18:00", date="2026-09-12", week="6", week_name="周六", slots=[slot_full])
    group_18 = TimeSlotGroup(time_range="18:00-19:30", start_time="18:00", end_time="19:30", date="2026-09-12", week="6", week_name="周六", slots=[slot_18])
    group_21 = TimeSlotGroup(time_range="21:00-22:30", start_time="21:00", end_time="22:30", date="2026-09-12", week="6", week_name="周六", slots=[slot_21])
    group_22 = TimeSlotGroup(time_range="22:30-23:30", start_time="22:30", end_time="23:30", date="2026-09-12", week="6", week_name="周六", slots=[slot_22])

    resp = IntervalResponse(
        status=1, info="ok", venue_id="14",
        date_list=[],
        time_slot_list=[group_full, group_22, group_18, group_21]
    )

    nearest = resp.find_nearest_available_slots(date="2026-09-12", preferred_time="19:30-21:00", column_id="67")
    
    # 满额的 16:30 不应该出现在可用候选中
    assert len(nearest) == 3
    # 距离 90 分钟的 18:00 和 21:00 应该排在距离 180 分钟的 22:30 前面
    times = [item[0].time_range for item in nearest]
    assert times[0] in ("18:00-19:30", "21:00-22:30")
    assert times[1] in ("18:00-19:30", "21:00-22:30")
    assert times[2] == "22:30-23:30"

def test_booking_engine_fallback_nearest_when_preferred_is_full():
    api = Mock()
    solver = Mock()
    solver.solve.return_value = "code"

    # 首选时段 19:30-21:00 已满
    pref_slot = SlotItem(column_id="67", date="2026-09-12", area_name="健身房", interval_id="100", price=0, selected=90, max_count=90, status="available")
    pref_group = TimeSlotGroup(time_range="19:30-21:00", start_time="19:30", end_time="21:00", date="2026-09-12", week="6", week_name="周六", slots=[pref_slot])

    # 备选就近时段 18:00-19:30 有余位
    near_slot = SlotItem(column_id="67", date="2026-09-12", area_name="健身房", interval_id="101", price=0, selected=50, max_count=90, status="available")
    near_group = TimeSlotGroup(time_range="18:00-19:30", start_time="18:00", end_time="19:30", date="2026-09-12", week="6", week_name="周六", slots=[near_slot])

    mock_interval_resp = IntervalResponse(
        status=1, info="ok", venue_id="14",
        date_list=[],
        time_slot_list=[pref_group, near_group]
    )
    api.get_intervals.return_value = mock_interval_resp
    api.choose_verify.return_value = {"status": 1}
    api.get_captcha.return_value = b"bytes"
    api.add_order.return_value = {"status": 1, "info": "预约成功", "data": []}

    cfg = AppConfig()
    cfg.target.preferred_time = "19:30-21:00"
    cfg.scheduler.fallback_nearest = True

    engine = BookingEngine(api=api, captcha_solver=solver, config=cfg)
    res = engine.execute_booking(target_date="2026-09-12", check_availability=True, fallback_nearest=True)

    assert res["success"] is True
    assert res.get("fallback") is True
    assert res["slot"].interval_id == "101"

def test_scheduler_pre_check_session():
    cfg = AppConfig()
    cfg.auth.auto_harvest_enabled = True
    session_mgr = Mock()
    session_mgr.check_alive.return_value = False  # 模拟失效
    client = Mock()
    api = Mock()
    solver = Mock()

    scheduler = BookingScheduler(
        config=cfg,
        session_mgr=session_mgr,
        client=client,
        api=api,
        solver=solver,
        config_path="config/config.example.yaml"
    )
    with patch.object(scheduler.harvest_service, "harvest", return_value="new_token_777") as mock_harvest:
        ok = scheduler.ensure_valid_session()
        assert ok is True
        mock_harvest.assert_called_once()
        session_mgr.update_token.assert_called_once_with("new_token_777")
        client.set_session_token.assert_called_once_with("new_token_777")

def test_scheduler_silent_run_flow():
    from datetime import datetime, timedelta
    cfg = AppConfig()
    cfg.auth.auto_harvest_enabled = True
    cfg.scheduler.pre_check_minutes = 5
    session_mgr = Mock()
    client = Mock()
    api = Mock()
    solver = Mock()

    scheduler = BookingScheduler(
        config=cfg,
        session_mgr=session_mgr,
        client=client,
        api=api,
        solver=solver,
        config_path="config/config.example.yaml"
    )

    # 模拟当前时刻即为 06:56:00 (预检时刻 06:55 已过，在 30 秒倒计时内)
    mock_now = datetime(2026, 9, 12, 6, 59, 40)
    mock_dt_cls = MagicMock(wraps=datetime)
    mock_dt_cls.now.return_value = mock_now

    with patch.object(scheduler, "ensure_valid_session", return_value=True) as mock_precheck, \
         patch("xdty_booking.core.scheduler.datetime", mock_dt_cls), \
         patch("xdty_booking.core.scheduler.TimeSync.get_server_time_offset", return_value=0.01) as mock_sync, \
         patch("xdty_booking.core.scheduler.TimeSync.wait_until") as mock_wait, \
         patch("xdty_booking.core.scheduler.BookingEngine") as mock_engine_cls:
        
        mock_engine = Mock()
        mock_engine.execute_booking.return_value = {"success": True, "info": "测试预约成功"}
        mock_engine_cls.return_value = mock_engine

        res = scheduler.run(target_time="07:00:00")
        assert res["success"] is True
        mock_precheck.assert_called_once()
        mock_sync.assert_called_once()
        mock_wait.assert_called_once()
        mock_engine.execute_booking.assert_called_once()
        session_mgr.start_heartbeat_daemon.assert_not_called()
