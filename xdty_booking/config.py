import os
import yaml
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

@dataclass
class AuthConfig:
    phpsessid: str = ""
    uid: str = ""
    heartbeat_interval_seconds: int = 300
    auto_harvest_enabled: bool = True
    wechat_appid: str = "wx81a2b2fa90759cb7"
    wechat_appex_path: str = ""
    auth_params: Dict[str, Any] = field(default_factory=dict)

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
    target_time: str = "07:00:00"
    advance_ms: int = 200
    retry_count: int = 5
    retry_interval_ms: int = 150
    fallback_nearest: bool = True       # 首选时段无名额时是否自动选择最近时段
    pre_check_minutes: int = 5          # 抢票前提前自检并尝试自愈 Session 的分钟数

# 开发者统一发信箱内置凭据 (保护性分发，买家仅需填写个人接收邮箱)
DEFAULT_DEVELOPER_EMAIL_SENDER = "1687354114@qq.com"
DEFAULT_DEVELOPER_EMAIL_AUTH = "cetwcelnwjfbfdff"
DEFAULT_DEVELOPER_SMTP_HOST = "smtp.qq.com"
DEFAULT_DEVELOPER_SMTP_PORT = 465
DEFAULT_DEVELOPER_SMTP_SSL = True

@dataclass
class EmailConfig:
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = 465
    ssl: bool = True
    sender: str = ""
    password: str = ""
    to_addrs: List[str] = field(default_factory=list)

@dataclass
class PushPlusConfig:
    token: str = ""

@dataclass
class ServerChanConfig:
    sendkey: str = ""

@dataclass
class BarkConfig:
    server_url: str = "https://api.day.app"
    device_key: str = ""

@dataclass
class NotifyConfig:
    enabled: bool = False
    channel: str = "pushplus"  # email, pushplus, serverchan, bark, all
    title_prefix: str = "【厦大体育馆预约】"
    email: EmailConfig = field(default_factory=EmailConfig)
    pushplus: PushPlusConfig = field(default_factory=PushPlusConfig)
    serverchan: ServerChanConfig = field(default_factory=ServerChanConfig)
    bark: BarkConfig = field(default_factory=BarkConfig)

@dataclass
class AppConfig:
    base_url: str = "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test"
    auth: AuthConfig = field(default_factory=AuthConfig)
    target: TargetConfig = field(default_factory=TargetConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)

def _build_dataclass(cls, data: Optional[Dict[str, Any]]):
    if not isinstance(data, dict):
        return cls()
    field_names = {f for f in cls.__dataclass_fields__}
    filtered = {k: v for k, v in data.items() if k in field_names}
    return cls(**filtered)

def load_config(config_path: str = "config/config.yaml") -> AppConfig:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    
    auth_data = data.get("auth", {})
    target_data = data.get("target", {})
    scheduler_data = data.get("scheduler", {})
    notify_data = data.get("notify", {})

    # 递归构建 NotifyConfig (支持 pushplus_token 极简单行写法与统一发信箱收件人极简写法)
    pushplus_raw = notify_data.get("pushplus")
    if not isinstance(pushplus_raw, dict):
        token = notify_data.get("pushplus_token") or notify_data.get("token")
        if token:
            pushplus_raw = {"token": str(token).strip()}
    
    # 解析 email 配置 (支持 recipient_email / to_addr / to_addrs 极简单行写法)
    email_raw = notify_data.get("email")
    if isinstance(email_raw, str):
        email_raw = {"to_addrs": [email_raw.strip()]}
    elif not isinstance(email_raw, dict):
        email_raw = {}
    else:
        email_raw = dict(email_raw)

    flat_to = notify_data.get("recipient_email") or notify_data.get("to_addr") or notify_data.get("to_email")
    if flat_to and "to_addrs" not in email_raw:
        if isinstance(flat_to, list):
            email_raw["to_addrs"] = [str(x).strip() for x in flat_to if str(x).strip()]
        else:
            email_raw["to_addrs"] = [str(flat_to).strip()]
    elif "to_addr" in email_raw and "to_addrs" not in email_raw:
        addr = email_raw.get("to_addr")
        email_raw["to_addrs"] = [str(addr).strip()] if addr else []

    if "to_addrs" in email_raw and isinstance(email_raw["to_addrs"], str):
        email_raw["to_addrs"] = [email_raw["to_addrs"].strip()]

    email_cfg = _build_dataclass(EmailConfig, email_raw)

    # 核心安全特性：若买家配置了收信邮箱但未提供自定义发信人，自动注入开发者统一安全发信凭据
    if email_cfg.to_addrs and not email_cfg.sender:
        email_cfg.smtp_host = DEFAULT_DEVELOPER_SMTP_HOST
        email_cfg.smtp_port = DEFAULT_DEVELOPER_SMTP_PORT
        email_cfg.ssl = DEFAULT_DEVELOPER_SMTP_SSL
        email_cfg.sender = DEFAULT_DEVELOPER_EMAIL_SENDER
        email_cfg.password = DEFAULT_DEVELOPER_EMAIL_AUTH

    pushplus_cfg = _build_dataclass(PushPlusConfig, pushplus_raw)
    serverchan_cfg = _build_dataclass(ServerChanConfig, notify_data.get("serverchan"))
    bark_cfg = _build_dataclass(BarkConfig, notify_data.get("bark"))

    notify_field_names = {f for f in NotifyConfig.__dataclass_fields__}
    filtered_notify = {k: v for k, v in notify_data.items() if k in notify_field_names and k not in ("email", "pushplus", "serverchan", "bark")}
    
    # 若用户未显式配置 enabled，但填写了任意推送 token 或接收邮箱，则自动启用通知
    if "enabled" not in filtered_notify:
        has_any_token = bool(
            pushplus_cfg.token or
            email_cfg.to_addrs or
            serverchan_cfg.sendkey or
            bark_cfg.device_key
        )
        filtered_notify["enabled"] = has_any_token

    # 若用户配置了接收邮箱且未指定推送通道，默认将 channel 对齐为 email
    if "channel" not in filtered_notify:
        if email_cfg.to_addrs and not pushplus_cfg.token:
            filtered_notify["channel"] = "email"

    notify_cfg = NotifyConfig(
        email=email_cfg,
        pushplus=pushplus_cfg,
        serverchan=serverchan_cfg,
        bark=bark_cfg,
        **filtered_notify
    )

    target_cfg = _build_dataclass(TargetConfig, target_data)
    # 智能自适应校区：若指定了思明校区 (stadium_id=6) 且未显式指定 area_id，自动对齐思明校区参数
    if target_cfg.stadium_id == 6 and "area_id" not in target_data:
        if target_cfg.stadium_name == "翔安校区健身房":
            target_cfg.stadium_name = "思明校区健身房"
        if target_cfg.area_name == "爱秋体育馆健身房":
            target_cfg.area_name = "思明校区健身房"
        target_cfg.area_id = 0
        target_cfg.user_range = "[]"
        if "venue_id" not in target_data:
            target_cfg.venue_id = 6

    return AppConfig(
        base_url=data.get("base_url", "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test"),
        auth=_build_dataclass(AuthConfig, auth_data),
        target=target_cfg,
        scheduler=_build_dataclass(SchedulerConfig, scheduler_data),
        notify=notify_cfg
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

def save_auth_params(config_path: str, params: Dict[str, Any]) -> bool:
    """
    持久化回写 checkLogin 续登参数 auth_params 至配置文件
    """
    if not os.path.exists(config_path):
        return False

    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    data = yaml.safe_load(content) or {}
    if "auth" not in data or not isinstance(data["auth"], dict):
        data["auth"] = {}
    if "auth_params" not in data["auth"] or not isinstance(data["auth"]["auth_params"], dict):
        data["auth"]["auth_params"] = {}

    data["auth"]["auth_params"].update(params)
    if "uid" in params and params["uid"]:
        data["auth"]["uid"] = str(params["uid"])

    new_content = yaml.dump(data, allow_unicode=True, sort_keys=False)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True

def save_target_and_scheduler_config(
    config_path: str,
    target_updates: Optional[Dict[str, Any]] = None,
    scheduler_updates: Optional[Dict[str, Any]] = None
) -> bool:
    """
    持久化回写用户选择的目标场馆地点、预约时段以及早 7 点抢票定时配置至配置文件
    """
    if not os.path.exists(config_path):
        return False

    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    data = yaml.safe_load(content) or {}
    if not isinstance(data, dict):
        data = {}

    if target_updates:
        if "target" not in data or not isinstance(data["target"], dict):
            data["target"] = {}
        data["target"].update(target_updates)

    if scheduler_updates:
        if "scheduler" not in data or not isinstance(data["scheduler"], dict):
            data["scheduler"] = {}
        data["scheduler"].update(scheduler_updates)

    new_content = yaml.dump(data, allow_unicode=True, sort_keys=False)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True


def save_notify_config(
    config_path: str,
    enabled: Optional[bool] = None,
    email: Optional[str] = None,
    channel: Optional[str] = None
) -> bool:
    """
    持久化回写通知配置 (通知总开关、接收邮箱、通知通道) 至 config.yaml
    """
    if not os.path.exists(config_path):
        return False

    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    data = yaml.safe_load(content) or {}
    if not isinstance(data, dict):
        data = {}

    if "notify" not in data or not isinstance(data["notify"], dict):
        data["notify"] = {}

    if enabled is not None:
        data["notify"]["enabled"] = bool(enabled)

    if channel is not None:
        data["notify"]["channel"] = str(channel).strip()

    if email is not None:
        email_clean = str(email).strip()
        if "email" not in data["notify"] or not isinstance(data["notify"]["email"], dict):
            data["notify"]["email"] = {}
        if email_clean:
            data["notify"]["email"]["to_addrs"] = [email_clean]
        else:
            data["notify"]["email"]["to_addrs"] = []
        # 若开启了通知且填了邮箱，确保通道默认对齐为 email
        if data["notify"].get("enabled") and email_clean and not data["notify"].get("channel"):
            data["notify"]["channel"] = "email"

    new_content = yaml.dump(data, allow_unicode=True, sort_keys=False)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True

