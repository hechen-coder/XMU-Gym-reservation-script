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
