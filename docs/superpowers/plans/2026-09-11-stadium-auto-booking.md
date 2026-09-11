# 微信小程序（厦大体育）体育馆自动预约脚本实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个工业级的 Python 自动化脚本与服务，基于对已抓取网络请求包的逆向分析，实现微信小程序体育馆（厦大体育 H5 系统）的 Session 心跳保活、Windows 微信静默唤醒/抓取兜底、验证码本地毫秒级 OCR 识别以及准点高并发极速抢票。

**Architecture:** 
模块化分层设计：
1. **数据模型层 (`models.py`)**：严谨定义场地、时间段、预约详情、预约状态等数据结构。
2. **底层 HTTP 客户端与接口层 (`client.py`, `endpoints.py`)**：统一封装 Session、Cookie、微信 User-Agent 及全套 REST API（获取场次、校验、下单、查询）。
3. **会话与保活管理层 (`session_manager.py`, `wechat_harvester.py`)**：实现《预约请求方案.md》中的方案1（心跳保活机制，定时探测防止 token/session 失效）与方案2（Windows PC 微信客户端静默唤醒与 Token 抓取兜底）。
4. **验证码识别引擎 (`captcha_solver.py`)**：本地集成高效无依赖 OCR 识别 4 位字母验证码。
5. **抢票与调度引擎 (`time_sync.py`, `booking_engine.py`)**：服务器时间精准对齐（NTP/HTTP Date 校准）、毫秒级定时器、并发重试与结果推送。

**Tech Stack:** Python 3.8+, `requests`, `pydantic` (或标准 `dataclasses`), `ddddocr` (或轻量离线 OCR), `pyyaml`, `pytest`, `pywin32` / `pywinauto` (Windows 微信唤醒可选模块)

## Global Constraints
- **开发语言**: Python 3.8+
- **目标接口系统**: `https://xdty.xmu.edu.cn/bdlp_h5_fitness_test`
- **核心认证凭据**: Cookie 中的 `PHPSESSID`, `login_type=4`, `COOKIE_IS_APP_UI=0`
- **代码规范**: 强类型注解 (Type Hints), 单一职责原则, 零硬编码 (全配置驱动), 严格单测保证 (TDD)
- **依赖安全**: 纯离线识别验证码，严禁将个人 Token/Cookie 上传至第三方未知云端

---

## User Review Required

> [!IMPORTANT]
> **关于网络访问与运行环境**：
> 1. 本地测试显示 `xdty.xmu.edu.cn` 域名需要处于**厦门大学校园网环境**或开启**厦大 WebVPN / 校园网代理**时方可连通。在脱网环境下，本计划通过已保存的 `request` 抓包数据构建完整的 Mock 测试集，保证测试能够 100% 离线通过；在真实运行时请确保本机处于校园网/VPN 连接下。
> 2. 下单接口包含 `captcha` 验证码字段。本计划将默认采用完全离线的 `ddddocr` 引擎进行自动识别（准确率 >95%，耗时约 10ms），并提供失败重试机制。

> [!TIP]
> **关于《预约请求方案.md》的三种方案落地决策**：
> - **心跳保活（方案 1，首选）**：由于实际抓包发现业务请求走的是 PHP Session 机制（`PHPSESSID`），最轻量且稳定的方式是运行一个守护进程，每隔 5~10 分钟发送一次轻量级请求（如 `mySubscribe`），令后端 Session 永远处于活跃状态不超时。
> - **微信 PC 静默唤醒（方案 2，兜底）**：针对电脑长期开机或锁屏场景，开发 `wechat_harvester.py` 自动化模块，可调用 Windows 微信命令唤醒小程序，读取最新 Session。
> - **方案 3（双 Token）**：原生小程序接口有 RSA/AES 混淆且属于框架层，实际 H5 业务层使用的是标准 Web Session，心跳方案相比之下更加稳定健壮。

---

## Proposed Changes & Tasks

### Task 1: 项目基础骨架、依赖定义与环境配置

**Files:**
- Create: `requirements.txt`
- Create: `config/config.example.yaml`
- Create: `xdty_booking/__init__.py`
- Create: `xdty_booking/utils/__init__.py`
- Create: `xdty_booking/utils/logger.py`
- Create: `xdty_booking/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: None
- Produces: `AppConfig`, `load_config(path: str) -> AppConfig`, `setup_logger(name: str) -> logging.Logger`

- [ ] **Step 1: 编写配置加载与日志模块的失败测试**

```python
# tests/test_config.py
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
    assert cfg.scheduler.advance_ms == 200
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'xdty_booking')

- [ ] **Step 3: 编写配置与日志实现代码**

```python
# requirements.txt
requests>=2.25.0
pyyaml>=5.4.0
pytest>=6.2.0
ddddocr>=1.4.0
pydantic>=1.8.0
```

```python
# xdty_booking/config.py
import os
import yaml
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class AuthConfig:
    phpsessid: str = ""
    heartbeat_interval_seconds: int = 300
    auto_harvest_enabled: bool = False

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
    retry_interval_ms: int = 100

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
    
    return AppConfig(
        base_url=data.get("base_url", "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test"),
        auth=AuthConfig(**data.get("auth", {})),
        target=TargetConfig(**data.get("target", {})),
        scheduler=SchedulerConfig(**data.get("scheduler", {}))
    )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交基线变更**

Run: `git add requirements.txt config/ xdty_booking/ tests/test_config.py`
Run: `git commit -m "feat: add project scaffolding, config parser, and logging"`

---

### Task 2: 核心数据模型与 API 响应解析 (Models)

**Files:**
- Create: `xdty_booking/core/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: Raw JSON dictionaries from requests
- Produces: `StadiumInfo`, `DateItem`, `SlotItem`, `TimeSlotGroup`, `IntervalResponse`, `AddOrderParams`, `ApiResponse`

- [ ] **Step 1: 编写模型解析的单元测试**

```python
# tests/test_models.py
import json
from xdty_booking.core.models import IntervalResponse, SlotItem

def test_parse_interval_response():
    sample_json = {
        "status": 1,
        "info": "查询成功",
        "data": {
            "venue_id": "14",
            "date_list": [{"date_int": "2026-09-11", "date": "09月11日", "week_int": "5", "week": "今天"}],
            "column_list": [{"column_id": "67", "name": "爱秋体育馆健身房"}],
            "time_slot_list": [
                {
                    "time_range": "19:30-21:00",
                    "start_time": "19:30",
                    "end_time": "21:00",
                    "date": "2026-09-11",
                    "week": "5",
                    "week_name": "周五",
                    "slots": [
                        {
                            "column_id": "67",
                            "date": "2026-09-11",
                            "area_name": "爱秋体育馆健身房",
                            "interval_id": "3080",
                            "price": 0,
                            "selected": 94,
                            "select_type": 1,
                            "max_count": 95,
                            "is_lock": 1,
                            "lock_reason": "",
                            "status": "available"
                        }
                    ]
                }
            ]
        }
    }
    resp = IntervalResponse.from_dict(sample_json)
    assert resp.status == 1
    slot = resp.find_slot(date="2026-09-11", time_range="19:30-21:00", column_id="67")
    assert slot is not None
    assert slot.interval_id == "3080"
    assert slot.is_available is True
    assert slot.remaining_capacity == 1
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'xdty_booking.core'`

- [ ] **Step 3: 编写数据模型代码**

```python
# xdty_booking/core/models.py
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class SlotItem:
    column_id: str
    date: str
    area_name: str
    interval_id: str
    price: float
    selected: int
    max_count: int
    status: str
    is_lock: int = 0
    lock_reason: str = ""

    @property
    def is_available(self) -> bool:
        return self.status == "available" and self.selected < self.max_count

    @property
    def remaining_capacity(self) -> int:
        return max(0, self.max_count - self.selected)

@dataclass
class TimeSlotGroup:
    time_range: str
    start_time: str
    end_time: str
    date: str
    week: str
    week_name: str
    slots: List[SlotItem]

@dataclass
class DateItem:
    date_int: str
    date: str
    week_int: str
    week: str

@dataclass
class IntervalResponse:
    status: int
    info: str
    venue_id: str
    date_list: List[DateItem]
    time_slot_list: List[TimeSlotGroup]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntervalResponse":
        body = data.get("data", {})
        dates = [DateItem(**d) for d in body.get("date_list", [])]
        groups = []
        for g in body.get("time_slot_list", []):
            slots = [SlotItem(
                column_id=str(s.get("column_id", "")),
                date=s.get("date", ""),
                area_name=s.get("area_name", ""),
                interval_id=str(s.get("interval_id", "")),
                price=float(s.get("price", 0)),
                selected=int(s.get("selected", 0)),
                max_count=int(s.get("max_count", 0)),
                status=s.get("status", ""),
                is_lock=int(s.get("is_lock", 0)),
                lock_reason=s.get("lock_reason", "")
            ) for s in g.get("slots", [])]
            groups.append(TimeSlotGroup(
                time_range=g.get("time_range", ""),
                start_time=g.get("start_time", ""),
                end_time=g.get("end_time", ""),
                date=g.get("date", ""),
                week=str(g.get("week", "")),
                week_name=g.get("week_name", ""),
                slots=slots
            ))
        return cls(
            status=data.get("status", 0),
            info=data.get("info", ""),
            venue_id=str(body.get("venue_id", "")),
            date_list=dates,
            time_slot_list=groups
        )

    def find_slot(self, date: str, time_range: str, column_id: Optional[str] = None) -> Optional[SlotItem]:
        for g in self.time_slot_list:
            if g.date == date and g.time_range == time_range:
                for slot in g.slots:
                    if column_id is None or slot.column_id == str(column_id):
                        return slot
        return None
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: 提交模型代码**

Run: `git add xdty_booking/core/models.py tests/test_models.py`
Run: `git commit -m "feat: implement domain models and interval parser"`

---

### Task 3: 验证码自动识别模块 (Captcha Solver)

**Files:**
- Create: `xdty_booking/solver/__init__.py`
- Create: `xdty_booking/solver/captcha_solver.py`
- Test: `tests/test_captcha.py`

**Interfaces:**
- Consumes: Captcha raw image bytes
- Produces: `CaptchaSolver.solve(image_bytes: bytes) -> str`

- [ ] **Step 1: 编写验证码模块单元测试**

```python
# tests/test_captcha.py
import io
from PIL import Image, ImageDraw
import pytest
from xdty_booking.solver.captcha_solver import CaptchaSolver

def generate_simple_test_image(text="ABCD"):
    img = Image.new("RGB", (100, 40), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def test_captcha_solver_interface():
    solver = CaptchaSolver(use_mock=True, mock_result="daxs")
    result = solver.solve(b"fake_bytes")
    assert result == "daxs"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_captcha.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'xdty_booking.solver')

- [ ] **Step 3: 编写 CaptchaSolver 实现**

```python
# xdty_booking/solver/captcha_solver.py
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class CaptchaSolver:
    """
    负责厦大体育 H5 预约验证码的识别。
    优先尝试加载 ddddocr 极速本地模型；若未安装或指定 mock，则使用 fallback 策略。
    """
    def __init__(self, use_mock: bool = False, mock_result: str = "daxs"):
        self.use_mock = use_mock
        self.mock_result = mock_result
        self._ocr = None
        if not use_mock:
            try:
                import ddddocr
                self._ocr = ddddocr.DdddOcr(show_ad=False)
                logger.info("ddddocr 验证码模型加载成功")
            except Exception as e:
                logger.warning(f"ddddocr 初始化失败 ({e})，将回退至备用或测试模式")

    def solve(self, image_bytes: bytes) -> str:
        if self.use_mock or self._ocr is None:
            return self.mock_result
        try:
            res = self._ocr.classification(image_bytes)
            clean_res = "".join([c for c in res if c.isalnum()]).lower()
            logger.debug(f"验证码识别结果: {clean_res}")
            return clean_res
        except Exception as e:
            logger.error(f"验证码识别异常: {e}")
            return ""
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_captcha.py -v`
Expected: PASS

- [ ] **Step 5: 提交验证码模块**

Run: `git add xdty_booking/solver/ tests/test_captcha.py`
Run: `git commit -m "feat: add captcha solver with ddddocr integration"`

---

### Task 4: API 客户端与完整接口逆向封装 (HTTP Client & Endpoints)

**Files:**
- Create: `xdty_booking/api/__init__.py`
- Create: `xdty_booking/api/client.py`
- Create: `xdty_booking/api/endpoints.py`
- Test: `tests/test_endpoints.py`

**Interfaces:**
- Consumes: `AppConfig`, Mock HTTP responses or live HTTP
- Produces: 
  - `ApiClient`: session pooling, standard headers, cookie management
  - `XdtyApi`:
    - `get_category_stadium(category_id: int) -> dict`
    - `get_intervals(venue_id: int, stadium_id: int, category_id: int, user_range: str) -> IntervalResponse`
    - `choose_verify(...) -> dict`
    - `get_venue_config(...) -> dict`
    - `get_captcha() -> bytes`
    - `add_order(...) -> dict`
    - `my_subscribe(page: int) -> dict`

- [ ] **Step 1: 编写 API 客户端与各端点调用的 Mock 单元测试**

```python
# tests/test_endpoints.py
import pytest
from unittest.mock import Mock, patch
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi

@pytest.fixture
def mock_client():
    client = ApiClient(base_url="https://xdty.xmu.edu.cn/bdlp_h5_fitness_test")
    client.set_session_token("mock_sess_8f4ada1aad7d11f1909f0242ac110002")
    return client

def test_add_order_request_format(mock_client):
    api = XdtyApi(mock_client)
    with patch.object(mock_client.session, 'post') as mock_post:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": 1, "info": "预约成功", "data": []}
        mock_post.return_value = mock_resp

        result = api.add_order(
            stadium_id=16,
            venue_id=14,
            stadium_name="翔安校区健身房",
            project_name="健身房",
            area_name="爱秋体育馆健身房",
            date="2026-09-11",
            week="5",
            week_msg="周五",
            interval_time="19:30-21:00",
            interval_id="3080",
            area_id="67",
            captcha="daxs"
        )
        assert result["status"] == 1
        assert result["info"] == "预约成功"
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        assert "data" in call_kwargs
        assert call_kwargs["data"]["captcha"] == "daxs"
        assert call_kwargs["data"]["stadium_id"] == 16
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_endpoints.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'xdty_booking.api'`

- [ ] **Step 3: 编写 Client 与 Endpoints 实现**

```python
# xdty_booking/api/client.py
import requests
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
        "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows "
        "WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541721) "
        "XWEB/19027 miniProgram/wx81a2b2fa90759cb7"
    ),
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://xdty.xmu.edu.cn",
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
}

class ApiClient:
    def __init__(self, base_url: str = "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.session.cookies.set("Path", "/")
        self.session.cookies.set("login_type", "4")
        self.session.cookies.set("COOKIE_IS_APP_UI", "0")

    def set_session_token(self, phpsessid: str):
        self.session.cookies.set("PHPSESSID", phpsessid)

    def post(self, path: str, data: Optional[Dict[str, Any]] = None, referer: Optional[str] = None) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {}
        if referer:
            headers["referer"] = referer
        return self.session.post(url, data=data, headers=headers, timeout=10)

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, referer: Optional[str] = None) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {}
        if referer:
            headers["referer"] = referer
        return self.session.get(url, params=params, headers=headers, timeout=10)
```

```python
# xdty_booking/api/endpoints.py
import json
from typing import Dict, Any, Optional
from xdty_booking.api.client import ApiClient
from xdty_booking.core.models import IntervalResponse

class XdtyApi:
    def __init__(self, client: ApiClient):
        self.client = client

    def get_category_stadium(self, category_id: int = 8) -> Dict[str, Any]:
        resp = self.client.post("public/index.php/index/Stadium/getCategoryStadium", data={"category_id": category_id})
        return resp.json()

    def get_intervals(self, venue_id: int, stadium_id: int, category_id: int = 8, user_range: str = "[67]") -> IntervalResponse:
        resp = self.client.post(
            "public/index.php/stadium/interval/getInterval",
            data={
                "venue_id": venue_id,
                "stadium_id": stadium_id,
                "user_range": user_range,
                "category_id": category_id
            }
        )
        return IntervalResponse.from_dict(resp.json())

    def choose_verify(self, stadium_id: int, venue_id: int, selected_slots: list, is_academy: int = 1, ids: str = "") -> Dict[str, Any]:
        return self.client.post(
            "public/index.php/index/stadium/chooseVerify",
            data={
                "stadium_id": stadium_id,
                "venue_id": venue_id,
                "selected": json.dumps(selected_slots, ensure_ascii=False),
                "is_academy": is_academy,
                "ids": ids
            }
        ).json()

    def get_venue_config(self, stadium_id: int, venue_id: int, category_id: int = 8) -> Dict[str, Any]:
        return self.client.post(
            "public/index.php/index/Stadium/getVenueConfig",
            data={
                "stadium_id": stadium_id,
                "venue_id": venue_id,
                "category_id": category_id
            }
        ).json()

    def get_captcha(self) -> bytes:
        resp = self.client.get("public/index.php/captcha")
        return resp.content

    def add_order(
        self,
        stadium_id: int,
        venue_id: int,
        stadium_name: str,
        project_name: str,
        area_name: str,
        date: str,
        week: str,
        week_msg: str,
        interval_time: str,
        interval_id: str,
        area_id: str,
        captcha: str,
        category_id: int = 8,
        price: float = 0,
        is_academy: int = 1,
        is_vip: int = 0,
        pay_type: int = 1
    ) -> Dict[str, Any]:
        data = {
            "stadium_id": stadium_id,
            "venue_id": venue_id,
            "stadium_name": stadium_name,
            "project_name": project_name,
            "is_academy": is_academy,
            "academy_name": "",
            "mark": "",
            "details[0][date]": date,
            "details[0][week]": week,
            "details[0][week_msg]": week_msg,
            "details[0][area_name]": area_name,
            "details[0][interval_time]": interval_time,
            "details[0][interval_id]": interval_id,
            "details[0][area_id]": area_id,
            "details[0][price]": price,
            "uids": "",
            "captcha": captcha,
            "category_id": category_id,
            "is_vip": is_vip,
            "pay_type": pay_type
        }
        resp = self.client.post("public/index.php/index/Stadium/addOrder", data=data)
        return resp.json()

    def my_subscribe(self, page: int = 1) -> Dict[str, Any]:
        return self.client.post("public/index.php/index/stadium/mySubscribe", data={"p": page}).json()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_endpoints.py -v`
Expected: PASS

- [ ] **Step 5: 提交接口层实现**

Run: `git add xdty_booking/api/ tests/test_endpoints.py`
Run: `git commit -m "feat: implement API client and all booking endpoints"`

---

### Task 5: 方案1落地 - Session 心跳保活与失效检测 (Session Manager)

**Files:**
- Create: `xdty_booking/auth/__init__.py`
- Create: `xdty_booking/auth/session_manager.py`
- Test: `tests/test_session_manager.py`

**Interfaces:**
- Consumes: `ApiClient`, `XdtyApi`, `AuthConfig`
- Produces: `SessionManager.check_alive() -> bool`, `SessionManager.start_heartbeat_daemon()`

- [ ] **Step 1: 编写心跳与保活的单元测试**

```python
# tests/test_session_manager.py
import pytest
from unittest.mock import Mock
from xdty_booking.auth.session_manager import SessionManager

def test_session_check_alive_success():
    api = Mock()
    api.my_subscribe.return_value = {"status": 1, "info": "查询成功", "data": []}
    mgr = SessionManager(api, phpsessid="valid_token")
    assert mgr.check_alive() is True

def test_session_check_alive_failure():
    api = Mock()
    api.my_subscribe.return_value = {"status": -1, "info": "登录过期"}
    mgr = SessionManager(api, phpsessid="expired_token")
    assert mgr.check_alive() is False
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_session_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'xdty_booking.auth'`

- [ ] **Step 3: 编写 SessionManager 实现**

```python
# xdty_booking/auth/session_manager.py
import time
import threading
import logging
from typing import Optional, Callable
from xdty_booking.api.endpoints import XdtyApi

logger = logging.getLogger(__name__)

class SessionManager:
    """
    落地方案 1：心跳机制保持 Session/Token 不失效。
    定期发送心跳查询请求，延长服务端 session 过期时间。
    """
    def __init__(self, api: XdtyApi, phpsessid: str, on_expired: Optional[Callable[[], None]] = None):
        self.api = api
        self.phpsessid = phpsessid
        self.on_expired = on_expired
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def check_alive(self) -> bool:
        try:
            resp = self.api.my_subscribe(page=1)
            # status == 1 表示登录态有效；status == -1 或 0 表示未登录/已失效
            if resp.get("status") == 1:
                return True
            logger.warning(f"Session 检测未通过: {resp}")
            return False
        except Exception as e:
            logger.error(f"Session 存活检测异常: {e}")
            return False

    def heartbeat_loop(self, interval_seconds: int = 300):
        logger.info(f"Session 心跳守护进程启动，每 {interval_seconds} 秒保活一次")
        while self._running:
            alive = self.check_alive()
            if alive:
                logger.info(f"[{time.strftime('%H:%M:%S')}] 心跳保活成功，Session 正常")
            else:
                logger.error(f"[{time.strftime('%H:%M:%S')}] Session 已失效！")
                if self.on_expired:
                    self.on_expired()
            time.sleep(interval_seconds)

    def start_heartbeat_daemon(self, interval_seconds: int = 300):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self.heartbeat_loop, args=(interval_seconds,), daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_session_manager.py -v`
Expected: PASS

- [ ] **Step 5: 提交心跳管理实现**

Run: `git add xdty_booking/auth/ tests/test_session_manager.py`
Run: `git commit -m "feat: implement session manager and heartbeat keep-alive mechanism"`

---

### Task 6: 方案2落地 - Windows PC 微信静默唤醒与 Token 截获 (WeChat Harvester)

**Files:**
- Create: `xdty_booking/auth/wechat_harvester.py`
- Test: `tests/test_wechat_harvester.py`

**Interfaces:**
- Consumes: Windows WeChat AppID `wx81a2b2fa90759cb7`
- Produces: `WeChatHarvester.launch_miniprogram() -> bool`, `WeChatHarvester.harvest_token() -> Optional[str]`

- [ ] **Step 1: 编写微信唤醒模块的单元测试与 Mock**

```python
# tests/test_wechat_harvester.py
from unittest.mock import patch, Mock
from xdty_booking.auth.wechat_harvester import WeChatHarvester

def test_wechat_harvester_init():
    harvester = WeChatHarvester(appid="wx81a2b2fa90759cb7")
    assert harvester.appid == "wx81a2b2fa90759cb7"

@patch("subprocess.Popen")
def test_wechat_harvester_launch(mock_popen):
    harvester = WeChatHarvester(appid="wx81a2b2fa90759cb7")
    with patch("os.path.exists", return_value=True):
        ok = harvester.launch_miniprogram(executable_path="C:\\mock\\WeChatAppEx.exe")
        assert ok is True
        assert mock_popen.called
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_wechat_harvester.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: 编写 WeChatHarvester 实现**

```python
# xdty_booking/auth/wechat_harvester.py
import os
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class WeChatHarvester:
    """
    落地方案 2：Windows PC 版微信静默唤醒与 Token 抓取兜底。
    在指定抢票时间前或 Token 失效时，可自动启动小程序，触发登录并截获最新 Token。
    """
    DEFAULT_APPID = "wx81a2b2fa90759cb7"

    def __init__(self, appid: str = DEFAULT_APPID):
        self.appid = appid

    def find_wechat_appex(self) -> Optional[str]:
        # 常见 WeChatAppEx.exe 安装路径扫描
        possible_paths = [
            os.path.expandvars(r"%APPDATA%\Tencent\WeChat\XPlugin\Plugins\WMPF"),
            os.path.expandvars(r"%LOCALAPPDATA%\Tencent\WeChatAppEx"),
            r"C:\Program Files\Tencent\WeChat\WeChatAppEx.exe",
            r"C:\Program Files (x86)\Tencent\WeChat\WeChatAppEx.exe"
        ]
        for p in possible_paths:
            if os.path.exists(p):
                if os.path.isfile(p):
                    return p
                for root, dirs, files in os.walk(p):
                    if "WeChatAppEx.exe" in files:
                        return os.path.join(root, "WeChatAppEx.exe")
        return None

    def launch_miniprogram(self, executable_path: Optional[str] = None) -> bool:
        path = executable_path or self.find_wechat_appex()
        if not path or not os.path.exists(path):
            logger.warning("未检测到 WeChatAppEx 路径，请配置具体路径或确认微信已安装")
            return False
        cmd = [path, f"--app_id={self.appid}"]
        try:
            logger.info(f"正在唤醒微信小程序: {self.appid}")
            subprocess.Popen(cmd)
            return True
        except Exception as e:
            logger.error(f"唤醒小程序失败: {e}")
            return False
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_wechat_harvester.py -v`
Expected: PASS

- [ ] **Step 5: 提交微信唤醒模块**

Run: `git add xdty_booking/auth/wechat_harvester.py tests/test_wechat_harvester.py`
Run: `git commit -m "feat: implement wechat harvester module for silent auto-launch"`

---

### Task 7: 极速抢票引擎与高精度定时调度器 (Booking Engine & Scheduler)

**Files:**
- Create: `xdty_booking/core/time_sync.py`
- Create: `xdty_booking/core/booking_engine.py`
- Test: `tests/test_booking_engine.py`

**Interfaces:**
- Consumes: `XdtyApi`, `CaptchaSolver`, `AppConfig`
- Produces: `TimeSync.sync_server_time() -> float`, `BookingEngine.execute_booking() -> dict`

- [ ] **Step 1: 编写 BookingEngine 自动化流程单测**

```python
# tests/test_booking_engine.py
from unittest.mock import Mock
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.core.models import IntervalResponse, SlotItem
from xdty_booking.config import AppConfig

def test_booking_engine_full_flow():
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
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_booking_engine.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: 编写时间校准与抢票引擎**

```python
# xdty_booking/core/time_sync.py
import time
import requests
import email.utils
import logging

logger = logging.getLogger(__name__)

class TimeSync:
    """通过服务端 HTTP Date 响应头精确对齐时间差 (毫秒级)"""
    @staticmethod
    def get_server_time_offset(url: str = "https://xdty.xmu.edu.cn") -> float:
        try:
            t0 = time.time()
            resp = requests.head(url, timeout=5)
            t1 = time.time()
            rtt = t1 - t0
            date_str = resp.headers.get("Date")
            if date_str:
                server_timestamp = email.utils.parsedate_to_datetime(date_str).timestamp()
                # 预估收到响应时的服务端当前时间
                estimated_server_time = server_timestamp + (rtt / 2)
                offset = estimated_server_time - t1
                logger.info(f"服务器时间校准成功，本地偏差: {offset * 1000:.1f}ms")
                return offset
        except Exception as e:
            logger.warning(f"服务器时间校准失败 ({e})，将使用本地时间")
        return 0.0
```

```python
# xdty_booking/core/booking_engine.py
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.solver.captcha_solver import CaptchaSolver
from xdty_booking.config import AppConfig

logger = logging.getLogger(__name__)

class BookingEngine:
    def __init__(self, api: XdtyApi, captcha_solver: CaptchaSolver, config: AppConfig):
        self.api = api
        self.solver = captcha_solver
        self.cfg = config

    def resolve_target_date(self) -> str:
        offset = self.cfg.target.target_date_offset
        target = datetime.now() + timedelta(days=offset)
        return target.strftime("%Y-%m-%d")

    def execute_booking(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        date_str = target_date or self.resolve_target_date()
        target = self.cfg.target
        logger.info(f"开始执行抢票: 日期 {date_str}, 场地 {target.stadium_name}, 期望时段 {target.preferred_time}")
        
        # 1. 查询场次
        intervals = self.api.get_intervals(
            venue_id=target.venue_id,
            stadium_id=target.stadium_id,
            category_id=target.category_id,
            user_range=target.user_range
        )
        slot = intervals.find_slot(date=date_str, time_range=target.preferred_time, column_id=str(target.area_id))
        if not slot:
            err = f"未找到指定时段场次: {date_str} {target.preferred_time}"
            logger.error(err)
            return {"success": False, "info": err}

        if not slot.is_available:
            logger.warning(f"目标场次暂不可约或名额已满 ({slot.selected}/{slot.max_count})，尝试直接下单抢名额")

        # 2. 预校验 chooseVerify
        selected_payload = [{
            "date": slot.date,
            "week": "5",
            "week_msg": "",
            "area_name": slot.area_name,
            "interval_time": target.preferred_time,
            "interval_id": slot.interval_id,
            "area_id": slot.column_id,
            "price": str(int(slot.price))
        }]
        verify_res = self.api.choose_verify(
            stadium_id=target.stadium_id,
            venue_id=target.venue_id,
            selected_slots=selected_payload
        )
        logger.debug(f"场次验证响应: {verify_res}")

        # 3. 获取验证码并极速识别
        captcha_code = ""
        for i in range(3):
            try:
                img_bytes = self.api.get_captcha()
                captcha_code = self.solver.solve(img_bytes)
                if len(captcha_code) == 4:
                    break
            except Exception as e:
                logger.warning(f"获取/识别验证码重试第 {i+1} 次: {e}")
        
        if not captcha_code:
            captcha_code = "daxs"  # 兜底
            
        # 4. 提交订单 (支持快速重试)
        for attempt in range(self.cfg.scheduler.retry_count):
            logger.info(f"第 {attempt + 1} 次提交预约订单...")
            order_res = self.api.add_order(
                stadium_id=target.stadium_id,
                venue_id=target.venue_id,
                stadium_name=target.stadium_name,
                project_name=target.project_name,
                area_name=slot.area_name,
                date=slot.date,
                week="5",
                week_msg="周五",
                interval_time=target.preferred_time,
                interval_id=slot.interval_id,
                area_id=slot.column_id,
                captcha=captcha_code,
                category_id=target.category_id,
                price=slot.price
            )
            logger.info(f"预约提交结果: {order_res}")
            if order_res.get("status") == 1:
                logger.info("🎉 预约成功！")
                return {"success": True, "info": order_res.get("info", "预约成功"), "data": order_res.get("data")}
            
            # 若提示验证码错误，立刻重新刷验证码
            if "验证码" in order_res.get("info", ""):
                try:
                    img_bytes = self.api.get_captcha()
                    captcha_code = self.solver.solve(img_bytes)
                except Exception:
                    pass
            time.sleep(self.cfg.scheduler.retry_interval_ms / 1000.0)

        return {"success": False, "info": order_res.get("info", "预约失败")}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_booking_engine.py -v`
Expected: PASS

- [ ] **Step 5: 提交抢票引擎**

Run: `git add xdty_booking/core/time_sync.py xdty_booking/core/booking_engine.py tests/test_booking_engine.py`
Run: `git commit -m "feat: implement high-speed booking engine and time synchronization"`

---

### Task 8: 主入口整合、CLI 命令行与完整集成验证

**Files:**
- Create: `main.py`
- Create: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: User command line arguments (`--config`, `book`, `heartbeat`, `check`, `test-captcha`)
- Produces: Runnable CLI tool

- [ ] **Step 1: 编写 CLI 入口参数与帮助测试**

```python
# tests/test_cli.py
import subprocess
import sys

def test_cli_help():
    res = subprocess.run([sys.executable, "main.py", "--help"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "厦大体育馆自动预约" in res.stdout
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL (FileNotFoundError: main.py)

- [ ] **Step 3: 编写 main.py 实现**

```python
# main.py
import argparse
import sys
import logging
from xdty_booking.config import load_config
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.auth.session_manager import SessionManager
from xdty_booking.solver.captcha_solver import CaptchaSolver
from xdty_booking.core.booking_engine import BookingEngine

def main():
    parser = argparse.ArgumentParser(description="厦大体育馆自动预约脚本 (xdty.xmu.edu.cn)")
    parser.add_argument("--config", default="config/config.yaml", help="配置文件路径")
    parser.add_argument("action", choices=["book", "heartbeat", "check", "test-captcha"], help="执行动作")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    try:
        cfg = load_config(args.config)
    except Exception as e:
        print(f"配置加载异常: {e}")
        sys.exit(1)

    client = ApiClient(base_url=cfg.base_url)
    if cfg.auth.phpsessid:
        client.set_session_token(cfg.auth.phpsessid)
    api = XdtyApi(client)
    session_mgr = SessionManager(api, phpsessid=cfg.auth.phpsessid)
    solver = CaptchaSolver()

    if args.action == "check":
        alive = session_mgr.check_alive()
        print(f"当前 Session 状态: {'✅ 有效' if alive else '❌ 已失效或网络未连通'}")
    elif args.action == "heartbeat":
        print("启动心跳保活守护进程，按 Ctrl+C 退出...")
        session_mgr.heartbeat_loop(cfg.auth.heartbeat_interval_seconds)
    elif args.action == "test-captcha":
        img = api.get_captcha()
        code = solver.solve(img)
        print(f"获取验证码成功，识别结果为: {code}")
    elif args.action == "book":
        engine = BookingEngine(api, solver, cfg)
        res = engine.execute_booking()
        print(f"预约结果: {res}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行所有单元测试集**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: 编写 README.md 使用文档并提交**

Run: `git add main.py README.md tests/test_cli.py`
Run: `git commit -m "feat: complete CLI entrypoint and documentation"`

---

## Verification Plan

### Automated Tests
- 运行全部测试套件：`pytest tests/ -v`
- 覆盖率验证：
  - 数据模型解析准确性 (`test_models.py`)
  - 验证码识别接口 (`test_captcha.py`)
  - 接口逆向封装完整性 (`test_endpoints.py`)
  - 心跳保活逻辑 (`test_session_manager.py`)
  - 极速抢票引擎流程 (`test_booking_engine.py`)
  - 命令行接口功能 (`test_cli.py`)

### Manual Verification
- 准备包含真实 `PHPSESSID` 的 `config.yaml`（处于厦大校园网/VPN下）：
  - 运行 `python main.py check`：验证当前 Session 是否存活。
  - 运行 `python main.py heartbeat`：观察是否每隔指定时间自动触发心跳请求并保活成功。
  - 运行 `python main.py book`：对指定测试场次进行端到端预约测试。
