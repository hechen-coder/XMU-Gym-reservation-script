import http.server
import json
import logging
import os
import socketserver
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

# 加入项目根目录导入支持
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from cas_qr_login.cas_client import CasQrLoginClient
from xdty_booking.config import save_phpsessid, save_auth_params, load_config

logger = logging.getLogger("CasQrServer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 全局共享状态
state_lock = threading.Lock()
cas_client = CasQrLoginClient()
login_result = None
is_logging_in = False
has_login_failed = False

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>厦门大学统一身份认证 · 扫码登录探究平台</title>
    <style>
        :root {
            --primary: #0f4c81;
            --primary-light: #1976d2;
            --accent: #d4af37;
            --success: #2e7d32;
            --bg-gradient: linear-gradient(135deg, #0d1b2a 0%, #1b263b 50%, #293241 100%);
            --card-bg: rgba(255, 255, 255, 0.96);
        }
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
        }
        body {
            min-height: 100vh;
            background: var(--bg-gradient);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            color: #333;
        }
        .container {
            width: 100%;
            max-width: 650px;
            background: var(--card-bg);
            border-radius: 20px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
            overflow: hidden;
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            transition: all 0.3s ease;
        }
        .header {
            background: linear-gradient(135deg, var(--primary) 0%, #002244 100%);
            color: white;
            padding: 26px 30px;
            text-align: center;
            border-bottom: 4px solid var(--accent);
        }
        .header h1 {
            font-size: 22px;
            font-weight: 700;
            letter-spacing: 1px;
            margin-bottom: 6px;
        }
        .header p {
            font-size: 13px;
            opacity: 0.85;
        }
        .content {
            padding: 32px 30px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .qr-box {
            position: relative;
            width: 250px;
            height: 250px;
            background: #ffffff;
            border: 2px solid #e0e6ed;
            border-radius: 16px;
            padding: 12px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.06);
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 20px;
        }
        .qr-box img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            border-radius: 8px;
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 18px;
            border-radius: 30px;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 22px;
            background: #eef2f6;
            color: #475569;
            transition: all 0.3s;
        }
        .status-badge.scanning {
            background: #e0f2fe;
            color: #0369a1;
        }
        .status-badge.confirming {
            background: #fef3c7;
            color: #b45309;
        }
        .status-badge.success {
            background: #dcfce7;
            color: #15803d;
        }
        .status-badge.expired {
            background: #fee2e2;
            color: #b91c1c;
        }
        .pulse-dot {
            width: 9px;
            height: 9px;
            border-radius: 50%;
            background: currentColor;
            display: inline-block;
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
            0% { transform: scale(0.8); opacity: 0.5; }
            50% { transform: scale(1.2); opacity: 1; }
            100% { transform: scale(0.8); opacity: 0.5; }
        }
        .tips {
            font-size: 13px;
            color: #64748b;
            text-align: center;
            line-height: 1.6;
            max-width: 480px;
        }
        .refresh-btn {
            margin-top: 15px;
            padding: 8px 18px;
            background: #f1f5f9;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            font-size: 13px;
            color: #334155;
            cursor: pointer;
            transition: all 0.2s;
        }
        .refresh-btn:hover {
            background: #e2e8f0;
        }
        .result-panel {
            width: 100%;
            margin-top: 15px;
            display: none;
            animation: fadeIn 0.4s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .token-card {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
        }
        .token-title {
            font-size: 12px;
            color: #64748b;
            font-weight: 600;
            margin-bottom: 6px;
            text-transform: uppercase;
        }
        .token-value-box {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            padding: 8px 12px;
            font-family: Consolas, Monaco, monospace;
            font-size: 14px;
            color: #0f172a;
            word-break: break-all;
        }
        .copy-btn {
            margin-left: 10px;
            padding: 5px 12px;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 12px;
            cursor: pointer;
            white-space: nowrap;
        }
        .copy-btn:hover {
            background: var(--primary-light);
        }
        .params-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            margin-top: 10px;
        }
        .params-table td {
            padding: 6px 8px;
            border-bottom: 1px solid #e2e8f0;
        }
        .params-table td:first-child {
            font-weight: 600;
            color: #475569;
            width: 32%;
        }
        .params-table td:last-child {
            font-family: Consolas, monospace;
            color: #0f172a;
            word-break: break-all;
        }
        .save-btn {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 700;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
            transition: all 0.2s;
            margin-top: 10px;
        }
        .save-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(16, 185, 129, 0.4);
        }
        .toast {
            position: fixed;
            bottom: 25px;
            left: 50%;
            transform: translateX(-50%);
            background: #1e293b;
            color: white;
            padding: 10px 22px;
            border-radius: 30px;
            font-size: 13px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.3);
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s;
            z-index: 999;
        }
        .toast.show {
            opacity: 1;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>厦门大学统一身份认证</h1>
            <p>纯 Python 模拟企业微信扫码登录 · 凭证自动提取闭环</p>
        </div>
        <div class="content">
            <!-- 二维码区 -->
            <div class="qr-box" id="qrBox">
                <img id="qrImg" src="" alt="二维码加载中...">
            </div>

            <!-- 状态胶囊 -->
            <div class="status-badge scanning" id="statusBadge">
                <span class="pulse-dot"></span>
                <span id="statusText">正在拉取登录二维码...</span>
            </div>

            <p class="tips" id="instructionTip">
                请打开手机上的 <strong>企业微信 APP</strong>，点击右上角【+】→【扫一扫】扫描上方二维码。<br>
                扫码后请在手机上点击<strong>【确认登录】</strong>，系统将自动完成票据交换与 Token 提取。
            </p>

            <button class="refresh-btn" id="refreshBtn" onclick="refreshQr()" style="display: none;">
                🔄 刷新二维码
            </button>

            <!-- 成功结果区 -->
            <div class="result-panel" id="resultPanel">
                <div class="token-card">
                    <div class="token-title">🎉 成功换取最新 PHPSESSID</div>
                    <div class="token-value-box">
                        <span id="phpsessidVal">---</span>
                        <button class="copy-btn" onclick="copyToken()">复制</button>
                    </div>
                </div>

                <div class="token-card">
                    <div class="token-title">📋 嗅探到的长效 auth_params 授权参数</div>
                    <table class="params-table" id="paramsTable">
                        <tbody></tbody>
                    </table>
                </div>

                <div style="display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap;">
                    <button class="save-btn" id="saveBtn" onclick="saveToConfig()" style="flex: 1; margin-top: 0;">
                        💾 持久化至 config.yaml
                    </button>
                    <a href="/dashboard" class="save-btn" id="enterBtn" style="flex: 1; margin-top: 0; text-align: center; text-decoration: none; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);">
                        🏋️ 进入体育馆查询与预约大厅 →
                    </a>
                </div>
            </div>
        </div>
    </div>

    <div class="toast" id="toast"></div>

    <script>
        let pollTimer = null;
        let isCompleted = false;

        function showToast(msg) {
            const t = document.getElementById("toast");
            t.innerText = msg;
            t.classList.add("show");
            setTimeout(() => t.classList.remove("show"), 2500);
        }

        async function initQr() {
            isCompleted = false;
            document.getElementById("resultPanel").style.display = "none";
            document.getElementById("qrBox").style.display = "flex";
            document.getElementById("instructionTip").style.display = "block";
            document.getElementById("refreshBtn").style.display = "none";
            updateStatus("scanning", "正在向统一认证中心申请 UUID...");

            try {
                const res = await fetch("/api/qr");
                const data = await res.json();
                if (data.success) {
                    document.getElementById("qrImg").src = data.qr_image;
                    updateStatus("scanning", "等待手机企业微信扫码...");
                    startPolling();
                } else {
                    updateStatus("expired", "初始化失败: " + (data.error || "未知错误"));
                    document.getElementById("refreshBtn").style.display = "inline-block";
                }
            } catch (err) {
                updateStatus("expired", "连接服务器异常: " + err.message);
                document.getElementById("refreshBtn").style.display = "inline-block";
            }
        }

        function updateStatus(type, text) {
            const b = document.getElementById("statusBadge");
            b.className = "status-badge " + type;
            document.getElementById("statusText").innerText = text;
        }

        function startPolling() {
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(async () => {
                if (isCompleted) {
                    clearInterval(pollTimer);
                    return;
                }
                try {
                    const res = await fetch("/api/status");
                    const data = await res.json();

                    if (data.code === "0") {
                        updateStatus("scanning", data.desc);
                    } else if (data.code === "2") {
                        // 2: 手机已扫码，等待用户在手机点击确认
                        updateStatus("confirming", data.desc);
                    } else if (data.code === "1" || data.logged_in) {
                        // 1: 手机端已确认授权
                        if (data.logged_in && data.data) {
                            handleSuccess(data.data);
                        } else {
                            updateStatus("success", data.desc || "授权成功！正在换取 Token...");
                        }
                    } else if (data.code === "3") {
                        updateStatus("expired", "二维码已过期失效");
                        clearInterval(pollTimer);
                        document.getElementById("refreshBtn").style.display = "inline-block";
                    } else if (data.code === "error") {
                        updateStatus("expired", data.desc);
                        clearInterval(pollTimer);
                        document.getElementById("refreshBtn").style.display = "inline-block";
                    }
                } catch (e) {
                    console.error("轮询异常:", e);
                }
            }, 1200);
        }

        function handleSuccess(resData) {
            isCompleted = true;
            clearInterval(pollTimer);
            updateStatus("success", "🎉 登录成功！所有凭据已成功提取与验证");
            
            document.getElementById("qrBox").style.display = "none";
            document.getElementById("instructionTip").style.display = "none";
            document.getElementById("refreshBtn").style.display = "none";

            document.getElementById("phpsessidVal").innerText = resData.phpsessid || "未获取";

            // 填充表格
            const tbody = document.querySelector("#paramsTable tbody");
            tbody.innerHTML = "";
            const p = resData.auth_params || {};
            
            const fieldLabels = {
                "student_num": "学号 (student_num)",
                "card_id": "一卡通号 (card_id)",
                "uid": "用户 ID (uid)",
                "token": "长效 Token",
                "sign": "校验签名 (sign)",
                "school_id": "高校编号 (school_id)",
                "login_type": "登录类型 (login_type)",
                "timestamp": "签发时间戳"
            };

            for (const [key, label] of Object.entries(fieldLabels)) {
                if (p[key]) {
                    const row = document.createElement("tr");
                    row.innerHTML = `<td>${label}</td><td>${p[key]}</td>`;
                    tbody.appendChild(row);
                }
            }

            // 存活状态
            if (resData.user_info) {
                const row = document.createElement("tr");
                row.innerHTML = `<td>会话在线存活探测</td><td style="color: #10b981; font-weight: bold;">✅ ${resData.user_info.status}</td>`;
                tbody.appendChild(row);
            }

            document.getElementById("resultPanel").style.display = "block";
            showToast("🎉 登录成功！凭据已捕获");

            // 自动保存配置
            setTimeout(saveToConfig, 300);
        }

        function copyToken() {
            const val = document.getElementById("phpsessidVal").innerText;
            navigator.clipboard.writeText(val).then(() => {
                showToast("✅ PHPSESSID 已复制到剪贴板！");
            });
        }

        async function saveToConfig() {
            const btn = document.getElementById("saveBtn");
            btn.disabled = true;
            btn.innerText = "⏳ 正在写入配置文件...";

            try {
                const res = await fetch("/api/save_config", { method: "POST" });
                const d = await res.json();
                if (d.success) {
                    showToast("💾 已成功写入 config/config.yaml！");
                    btn.innerText = "✅ 已成功持久化至配置文件";
                    btn.style.background = "#059669";
                } else {
                    showToast("❌ 写入失败: " + d.error);
                    btn.disabled = false;
                    btn.innerText = "💾 重试保存到 config.yaml";
                }
            } catch (err) {
                showToast("❌ 保存异常: " + err.message);
                btn.disabled = false;
                btn.innerText = "💾 重试保存到 config.yaml";
            }
        }

        function refreshQr() {
            initQr();
        }

        window.onload = initQr;
    </script>
</body>
</html>
"""

class CasQrRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # 简化终端访问日志
        pass

    def do_GET(self):
        global cas_client, login_result, is_logging_in, has_login_failed
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))

        elif path == "/api/qr":
            with state_lock:
                try:
                    cas_client = CasQrLoginClient()
                    login_result = None
                    is_logging_in = False
                    has_login_failed = False
                    uuid, _ = cas_client.init_qr_session()
                    b64_img = cas_client.get_qr_image_base64()
                    
                    data = {
                        "success": True,
                        "uuid": uuid,
                        "qr_image": b64_img
                    }
                except Exception as e:
                    logger.error(f"初始化二维码失败: {e}", exc_info=True)
                    data = {"success": False, "error": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))

        elif path == "/api/status":
            with state_lock:
                if login_result:
                    data = {
                        "code": "1",
                        "desc": "登录成功！",
                        "logged_in": True,
                        "data": login_result
                    }
                elif has_login_failed:
                    data = {
                        "code": "error",
                        "desc": "凭证置换异常，请点击下方按钮刷新二维码重新扫码",
                        "logged_in": False,
                        "data": None
                    }
                else:
                    code, desc = cas_client.check_status()
                    logged_in = False

                    # 只有手机端点击了【确认登录】(code == "1") 时，才触发后台表单提交与凭据换发！
                    # code == "2" 时表示已扫码但手机端尚未确认，不可提前提交！
                    if code == "1" and not is_logging_in:
                        is_logging_in = True
                        logger.info("🎯 检测到手机端扫码确认授权完成 (code=1)，开始触发 CAS 票据提交与 Token 置换...")
                        try:
                            res = cas_client.exchange_and_login()
                            login_result = res
                            logged_in = True
                        except Exception as e:
                            logger.error(f"换发登录凭据异常: {e}", exc_info=True)
                            login_result = None
                            has_login_failed = True
                            desc = f"凭据换发异常: {e}"

                    data = {
                        "code": code,
                        "desc": desc,
                        "logged_in": logged_in,
                        "data": login_result
                    }

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))

        elif path == "/dashboard" or path == "/gym":
            from xdty_booking.web.server import query_gym_status
            from xdty_booking.web.template import render_dashboard
            config_file = os.path.join(PROJECT_ROOT, "config", "config.yaml")
            try:
                data = query_gym_status(config_file)
                html = render_dashboard(data)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            except Exception as e:
                logger.error(f"加载预约页面异常: {e}")
                self.send_error(500, f"Error: {e}")

        elif path.startswith("/api/book"):
            from xdty_booking.web.server import book_gym_slot
            params = parse_qs(parsed.query)
            interval_id = params.get("interval_id", [None])[0]
            date = params.get("date", [None])[0]
            time_slot = params.get("time", [None])[0]
            config_file = os.path.join(PROJECT_ROOT, "config", "config.yaml")
            res = book_gym_slot(interval_id=interval_id, date=date, time_slot=time_slot, config_path=config_file, auto_heal=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))

        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        global cas_client, login_result
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/save_config":
            with state_lock:
                if not login_result or not login_result.get("phpsessid"):
                    data = {"success": False, "error": "当前尚未成功登录，无有效凭据"}
                else:
                    config_file = os.path.join(PROJECT_ROOT, "config", "config.yaml")
                    local_config_file = os.path.join(CURRENT_DIR, "config.yaml")
                    try:
                        phpsessid = login_result.get("phpsessid")
                        auth_params = login_result.get("auth_params", {})

                        if os.path.exists(config_file):
                            if phpsessid:
                                save_phpsessid(config_file, phpsessid)
                            if auth_params:
                                save_auth_params(config_file, auth_params)
                            logger.info(f"💾 凭据已成功持久化回写至主配置: {config_file}")

                        # 同时也写一份本地 config.yaml
                        lines = [
                            "# 厦大统一身份认证 · 自动生成凭证备份\n",
                            f"phpsessid: \"{phpsessid}\"\n",
                            "auth_params:\n"
                        ]
                        for k, v in (auth_params or {}).items():
                            lines.append(f"  {k}: \"{v}\"\n")
                        with open(local_config_file, "w", encoding="utf-8") as f:
                            f.writelines(lines)
                        logger.info(f"💾 凭据已成功持久化回写至模块配置: {local_config_file}")

                        data = {"success": True, "message": "配置保存成功"}
                    except Exception as e:
                        logger.error(f"写入配置文件失败: {e}")
                        data = {"success": False, "error": str(e)}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

def start_cas_qr_server(port: int = 8899) -> http.server.HTTPServer:
    """启动扫码认证 Web 服务"""
    server_address = ("127.0.0.1", port)
    
    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    httpd = ReusableTCPServer(server_address, CasQrRequestHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    logger.info(f"🚀 CAS 扫码登录服务端已就绪: http://127.0.0.1:{port}")
    return httpd
