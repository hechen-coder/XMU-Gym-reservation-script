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


