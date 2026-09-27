from datetime import datetime
from unittest.mock import Mock, patch
from types import SimpleNamespace

import pytest
from xdty_booking.config import AppConfig, SchedulerConfig, load_config, save_target_and_scheduler_config
from xdty_booking.core.scheduler import BookingScheduler, next_scheduled_booking, planned_slots
from xdty_booking.web.server import GymStatusHandler, SchedulerManager, query_gym_status


@pytest.mark.parametrize('now,offset,plan,run_at,visit,slot', [
    ('2026-09-18 06:00:00', 1, {'6': '16:30-18:00', '7': '16:30-18:00'}, '2026-09-18 07:00:00', '2026-09-19', '16:30-18:00'),
    ('2026-09-18 07:00:00', 1, {'6': '16:30-18:00', '7': '18:00-19:30'}, '2026-09-19 07:00:00', '2026-09-20', '18:00-19:30'),
    ('2026-09-19 16:00:00', 1, {'6': '16:30-18:00', '7': '16:30-18:00'}, '2026-09-25 07:00:00', '2026-09-26', '16:30-18:00'),
    ('2026-12-31 08:00:00', 1, {'6': '16:30-18:00'}, '2027-01-01 07:00:00', '2027-01-02', '16:30-18:00'),
    ('2026-09-19 06:00:00', 0, {'6': '16:30-18:00'}, '2026-09-19 07:00:00', '2026-09-19', '16:30-18:00'),
])
def test_weekly_plan_uses_visit_weekday_and_skips_unplanned_days(now, offset, plan, run_at, visit, slot):
    cfg = AppConfig(scheduler=SchedulerConfig(weekly_enabled=True, weekly_plan=plan))
    cfg.target.target_date_offset = offset
    result = next_scheduled_booking(cfg, datetime.fromisoformat(now))
    assert result == (datetime.fromisoformat(run_at), visit, [slot])


@pytest.mark.parametrize('plan', [{}, {'8': '16:30-18:00'}, {'6': '25:00-26:00'}, {'6': '18:00-16:30'}, {'6': '<script>'}, ['16:30-18:00'],
                                  {'6': ['15:00-16:30', '16:30-18:00', '13:30-15:00', '10:30-12:00']}, {'6': ['16:30-18:00', '16:30-18:00']}])
def test_invalid_plan_does_not_overwrite_config(tmp_path, plan):
    path = tmp_path / 'config.yaml'
    original = 'auth:\n  phpsessid: keep-me\n'
    path.write_text(original)
    with pytest.raises(ValueError):
        save_target_and_scheduler_config(str(path), scheduler_updates={'weekly_enabled': True, 'weekly_plan': plan})
    assert path.read_text() == original


def test_plan_round_trip_preserves_credentials_and_normalizes_yaml_weekdays(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('auth:\n  phpsessid: keep-me\n')
    save_target_and_scheduler_config(str(path), scheduler_updates={'weekly_enabled': True, 'weekly_plan': {6: '16:30-18:00', 7: '16:30-18:00'}})
    cfg = load_config(str(path))
    assert cfg.auth.phpsessid == 'keep-me'
    assert cfg.scheduler.weekly_plan == {'6': ['16:30-18:00'], '7': ['16:30-18:00']}


@pytest.mark.parametrize('outcome', ['success', 'full', 'exception'])
def test_weekly_scheduler_continues_after_failure_and_never_repeats_a_run(outcome):
    cfg = AppConfig(scheduler=SchedulerConfig(weekly_enabled=True, weekly_plan={'6': '16:30-18:00', '7': '18:00-19:30'}))
    scheduler = BookingScheduler(cfg, Mock(), Mock(), Mock(), Mock())
    seen = []

    def attempt(*args, **kwargs):
        seen.append(scheduler.next_booking)
        if len(seen) == 2:
            scheduler.stop()
        if outcome == 'exception':
            raise ConnectionError('offline')
        return {'success': outcome == 'success', 'info': outcome}

    with patch('xdty_booking.core.scheduler.datetime', wraps=datetime) as clock, patch.object(scheduler, '_run_once', side_effect=attempt):
        clock.now.return_value = datetime(2026, 9, 18, 6, 59, 40)
        scheduler.run()
    assert seen == [
        (datetime(2026, 9, 18, 7), '2026-09-19', ['16:30-18:00']),
        (datetime(2026, 9, 19, 7), '2026-09-20', ['18:00-19:30']),
    ]


def test_weekly_submission_uses_planned_date_time_and_disables_fallback():
    cfg = AppConfig(scheduler=SchedulerConfig(weekly_enabled=True, weekly_plan={'6': '16:30-18:00'}))
    scheduler = BookingScheduler(cfg, Mock(), Mock(), Mock(), Mock())
    scheduler.next_booking = (datetime(2026, 9, 18, 7), '2026-09-19', ['16:30-18:00'])
    with patch('xdty_booking.core.scheduler.datetime', wraps=datetime) as clock, \
         patch.object(scheduler, 'ensure_valid_session', return_value=True), \
         patch('xdty_booking.core.scheduler.TimeSync.get_server_time_offset', return_value=0), \
         patch('xdty_booking.core.scheduler.TimeSync.wait_until'), \
         patch('xdty_booking.core.scheduler.BookingEngine') as engine:
        clock.now.return_value = datetime(2026, 9, 18, 6, 59, 40)
        engine.return_value.execute_booking.return_value = {'success': True}
        scheduler._run_once()
        kwargs = engine.return_value.execute_booking.call_args.kwargs
    assert kwargs['target_date'] == '2026-09-19'
    assert kwargs['preferred_time'] == '16:30-18:00'
    assert kwargs['fallback_nearest'] is False


def test_plan_api_saves_and_returns_plan_and_rejects_invalid_input(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('{}')
    handler = GymStatusHandler.__new__(GymStatusHandler)
    responses = []
    handler._send_json = lambda code, body: responses.append((code, body))
    plan = {'weekly_enabled': True, 'weekly_plan': {'6': '16:30-18:00'}}
    with patch('xdty_booking.web.server._GLOBAL_CONFIG_PATH', str(path)):
        handler._handle_scheduler_config_save({'scheduler': plan}, {})
        handler._handle_scheduler_config_get()
        assert responses[-1][1]['scheduler']['weekly_plan'] == {'6': ['16:30-18:00']}
        handler._handle_scheduler_config_save({'scheduler': {'weekly_plan': {'6': 'invalid'}}}, {})
    assert responses[-1][0] == 400
    assert load_config(str(path)).scheduler.weekly_plan == {'6': ['16:30-18:00']}


def test_single_schedule_remains_one_shot():
    scheduler = BookingScheduler(AppConfig(), Mock(), Mock(), Mock(), Mock())
    with patch.object(scheduler, '_run_once', return_value={'success': True}) as attempt:
        assert scheduler.run() == {'success': True}
    assert attempt.call_count == 1


def test_dashboard_highlights_each_dates_weekly_slot():
    cfg = AppConfig(scheduler=SchedulerConfig(weekly_enabled=True, weekly_plan={'6': '16:30-18:00'}))
    groups = [SimpleNamespace(date=day, week_name='', time_range=slot, slots=[])
              for day, slot in [('2026-09-19', '16:30-18:00'), ('2026-09-19', '19:30-21:00'), ('2026-09-18', '16:30-18:00')]]
    with patch('xdty_booking.web.server.load_config', return_value=cfg), patch('xdty_booking.web.server.XdtyApi') as api:
        api.return_value.get_intervals.return_value = SimpleNamespace(status=1, info='ok', date_list=[], time_slot_list=groups)
        result = query_gym_status(auto_heal=False)
    assert [group['is_preferred'] for group in result['groups']] == [True, False, False]


def test_waking_late_after_precheck_does_not_submit_old_booking():
    cfg = AppConfig(scheduler=SchedulerConfig(weekly_enabled=True, weekly_plan={'6': '16:30-18:00'}))
    scheduler = BookingScheduler(cfg, Mock(), Mock(), Mock(), Mock())
    scheduler.next_booking = (datetime(2026, 9, 18, 7), '2026-09-19', ['16:30-18:00'])
    with patch('xdty_booking.core.scheduler.datetime', wraps=datetime) as clock, \
         patch.object(scheduler, 'ensure_valid_session', return_value=True), \
         patch('xdty_booking.core.scheduler.TimeSync.get_server_time_offset', return_value=0), \
         patch('xdty_booking.core.scheduler.TimeSync.wait_until') as wait, \
         patch('xdty_booking.core.scheduler.BookingEngine') as engine:
        clock.now.return_value = datetime(2026, 9, 18, 6, 59, 40)
        def wake_late(*args, **kwargs):
            clock.now.return_value = datetime(2026, 9, 19, 12)
        wait.side_effect = wake_late
        result = scheduler._run_once()
    assert result['success'] is False
    engine.assert_not_called()


def test_running_weekly_plan_exposes_visit_date_and_blocks_edits(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('{}')
    save_target_and_scheduler_config(str(path), scheduler_updates={'weekly_enabled': True, 'weekly_plan': {'6': '16:30-18:00'}})
    original = path.read_text()
    manager = SchedulerManager()
    handler = GymStatusHandler.__new__(GymStatusHandler)
    responses = []
    handler._send_json = lambda code, body: responses.append((code, body))
    with patch('xdty_booking.core.scheduler.datetime', wraps=datetime) as clock, \
         patch('xdty_booking.web.server.datetime', wraps=datetime) as server_clock, \
         patch('xdty_booking.web.server.CaptchaSolver'), \
         patch('xdty_booking.web.server._scheduler_manager', manager), \
         patch('xdty_booking.web.server._GLOBAL_CONFIG_PATH', str(path)):
        clock.now.return_value = server_clock.now.return_value = datetime(2026, 9, 18, 6)
        try:
            manager.start(str(path))
            status = manager.get_status()
            assert status['running'] is True
            assert status['target_date'] == '2026-09-19'
            assert status['next_run_dt'] == '2026-09-18 07:00:00'
            assert status['preferred_time'] == '16:30-18:00'
            handler._handle_scheduler_config_save({'scheduler': {'weekly_plan': {'7': '18:00-19:30'}}}, {})
            assert responses[-1][0] == 409
            assert path.read_text() == original
        finally:
            manager.stop()
            manager._thread.join(timeout=2)
        assert not manager._thread.is_alive()
        assert manager.get_status()['running'] is False


def test_date_override_replaces_planned_slot_without_touching_plan():
    cfg = AppConfig(scheduler=SchedulerConfig(
        weekly_enabled=True, weekly_plan={'3': '18:00-19:30'},
        date_overrides={'2026-09-23': '15:00-16:30', '2026-09-25': '16:30-18:00'}))

    # 09-23（周三）计划 18:00-19:30，特例改为 15:00-16:30
    assert next_scheduled_booking(cfg, datetime(2026, 9, 21, 17)) == (datetime(2026, 9, 22, 7), '2026-09-23', ['15:00-16:30'])
    # 09-25（周五）计划表没有，特例也能安排
    assert next_scheduled_booking(cfg, datetime(2026, 9, 23, 17)) == (datetime(2026, 9, 24, 7), '2026-09-25', ['16:30-18:00'])
    # 下周三回到计划表
    assert next_scheduled_booking(cfg, datetime(2026, 9, 28, 17)) == (datetime(2026, 9, 29, 7), '2026-09-30', ['18:00-19:30'])
    assert cfg.scheduler.weekly_plan == {'3': ['18:00-19:30']}


@pytest.mark.parametrize('overrides', [{'2026-9-23': '15:00-16:30'}, {'2026-09-23': '15:00'}, {'2026-09-23': '16:30-15:00'}, ['2026-09-23'],
                                       {'2026-09-23': ['15:00-16:30', '16:30-18:00', '13:30-15:00', '10:30-12:00']}])
def test_invalid_date_override_is_rejected(overrides):
    with pytest.raises(ValueError):
        SchedulerConfig(date_overrides=overrides)


def test_date_override_round_trips_through_config_file(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('scheduler:\n  weekly_enabled: true\n  weekly_plan:\n    "3": 18:00-19:30\n', encoding='utf-8')
    save_target_and_scheduler_config(str(path), scheduler_updates={'date_overrides': {'2026-09-23': '15:00-16:30'}})
    cfg = load_config(str(path))
    assert cfg.scheduler.date_overrides == {'2026-09-23': ['15:00-16:30']}
    assert cfg.scheduler.weekly_plan == {'3': ['18:00-19:30']}


def test_override_api_saves_returns_drops_expired_and_rejects_invalid(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('{}')
    handler = GymStatusHandler.__new__(GymStatusHandler)
    responses = []
    handler._send_json = lambda code, body: responses.append((code, body))
    overrides = {'2026-09-23': '15:00-16:30', '2026-09-01': '16:30-18:00'}  # 后者已过期
    with patch('xdty_booking.web.server._GLOBAL_CONFIG_PATH', str(path)), \
         patch('xdty_booking.web.server.datetime', wraps=datetime) as clock:
        clock.now.return_value = datetime(2026, 9, 21, 18)
        handler._handle_scheduler_config_save({'scheduler': {'weekly_enabled': True, 'weekly_plan': {'3': '18:00-19:30'},
                                                              'date_overrides': overrides}}, {})
        assert responses[-1][0] == 200
        handler._handle_scheduler_config_get()
        assert responses[-1][1]['scheduler']['date_overrides'] == {'2026-09-23': ['15:00-16:30']}
        handler._handle_scheduler_config_save({'scheduler': {'date_overrides': {'2026-09-23': 'bad'}}}, {})
        assert responses[-1][0] == 400
        # 提交空表 = 清空特例
        handler._handle_scheduler_config_save({'scheduler': {'date_overrides': {}}}, {})
    cfg = load_config(str(path))
    assert cfg.scheduler.date_overrides == {}
    assert cfg.scheduler.weekly_plan == {'3': ['18:00-19:30']}


def test_dashboard_highlights_override_slot_over_weekly_plan():
    cfg = AppConfig(scheduler=SchedulerConfig(weekly_enabled=True, weekly_plan={'3': '18:00-19:30'},
                                              date_overrides={'2026-09-23': '15:00-16:30'}))
    groups = [SimpleNamespace(date=day, week_name='', time_range=slot, slots=[])
              for day, slot in [('2026-09-23', '15:00-16:30'), ('2026-09-23', '18:00-19:30'), ('2026-09-30', '18:00-19:30')]]
    with patch('xdty_booking.web.server.load_config', return_value=cfg), patch('xdty_booking.web.server.XdtyApi') as api:
        api.return_value.get_intervals.return_value = SimpleNamespace(status=1, info='ok', date_list=[], time_slot_list=groups)
        result = query_gym_status(auto_heal=False)
    assert [group['is_preferred'] for group in result['groups']] == [True, False, True]
    assert result['scheduler_config']['date_overrides'] == {'2026-09-23': ['15:00-16:30']}


def test_dashboard_renders_override_rows_and_submits_them():
    from xdty_booking.web.template import render_dashboard
    html = render_dashboard({
        'stadium_name': 'x', 'area_name': 'y', 'query_time': '', 'session_valid': True, 'info': '', 'groups': [],
        'scheduler_config': {'weekly_enabled': True, 'weekly_plan': {'3': '18:00-19:30'},
                             'date_overrides': {'2026-09-23': '15:00-16:30'}},
    })
    assert 'value="2026-09-23"' in html and 'value="15:00-16:30"' in html
    assert 'date_overrides' in html  # 保存 payload 中携带
    assert 'addOverrideRow' in html


def test_priority_slots_survive_a_config_file_round_trip(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('auth:\n  phpsessid: keep-me\n')
    save_target_and_scheduler_config(str(path), scheduler_updates={
        'weekly_enabled': True,
        'weekly_plan': {'3': ['18:00-19:30', '16:30-18:00', '15:00-16:30']},
        'date_overrides': {'2026-09-25': ['16:30-18:00', '15:00-16:30']}})
    cfg = load_config(str(path))
    assert cfg.auth.phpsessid == 'keep-me'
    assert cfg.scheduler.weekly_plan == {'3': ['18:00-19:30', '16:30-18:00', '15:00-16:30']}
    assert planned_slots(cfg, '2026-09-23') == ['18:00-19:30', '16:30-18:00', '15:00-16:30']
    assert planned_slots(cfg, '2026-09-25') == ['16:30-18:00', '15:00-16:30']  # 特例优先于计划表
    assert planned_slots(cfg, '2026-09-24') == []


def test_dashboard_highlights_every_priority_slot_and_renders_all_inputs():
    from xdty_booking.web.template import render_dashboard
    cfg = AppConfig(scheduler=SchedulerConfig(weekly_enabled=True, weekly_plan={'3': ['18:00-19:30', '16:30-18:00']}))
    groups = [SimpleNamespace(date='2026-09-23', week_name='', time_range=slot, slots=[])
              for slot in ['18:00-19:30', '16:30-18:00', '19:30-21:00']]
    with patch('xdty_booking.web.server.load_config', return_value=cfg), patch('xdty_booking.web.server.XdtyApi') as api:
        api.return_value.get_intervals.return_value = SimpleNamespace(status=1, info='ok', date_list=[], time_slot_list=groups)
        result = query_gym_status(auto_heal=False)
    assert [group['is_preferred'] for group in result['groups']] == [True, True, False]

    html = render_dashboard({'stadium_name': 'x', 'area_name': 'y', 'query_time': '', 'session_valid': True,
                             'info': '', 'groups': [], 'scheduler_config': result['scheduler_config']})
    assert 'id="weeklyDay3_1"' in html and 'id="weeklyDay3_2"' in html and 'id="weeklyDay3_3"' in html
    assert 'value="18:00-19:30"' in html and 'value="16:30-18:00"' in html
