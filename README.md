# 厦大体育馆自动预约系统 (Python)

基于对微信小程序及 H5 Webview (`xdty.xmu.edu.cn`) 预约流程网络抓包数据的完整逆向，本项目提供了一套工业级的自动化预约与准点抢票解决方案。

实现了《预约请求方案.md》中的核心需求：
- **方案 1：Session 心跳保活机制**：定时探测并向服务端发送轻量级请求，防止 `PHPSESSID` 超时失效。
- **方案 2：Windows PC 微信静默唤醒**：在开机/云服务器无人值守状态下，支持定时唤醒小程序。
- **离线验证码极速识别 (OCR)**：针对下单所需的 4 位图形验证码，集成极速离线 OCR，识别耗时 ~10ms，支持识别错误秒级重试。
- **高精度毫秒级定时抢票引擎**：利用 HTTP Date 响应头精确校准本地与服务端时间差，支持提前探测、毫秒级准点提交与并发重试。

---

## 目录结构

```
.
├── config/
│   └── config.example.yaml     # 配置文件示例（场馆、时段、PHPSESSID、调度参数）
├── xdty_booking/
│   ├── api/                    # 接口封装与网络客户端
│   │   ├── client.py           # 带有微信 UA、Cookie 管理的 Session 客户端
│   │   └── endpoints.py        # 场次查询、选场校验、验证码、下单、记录接口
│   ├── auth/                   # 认证与保活模块
│   │   ├── session_manager.py  # 方案1：心跳保活守护进程
│   │   └── wechat_harvester.py # 方案2：Windows 微信静默唤醒
│   ├── core/                   # 业务模型与抢票引擎
│   │   ├── models.py           # 场地与时间段数据模型
│   │   ├── time_sync.py        # 服务端时间差校准与毫秒级等待
│   │   └── booking_engine.py   # 极速抢票执行流程
│   ├── solver/                 # 验证码识别模块
│   │   └── captcha_solver.py   # 4位图形验证码本地识别
│   ├── utils/
│   │   └── logger.py           # 统一日志格式化
│   └── config.py               # 配置读取与解析
├── tests/                      # 完整单元测试集 (23项全绿)
├── main.py                     # CLI 主入口
├── requirements.txt            # Python 依赖清单
└── 预约请求方案.md              # 原始方案需求
```

---

## 快速上手指南

### 1. 安装依赖

确保本机环境为 Python 3.8+，执行：

```bash
pip install -r requirements.txt
```

*(可选)* 若需启用完全自动化的验证码离线高精度识别，安装 `ddddocr`：
```bash
pip install ddddocr
```

### 2. 配置参数

复制示例配置文件为正式配置：

```bash
cp config/config.example.yaml config/config.yaml
```

编辑 `config/config.yaml`，填入你的配置信息：
```yaml
# 认证与保活配置
auth:
  phpsessid: "在此填入你的有效 PHPSESSID"
  heartbeat_interval_seconds: 300 # 每5分钟发送一次心跳保活

# 目标场馆与时段 (以翔安校区健身房为例)
target:
  stadium_id: 16                # 场馆 ID
  venue_id: 14                  # 场地 ID
  category_id: 8                # 分类 ID (8 为健身房)
  stadium_name: "翔安校区健身房"
  project_name: "健身房"
  area_name: "爱秋体育馆健身房"
  area_id: 67
  preferred_time: "19:30-21:00"  # 目标时段
  target_date_offset: 1         # 0 为预约今天，1 为预约明天

# 定时抢票调度
scheduler:
  target_time: "08:00:00"       # 抢票开始时间
  advance_ms: 200               # 提前探测毫秒数 (用于抵消网络延迟)
  retry_count: 5                # 失败重试次数
  retry_interval_ms: 150        # 重试间隔 (毫秒)
```

> **注意**：厦大体育系统服务器 (`xdty.xmu.edu.cn`) 需在**校园网**或开启**厦大 WebVPN / EasyConnect** 的环境下连通。

---

## 常用命令

### 1. 验证当前 Session 是否有效
```bash
python main.py check
```

### 2. 启动心跳守护进程 (方案 1，Session 永不过期)
挂起在后台或前台终端运行，按设定的周期持续保活：
```bash
python main.py heartbeat
```

### 3. 立即执行一次预约抢票 (即时测试)
```bash
python main.py book
```

### 4. 启动高精度定时自动抢票模式
启动后，脚本会自动校准服务端毫秒级时差，并在后台启动心跳保活。一旦到达设定的目标时刻（如 `08:00:00`），将以毫秒级精度提前探测并极速突发提交：
```bash
python main.py schedule
```

### 5. 测试验证码识别
拉取验证码图片并检验识别速度与准确率：
```bash
python main.py test-captcha
```

### 6. 测试唤醒 Windows 微信小程序 (方案 2)
```bash
python main.py launch-wechat
```

---

## 运行自动化测试

项目具备高覆盖率的自动化测试集，可完全脱网离线运行验证：

```bash
pytest tests/ -v
```
所有 23 项测试均已通过，覆盖模型解析、接口构造、验证码容错、会话保活以及定时调度逻辑。
