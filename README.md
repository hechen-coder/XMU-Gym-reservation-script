# 厦大体育馆自动预约系统 (Python)

基于对微信小程序及 H5 Webview (`xdty.xmu.edu.cn`) 预约流程网络抓包数据的完整逆向，本项目提供了一套工业级的全自动化预约与准点抢票解决方案。

---

## 核心特性

- **方案 A：WeChatHarvester + 本地透明轻量代理自动嗅探（全自动静默截取闭环）**：
  - **智能失效探测**：系统启动或执行任何操作前，自动检查 `PHPSESSID` 是否为空或失效；
  - **本地极简嗅探代理**：按需启动后台轻量代理（默认监听 `127.0.0.1:8889`），智能复用本机受信任 CA（如 Reqable 根证书）签发专属 TLS 证书，实现微信小程序无感握手与解密；
  - **Windows 注册表动态切换**：利用 WinINet API 临时切换系统网络代理，无需重启应用；
  - **多策略静默唤醒小程序**：支持窗口激活、桌面快捷方式（`.lnk`）、微信官方 `weixin://launchapplet` 协议及 `WeChatAppEx` 核心进程多级自适应调度（全面兼容微信 4.0 / Weixin NT 与 3.x）；
  - **双向报文嗅探**：无论是冷启动时服务端下发的 `Set-Cookie: PHPSESSID=...`，还是已有会话发起请求携带的 `Cookie: PHPSESSID=...` 均可秒级精准捕获；
  - **安全收尾与配置持久化**：捕获成功的瞬间，**100% 自动还原原始 Windows 系统代理配置**（绝不影响 Clash/VPN 等网络工具），立即终止小程序进程（`WeChatAppEx.exe`），并**无损回写持久化至 `config/config.yaml`**（完整保留原有注释与排版）。
- **方案 1：Session 心跳保活守护进程**：
  - 定时向服务端发送轻量级探测请求，保持 `PHPSESSID` 长期在线不超时；支持在心跳检测到过期时自动调用方案 A 嗅探自愈。
- **高精度毫秒级定时抢票引擎**：
  - 利用 HTTP `Date` 响应头精确校准本地与服务端时间差，支持提前探测（`advance_ms`）、毫秒级准点提交与突发失败重试。
- **捡漏监听秒抢模式 (`--watch`)**：
  - 针对热门场次持续轮询监听，一旦有其他用户退票或放出余量，毫秒级突发锁定并自动完成预约下单。
- **实时场馆余量与空闲查询 (`query`)**：
  - 命令行一键输出目标场馆的开放日期列表、各时段容量（已约/最大）、空闲充裕度及目标时段高亮。
- **离线验证码极速识别 (OCR)**：
  - 集成极速离线 OCR 模型（`ddddocr`），识别耗时 ~10ms，支持验证码拉取与识别异常的秒级重试。

---

## 目录结构

```
.
├── config/
│   ├── config.yaml             # 本地正式配置文件（场馆、时段、凭证、调度参数）
│   └── config.example.yaml     # 配置文件示例模板
├── xdty_booking/
│   ├── api/                    # 接口封装与网络客户端
│   │   ├── client.py           # 带有微信 UA、Cookie 管理的 Session 客户端
│   │   └── endpoints.py        # 场次查询、选场校验、验证码、下单、记录接口
│   ├── auth/                   # 认证、凭证嗅探与保活模块
│   │   ├── cert_generator.py   # 智能自签名/CA复用 TLS 证书生成器
│   │   ├── proxy_manager.py    # Windows WinINet 注册表代理临时切换与安全还原
│   │   ├── sniffer_proxy.py    # 本地轻量级 HTTP/HTTPS 嗅探与透明转发代理
│   │   ├── harvester_service.py# 方案 A 自动化调度编排引擎
│   │   ├── session_manager.py  # 方案 1 心跳保活守护进程
│   │   └── wechat_harvester.py # 微信小程序多策略静默唤醒与进程管理
│   ├── core/                   # 业务模型与抢票引擎
│   │   ├── models.py           # 场地与时间段数据模型
│   │   ├── time_sync.py        # 服务端时间差校准与高精度等待
│   │   └── booking_engine.py   # 极速抢票与捡漏执行引擎
│   ├── solver/                 # 验证码识别模块
│   │   └── captcha_solver.py   # 4 位图形验证码本地离线识别
│   ├── utils/
│   │   └── logger.py           # 统一终端与文件安全日志
│   └── config.py               # 配置读取与注释保留回写
├── tests/                      # 完整单元测试集 (43 项全绿通过)
├── main.py                     # 统一 CLI 主入口
├── requirements.txt            # Python 依赖清单
└── 预约请求方案.md              # 逆向分析与方案规划文档
```

---

## 快速上手指南

### 1. 安装依赖

确保本机环境为 Python 3.8+，执行：

```bash
pip install -r requirements.txt
```

*(推荐)* 若需启用完全自动化的验证码离线高精度识别，安装 `ddddocr`：
```bash
pip install ddddocr
```

### 2. 配置参数

复制示例配置文件为正式配置：

```bash
cp config/config.example.yaml config/config.yaml
```

编辑 `config/config.yaml`，填入你的预约目标：

```yaml
# 基础服务地址
base_url: "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test"

# 认证与保活配置 (方案 A 与 方案 1)
auth:
  # 当前有效 PHPSESSID (若开启 auto_harvest_enabled，可留空由程序自动嗅探填入)
  phpsessid: ""
  # 用户 UID (可选，留空则自动通过预约历史接口获取)
  uid: "1073507"
  # 心跳保活周期 (秒)，默认 300 秒 (5分钟)
  heartbeat_interval_seconds: 300
  # 是否开启全自动静默唤醒与本地嗅探 (方案 A，推荐开启)
  auto_harvest_enabled: true
  wechat_appid: "wx81a2b2fa90759cb7"
  # 可选：手动指定微信小程序核心进程路径 (留空则自动多级扫描)
  wechat_appex_path: ""

# 预约目标场地配置 (以翔安校区健身房为例)
target:
  stadium_id: 16                # 场馆 ID
  venue_id: 14                  # 场地 ID
  category_id: 8                # 分类 ID (8 为健身房)
  stadium_name: "翔安校区健身房"
  project_name: "健身房"
  area_name: "爱秋体育馆健身房"
  area_id: 67
  user_range: "[67]"
  preferred_time: "19:30-21:00"  # 目标时段
  target_date_offset: 1         # 0 为预约今天，1 为预约明天

# 定时抢票与调度配置
scheduler:
  target_time: "08:00:00"       # 抢票开始时间 (24小时制)
  advance_ms: 200               # 提前探测毫秒数 (用于抵消网络延迟)
  retry_count: 5                # 失败重试次数
  retry_interval_ms: 150        # 重试间隔 (毫秒)
```

> **网络环境提示**：厦大体育系统服务器 (`xdty.xmu.edu.cn`) 需在**校园网**或开启**厦大 WebVPN / EasyConnect** 的环境下连通。

---

## 常用指令清单

### 1. 手动触发凭证自动嗅探与截获 (方案 A)
一键启动本地嗅探代理，唤醒微信小程序并截获凭证，成功后自动回写 `config.yaml`：
```bash
python main.py harvest [--timeout 30]
```

### 2. 检测 Session 登录态有效性 (支持自动自愈)
若当前 Session 有效，则提示成功；若检测到失效且开启了 `auto_harvest_enabled: true`，将**自动无缝触发方案 A 嗅探自愈**：
```bash
python main.py check
```

### 3. 查询场馆实时空闲与余量状态
直观以表格化格式打印目标场馆所有开放日期、时段余量及目标时段标记：
```bash
python main.py query
```

### 4. 立即执行单次预约 (即时测试抢票)
```bash
python main.py book
```

### 5. 开启捡漏监听秒抢模式 (`--watch`)
不断循环探测目标场次，一旦有人退票放出空位立刻自动秒抢：
```bash
python main.py book --watch [--poll-interval 2.0]
```

### 6. 启动高精度毫秒级准点定时抢票
脚本将自动校准服务器毫秒级时差，后台保持心跳保活；准点时刻到达前（如提前 200ms）毫秒级突发提交抢票：
```bash
python main.py schedule
```

### 7. 启动 Session 心跳保活守护进程 (方案 1)
持续在后台定时保活，Session 永不过期：
```bash
python main.py heartbeat
```

### 8. 测试验证码识别
拉取验证码图片并检验识别速度与准确率：
```bash
python main.py test-captcha
```

### 9. 测试唤醒 Windows PC 微信小程序
```bash
python main.py launch-wechat
```

---

## 自动化测试

项目拥有覆盖完整核心业务流的单元测试集，支持离线脱网运行验证：

```bash
pytest tests/ -v
```

**测试覆盖范围（43 项全绿通过 ✅）**：
- `test_sniffer_and_proxy.py`：自签名/CA复用证书签发、报文双向 Cookie 提取、注册表上下文代理安全切换与还原、Harvest 编排全流程；
- `test_wechat_harvester.py`：进程扫描、多级路径推导、窗口还原激活、桌面快捷方式唤醒、URL 协议唤起、命令行启动；
- `test_config.py`：YAML 规范加载与**注释保留回写**；
- `test_session_manager.py`：心跳守护、失效探测、自动唤醒嗅探自愈；
- `test_booking_engine.py`：极速下单流程、选场校验、捡漏监听模式；
- `test_query.py` & `test_endpoints.py`：接口参数编解码与数据解析；
- `test_captcha.py`：本地验证码识别；
- `test_cli.py`：命令行子命令与参数解析。
