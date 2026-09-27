from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from xdty_booking.config import AppConfig, SchedulerConfig
from xdty_booking.core.scheduler import BookingScheduler

NOT_RELEASED = {'success': False, 'skipped': True, 'reason': 'course_occupied', 'info': '仍锁定'}
MISSING = {'success': False, 'reason': 'slot_missing', 'info': '未找到指定时段场次'}
BOOKED = {'success': True, 'info': '预约成功'}
FULL = {'success': False, 'info': '该时段目前无空闲名额 (已约满 30/30)', 'full': True}


def run_once(cfg, results):
    scheduler = BookingScheduler(cfg, Mock(), Mock(), Mock(), Mock(), notifier=Mock())
    with patch('xdty_booking.core.scheduler.datetime', wraps=datetime) as clock, \
         patch.object(scheduler, 'ensure_valid_session', return_value=True), \
         patch.object(scheduler._stop_event, 'wait', return_value=False), \
         patch('xdty_booking.core.scheduler.TimeSync.get_server_time_offset', return_value=0), \
         patch('xdty_booking.core.scheduler.TimeSync.wait_until'), \
         patch('xdty_booking.core.scheduler.BookingEngine.execute_booking', side_effect=results) as booking:
        clock.now.return_value = datetime(2026, 9, 22, 6, 59, 40)
        res = scheduler._run_once()
    return res, booking


def test_keeps_polling_until_slot_is_released():
    res, booking = run_once(AppConfig(), [MISSING, NOT_RELEASED, BOOKED])
    assert res['success'] and booking.call_count == 3


def test_still_locked_after_grace_period_is_course_occupied():
    cfg = AppConfig(scheduler=SchedulerConfig(release_grace_seconds=0))
    res, booking = run_once(cfg, [NOT_RELEASED, BOOKED])
    assert res['reason'] == 'course_occupied' and booking.call_count == 1


# 时钟停在 2026-09-22 06:59:40，入场日期为次日 09-23（周三）
def priority_cfg(*slots, grace=600):
    return AppConfig(scheduler=SchedulerConfig(
        weekly_enabled=True, weekly_plan={'3': list(slots)}, release_grace_seconds=grace))


def attempted_slots(booking):
    return [call.kwargs['preferred_time'] for call in booking.call_args_list]


def test_highest_priority_wins_when_it_is_bookable():
    res, booking = run_once(priority_cfg('15:00-16:30', '16:30-18:00', '13:30-15:00'), [BOOKED])
    assert res['success'] and attempted_slots(booking) == ['15:00-16:30']


def test_full_slot_falls_through_to_next_priority_in_the_same_round():
    res, booking = run_once(priority_cfg('15:00-16:30', '16:30-18:00'), [FULL, BOOKED])
    assert res['success'] and attempted_slots(booking) == ['15:00-16:30', '16:30-18:00']


def test_course_occupied_priority_does_not_block_lower_priorities():
    res, booking = run_once(priority_cfg('15:00-16:30', '16:30-18:00'), [NOT_RELEASED, BOOKED])
    assert res['success'] and attempted_slots(booking) == ['15:00-16:30', '16:30-18:00']


def test_unreleased_priority_is_retried_while_lower_ones_are_already_ruled_out():
    # 第一轮：优先级 1 尚未放出（保留），优先级 2 已满（剔除）；第二轮只重试优先级 1
    res, booking = run_once(priority_cfg('15:00-16:30', '16:30-18:00'), [MISSING, FULL, BOOKED])
    assert res['success'] and attempted_slots(booking) == ['15:00-16:30', '16:30-18:00', '15:00-16:30']


def test_gives_up_only_after_every_priority_is_exhausted():
    res, booking = run_once(priority_cfg('15:00-16:30', '16:30-18:00', '13:30-15:00'), [FULL, FULL, FULL])
    assert res['success'] is False and booking.call_count == 3


def test_all_priorities_course_occupied_sends_one_skip_notification():
    cfg = priority_cfg('15:00-16:30', '16:30-18:00', grace=0)
    scheduler = BookingScheduler(cfg, Mock(), Mock(), Mock(), Mock(), notifier=Mock())
    with patch('xdty_booking.core.scheduler.datetime', wraps=datetime) as clock, \
         patch.object(scheduler, 'ensure_valid_session', return_value=True), \
         patch.object(scheduler._stop_event, 'wait', return_value=False), \
         patch('xdty_booking.core.scheduler.TimeSync.get_server_time_offset', return_value=0), \
         patch('xdty_booking.core.scheduler.TimeSync.wait_until'), \
         patch('xdty_booking.core.scheduler.BookingEngine.execute_booking', side_effect=[NOT_RELEASED, NOT_RELEASED]):
        clock.now.return_value = datetime(2026, 9, 22, 6, 59, 40)
        res = scheduler._run_once()
    kwargs = scheduler.notifier.send.call_args.kwargs
    assert res['reason'] == 'course_occupied'
    assert '课程占用，已跳过' in kwargs['title'] and '15:00-16:30 等 2 个时段' in kwargs['title']
    assert '15:00-16:30' in kwargs['content'] and '16:30-18:00' in kwargs['content']

