# 厦大统一身份认证 · 纯 Python 企业微信扫码登录模块

> [!TIP]
> 本模块的架构设计、302 重定向拦截原理与全套时序交互已全面并入项目白皮书：  
> 👉 **[系统执行全流程技术文档 - 流程 9：企业微信 CAS 扫码直通登录全流程](../docs/系统执行全流程技术文档.md#9-企业微信-cas-扫码直通登录全流程-cas_qr_login)**

本项目实现了**彻底脱离微信 PC 客户端**的纯代码扫码登录方案：
1. 直接与厦门大学统一身份认证中心 (`ids.xmu.edu.cn` CAS / IDS) 建立会话；
2. 拉取官方二维码并在现代化 Web 界面与控制台中呈现；
3. 用户使用手机端企业微信扫码并点击确认；
4. Python 脚本自动捕获 302 重定向流，拦截并换取 Service Ticket (ST)；
5. 向体育馆后台完成验票，提取全套长效凭据（`token`、`sign`、`uid`、`card_id`、`student_num`）；
6. 自动调用 `checkLogin` 接口换发最新 `PHPSESSID`，并完成实机存活校验；
7. 支持在 Web 界面上一键持久化回写至 `config/config.yaml`。

---

## 启动方式

在项目根目录下执行以下命令即可启动：

```bash
python cas_qr_login/run_login.py
```

终端将自动启动本地 Web 服务（默认 `http://127.0.0.1:8899`）并自动弹出浏览器。

---

## 核心接口说明

- **`CasQrLoginClient` (`cas_client.py`)**：
  - `init_qr_session()`：初始化会话，生成 `uuid`，获取二维码二进制图片；
  - `get_qr_image_base64()`：将二维码转换为 Base64 字符串供 Web 前端渲染；
  - `check_status()`：向 CAS 轮询扫码状态（0: 等待扫码, 1: 已扫码待确认, 2: 已授权, 3: 过期）；
  - `exchange_and_login()`：提交表单，跟随 302 重定向链，提取 `auth_params` 并换取激活的 `PHPSESSID`。

- **`server.py`**：
  - 本地轻量级 HTTP 服务，提供响应式现代化扫码看板，支持实时状态流转、凭证查看、一键复制与配置持久化保存。
