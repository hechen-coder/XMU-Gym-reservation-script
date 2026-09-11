import os
import yaml
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class AuthConfig:
    phpsessid: str = ""
    uid: str = ""
    heartbeat_interval_seconds: int = 300
    auto_harvest_enabled: bool = False
    wechat_appid: str = "wx81a2b2fa90759cb7"
    wechat_appex_path: str = ""

@dataclass
class TargetConfig:
    stadium_id: int = 16
    venue_id: int = 14
    category_id: int = 8
    stadium_name: str = "翔安校区健身房"
    project_name: str = "健身房"
    area_name: str = "爱秋体育馆健身房"
    area_id: int = 67
    preferred_time: str = "19:30-21:00"
    target_date_offset: int = 1  # 0 为今天，1 为明天
    user_range: str = "[67]"

@dataclass
class SchedulerConfig:
    target_time: str = "08:00:00"
    advance_ms: int = 200
    retry_count: int = 5
    retry_interval_ms: int = 150

@dataclass
class AppConfig:
    base_url: str = "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test"
    auth: AuthConfig = field(default_factory=AuthConfig)
    target: TargetConfig = field(default_factory=TargetConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)

def load_config(config_path: str = "config/config.yaml") -> AppConfig:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    
    auth_data = data.get("auth", {})
    target_data = data.get("target", {})
    scheduler_data = data.get("scheduler", {})

    return AppConfig(
        base_url=data.get("base_url", "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test"),
        auth=AuthConfig(**auth_data),
        target=TargetConfig(**target_data),
        scheduler=SchedulerConfig(**scheduler_data)
    )

def save_phpsessid(config_path: str, new_token: str) -> bool:
    """
    持久化回写新的 PHPSESSID 至配置文件，保留原有注释与缩进
    """
    if not os.path.exists(config_path):
        return False

    import re
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r'(phpsessid:\s*)(["\']?[a-zA-Z0-9_-]*["\']?)'
    if re.search(pattern, content):
        new_content = re.sub(pattern, rf'\g<1>"{new_token}"', content, count=1)
    else:
        data = yaml.safe_load(content) or {}
        if "auth" not in data:
            data["auth"] = {}
        data["auth"]["phpsessid"] = new_token
        new_content = yaml.dump(data, allow_unicode=True, sort_keys=False)

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True
