# 厦大体育馆自动预约系统架构重构与多场景全功能落地计划

本项目将针对用户提出的四大核心业务场景（**早 7 点准点抢次日名额+就近降级**、**8080 端口 Web 实时查询一键预约+过期自愈**、**满票持续监听秒杀捡漏**、**抢票成功即时通知**），以及整体代码架构的模块化整合需求，制定一套高可用、高内聚、易扩展的落地方案。

---

## 一、 用户关注要点与决策设计

> [!IMPORTANT]
> **1. 早上 7:00 准点抢票与“就近时段”策略**
> - 厦大体育系统每天早 7 点刷新开放次日预约名额（`target_date_offset: 1`）。
> - 若首选时段（如 `19:30-21:00`）已满或名额不足，算法将以**时差绝对值升序**（`|候选开始时间 - 首选开始时间|`）动态计算同一天内所有有余量（`remaining > 0`）的时段，按距离最近顺序自动降级并秒速下单，确保绝不空手而归。
> - 在抢票准点到达前（如 06:55），系统提前执行心跳与有效性探测，若 `PHPSESSID` 失效，**自动在抢票前调用方案 A（微信小程序代理嗅探）完成更新并持久化**，确保 7 点到达时凭证绝对新鲜有效。

> [!TIP]
> **2. 通知渠道选型建议 (多通道自由配置)**
> - **微信推送（最推荐，PushPlus 或 Server酱）**：无需搭服务器，只需关注公众号填入 Token/SendKey，抢到票后手机微信直接弹出卡片通知，包含场馆、日期、时段、订单号等详细信息。
> - **邮件通知 (SMTP)**：支持 QQ 邮箱、163 邮箱、教育网邮箱等，配置授权码后即发即收。
> - **苹果推送 (Bark)**：iOS 用户专属，毫秒级通知直达锁屏。

---

## 二、 整体架构重构与模块划分

重构前：`main.py` 聚集大量 if-else，`query_gym.py` 孤立且未引入 Session 失效检测与通知，各场景缺乏时段降级与长时间监听自愈。

重构后模块架构：
```
xdty_booking/
├── api/                    # 接口网络层 (client.py, endpoints.py)
├── auth/                   # 认证自愈层 (harvester_service, session_manager, sniffer_proxy...)
├── core/                   # 抢票核心调度层
│   ├── models.py           # 数据模型 (扩展时段距离计算与就近时段推荐)
│   ├── booking_engine.py   # 极速下单与多候选降级逻辑
│   ├── scheduler.py        # 07:00 准点抢票调度引擎 (预热唤醒、毫秒校准、自动自愈、成功通知)
│   └── time_sync.py        # 服务端时间差微秒对齐
├── notify/                 # [新增] 统一通知服务
│   ├── __init__.py
│   ├── notifier.py         # 多通道通知聚合分发器
│   └── channels/           # Email, PushPlus, ServerChan, Bark 各通道实现
├── web/                    # [新增/重构] 8080 Web 服务模块
│   ├── __init__.py
│   ├── server.py           # 轻量 HTTP 服务 (带 Session 失效检测/自动自愈拦截器)
│   └── template.py         # 现代化、自适应的响应式前端界面 (余量进度、一键预约、状态弹窗)
├── solver/                 # 验证码识别层 (captcha_solver.py)
├── utils/                  # 工具层 (logger.py)
├── config.py               # 配置文件加载/注释保留回写 (扩充 scheduler 与 notify)
main.py                     # 统一 CLI 主入口 (命令清晰分发，精简主逻辑)
query_gym.py                # 薄封装兼容入口 (直接调起 xdty_booking.web)
```

---

## 三、 详细实现方案

### 1. 配置扩展 (`xdty_booking/config.py` & `config/config.yaml`)

- **抢票配置扩充 (`scheduler`)**：
  - `target_time: "07:00:00"`（改为 7 点刷新）
  - `fallback_nearest: true`（首选时段满时，自动降级选择最近时段）
  - `pre_check_minutes: 5`（提前 5 分钟预热自检 Session）
- **通知配置新增 (`notify`)**：
  - `enabled: true`
  - `channels: ["pushplus", "email"]`
  - `email`: `smtp_host`, `smtp_port`, `ssl`, `sender`, `password`, `to_addrs`
  - `pushplus`: `token`
  - `serverchan`: `sendkey`
  - `bark`: `server_url`, `device_key`

---

### 2. 核心调度与抢票引擎增强 (`xdty_booking/core/`)

#### (1) 就近时段排序与降级算法 (`core/models.py` & `core/booking_engine.py`)
- 给 `TimeSlotGroup` 与 `IntervalResponse` 增加计算时段距离方法：
  - 将 `"19:30-21:00"` 解析为起始时间分钟数 $19 \times 60 + 30 = 1170$。
  - 对目标日期的所有时段，按 $|t_{candidate} - t_{preferred}|$ 计算时差并升序排序。
- 在 `BookingEngine.execute_booking` 中：
  - 若指定了首选时段且 `fallback_nearest=True`：
    - 首先尝试预约首选时段；
    - 若首选时段名额不足（`remaining == 0`）或预校验 `chooseVerify` 提示人数已满，立即输出警告并切换至最近的备选可用时段，连续尝试提交，直至预约成功或全部无票。

#### (2) 07:00 准点抢票调度服务 (`core/scheduler.py`)
- 计算到明天 07:00:00 的倒计时；
- **提前预热机制**：在目标时间前 `pre_check_minutes` 分钟（如 06:55），自动唤醒后台执行一次 Session 探测；如果已失效，自动触发 `HarvestService` 嗅探获取新凭证，刷新内存并保存至 `config.yaml`；
- 启动心跳线程保持 Session 活跃；
- 准点前毫秒级等待（结合服务端时间偏移校准 `TimeSync` 与 `advance_ms`）；
- 07:00:00 准点发起首选/就近极速下单；
- 预约成功后，自动调用通知引擎推送好消息。

#### (3) 捡漏监听秒杀增强 (`BookingEngine.snipe_booking`)
- 解决长时间监听 Session 过期导致的崩溃退出：
  - 循环探测期间，若捕获到 Session 过期或未登录错误，自动执行自愈流程，重新更新 Session 后无缝继续监听；
  - 增加动态随机微小抖动（如 1.8s~2.5s），防止频繁高频固定请求被 WAF 限制；
  - 一旦监测到空余名额立即秒抢，成功后触发全渠道通知。

---

### 3. 多通道通知模块 (`xdty_booking/notify/`)

- 新建 `xdty_booking/notify/notifier.py`：
  - 统一调用接口：`Notifier.send_booking_success(slot_info, order_res)`
  - 统一调用接口：`Notifier.send_alert(title, message)`
- 实现子通道：
  - **邮件通道 (Email)**：标准 `smtplib` + `email.mime`，支持 SSL/TLS，格式化 HTML 邮件。
  - **PushPlus 通道**：HTTP POST `http://www.pushplus.plus/send`，传入 token、title、content。
  - **Server酱通道**：HTTP POST `https://sctapi.ftqq.com/{sendkey}.send`。
  - **Bark 通道**：HTTP GET/POST 推送至 iOS 客户端。
- 增加 CLI 调试命令：`python main.py test-notify`，方便用户在正式抢票前验证推送是否配置正确。

---

### 4. 8080 Web 实时查询与预约整合 (`xdty_booking/web/`)

- 将原本散落的 `query_gym.py` 逻辑封装为 `xdty_booking/web/server.py`：
  - **Session 失效自动自愈中间件**：在 `GET /`、`GET /api/status`、`POST/GET /api/book` 前后，统一拦截登录失效响应。一旦发现失效且配置开启了自动嗅探，自动在后台拉起方案 A 嗅探更新并自动重试当前操作；
  - **Web 界面现代化升级**：
    - 清晰展示各时段总容量、已约人数、剩余人数进度条；
    - 增加“一键触发凭证自愈”、“状态刷新”按钮；
    - 点击“⚡ 立刻预约”后，异步提交，展示进度动画并在成功后调用系统通知；
- `query_gym.py` 瘦身为兼容入口文件，直接调用模块化代码。

---

### 5. 主入口重构整合 (`main.py`)

将现有杂乱的 CLI 分发重构为清晰的子命令架构：
```bash
python main.py schedule        # 启动 07:00 定时抢票守护 (支持提前自检自愈、就近时段降级、成功通知)
python main.py web [--port]    # 启动 8080 端口 Web 状态监控与一键预约平台 (带 Session 自愈)
python main.py snipe           # 启动捡漏秒杀监听 (或 main.py book --watch，长效保活与自愈)
python main.py book            # 立即单次预约 (支持指定日期/时段/就近降级)
python main.py query           # 终端输出当前场馆余量表格
python main.py check           # 检查当前登录态，失效则自动嗅探自愈
python main.py harvest         # 手动触发微信小程序本地代理嗅探截取
python main.py heartbeat       # 独立心跳守护进程
python main.py test-notify     # 发送一条测试通知，验证邮件或微信配置
python main.py test-captcha    # 验证码识别测试
```

---

## 四、 计划修改与新增的文件清单

| 状态 | 文件路径 | 功能说明 |
| :--- | :--- | :--- |
| **[NEW]** | `xdty_booking/notify/notifier.py` | 统一通知聚合器 (邮件、PushPlus、Server酱、Bark) |
| **[NEW]** | `xdty_booking/web/server.py` | 8080 端口 HTTP 服务端与自动 Session 自愈中间件 |
| **[NEW]** | `xdty_booking/web/template.py` | 响应式 Web 监控与一键预约前端页面 |
| **[NEW]** | `xdty_booking/core/scheduler.py` | 07:00 准点定时抢票、提前预热自愈与调度引擎 |
| **[MODIFY]** | `xdty_booking/core/models.py` | 增加根据时差绝对值排序的就近时段推荐方法 |
| **[MODIFY]** | `xdty_booking/core/booking_engine.py` | 整合就近降级时段预约逻辑、增强版断线自愈捡漏 |
| **[MODIFY]** | `xdty_booking/config.py` | 扩展配置数据类（增加 notify、scheduler 降级与预热参数） |
| **[MODIFY]** | `config/config.yaml` / `.example.yaml` | 增加 07:00:00 目标时间、就近时段开关与通知配置模板 |
| **[MODIFY]** | `main.py` | 全面重构为结构清晰的子命令分发，整合所有场景入口 |
| **[MODIFY]** | `query_gym.py` | 重构为兼容包装器，直接复用 `xdty_booking.web` |
| **[NEW]** | `tests/test_notify.py` | 通知模块单元测试 (Mock 邮件与 Webhook) |
| **[NEW]** | `tests/test_scheduler_and_fallback.py` | 就近时段算法与 07:00 抢票流程测试 |

---

## 五、 验证与测试计划

1. **单元测试回归验证**：
   - 保证原有的 43 项测试 100% 继续通过；
   - 增加 `test_notify.py` 测试邮件及 Webhook 格式化与发送逻辑（离线 Mock）；
   - 增加 `test_scheduler_and_fallback.py` 测试“首选时段满时，就近时段计算与自动尝试降级”算法；
   - 运行 `pytest tests/ -v` 确保全绿通过。

2. **业务场景功能验证**：
   - **就近时段降级测试**：Mock 首选时段已满，验证引擎是否自动按时间差升序尝试并成功约下次近时段；
   - **Session 失效自愈联动测试**：模拟 `phpsessid` 失效，验证 `web` 接口与 `scheduler` 是否能自动触发 `harvest` 闭环；
   - **Web 8080 端口服务测试**：启动服务后测试 `GET /` 页面渲染、`GET /api/status`、`POST /api/book` 接口；
   - **通知测试**：执行 `python main.py test-notify` 验证通知模块接口无异常。
