import os
import pytest
from xdty_booking.config import load_config, AppConfig

def test_load_config(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
base_url: "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test"
auth:
  phpsessid: "test_phpsessid_123"
  heartbeat_interval_seconds: 300
target:
  stadium_id: 16
  venue_id: 14
  category_id: 8
  stadium_name: "翔安校区健身房"
  project_name: "健身房"
  area_name: "爱秋体育馆健身房"
  area_id: 67
  preferred_time: "19:30-21:00"
  target_date_offset: 1
scheduler:
  target_time: "08:00:00"
  advance_ms: 200
  retry_count: 5
  retry_interval_ms: 100
""", encoding="utf-8")
    
    cfg = load_config(str(config_file))
    assert isinstance(cfg, AppConfig)
    assert cfg.auth.phpsessid == "test_phpsessid_123"
    assert cfg.target.stadium_id == 16
    assert cfg.target.venue_id == 14
    assert cfg.scheduler.advance_ms == 200
    assert cfg.target.preferred_time == "19:30-21:00"

def test_load_config_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_config("non_existent_config.yaml")

def test_load_minimal_config(tmp_path):
    config_file = tmp_path / "config.minimal.yaml"
    config_file.write_text("""
target:
  preferred_time: "18:00-19:30"
notify:
  pushplus_token: "test_token_xyz"
""", encoding="utf-8")

    cfg = load_config(str(config_file))
    assert cfg.target.preferred_time == "18:00-19:30"
    assert cfg.target.stadium_id == 16  # 默认翔安
    assert cfg.notify.pushplus.token == "test_token_xyz"
    assert cfg.notify.enabled is True  # 自动启用
    assert cfg.auth.auto_harvest_enabled is True  # 默认开启自愈

def test_siming_campus_auto_adaptation(tmp_path):
    config_file = tmp_path / "config.siming.yaml"
    config_file.write_text("""
target:
  stadium_id: 6
  venue_id: 6
""", encoding="utf-8")

    cfg = load_config(str(config_file))
    assert cfg.target.stadium_id == 6
    assert cfg.target.venue_id == 6
    assert cfg.target.stadium_name == "思明校区健身房"
    assert cfg.target.area_name == "思明校区健身房"
    assert cfg.target.area_id == 0
    assert cfg.target.user_range == "[]"

def test_ensure_config_path_auto_creates(tmp_path, monkeypatch):
    from xdty_booking.web.server import _ensure_config_path
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    example = config_dir / "config.example.yaml"
    example.write_text("target:\n  preferred_time: '19:30-21:00'\n", encoding="utf-8")
    
    # 验证当 config.yaml 不存在时，自动生成并返回 target path
    target = str(config_dir / "config.yaml")
    res = _ensure_config_path(target)
    assert os.path.exists(target)
    assert res == target

def test_load_config_with_single_space_indentation_auto_repair(tmp_path):
    """验证当配置文件存在单空格缩进错误时，系统能自动容错修复并成功读取"""
    config_file = tmp_path / "config.yaml"
    # 模拟用户遇到的典型缩进问题：第 5 行仅有 1 个前导空格
    malformed_yaml = """auth:
  auth_params:
    token: 6F3AB4EF7E8278980F46182707F08616
  uid: '1073507'
 uid: '1073507'
target:
  preferred_time: 19:30-21:00
"""
    config_file.write_text(malformed_yaml, encoding="utf-8")
    cfg = load_config(str(config_file))
    assert cfg.auth.uid == "1073507"
    assert cfg.target.preferred_time == "19:30-21:00"

def test_load_config_with_broken_yaml_fallback(tmp_path):
    """验证当配置文件严重损坏时，系统自动降级使用默认模板或默认实例而不崩溃"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("::: !!! INVALID YAML SYNTAX !!! :::", encoding="utf-8")
    
    cfg = load_config(str(config_file))
    assert isinstance(cfg, AppConfig)
    # 默认值保障系统不崩溃
    assert cfg.target.stadium_id == 16


def test_scheduler_target_time_normalization():
    from xdty_booking.config import SchedulerConfig
    # 标准 HH:MM:SS
    sc = SchedulerConfig(target_time="07:01:34")
    assert sc.target_time == "07:01:34"

    # 单数位小时容错
    sc2 = SchedulerConfig(target_time="7:01:34")
    assert sc2.target_time == "07:01:34"

    # 全角中文冒号容错
    sc3 = SchedulerConfig(target_time="7：01：34")
    assert sc3.target_time == "07:01:34"

    # 简写无秒数自动补全 00
    sc4 = SchedulerConfig(target_time="07:00")
    assert sc4.target_time == "07:00:00"

    # 包含首尾空格
    sc5 = SchedulerConfig(target_time="  07:01:34  ")
    assert sc5.target_time == "07:01:34"

    # 非法格式应抛异常
    with pytest.raises(ValueError, match="定时预约时间格式应为 HH:MM:SS"):
        SchedulerConfig(target_time="25:00:00")

    with pytest.raises(ValueError, match="定时预约时间格式应为 HH:MM:SS"):
        SchedulerConfig(target_time="invalid_time")


def test_save_target_and_scheduler_custom_target_time(tmp_path):
    from xdty_booking.config import save_target_and_scheduler_config
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
scheduler:
  target_time: "07:00:00"
target:
  preferred_time: "12:00-13:30"
""", encoding="utf-8")

    # 保存自定义 7：01：34
    res = save_target_and_scheduler_config(
        str(config_file),
        scheduler_updates={"target_time": "7：01：34"}
    )
    assert res is True
    cfg = load_config(str(config_file))
    assert cfg.scheduler.target_time == "07:01:34"
    assert cfg.target.preferred_time == "12:00-13:30"




