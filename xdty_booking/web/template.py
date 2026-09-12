def render_dashboard(data: dict) -> str:
    """生成现代化美观响应式的健身房实时空闲状态与一键预约仪表板页面"""
    groups = data.get("groups", [])
    stadium_name = data.get("stadium_name", "厦大健身房")
    area_name = data.get("area_name", "")
    query_time = data.get("query_time", "")
    info_msg = data.get("info", "")
    is_session_valid = data.get("session_valid", True)
    has_auth_params = data.get("has_auth_params", False)
    phpsessid_masked = data.get("phpsessid", "")

    if is_session_valid:
        session_badge = f'<span class="status-pill ok">● 登录态有效 {f"({phpsessid_masked})" if phpsessid_masked else ""}</span>'
    else:
        session_badge = f'<span class="status-pill warn">⚠️ 凭证已失效 ({info_msg or "点击自动续登"})</span>'

    rows_html = ""
    for g in groups:
        for s in g.get("slots", []):
            avail = s.get("is_available", False)
            rem = s.get("remaining", 0)
            sel = s.get("selected", 0)
            max_c = s.get("max_count", 0)
            pct = int((sel / max_c * 100) if max_c > 0 else 0)
            
            avail_cls = "avail" if avail else "full"
            if avail:
                badge_text = f"剩余 {rem} 人"
                bar_color = "#10b981" if rem > 10 else "#f59e0b"
            else:
                badge_text = "已约满"
                bar_color = "#ef4444"

            pref_tag = "<span class='pref-tag'>⭐ 设定的目标时段</span>" if g.get("is_preferred") else ""
            date_str = f"{g.get('date')} {g.get('week_name')}"
            time_str = g.get('time_range')
            slot_id = s.get('interval_id')

            rows_html += f"""
            <tr class="slot-row {avail_cls}">
                <td>
                    <div class="date-main">{date_str}</div>
                </td>
                <td>
                    <div class="time-main"><strong>{time_str}</strong> {pref_tag}</div>
                </td>
                <td>
                    <div class="capacity-box">
                        <div class="capacity-text">{sel} / {max_c} ({pct}%)</div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: {pct}%; background: {bar_color};"></div>
                        </div>
                    </div>
                </td>
                <td>
                    <span class="badge {avail_cls}">{badge_text}</span>
                </td>
                <td>
                    <button class="btn-book" onclick="bookSlot('{slot_id}', '{g.get('date')}', '{time_str}')" {'disabled' if not avail else ''}>
                        ⚡ 立刻预约
                    </button>
                </td>
            </tr>
            """

    if not rows_html:
        if not is_session_valid:
            token_tip = '<div style="font-size: 13px; color: #15803d; background: #ecfdf5; border: 1px solid #a7f3d0; padding: 8px 16px; border-radius: 8px; margin-bottom: 16px; display: inline-block;">✨ 系统已就绪长效 Token，可直接点击下方【⚡ 纯 HTTP 自动续登】，无需打开微信，秒级刷新！</div>' if has_auth_params else '<div style="font-size: 13px; color: #64748b; margin-bottom: 16px;">未配置长效 Token，可通过微信小程序嗅探或手动输入</div>'

            rows_html = f'''<tr><td colspan="5" style="text-align: center; color: #dc2626; padding: 36px 20px;">
                <div style="font-size: 17px; font-weight: 700; margin-bottom: 8px;">⚠️ 当前登录凭证已失效 (PHPSESSID 未登录或已过期)</div>
                <div style="font-size: 13px; color: #64748b; margin-bottom: 12px;">{info_msg or "服务端返回: 登录信息失效, 请退出重新登录"}</div>
                {token_tip}
                <div style="display: flex; justify-content: center; gap: 12px; flex-wrap: wrap;">
                    <button class="btn-action btn-success" onclick="reloginSession()" style="padding: 10px 20px; font-size: 14px; font-weight: 700;">
                        ⚡ 一键 HTTP 自动续登 (秒级换票 · 推荐)
                    </button>
                    <button class="btn-action" onclick="harvestSession()" style="padding: 10px 18px; font-size: 14px;">
                        🔑 微信小程序嗅探 (兜底)
                    </button>
                    <button class="btn-action" onclick="setManualToken()" style="padding: 10px 18px; font-size: 14px;">
                        ✏️ 手动输入 Token
                    </button>
                </div>
            </td></tr>'''
        else:
            rows_html = '<tr><td colspan="5" style="text-align: center; color: #94a3b8; padding: 30px;">暂无开放场次数据，请检查网络或系统开放时间</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{stadium_name} - 实时空位监控与极速预约</title>
    <style>
        :root {{
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --success: #10b981;
            --success-hover: #059669;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text-main: #0f172a;
            --text-sub: #64748b;
            --border: #e2e8f0;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: var(--bg);
            color: var(--text-main);
            margin: 0;
            padding: 24px 16px;
        }}
        .container {{
            max-width: 960px;
            margin: 0 auto;
            background: var(--card-bg);
            border-radius: 16px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.01);
            padding: 28px;
            border: 1px solid var(--border);
        }}
        .header {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
            gap: 12px;
        }}
        .title-group h1 {{
            margin: 0 0 6px 0;
            font-size: 24px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .subtitle {{
            color: var(--text-sub);
            font-size: 14px;
            margin: 0;
        }}
        .status-bar {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .status-pill {{
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
        }}
        .status-pill.ok {{ background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }}
        .status-pill.warn {{ background: #fffbeb; color: #92400e; border: 1px solid #fde68a; }}
        .btn-action {{
            background: white;
            border: 1px solid var(--border);
            color: var(--text-main);
            padding: 7px 14px;
            border-radius: 8px;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
            font-weight: 500;
        }}
        .btn-action:hover {{ background: #f1f5f9; border-color: #cbd5e1; }}
        .btn-primary {{
            background: var(--primary);
            color: white;
            border: none;
        }}
        .btn-primary:hover {{ background: var(--primary-hover); }}
        .btn-success {{
            background: #10b981;
            color: white;
            border: 1px solid #059669;
        }}
        .btn-success:hover {{
            background: #059669;
            color: white;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        th {{
            background: #f8fafc;
            color: var(--text-sub);
            font-weight: 600;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 12px 14px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        td {{
            padding: 14px;
            border-bottom: 1px solid var(--border);
            font-size: 14px;
            vertical-align: middle;
        }}
        .slot-row:hover {{
            background: #f8fafc;
        }}
        .slot-row.avail {{
            background: #f0fdf440;
        }}
        .date-main {{ font-weight: 600; color: #334155; }}
        .time-main {{ font-size: 15px; }}
        .pref-tag {{
            background: #fef3c7;
            color: #b45309;
            font-size: 11px;
            padding: 2px 7px;
            border-radius: 4px;
            font-weight: 600;
            margin-left: 6px;
        }}
        .capacity-box {{ width: 140px; }}
        .capacity-text {{ font-size: 12px; color: var(--text-sub); margin-bottom: 4px; }}
        .progress-bar {{
            height: 6px;
            background: #e2e8f0;
            border-radius: 3px;
            overflow: hidden;
        }}
        .progress-fill {{ height: 100%; transition: width 0.3s ease; }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        .badge.avail {{ background: #dcfce7; color: #15803d; }}
        .badge.full {{ background: #fee2e2; color: #b91c1c; }}
        
        .btn-book {{
            background: var(--success);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }}
        .btn-book:hover:not(:disabled) {{
            background: var(--success-hover);
            transform: translateY(-1px);
            box-shadow: 0 4px 6px -1px rgba(16, 185, 129, 0.2);
        }}
        .btn-book:disabled {{
            background: #cbd5e1;
            color: #64748b;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }}
        .footer {{
            margin-top: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 13px;
            color: var(--text-sub);
            padding-top: 16px;
            border-top: 1px solid var(--border);
        }}
        #toast {{
            position: fixed;
            bottom: 24px;
            right: 24px;
            padding: 14px 20px;
            border-radius: 10px;
            background: #1e293b;
            color: white;
            font-size: 14px;
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.2);
            display: none;
            z-index: 1000;
            animation: fadeIn 0.3s;
        }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title-group">
                <h1>🏋️ {stadium_name}</h1>
                <p class="subtitle">{area_name} · 实时数据直连校内系统 · 点击右侧极速锁定下单</p>
            </div>
            <div class="status-bar">
                {session_badge}
                <label style="display: inline-flex; align-items: center; gap: 5px; font-size: 13px; color: var(--text-sub); cursor: pointer; user-select: none;">
                    <input type="checkbox" id="autoRefreshToggle" onchange="toggleAutoRefresh(this.checked)" style="cursor: pointer;">
                    <span>自动刷新(30s)</span>
                </label>
                <button class="btn-action btn-success" onclick="reloginSession()" title="使用长效 Token 发起纯 HTTP checkLogin 换票，无需启动微信，秒级刷新">
                    ⚡ HTTP 自动续登
                </button>
                <button class="btn-action" onclick="harvestSession()" title="拉起微信小程序代理重新抓取 (长效 Token 失效时兜底)">
                    🔑 微信嗅探 (兜底)
                </button>
                <button class="btn-action" onclick="setManualToken()" title="手动粘贴或更新 PHPSESSID">
                    ✏️ 手动输入 Token
                </button>
                <button class="btn-action btn-primary" onclick="location.reload()">
                    🔄 刷新余量
                </button>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>预约日期</th>
                    <th>预约时段</th>
                    <th>已约 / 总名额</th>
                    <th>状态</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <div class="footer">
            <span>最后查询时间: {query_time}</span>
            <div>
                <a href="/api/status" style="color: var(--primary); text-decoration: none; margin-right: 12px;">📊 JSON 接口</a>
                <a href="/api/relogin" style="color: var(--success); text-decoration: none; margin-right: 12px;">⚡ HTTP 续登接口</a>
                <a href="/api/check" style="color: var(--text-sub); text-decoration: none;">🔍 登录态诊断</a>
            </div>
        </div>
    </div>

    <div id="toast"></div>

    <script>
        function showToast(msg, isSuccess = true) {{
            const t = document.getElementById("toast");
            t.innerText = msg;
            t.style.background = isSuccess ? "#065f46" : "#991b1b";
            t.style.display = "block";
            setTimeout(() => {{ t.style.display = "none"; }}, 4000);
        }}

        let autoRefreshInterval = null;
        function toggleAutoRefresh(enable, showNotify = true) {{
            try {{
                localStorage.setItem("xdty_auto_refresh", enable ? "1" : "0");
            }} catch(e) {{}}

            if (autoRefreshInterval) {{
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
            }}
            const chk = document.getElementById("autoRefreshToggle");
            if (chk) chk.checked = enable;

            if (enable) {{
                autoRefreshInterval = setInterval(() => {{
                    location.reload();
                }}, 30000);
                if (showNotify) showToast("已开启 30 秒自动刷新余量与会话保活", true);
            }} else {{
                if (showNotify) showToast("已关闭自动刷新", true);
            }}
        }}

        window.addEventListener("DOMContentLoaded", () => {{
            try {{
                const saved = localStorage.getItem("xdty_auto_refresh");
                if (saved === "1") {{
                    toggleAutoRefresh(true, false);
                }}
            }} catch(e) {{}}
        }});

        function reloginSession() {{
            showToast("⏳ 正在通过 checkLogin 执行纯 HTTP 自动续登 (无需打开微信)...", true);
            fetch('/api/relogin')
                .then(r => r.json())
                .then(data => {{
                    if (data.success) {{
                        showToast(data.info || "🎉 纯 HTTP 自动续登成功！最新 Session 已生效", true);
                        setTimeout(() => location.reload(), 900);
                    }} else {{
                        alert(data.info || "❌ checkLogin 纯 HTTP 续登未成功，可能长效 Token 已过期，请尝试微信小程序嗅探兜底");
                    }}
                }})
                .catch(e => alert("续登请求出错: " + e));
        }}

        function setManualToken() {{
            const token = prompt("请输入最新的 PHPSESSID 字符串 (如 0e3af18a85fad0fc5bbb7071ecbe20c5):");
            if (!token || !token.trim()) return;
            showToast("⏳ 正在验证并保存 Token...", true);
            fetch('/api/set_token', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{ token: token.trim() }})
            }})
            .then(r => r.json())
            .then(data => {{
                if (data.success) {{
                    alert(data.info);
                    location.reload();
                }} else {{
                    alert("❌ 保存失败: " + data.info);
                }}
            }})
            .catch(e => alert("请求出错: " + e));
        }}

        function harvestSession() {{
            if (!confirm("【💡 微信嗅探兜底提示】\\n1. 本操作通常仅在长效 Token 彻底过期时才需要。\\n2. 点击确定后将启动微信小程序。\\n3. 小程序打开后，请在窗口中点击一下【场馆预约】或【健身房】！\\n4. 系统嗅探到有效凭证后会自动保存并关闭小程序。\\n\\n是否立即开始？")) return;
            showToast("⏳ 小程序已唤起，请在弹出窗口中点击【场馆预约】！", true);
            fetch('/api/harvest')
                .then(r => r.json())
                .then(data => {{
                    if (data.success) {{
                        alert("🎉 凭证自动更新成功！新 Session 已生效并持久化。");
                        location.reload();
                    }} else {{
                        alert("❌ 凭证自愈超时或失败: " + (data.info || "请确认微信已登录并在弹出的页面点击了【场馆预约】"));
                    }}
                }})
                .catch(e => alert("请求出错: " + e));
        }}

        function bookSlot(intervalId, date, timeRange) {{
            if (!confirm(`确认立即抢购【${{date}} ${{timeRange}}】的健身房名额吗？`)) return;
            const btn = event.target;
            btn.disabled = true;
            const originText = btn.innerText;
            btn.innerText = "预约提交中...";

            fetch(`/api/book?interval_id=${{intervalId}}&date=${{date}}&time=${{encodeURIComponent(timeRange)}}`)
                .then(r => r.json())
                .then(res => {{
                    if (res.success) {{
                        alert(`🎉 恭喜您预约成功！\\n${{res.info || '场地名额已锁定！'}}`);
                        location.reload();
                    }} else {{
                        // 如果提示凭证失效，先尝试纯 HTTP 自动续期并重试
                        if (res.need_harvest || (res.info && (res.info.includes("登录") || res.info.includes("过期") || res.info.includes("失效")))) {{
                            showToast("⚠️ 凭证失效，正在尝试纯 HTTP 自动续期并重新下单...", true);
                            fetch('/api/relogin')
                                .then(r => r.json())
                                .then(rel => {{
                                    if (rel.success) {{
                                        showToast("🎉 续期成功，正在重新提交预约...", true);
                                        setTimeout(() => bookSlot(intervalId, date, timeRange), 600);
                                    }} else {{
                                        if (confirm("⚠️ 纯 HTTP 续登未成功，是否唤醒微信小程序自动嗅探兜底？")) {{
                                            harvestSession();
                                        }} else {{
                                            btn.disabled = false;
                                            btn.innerText = originText;
                                        }}
                                    }}
                                }})
                                .catch(() => {{
                                    btn.disabled = false;
                                    btn.innerText = originText;
                                }});
                            return;
                        }}
                        alert(`⚠️ 预约未成功: ${{res.info || '名额已被抢完或网络异常'}}`);
                        btn.disabled = false;
                        btn.innerText = originText;
                    }}
                }})
                .catch(err => {{
                    alert(`请求发生异常: ${{err}}`);
                    btn.disabled = false;
                    btn.innerText = originText;
                }});
        }}
    </script>
</body>
</html>
"""
