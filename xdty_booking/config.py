import os
import re
import yaml
import logging
from dataclasses import dataclass, field
from typing import ClassVar, Optional, List, Dict, Any

logger = logging.getLogger(__name__)

def safe_load_yaml_file(config_path: str) -> Dict[str, Any]:
    """
    安全读取并解析 YAML 配置文件，具备行级容错与自动修复机制。
    针对用户手动编辑、复制粘贴时常见的格式错误（如单空格前缀、混合缩进、重复键等）：
    1. 首先尝试原生 safe_load；
    2. 若解析失败 (yaml.YAMLError)，自动对缩进行级智能对齐容错；
    3. 若修复成功，自动将修复后的合规 YAML 回写至原文件；
    4. 若文件严重损坏彻底无法修复，自动尝试读取同级 config.example.yaml 兜底，绝不抛出阻断性崩溃。
    """
    if not os.path.exists(config_path):
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.error(f"读取配置文件 '{config_path}' 失败: {e}")
        return {}

    # 1. 尝试原生安全解析
    try:
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            return data
        if data is None:
            return {}
    except yaml.YAMLError as err:
        logger.warning(f"⚠️ 配置文件 '{config_path}' 存在 YAML 语法或缩进格式问题: {err}，正在启动自动容错修复...")

    # 2. 尝试行级智能缩进修正
    try:
        lines = content.splitlines()
        fixed_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                fixed_lines.append(line)
                continue
            leading_spaces = len(line) - len(line.lstrip(" "))
            # 常见手误：1 个前导空格（通常原本应为 2 空格子项）
            if leading_spaces == 1:
                fixed_lines.append("  " + line.lstrip(" "))
            # 常见手误：3 个前导空格（通常原本应为 4 空格深层子项）
            elif leading_spaces == 3:
                fixed_lines.append("    " + line.lstrip(" "))
            else:
                fixed_lines.append(line)

        fixed_content = "\n".join(fixed_lines)
        fixed_data = yaml.safe_load(fixed_content)
        if isinstance(fixed_data, dict):
            logger.info(f"✅ 已成功自动修复 '{config_path}' 的缩进格式问题，正在回写规范化配置...")
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(fixed_data, f, allow_unicode=True, sort_keys=False)
            except Exception as write_err:
                logger.debug(f"回写自动修复配置出现小警告: {write_err}")
            return fixed_data
    except Exception as fix_err:
        logger.debug(f"行级缩进自动修正未完全成功: {fix_err}")

    # 3. 尝试去除报错行或极端异常行进行容错
    try:
        clean_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ":" in stripped:
                clean_lines.append(line)
        clean_content = "\n".join(clean_lines)
        clean_data = yaml.safe_load(clean_content)
        if isinstance(clean_data, dict):
            logger.info(f"✅ 已通过异常行过滤策略成功修复 '{config_path}'！")
            return clean_data
    except Exception:
        pass

    # 4. 终极兜底：尝试读取 config.example.yaml
    dir_name = os.path.dirname(config_path)
    example_path = os.path.join(dir_name, "config.example.yaml") if dir_name else "config/config.example.yaml"
    if not os.path.exists(example_path):
        example_path = "config/config.example.yaml"
    if os.path.exists(example_path):
        try:
            with open(example_path, "r", encoding="utf-8") as ef:
                example_data = yaml.safe_load(ef)
                if isinstance(example_data, dict):
                    logger.warning(f"⚠️ 配置文件 '{config_path}' 严重损坏，已自动应用默认配置模板 '{example_path}' 兜底运行。")
                    return example_data
        except Exception:
            pass

    logger.error(f"❌ 配置文件 '{config_path}' 无法解析且未能加载模板，使用默认空字典兜底。")
    return {}

@dataclass
class AuthConfig:
    phpsessid: str = ""
    uid: str = ""
    cas_username: str = ""
    cas_password: str = ""
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
    release_grace_seconds: float = 600.0  # 准点后放票并非瞬时完成：时段缺失/仍锁定时持续轮询的秒数
    weekly_enabled: bool = False
    # 每天可填最多 MAX_SLOTS 个时段，按优先级从高到低；高优先级约不到时自动尝试下一个
    weekly_plan: Dict[str, List[str]] = field(default_factory=dict)  # 入场日期：1=周一…7=周日
    date_overrides: Dict[str, List[str]] = field(default_factory=dict)  # 特例：入场日期 YYYY-MM-DD -> 时段；优先于计划表

    MAX_SLOTS: ClassVar[int] = 3

    @staticmethod
    def _check_slot(slot) -> str:
        if not isinstance(slot, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d", slot):
            raise ValueError("计划时段格式应为 HH:MM-HH:MM，例如 16:30-18:00")
        if slot[:5] >= slot[6:]:
            raise ValueError("计划时段结束时间必须晚于开始时间")
        return slot

    @classmethod
    def _check_slots(cls, value) -> List[str]:
        """按优先级从高到低的时段列表；旧配置里的单个字符串按一个时段处理"""
        if value in (None, "", []):
            return []
        slots = [value] if isinstance(value, str) else value
        if not isinstance(slots, list) or len(slots) > cls.MAX_SLOTS:
            raise ValueError(f"每天最多设置 {cls.MAX_SLOTS} 个优先级时段")
        slots = [cls._check_slot(s) for s in slots]
        if len(set(slots)) != len(slots):
            raise ValueError("同一天的优先级时段不能重复")
        return slots

    def __post_init__(self):
        if isinstance(self.target_time, str):
            t = self.target_time.strip().replace("：", ":")
            parts = t.split(":")
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                parts.append("00")
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                try:
                    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                    if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59:
                        self.target_time = f"{h:02d}:{m:02d}:{s:02d}"
                except ValueError:
                    pass
        if not isinstance(self.target_time, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d", self.target_time):
            raise ValueError("定时预约时间格式应为 HH:MM:SS")
        for name in ("retry_count", "retry_interval_ms", "pre_check_minutes"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"scheduler.{name} 必须是非负整数")
        grace = getattr(self, "release_grace_seconds")
        if type(grace) not in (int, float) or grace < 0:
            raise ValueError("scheduler.release_grace_seconds 必须是非负数")
        if not 1 <= self.retry_count <= 5:
            raise ValueError("scheduler.retry_count 必须在 1 至 5 之间")
        if not 100 <= self.retry_interval_ms <= 10000:
            raise ValueError("scheduler.retry_interval_ms 必须在 100 至 10000 毫秒之间")
        if not 1 <= self.pre_check_minutes <= 60:
            raise ValueError("scheduler.pre_check_minutes 必须在 1 至 60 分钟之间")
        if not 0 <= self.release_grace_seconds <= 600:
            raise ValueError("scheduler.release_grace_seconds 必须在 0 至 600 秒之间")
        if type(self.advance_ms) is not int or not 0 <= self.advance_ms <= 1000:
            raise ValueError("scheduler.advance_ms 必须在 0 至 1000 毫秒之间")
        if not isinstance(self.weekly_enabled, bool) or not isinstance(self.weekly_plan, dict) \
                or not isinstance(self.date_overrides, dict):
            raise ValueError("每周计划格式错误")
        plan = {}
        for day, slots in self.weekly_plan.items():
            if str(day) not in "1 2 3 4 5 6 7".split():
                raise ValueError("每周计划的星期必须是 1（周一）至 7（周日）")
            slots = self._check_slots(slots)
            if slots:
                plan[str(day)] = slots
        if self.weekly_enabled and not plan:
            raise ValueError("每周计划至少需要设置一天")
        self.weekly_plan = plan
        overrides = {}
        for day, slots in self.date_overrides.items():
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day)):
                raise ValueError("特例日期格式应为 YYYY-MM-DD")
            slots = self._check_slots(slots)
            if slots:
                overrides[str(day)] = slots
        self.date_overrides = overrides

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
class FeishuConfig:
    webhook_url: str = ""
    secret: str = ""  # 机器人开启签名校验时填写

@dataclass
class NotifyConfig:
    enabled: bool = False
    channel: str = "email"  # email, pushplus, serverchan, bark, feishu, all
    title_prefix: str = "【厦大体育馆预约】"
    email: EmailConfig = field(default_factory=EmailConfig)
    pushplus: PushPlusConfig = field(default_factory=PushPlusConfig)
    serverchan: ServerChanConfig = field(default_factory=ServerChanConfig)
    bark: BarkConfig = field(default_factory=BarkConfig)
    feishu: FeishuConfig = field(default_factory=FeishuConfig)

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
    data = safe_load_yaml_file(config_path)
    
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
    feishu_cfg = _build_dataclass(FeishuConfig, notify_data.get("feishu"))

    notify_field_names = {f for f in NotifyConfig.__dataclass_fields__}
    filtered_notify = {k: v for k, v in notify_data.items() if k in notify_field_names and k not in ("email", "pushplus", "serverchan", "bark", "feishu")}
    
    # 若用户未显式配置 enabled，但填写了任意推送 token 或接收邮箱，则自动启用通知
    if "enabled" not in filtered_notify:
        has_any_token = bool(
            pushplus_cfg.token or
            email_cfg.to_addrs or
            serverchan_cfg.sendkey or
            bark_cfg.device_key or
            feishu_cfg.webhook_url
        )
        filtered_notify["enabled"] = has_any_token

    # 若用户配置了接收邮箱且未指定推送通道，默认将 channel 对齐为 email
    if "channel" not in filtered_notify:
        if email_cfg.to_addrs and not pushplus_cfg.token and not feishu_cfg.webhook_url:
            filtered_notify["channel"] = "email"

    notify_cfg = NotifyConfig(
        email=email_cfg,
        pushplus=pushplus_cfg,
        serverchan=serverchan_cfg,
        bark=bark_cfg,
        feishu=feishu_cfg,
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
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        content = ""

    pattern = r'(phpsessid:\s*)(["\']?[a-zA-Z0-9_-]*["\']?)'
    if re.search(pattern, content):
        new_content = re.sub(pattern, rf'\g<1>"{new_token}"', content, count=1)
        try:
            yaml.safe_load(new_content)
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return True
        except yaml.YAMLError:
            pass

    data = safe_load_yaml_file(config_path)
    if "auth" not in data or not isinstance(data["auth"], dict):
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

    data = safe_load_yaml_file(config_path)
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
    if target_updates is not None and not isinstance(target_updates, dict):
        raise ValueError("目标配置必须是字典映射")
    if scheduler_updates is not None and not isinstance(scheduler_updates, dict):
        raise ValueError("定时配置必须是字典映射")

    if not os.path.exists(config_path):
        return False

    data = safe_load_yaml_file(config_path)
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

    # 校验合法性，避免写入非法参数导致下次启动崩溃
    if "target" in data and isinstance(data["target"], dict):
        _build_dataclass(TargetConfig, data["target"])
    if "scheduler" in data and isinstance(data["scheduler"], dict):
        validated_scheduler = _build_dataclass(SchedulerConfig, data["scheduler"])
        data["scheduler"]["target_time"] = validated_scheduler.target_time
        data["scheduler"]["weekly_plan"] = validated_scheduler.weekly_plan
        data["scheduler"]["date_overrides"] = validated_scheduler.date_overrides

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

    data = safe_load_yaml_file(config_path)
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


def save_cas_credentials(config_path: str, username: str, password: str) -> bool:
    """
    持久化回写统一身份认证 (CAS) 账号密码至 config.yaml
    """
    if not os.path.exists(config_path):
        return False

    data = safe_load_yaml_file(config_path)
    if not isinstance(data, dict):
        data = {}

    if "auth" not in data or not isinstance(data["auth"], dict):
        data["auth"] = {}

    data["auth"]["cas_username"] = str(username).strip()
    data["auth"]["cas_password"] = str(password)

    new_content = yaml.dump(data, allow_unicode=True, sort_keys=False)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True

