from datetime import datetime, timedelta

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

    scheduler_status = data.get("scheduler_status", {})
    target_config = data.get("target_config", {})
    scheduler_config = data.get("scheduler_config", {})
    is_sched_running = scheduler_status.get("running", False)
    current_target_time = scheduler_config.get("target_time", "07:00:00")
    current_pref_time = target_config.get("preferred_time", "19:30-21:00")
    current_stadium_id = target_config.get("stadium_id", 16)
    current_venue_id = target_config.get("venue_id", 14)
    current_area_id = target_config.get("area_id", 67)
    current_user_range = target_config.get("user_range", "[67]")
    xiangan_selected = "selected" if current_stadium_id != 6 else ""
    siming_selected = "selected" if current_stadium_id == 6 else ""

    snipe_status = data.get("snipe_status", {})
    is_snipe_running = snipe_status.get("running", False)

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    after_tomorrow_str = (now + timedelta(days=2)).strftime("%Y-%m-%d")

    if current_stadium_id == 6:
        preset_times = [
            ("19:30-21:00", "⭐ 19:30-21:00 (晚场)"),
            ("18:30-19:20", "18:30-19:20 (傍晚)"),
            ("16:40-18:20", "16:40-18:20 (下午)"),
            ("14:30-16:10", "14:30-16:10 (午后)")
        ]
    else:
        preset_times = [
            ("19:30-21:00", "⭐ 19:30-21:00 (晚场)"),
            ("18:00-19:30", "18:00-19:30 (傍晚)"),
            ("16:30-18:00", "16:30-18:00 (下午)"),
            ("15:00-16:30", "15:00-16:30 (下午)"),
            ("13:30-15:00", "13:30-15:00 (午间)"),
            ("10:30-12:00", "10:30-12:00 (上午)")
        ]

    sched_time_chips_html = "".join([
        f'<button type="button" class="time-chip {"active" if current_pref_time == t[0] else ""}" data-val="{t[0]}" onclick="setTimeChip(\'{t[0]}\')">{t[1]}</button>'
        for t in preset_times
    ])
    snipe_time_chips_html = "".join([
        f'<button type="button" class="time-chip {"active" if current_pref_time == t[0] else ""}" data-val="{t[0]}" onclick="setSnipeTime(\'{t[0]}\')">{t[1]}</button>'
        for t in preset_times
    ])

    if is_session_valid:
        session_badge = '<span class="status-pill ok">● 登录有效</span>'
        top_bar_actions = """
            <div class="actions-group">
                <button type="button" class="btn-action" onclick="location.reload()" title="刷新当前场地余量">
                    🔄 刷新
                </button>
                <label class="auto-refresh-box" title="每 30 秒自动刷新余量与会话保活">
                    <input type="checkbox" id="autoRefreshToggle" onchange="toggleAutoRefresh(this.checked)" style="cursor: pointer;">
                    <span>自动刷新(30s)</span>
                </label>
                <a href="/login" class="btn-link" title="重新扫码登录或切换账号">
                    重新登录
                </a>
            </div>
        """
    else:
        session_badge = '<span class="status-pill warn">⚠️ 未登录</span>'
        top_bar_actions = """
            <div class="actions-group">
                <a href="/login" class="btn-action btn-primary" style="text-decoration: none; display: inline-flex; align-items: center; gap: 4px; font-weight: 600;" title="使用手机企业微信扫码登录">
                    📱 扫码登录
                </a>
                <button type="button" class="btn-action" onclick="location.reload()" title="刷新状态">
                    🔄 刷新
                </button>
            </div>
        """

    rows_html = ""
    for g in groups:
        for s in g.get("slots", []):
            avail = s.get("is_available", False)
            rem = s.get("remaining", 0)
            sel = s.get("selected", 0)
            max_c = s.get("max_count", 0)
            status_val = str(s.get("status", "")).lower()
            is_locked = s.get("is_locked", False) or (status_val == "locked") or (not avail and sel == 0)

            if is_locked:
                avail_cls = "locked"
                badge_text = "课程占用"
                capacity_display = f'<span style="color: #6d28d9; font-weight: 500;">教学课程占用</span>'
                progress_html = '<div class="progress-fill" style="width: 100%; background: #ddd6fe;" title="该时段为教学排课占用"></div>'
                btn_html = '<button class="btn-book locked" disabled title="该时段为学校体育课或场馆保留，暂不开放个人预约">课程占用</button>'
            elif avail:
                avail_cls = "avail"
                badge_text = f"剩余 {rem} 人"
                pct = int((sel / max_c * 100) if max_c > 0 else 0)
                bar_color = "#10b981" if rem > 10 else "#f59e0b"
                capacity_display = f"{sel} / {max_c} ({pct}%)"
                progress_html = f'<div class="progress-fill" style="width: {pct}%; background: {bar_color};"></div>'
                btn_html = f'<button class="btn-book" onclick="bookSlot(\'{s.get("interval_id")}\', \'{g.get("date")}\', \'{g.get("time_range")}\')">⚡ 立刻预约</button>'
            else:
                avail_cls = "full"
                badge_text = "已约满"
                pct = int((sel / max_c * 100) if max_c > 0 else 0)
                bar_color = "#ef4444"
                capacity_display = f"{sel} / {max_c} ({pct}%)"
                progress_html = f'<div class="progress-fill" style="width: {pct}%; background: {bar_color};"></div>'
                btn_html = '<button class="btn-book" disabled title="该场次名额已被全部约满">已约满</button>'

            pref_tag = "<span class='pref-tag'>⭐ 设定的目标时段</span>" if g.get("is_preferred") else ""
            date_str = f"{g.get('date')} {g.get('week_name')}"
            time_str = g.get('time_range')

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
                        <div class="capacity-text">{capacity_display}</div>
                        <div class="progress-bar">
                            {progress_html}
                        </div>
                    </div>
                </td>
                <td>
                    <span class="badge {avail_cls}">{badge_text}</span>
                </td>
                <td>
                    {btn_html}
                </td>
            </tr>
            """

    if not rows_html:
        if not is_session_valid:
            rows_html = f'''<tr><td colspan="5" style="text-align: center; padding: 42px 16px;">
                <div style="max-width: 440px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 32px 24px; box-shadow: 0 4px 20px rgba(0,0,0,0.03);">
                    <div style="font-size: 34px; margin-bottom: 8px;">📱</div>
                    <div style="font-size: 18px; font-weight: 700; color: #0f172a; margin-bottom: 6px;">
                        请先登录以查看场地与预约
                    </div>
                    <div style="font-size: 13px; color: #64748b; margin-bottom: 20px; line-height: 1.5;">
                        当前登录凭证已失效或未登录，请使用手机【企业微信】扫一扫直接登录
                    </div>

                    <!-- 居中内嵌二维码 -->
                    <div style="display: flex; flex-direction: column; align-items: center; margin-bottom: 18px;">
                        <div style="width: 190px; height: 190px; border: 2px solid #e2e8f0; border-radius: 14px; padding: 10px; background: #fff; box-shadow: 0 4px 12px rgba(0,0,0,0.04); display: flex; align-items: center; justify-content: center;">
                            <img id="inlineQrImg" src="" alt="二维码加载中..." style="width: 100%; height: 100%; object-fit: contain; border-radius: 6px;">
                        </div>
                        <div id="inlineQrStatus" style="font-size: 13px; color: #0284c7; margin-top: 10px; font-weight: 500;">
                            正在向认证中心拉取二维码...
                        </div>
                        <button id="inlineRefreshBtn" onclick="initInlineQr()" style="display: none; margin-top: 8px; font-size: 12px; padding: 5px 14px; border-radius: 6px; border: 1px solid #cbd5e1; background: #f8fafc; cursor: pointer;">
                            🔄 刷新二维码
                        </button>
                    </div>

                    <div style="display: flex; justify-content: center; gap: 10px;">
                        <a href="/login" class="btn-action btn-primary" style="padding: 10px 24px; font-size: 14px; font-weight: 600; text-decoration: none; border-radius: 8px;">
                            📱 全屏扫码页面
                        </a>
                    </div>

                    <!-- 更多选项折叠（避免干扰普通使用者） -->
                    <details style="margin-top: 24px; border-top: 1px dashed #e2e8f0; padding-top: 14px; text-align: center;">
                        <summary style="font-size: 12px; color: #94a3b8; cursor: pointer; user-select: none;">🛠️ 更多选项 ▾</summary>
                        <div style="display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; margin-top: 12px;">
                            <button class="btn-action btn-success" onclick="reloginSession()" style="font-size: 12px; padding: 6px 14px;" title="使用已有凭据快速换票">
                                ⚡ HTTP 自动续登
                            </button>
                            <button class="btn-action" onclick="harvestSession()" style="font-size: 12px; padding: 6px 14px;" title="通过桌面快捷方式启动微信小程序完成登录">
                                🔑 手动登录
                            </button>
                            <button class="btn-action" onclick="setManualToken()" style="font-size: 12px; padding: 6px 14px;" title="手动粘贴凭据">
                                ✏️ 手动输入 Token
                            </button>
                        </div>
                    </details>
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
        .title-row {{
            display: flex;
            align-items: center;
            gap: 14px;
            flex-wrap: wrap;
            margin-bottom: 6px;
        }}
        .title-row h1 {{
            margin: 0;
            font-size: 24px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .campus-switch-container {{
            display: inline-flex;
            background: #f1f5f9;
            border: 1px solid #cbd5e1;
            border-radius: 9999px;
            padding: 3px;
            gap: 3px;
            box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.05);
        }}
        .campus-toggle-btn {{
            border: none;
            background: transparent;
            padding: 5px 14px;
            font-size: 13px;
            font-weight: 500;
            color: #64748b;
            border-radius: 9999px;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            display: inline-flex;
            align-items: center;
            gap: 4px;
            user-select: none;
        }}
        .campus-toggle-btn:hover:not(.active) {{
            color: #1e293b;
            background: rgba(255, 255, 255, 0.8);
        }}
        .campus-toggle-btn.active {{
            background: #2563eb;
            color: #ffffff;
            font-weight: 700;
            box-shadow: 0 2px 6px rgba(37, 99, 235, 0.35);
        }}
        .subtitle {{
            color: var(--text-sub);
            font-size: 14px;
            margin: 0;
        }}
        .status-bar {{
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }}
        .status-group {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .actions-group {{
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            padding-left: 10px;
            border-left: 1px solid var(--border);
        }}
        @media (max-width: 720px) {{
            .actions-group {{
                border-left: none;
                padding-left: 0;
            }}
        }}
        .status-pill {{
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
            display: inline-flex;
            align-items: center;
            gap: 5px;
            user-select: none;
        }}
        .status-pill.ok {{ background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }}
        .status-pill.warn {{ background: #fffbeb; color: #92400e; border: 1px solid #fde68a; }}
        /* 自动化功能专属栏样式 */
        .feature-bar {{
            margin-top: 16px;
            margin-bottom: 6px;
            padding: 10px 16px;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .feature-left {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .feature-title {{
            font-size: 13px;
            font-weight: 700;
            color: #334155;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding-right: 4px;
        }}
        .btn-feature {{
            background: #ffffff;
            border: 1.5px solid #cbd5e1;
            color: #1e293b;
            padding: 7px 15px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 5px;
            transition: all 0.2s;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
        }}
        .btn-feature:hover {{
            border-color: #2563eb;
            color: #2563eb;
            background: #eff6ff;
            transform: translateY(-1px);
        }}
        .status-pill-running {{
            border: 1.5px solid #10b981;
            background: #ecfdf5;
            color: #065f46;
            font-size: 13px;
            font-weight: 700;
            padding: 6px 14px;
            border-radius: 20px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s;
            box-shadow: 0 2px 5px rgba(16, 185, 129, 0.15);
        }}
        .status-pill-running:hover {{
            background: #d1fae5;
            transform: translateY(-1px);
        }}
        .status-pill-running.snipe {{
            border-color: #3b82f6;
            background: #eff6ff;
            color: #1d4ed8;
            box-shadow: 0 2px 5px rgba(59, 130, 246, 0.15);
        }}
        .status-pill-running.snipe:hover {{
            background: #dbeafe;
        }}
        .feature-tip {{
            font-size: 12px;
            color: #64748b;
        }}
        .auto-refresh-box {{
            display: inline-flex;
            align-items: center;
            gap: 5px;
            font-size: 13px;
            color: var(--text-sub);
            cursor: pointer;
            user-select: none;
            padding: 0 2px;
        }}
        .btn-link {{
            font-size: 13px;
            color: var(--text-sub);
            text-decoration: none;
            padding: 4px 6px;
            border-radius: 4px;
            transition: color 0.15s;
        }}
        .btn-link:hover {{
            color: #1e293b;
            text-decoration: underline;
        }}
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
        .badge.locked {{ background: #ede9fe; color: #6d28d9; border: 1px solid #ddd6fe; }}
        .slot-row.locked {{ background: rgba(245, 243, 255, 0.45); }}
        .btn-book.locked {{ background: #f1f5f9 !important; color: #64748b !important; border: 1px solid #cbd5e1; cursor: not-allowed; }}
        
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

        /* 定时预约模态框样式 */
        .modal-overlay {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(15, 23, 42, 0.65);
            backdrop-filter: blur(5px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1100;
            padding: 16px;
            box-sizing: border-box;
            animation: fadeIn 0.2s ease;
        }}
        .modal-card {{
            background: #ffffff;
            width: 100%;
            max-width: 620px;
            max-height: 90vh;
            border-radius: 18px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.35);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            animation: slideUp 0.25s ease;
        }}
        @keyframes slideUp {{
            from {{ opacity: 0; transform: translateY(16px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .modal-header {{
            padding: 18px 24px;
            border-bottom: 1px solid #e2e8f0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #ffffff;
        }}
        .modal-close-btn {{
            background: none;
            border: none;
            font-size: 20px;
            color: #94a3b8;
            cursor: pointer;
            padding: 4px 8px;
            border-radius: 6px;
            transition: all 0.2s;
        }}
        .modal-close-btn:hover {{
            background: #f1f5f9;
            color: #1e293b;
        }}
        .modal-body {{
            padding: 20px 24px;
            overflow-y: auto;
            flex: 1;
        }}
        .modal-footer {{
            padding: 14px 24px;
            border-top: 1px solid #e2e8f0;
            background: #f8fafc;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .rule-banner {{
            background: #eff6ff;
            border: 1px solid #bfdbfe;
            border-radius: 12px;
            padding: 13px 16px;
            margin-bottom: 16px;
        }}
        .status-summary-card {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 12px 16px;
            margin-bottom: 16px;
        }}
        .form-group {{
            margin-bottom: 16px;
        }}
        .form-label {{
            font-size: 13px;
            font-weight: 600;
            color: #1e293b;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }}
        .venue-cards-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-top: 6px;
        }}
        .venue-card {{
            border: 2px solid #e2e8f0;
            border-radius: 12px;
            padding: 12px 14px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 10px;
            background: #ffffff;
        }}
        .venue-card:hover {{
            border-color: #93c5fd;
            background: #f8fafc;
        }}
        .venue-card.selected {{
            border-color: #2563eb;
            background: #eff6ff;
        }}
        .venue-card-title {{
            font-size: 14px;
            font-weight: 700;
            color: #0f172a;
        }}
        .venue-card-desc {{
            font-size: 12px;
            color: #64748b;
            margin-top: 2px;
        }}
        .time-chips-wrap {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 6px;
        }}
        .time-chip {{
            background: #f1f5f9;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 5px 10px;
            font-size: 12px;
            cursor: pointer;
            color: #334155;
            transition: all 0.15s;
        }}
        .time-chip:hover {{
            background: #2563eb;
            color: white;
            border-color: #2563eb;
        }}
        .time-chip.active {{
            background: #2563eb !important;
            color: #ffffff !important;
            border-color: #2563eb !important;
            font-weight: 700;
            box-shadow: 0 2px 6px rgba(37, 99, 235, 0.28);
        }}
        .form-input {{
            width: 100%;
            padding: 9px 12px;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            font-size: 13px;
            box-sizing: border-box;
            outline: none;
            transition: border-color 0.2s;
        }}
        .form-input:focus {{
            border-color: #2563eb;
        }}
        .pulse-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
            animation: pulse 1.5s infinite;
        }}

        /* 全局现代拟态对话框样式 (彻底告别8080端口抬头，零阻塞高颜值) */
        .custom-dialog-overlay {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(15, 23, 42, 0.68);
            backdrop-filter: blur(6px);
            -webkit-backdrop-filter: blur(6px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 2000;
            padding: 16px;
            box-sizing: border-box;
            animation: dialogFadeIn 0.2s ease-out;
        }}
        @keyframes dialogFadeIn {{
            from {{ opacity: 0; }}
            to {{ opacity: 1; }}
        }}
        .custom-dialog-card {{
            background: #ffffff;
            border-radius: 16px;
            max-width: 460px;
            width: 100%;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.35), 0 0 0 1px rgba(0, 0, 0, 0.05);
            padding: 24px;
            box-sizing: border-box;
            animation: dialogPopIn 0.22s cubic-bezier(0.16, 1, 0.3, 1);
            text-align: left;
        }}
        @keyframes dialogPopIn {{
            from {{ opacity: 0; transform: scale(0.94) translateY(8px); }}
            to {{ opacity: 1; transform: scale(1) translateY(0); }}
        }}
        .custom-dialog-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;
        }}
        .custom-dialog-icon {{
            font-size: 24px;
            line-height: 1;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 44px;
            height: 44px;
            border-radius: 12px;
            background: #f1f5f9;
            flex-shrink: 0;
        }}
        .custom-dialog-icon.success {{ background: #dcfce7; }}
        .custom-dialog-icon.warning {{ background: #fef3c7; }}
        .custom-dialog-icon.error {{ background: #fee2e2; }}
        .custom-dialog-icon.info {{ background: #eff6ff; }}
        .custom-dialog-title {{
            margin: 0;
            font-size: 17px;
            font-weight: 700;
            color: #0f172a;
            line-height: 1.3;
        }}
        .custom-dialog-content {{
            font-size: 14px;
            color: #475569;
            line-height: 1.6;
            margin-bottom: 18px;
            word-break: break-word;
            white-space: pre-wrap;
        }}
        .custom-dialog-input-wrap {{
            margin-bottom: 18px;
        }}
        .custom-dialog-input {{
            width: 100%;
            padding: 10px 14px;
            border: 1.5px solid #cbd5e1;
            border-radius: 8px;
            font-size: 13px;
            box-sizing: border-box;
            outline: none;
            transition: border-color 0.2s;
            font-family: inherit;
        }}
        .custom-dialog-input:focus {{
            border-color: #2563eb;
        }}
        .custom-dialog-footer {{
            display: flex;
            justify-content: flex-end;
            align-items: center;
            gap: 10px;
        }}
        .dialog-btn {{
            padding: 8px 18px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
            border: 1px solid transparent;
        }}
        .dialog-btn-cancel {{
            background: #f1f5f9;
            border-color: #cbd5e1;
            color: #475569;
        }}
        .dialog-btn-cancel:hover {{
            background: #e2e8f0;
            color: #1e293b;
        }}
        .dialog-btn-confirm {{
            background: #2563eb;
            color: #ffffff;
        }}
        .dialog-btn-confirm:hover {{
            background: #1d4ed8;
            transform: translateY(-1px);
            box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.25);
        }}
        .dialog-btn-confirm.danger {{
            background: #dc2626;
        }}
        .dialog-btn-confirm.danger:hover {{
            background: #b91c1c;
            box-shadow: 0 4px 6px -1px rgba(220, 38, 38, 0.25);
        }}
        .dialog-btn-confirm.success {{
            background: #10b981;
        }}
        .dialog-btn-confirm.success:hover {{
            background: #059669;
            box-shadow: 0 4px 6px -1px rgba(16, 185, 129, 0.25);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title-group">
                <div class="title-row">
                    <h1>🏋️ {stadium_name}</h1>
                    <div class="campus-switch-container" title="快速切换当前查询与预约的校区">
                        <button type="button" class="campus-toggle-btn {'active' if current_stadium_id != 6 else ''}" onclick="switchCampus('xiangan')">
                            <span>🏢 翔安校区</span>
                        </button>
                        <button type="button" class="campus-toggle-btn {'active' if current_stadium_id == 6 else ''}" onclick="switchCampus('siming')">
                            <span>🏛️ 思明校区</span>
                        </button>
                    </div>
                </div>
                <p class="subtitle">{area_name} · 实时数据直连 · 点击右侧立即预约</p>
            </div>
            <div class="status-bar">
                <div class="status-group">
                    {session_badge}
                </div>
                {top_bar_actions}
            </div>
        </div>

        <!-- 下一栏：功能专属栏（定时预约 与 捡漏监听） -->
        <div class="feature-bar">
            <div class="feature-left">
                <span class="feature-title">⚡ 自动化功能</span>
                <!-- 定时预约按钮：未运行时展示常规按钮，运行时展示高亮活动状态 -->
                <button type="button" class="btn-feature" id="featureSchedBtn" onclick="openSchedulerModal()" style="display: {'none' if is_sched_running else 'inline-flex'};" title="预约次日早7点开放名额，准点自动极速提交">
                    ⏰ 定时预约
                </button>
                <button type="button" class="status-pill-running" id="featureSchedActiveBtn" onclick="openSchedulerModal()" style="display: {'inline-flex' if is_sched_running else 'none'};" title="定时预约待命中，点击查看详情或停止">
                    <span class="pulse-dot" style="background: #10b981;"></span>
                    <span>🟢 定时预约中 (点击查看)</span>
                </button>

                <!-- 捡漏监听按钮：未运行时展示常规按钮，运行时展示高亮活动状态 -->
                <button type="button" class="btn-feature" id="featureSnipeBtn" onclick="openSnipeModal()" style="display: {'none' if is_snipe_running else 'inline-flex'};" title="高频监测退票名额，毫秒级极速捡漏秒抢">
                    🎯 捡漏监听
                </button>
                <button type="button" class="status-pill-running snipe" id="featureSnipeActiveBtn" onclick="openSnipeModal()" style="display: {'inline-flex' if is_snipe_running else 'none'};" title="捡漏监听进行中，点击查看实时日志或停止">
                    <span class="pulse-dot" style="background: #2563eb;"></span>
                    <span>🟢 正在捡漏中 (点击查看)</span>
                </button>
            </div>
            <div class="feature-tip">
                <span>💡 <strong>定时预约</strong>：次日早 07:00 准点秒抢 ｜ <strong>捡漏监听</strong>：高频监测退票名额毫秒捡漏</span>
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
            <div style="font-size: 12px; color: var(--text-sub);">
                厦门大学体育馆场地预约 · 实时直连系统
            </div>
        </div>
    </div>

    <div id="toast"></div>

    <!-- 全局通用高颜值拟态对话框 (彻底替代原生 alert / confirm / prompt，无8080端口抬头) -->
    <div id="customDialogModal" class="custom-dialog-overlay" style="display: none;">
        <div class="custom-dialog-card">
            <div class="custom-dialog-header">
                <div id="customDialogIcon" class="custom-dialog-icon">💡</div>
                <h3 id="customDialogTitle" class="custom-dialog-title">提示</h3>
            </div>
            <div id="customDialogContent" class="custom-dialog-content"></div>
            <div id="customDialogInputWrap" class="custom-dialog-input-wrap" style="display: none;">
                <input type="text" id="customDialogInput" class="custom-dialog-input" placeholder="">
            </div>
            <div class="custom-dialog-footer" id="customDialogButtons">
                <button type="button" class="dialog-btn dialog-btn-cancel" id="customDialogCancelBtn">取消</button>
                <button type="button" class="dialog-btn dialog-btn-confirm" id="customDialogConfirmBtn">确定</button>
            </div>
        </div>
    </div>

    <!-- 定时预约可视化设置与后台守护模态框 -->
    <div id="schedulerModal" class="modal-overlay" style="display: none;">
        <div class="modal-card">
            <div class="modal-header">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 24px;">⏰</span>
                    <div>
                        <h2 style="font-size: 17px; font-weight: 700; color: #0f172a; margin: 0;">定时预约</h2>
                        <p style="font-size: 12px; color: #64748b; margin: 3px 0 0 0;">预约次日开放名额 · 系统在早 07:00 准点自动极速提交</p>
                    </div>
                </div>
                <button type="button" class="modal-close-btn" onclick="closeSchedulerModal()" title="关闭">✕</button>
            </div>

            <div class="modal-body">
                <!-- 业务规则说明横幅 (已删除5分钟自检与防休眠技术冗余介绍) -->
                <div class="rule-banner">
                    <div style="font-weight: 700; color: #1e3a8a; margin-bottom: 5px; display: flex; align-items: center; gap: 6px;">
                        <span>💡</span>
                        <span>预约规则说明</span>
                    </div>
                    <div style="color: #1e40af; font-size: 13px; line-height: 1.6;">
                        系统<strong>默认定时预约当天早上 07:00:00 开放的第二天的健身房名额</strong>。<br>
                        <em>例如：周一早 07:00 会准点为您争抢周二的健身房场地。</em>
                    </div>
                </div>

                <!-- 当前预约详情卡片 (正在预约时高亮展示) -->
                <div id="bookingInfoCard" style="display: {'block' if is_sched_running else 'none'}; background: #f0fdf4; border: 1.5px solid #86efac; border-radius: 12px; padding: 14px 16px; margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span class="pulse-dot" style="background: #10b981;"></span>
                            <span style="font-weight: 700; font-size: 14px; color: #166534;">🟢 当前正在预约中</span>
                        </div>
                        <span style="font-size: 12px; color: #15803d; font-weight: 600; background: #dcfce7; padding: 2px 8px; border-radius: 10px;">已在后台待命</span>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 13px; color: #1e293b;">
                        <div><strong>📍 预约地点:</strong> <span id="infoStadiumName">{stadium_name}</span></div>
                        <div><strong>🕒 目标时段:</strong> <span id="infoPrefTime">{current_pref_time}</span></div>
                        <div><strong>📅 预约场次:</strong> <span>第二天 (次日场地)</span></div>
                        <div><strong>⏰ 开抢时刻:</strong> <span>明天早 07:00:00</span></div>
                    </div>
                    <div id="infoStatusDesc" style="font-size: 12px; color: #15803d; margin-top: 10px; padding-top: 8px; border-top: 1px dashed #bbf7d0;">
                        {scheduler_status.get('status_text', '将在早 07:00:00 准点为您极速提交预约')}
                    </div>
                </div>

                <!-- 表单项 1: 想去的地点选择 (用户能够修改想去的地点) -->
                <div class="form-group">
                    <div class="form-label">
                        <span>📍 想去的地点 (校区与场馆选择)</span>
                        <span style="font-size: 12px; font-weight: normal; color: #64748b;">点击卡片即可切换</span>
                    </div>
                    <div class="venue-cards-grid">
                        <div class="venue-card {xiangan_selected}" id="cardVenueXiangan" onclick="selectVenuePreset('xiangan')">
                            <div style="font-size: 20px;">🏢</div>
                            <div>
                                <div class="venue-card-title">翔安校区健身房</div>
                                <div class="venue-card-desc">爱秋体育馆健身房 · 一楼力量与器械区</div>
                            </div>
                        </div>
                        <div class="venue-card {siming_selected}" id="cardVenueSiming" onclick="selectVenuePreset('siming')">
                            <div style="font-size: 20px;">🏛️</div>
                            <div>
                                <div class="venue-card-title">思明校区健身房</div>
                                <div class="venue-card-desc">思明校区健身房 · 综合体能训练区</div>
                            </div>
                        </div>
                    </div>
                    <input type="hidden" id="schedStadiumId" value="{current_stadium_id}">
                    <input type="hidden" id="schedStadiumName" value="{stadium_name}">
                    <input type="hidden" id="schedAreaName" value="{area_name}">
                    <input type="hidden" id="schedVenueId" value="{current_venue_id}">
                    <input type="hidden" id="schedAreaId" value="{current_area_id}">
                    <input type="hidden" id="schedUserRange" value="{current_user_range}">
                </div>

                <!-- 表单项 2: 目标预约时段 -->
                <div class="form-group">
                    <div class="form-label">
                        <span>🕒 目标预约时段 (想约的健身时间)</span>
                        <span style="font-size: 12px; font-weight: normal; color: #64748b;">快捷选择或在下方手动修改</span>
                    </div>
                    <div class="time-chips-wrap" id="schedTimeChips">
                        {sched_time_chips_html}
                    </div>
                    <div style="margin-top: 8px;">
                        <input type="text" id="schedPrefTimeInput" class="form-input" placeholder="例如: 19:30-21:00" value="{current_pref_time}">
                    </div>
                </div>

                <!-- 隐藏的固定抢票时刻与目标日期 (默认早7点，次日场地，不向用户暴露) -->
                <input type="hidden" id="schedTargetTimeInput" value="07:00:00">
                <input type="hidden" id="schedTargetDateOffset" value="1">

                <!-- 表单项 3: 辅助选项 -->
                <div style="padding: 12px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; margin-top: 6px;">
                    <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; color: #334155; cursor: pointer;">
                        <input type="checkbox" id="schedFallbackNearest" checked style="cursor: pointer;">
                        <span>首选时段满额时，自动就近选择相邻时段降级抢票（极大提高成功率）</span>
                    </label>
                </div>
            </div>

            <div class="modal-footer">
                <div style="display: flex; gap: 8px;">
                    <button type="button" class="btn-action" id="btnStopScheduler" onclick="stopSchedulerTask()" style="display: {'inline-block' if is_sched_running else 'none'}; background: #fee2e2; border-color: #fca5a5; color: #b91c1c; font-weight: 600;">
                        ⏹️ 取消 / 停止预约
                    </button>
                    <button type="button" class="btn-action" onclick="saveSchedulerConfigOnly()" style="font-weight: 500;">
                        💾 仅保存设置
                    </button>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button type="button" class="btn-action" onclick="closeSchedulerModal()">关闭</button>
                    <button type="button" class="btn-action btn-primary" id="btnStartScheduler" onclick="startSchedulerTask()" style="font-weight: 700; padding: 8px 18px;">
                        {'🔄 更新预约设置' if is_sched_running else '🚀 开启定时预约'}
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- 实时退票捡漏监听设置与运行状态模态框 -->
    <div id="snipeModal" class="modal-overlay" style="display: none;">
        <div class="modal-card">
            <div class="modal-header">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 24px;">🎯</span>
                    <div>
                        <h2 style="font-size: 17px; font-weight: 700; color: #0f172a; margin: 0;">实时退票捡漏监听</h2>
                        <p style="font-size: 12px; color: #64748b; margin: 3px 0 0 0;">高频监测目标场次退票名额 · 毫秒级极速并发抢单</p>
                    </div>
                </div>
                <button type="button" class="modal-close-btn" onclick="closeSnipeModal()" title="关闭">✕</button>
            </div>

            <div class="modal-body">
                <!-- 捡漏原理说明横幅 -->
                <div class="rule-banner">
                    <div style="font-weight: 700; color: #1e3a8a; margin-bottom: 5px; display: flex; align-items: center; gap: 6px;">
                        <span>💡</span>
                        <span>捡漏原理说明</span>
                    </div>
                    <div style="color: #1e40af; font-size: 13px; line-height: 1.6;">
                        针对已约满的热门场次，系统以<strong>高频持续轮询探测</strong>。<br>
                        一旦有其他同学<strong>退票释出名额，毫秒级瞬间并发提交抢单锁定</strong>。
                    </div>
                </div>

                <!-- 当前捡漏监听状态卡片 (正在捡漏时高亮展示) -->
                <div id="snipeInfoCard" style="display: {'block' if is_snipe_running else 'none'}; background: #eff6ff; border: 1.5px solid #93c5fd; border-radius: 12px; padding: 14px 16px; margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span class="pulse-dot" style="background: #2563eb;"></span>
                            <span style="font-weight: 700; font-size: 14px; color: #1d4ed8;">🟢 正在高频捡漏监听中</span>
                        </div>
                        <span id="snipeInfoPollCount" style="font-size: 12px; color: #1d4ed8; font-weight: 600; background: #dbeafe; padding: 2px 8px; border-radius: 10px;">已探测 {snipe_status.get('poll_count', 0)} 次</span>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 13px; color: #1e293b;">
                        <div><strong>📍 目标场馆:</strong> <span id="snipeInfoStadium">{snipe_status.get('stadium_name') or stadium_name}</span></div>
                        <div><strong>📅 目标日期:</strong> <span id="snipeInfoDate">{snipe_status.get('target_date') or tomorrow_str}</span></div>
                        <div><strong>🕒 目标时段:</strong> <span id="snipeInfoTime">{snipe_status.get('preferred_time') or current_pref_time}</span></div>
                        <div><strong>⚡ 运行模式:</strong> <span>毫秒并发秒抢</span></div>
                    </div>
                    <div id="snipeInfoStatusDesc" style="font-size: 12px; color: #1d4ed8; margin-top: 10px; padding-top: 8px; border-top: 1px dashed #bfdbfe;">
                        {snipe_status.get('status_text', '正在监听目标场次余量...')}
                    </div>
                </div>

                <!-- 捡漏表单 1: 目标日期 -->
                <div class="form-group">
                    <div class="form-label">
                        <span>📅 目标日期 (选择需要捡漏的日期)</span>
                        <span style="font-size: 12px; font-weight: normal; color: #64748b;">快捷选择</span>
                    </div>
                    <div class="time-chips-wrap" id="snipeDateChips">
                        <button type="button" class="time-chip" data-val="{today_str}" onclick="setSnipeDate('{today_str}')">今天 ({today_str})</button>
                        <button type="button" class="time-chip active" data-val="{tomorrow_str}" onclick="setSnipeDate('{tomorrow_str}')">明天 ({tomorrow_str})</button>
                    </div>
                    <div style="margin-top: 8px;">
                        <input type="text" id="snipeDateInput" class="form-input" placeholder="输入日期如: {tomorrow_str}" value="{tomorrow_str}">
                    </div>
                </div>

                <!-- 捡漏表单 2: 目标时段 -->
                <div class="form-group">
                    <div class="form-label">
                        <span>🕒 目标预约时段 (想约的健身时间)</span>
                        <span style="font-size: 12px; font-weight: normal; color: #64748b;">快捷选择</span>
                    </div>
                    <div class="time-chips-wrap" id="snipeTimeChips">
                        {snipe_time_chips_html}
                    </div>
                    <div style="margin-top: 8px;">
                        <input type="text" id="snipePrefTimeInput" class="form-input" placeholder="例如: 19:30-21:00" value="{current_pref_time}">
                    </div>
                </div>

                <!-- 捡漏表单 3: 轮询频率选择 -->
                <div class="form-group">
                    <div class="form-label">
                        <span>⏱️ 轮询检测间隔</span>
                        <span style="font-size: 12px; font-weight: normal; color: #64748b;">当前选中: <strong id="snipeIntervalDisplay" style="color: #2563eb; font-weight: 700;">2.0 秒</strong> (推荐平衡 · 默认)</span>
                    </div>
                    <div class="time-chips-wrap" id="snipeIntervalChips">
                        <button type="button" class="time-chip" data-val="1.5" onclick="setSnipeInterval(1.5)">⚡ 1.5 秒 (极速)</button>
                        <button type="button" class="time-chip active" data-val="2.0" onclick="setSnipeInterval(2.0)">⭐ 2.0 秒 (推荐平衡 · 默认)</button>
                        <button type="button" class="time-chip" data-val="3.0" onclick="setSnipeInterval(3.0)">🌿 3.0 秒 (平稳静默)</button>
                    </div>
                    <input type="hidden" id="snipePollInterval" value="2.0">
                </div>

                <!-- 捡漏表单 4: 辅助选项 -->
                <div style="padding: 12px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; margin-top: 6px;">
                    <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; color: #334155; cursor: pointer;">
                        <input type="checkbox" id="snipeFallbackNearest" checked style="cursor: pointer;">
                        <span>首选时段暂无退票时，临近时段一旦有退票也自动争抢（提高捡漏成功几率）</span>
                    </label>
                </div>
            </div>

            <div class="modal-footer">
                <div>
                    <button type="button" class="btn-action" id="btnStopSnipe" onclick="stopSnipeTask()" style="display: {'inline-block' if is_snipe_running else 'none'}; background: #fee2e2; border-color: #fca5a5; color: #b91c1c; font-weight: 600;">
                        ⏹️ 停止捡漏监听
                    </button>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button type="button" class="btn-action" onclick="closeSnipeModal()">关闭</button>
                    <button type="button" class="btn-action btn-primary" id="btnStartSnipe" onclick="startSnipeTask()" style="font-weight: 700; padding: 8px 18px;" {'disabled' if is_snipe_running else ''}>
                        {'🟢 正在捡漏中' if is_snipe_running else '🚀 启动捡漏监听'}
                    </button>
                </div>
            </div>
        </div>
    </div>

    <script>
        function showToast(msg, isSuccess = true) {{
            const t = document.getElementById("toast");
            t.innerText = msg;
            t.style.background = isSuccess ? "#065f46" : "#991b1b";
            t.style.display = "block";
            setTimeout(() => {{ t.style.display = "none"; }}, 4000);
        }}

        let _dialogResolve = null;

        function _closeCustomDialog(result) {{
            const modal = document.getElementById("customDialogModal");
            if (modal) modal.style.display = "none";
            if (_dialogResolve) {{
                const cb = _dialogResolve;
                _dialogResolve = null;
                cb(result);
            }}
        }}

        function customAlert(message, type = "info", title = "") {{
            return new Promise((resolve) => {{
                const modal = document.getElementById("customDialogModal");
                const iconEl = document.getElementById("customDialogIcon");
                const titleEl = document.getElementById("customDialogTitle");
                const contentEl = document.getElementById("customDialogContent");
                const inputWrap = document.getElementById("customDialogInputWrap");
                const cancelBtn = document.getElementById("customDialogCancelBtn");
                const confirmBtn = document.getElementById("customDialogConfirmBtn");

                if (!modal) {{
                    showToast(message, type === "success" || type === "info");
                    resolve();
                    return;
                }}

                _dialogResolve = resolve;

                const icons = {{
                    success: "🎉",
                    error: "❌",
                    warning: "⚠️",
                    info: "💡"
                }};
                const titles = {{
                    success: "操作成功",
                    error: "操作失败",
                    warning: "温馨提醒",
                    info: "系统提示"
                }};

                iconEl.className = "custom-dialog-icon " + type;
                iconEl.innerText = icons[type] || "💡";
                titleEl.innerText = title || titles[type] || "系统提示";
                contentEl.innerText = message;
                if (inputWrap) inputWrap.style.display = "none";
                if (cancelBtn) cancelBtn.style.display = "none";
                if (confirmBtn) {{
                    confirmBtn.innerText = "我知道了";
                    confirmBtn.className = "dialog-btn dialog-btn-confirm" + (type === "error" ? " danger" : (type === "success" ? " success" : ""));
                    confirmBtn.onclick = () => _closeCustomDialog(true);
                }}

                modal.style.display = "flex";
            }});
        }}

        function customConfirm(message, title = "请确认操作", options = {{}}) {{
            return new Promise((resolve) => {{
                const modal = document.getElementById("customDialogModal");
                const iconEl = document.getElementById("customDialogIcon");
                const titleEl = document.getElementById("customDialogTitle");
                const contentEl = document.getElementById("customDialogContent");
                const inputWrap = document.getElementById("customDialogInputWrap");
                const cancelBtn = document.getElementById("customDialogCancelBtn");
                const confirmBtn = document.getElementById("customDialogConfirmBtn");

                if (!modal) {{
                    resolve(false);
                    return;
                }}

                _dialogResolve = resolve;

                const isDanger = !!options.isDanger;
                const confirmText = options.confirmText || "确认";
                const cancelText = options.cancelText || "取消";
                const icon = options.icon || (isDanger ? "⚠️" : "❓");
                const iconClass = isDanger ? "warning" : "info";

                iconEl.className = "custom-dialog-icon " + iconClass;
                iconEl.innerText = icon;
                titleEl.innerText = title;
                contentEl.innerText = message;
                if (inputWrap) inputWrap.style.display = "none";

                if (cancelBtn) {{
                    cancelBtn.style.display = "inline-block";
                    cancelBtn.innerText = cancelText;
                    cancelBtn.onclick = () => _closeCustomDialog(false);
                }}
                if (confirmBtn) {{
                    confirmBtn.innerText = confirmText;
                    confirmBtn.className = "dialog-btn dialog-btn-confirm" + (isDanger ? " danger" : "");
                    confirmBtn.onclick = () => _closeCustomDialog(true);
                }}

                modal.style.display = "flex";
            }});
        }}

        function customPrompt(message, defaultValue = "", title = "请输入") {{
            return new Promise((resolve) => {{
                const modal = document.getElementById("customDialogModal");
                const iconEl = document.getElementById("customDialogIcon");
                const titleEl = document.getElementById("customDialogTitle");
                const contentEl = document.getElementById("customDialogContent");
                const inputWrap = document.getElementById("customDialogInputWrap");
                const inputEl = document.getElementById("customDialogInput");
                const cancelBtn = document.getElementById("customDialogCancelBtn");
                const confirmBtn = document.getElementById("customDialogConfirmBtn");

                if (!modal) {{
                    resolve(null);
                    return;
                }}

                _dialogResolve = resolve;

                iconEl.className = "custom-dialog-icon info";
                iconEl.innerText = "✏️";
                titleEl.innerText = title;
                contentEl.innerText = message;

                if (inputWrap && inputEl) {{
                    inputWrap.style.display = "block";
                    inputEl.value = defaultValue;
                    setTimeout(() => {{
                        inputEl.focus();
                        inputEl.select();
                    }}, 100);
                }}

                if (cancelBtn) {{
                    cancelBtn.style.display = "inline-block";
                    cancelBtn.innerText = "取消";
                    cancelBtn.onclick = () => _closeCustomDialog(null);
                }}
                if (confirmBtn) {{
                    confirmBtn.innerText = "保存提交";
                    confirmBtn.className = "dialog-btn dialog-btn-confirm";
                    confirmBtn.onclick = () => {{
                        const val = inputEl ? inputEl.value.trim() : "";
                        _closeCustomDialog(val);
                    }};
                }}

                modal.style.display = "flex";
            }});
        }}

        // 嵌入式二维码自动初始化与状态轮询
        let inlinePollTimer = null;
        async function initInlineQr() {{
            const qrImg = document.getElementById("inlineQrImg");
            const qrStatus = document.getElementById("inlineQrStatus");
            const refBtn = document.getElementById("inlineRefreshBtn");
            if (!qrImg) return;

            if (refBtn) refBtn.style.display = "none";
            if (qrStatus) qrStatus.innerText = "正在获取企业微信登录二维码...";

            try {{
                const res = await fetch("/api/qr");
                const data = await res.json();
                if (data.success) {{
                    qrImg.src = data.qr_image;
                    if (qrStatus) qrStatus.innerText = "请使用手机企业微信扫一扫";
                    startInlinePolling();
                }} else {{
                    if (qrStatus) qrStatus.innerText = "获取失败: " + (data.error || "网络异常");
                    if (refBtn) refBtn.style.display = "inline-block";
                }}
            }} catch (err) {{
                if (qrStatus) qrStatus.innerText = "连接异常: " + err.message;
                if (refBtn) refBtn.style.display = "inline-block";
            }}
        }}

        function startInlinePolling() {{
            if (inlinePollTimer) clearInterval(inlinePollTimer);
            inlinePollTimer = setInterval(async () => {{
                const qrStatus = document.getElementById("inlineQrStatus");
                const refBtn = document.getElementById("inlineRefreshBtn");
                try {{
                    const res = await fetch("/api/qr_status");
                    const data = await res.json();
                    if (data.code === "0") {{
                        if (qrStatus) qrStatus.innerText = "等待手机企业微信扫码...";
                    }} else if (data.code === "2") {{
                        if (qrStatus) qrStatus.innerText = "已扫码！请在手机端点击【确认登录】...";
                    }} else if (data.code === "1" || data.logged_in) {{
                        clearInterval(inlinePollTimer);
                        if (qrStatus) qrStatus.innerText = "🎉 登录成功！正在加载场地...";
                        showToast("🎉 登录成功！正在加载场地...", true);
                        setTimeout(() => location.reload(), 900);
                    }} else if (data.code === "3") {{
                        clearInterval(inlinePollTimer);
                        if (qrStatus) qrStatus.innerText = "二维码已失效，请刷新";
                        if (refBtn) refBtn.style.display = "inline-block";
                    }} else if (data.code === "error") {{
                        clearInterval(inlinePollTimer);
                        if (qrStatus) qrStatus.innerText = data.desc || "凭据置换异常，请刷新重试";
                        if (refBtn) refBtn.style.display = "inline-block";
                    }}
                }} catch(e) {{}}
            }}, 1200);
        }}

        const IS_SESSION_VALID = {"true" if is_session_valid else "false"};
        let autoRefreshInterval = null;
        function toggleAutoRefresh(enable, showNotify = true) {{
            if (!IS_SESSION_VALID) {{
                if (autoRefreshInterval) {{
                    clearInterval(autoRefreshInterval);
                    autoRefreshInterval = null;
                }}
                const chk = document.getElementById("autoRefreshToggle");
                if (chk) chk.checked = false;
                return;
            }}

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
            if (IS_SESSION_VALID) {{
                try {{
                    const saved = localStorage.getItem("xdty_auto_refresh");
                    if (saved === "1") {{
                        toggleAutoRefresh(true, false);
                    }}
                }} catch(e) {{}}
            }} else {{
                // 未登录状态下清除定时器，确保不会每隔 30 秒重复检测
                if (autoRefreshInterval) {{
                    clearInterval(autoRefreshInterval);
                    autoRefreshInterval = null;
                }}
            }}

            if (document.getElementById("inlineQrImg")) {{
                initInlineQr();
            }}

            fetchSchedulerStatus();
            fetchSnipeStatus();
        }});

        let currentSchedulerRunning = false;

        function openSchedulerModal() {{
            const modal = document.getElementById("schedulerModal");
            if (modal) modal.style.display = "flex";
            fetchSchedulerStatus();
        }}

        function closeSchedulerModal() {{
            const modal = document.getElementById("schedulerModal");
            if (modal) modal.style.display = "none";
        }}

        function selectVenuePreset(key) {{
            const xianganCard = document.getElementById("cardVenueXiangan");
            const simingCard = document.getElementById("cardVenueSiming");
            const sId = document.getElementById("schedStadiumId");
            const sName = document.getElementById("schedStadiumName");
            const aName = document.getElementById("schedAreaName");
            const vId = document.getElementById("schedVenueId");
            const aId = document.getElementById("schedAreaId");
            const uRange = document.getElementById("schedUserRange");
            const schedWrap = document.getElementById("schedTimeChips");

            const xianganTimes = [
                ["19:30-21:00", "⭐ 19:30-21:00 (晚场)"],
                ["18:00-19:30", "18:00-19:30 (傍晚)"],
                ["16:30-18:00", "16:30-18:00 (下午)"],
                ["15:00-16:30", "15:00-16:30 (下午)"],
                ["13:30-15:00", "13:30-15:00 (午间)"],
                ["10:30-12:00", "10:30-12:00 (上午)"]
            ];
            const simingTimes = [
                ["19:30-21:00", "⭐ 19:30-21:00 (晚场)"],
                ["18:30-19:20", "18:30-19:20 (傍晚)"],
                ["16:40-18:20", "16:40-18:20 (下午)"],
                ["14:30-16:10", "14:30-16:10 (午后)"]
            ];

            if (key === "siming") {{
                if (xianganCard) xianganCard.classList.remove("selected");
                if (simingCard) simingCard.classList.add("selected");
                if (sId) sId.value = "6";
                if (sName) sName.value = "思明校区健身房";
                if (aName) aName.value = "思明校区健身房";
                if (vId) vId.value = "6";
                if (aId) aId.value = "0";
                if (uRange) uRange.value = "[]";
                if (schedWrap) {{
                    const curVal = document.getElementById("schedPrefTimeInput")?.value || "19:30-21:00";
                    schedWrap.innerHTML = simingTimes.map(t => `<button type="button" class="time-chip ${{curVal === t[0] ? 'active' : ''}}" data-val="${{t[0]}}" onclick="setTimeChip('${{t[0]}}')">${{t[1]}}</button>`).join("");
                }}
            }} else {{
                if (simingCard) simingCard.classList.remove("selected");
                if (xianganCard) xianganCard.classList.add("selected");
                if (sId) sId.value = "16";
                if (sName) sName.value = "翔安校区健身房";
                if (aName) aName.value = "爱秋体育馆健身房";
                if (vId) vId.value = "14";
                if (aId) aId.value = "67";
                if (uRange) uRange.value = "[67]";
                if (schedWrap) {{
                    const curVal = document.getElementById("schedPrefTimeInput")?.value || "19:30-21:00";
                    schedWrap.innerHTML = xianganTimes.map(t => `<button type="button" class="time-chip ${{curVal === t[0] ? 'active' : ''}}" data-val="${{t[0]}}" onclick="setTimeChip('${{t[0]}}')">${{t[1]}}</button>`).join("");
                }}
            }}
        }}

        function setTimeChip(val) {{
            const inp = document.getElementById("schedPrefTimeInput");
            if (inp) inp.value = val;
            const chips = document.querySelectorAll("#schedTimeChips .time-chip");
            chips.forEach(btn => {{
                if (btn.getAttribute("data-val") === val) {{
                    btn.classList.add("active");
                }} else {{
                    btn.classList.remove("active");
                }}
            }});
        }}

        async function fetchSchedulerStatus() {{
            try {{
                const res = await fetch("/api/scheduler/status");
                const data = await res.json();
                const isRunning = !!data.running;
                currentSchedulerRunning = isRunning;

                // 1. 同步功能专属栏定时预约按钮与活动状态
                const featBtn = document.getElementById("featureSchedBtn");
                const featActive = document.getElementById("featureSchedActiveBtn");
                if (isRunning) {{
                    if (featBtn) featBtn.style.display = "none";
                    if (featActive) featActive.style.display = "inline-flex";
                }} else {{
                    if (featBtn) featBtn.style.display = "inline-flex";
                    if (featActive) featActive.style.display = "none";
                }}

                // 2. 同步弹窗内的当前预约信息卡片与操作按钮
                const infoCard = document.getElementById("bookingInfoCard");
                const btnStop = document.getElementById("btnStopScheduler");
                const btnStart = document.getElementById("btnStartScheduler");
                const infoStadium = document.getElementById("infoStadiumName");
                const infoPref = document.getElementById("infoPrefTime");
                const infoDesc = document.getElementById("infoStatusDesc");

                if (infoStadium && data.stadium_name) infoStadium.innerText = data.stadium_name;
                if (infoPref && data.preferred_time) infoPref.innerText = data.preferred_time;
                if (infoDesc && data.status_text) infoDesc.innerText = data.status_text;

                if (isRunning) {{
                    if (infoCard) infoCard.style.display = "block";
                    if (btnStop) btnStop.style.display = "inline-block";
                    if (btnStart) btnStart.innerText = "🔄 更新预约设置";
                }} else {{
                    if (infoCard) infoCard.style.display = "none";
                    if (btnStop) btnStop.style.display = "none";
                    if (btnStart) btnStart.innerText = "🚀 开启定时预约";
                }}
            }} catch(e) {{}}
        }}

        function getSchedulerPayload() {{
            const sId = parseInt(document.getElementById("schedStadiumId").value || "16");
            const sName = document.getElementById("schedStadiumName").value || "翔安校区健身房";
            const aName = document.getElementById("schedAreaName").value || "爱秋体育馆健身房";
            const vId = parseInt(document.getElementById("schedVenueId").value || (sId === 6 ? "6" : "14"));
            const aId = parseInt(document.getElementById("schedAreaId").value || (sId === 6 ? "0" : "67"));
            const uRange = document.getElementById("schedUserRange").value || (sId === 6 ? "[]" : "[67]");
            const prefTime = (document.getElementById("schedPrefTimeInput").value || "19:30-21:00").trim();
            const targetTime = (document.getElementById("schedTargetTimeInput").value || "07:00:00").trim();
            const dateOffset = parseInt(document.getElementById("schedTargetDateOffset").value || "1");
            const fallbackNearest = document.getElementById("schedFallbackNearest").checked;

            return {{
                target: {{
                    stadium_id: sId,
                    stadium_name: sName,
                    area_name: aName,
                    venue_id: vId,
                    area_id: aId,
                    user_range: uRange,
                    preferred_time: prefTime,
                    target_date_offset: dateOffset
                }},
                scheduler: {{
                    target_time: targetTime,
                    fallback_nearest: fallbackNearest
                }}
            }};
        }}

        async function saveSchedulerConfigOnly() {{
            const payload = getSchedulerPayload();
            showToast("⏳ 正在保存配置...", true);
            try {{
                const res = await fetch("/api/scheduler/config", {{
                    method: "POST",
                    headers: {{"Content-Type": "application/json"}},
                    body: JSON.stringify(payload)
                }});
                const data = await res.json();
                if (data.success) {{
                    showToast("🎉 配置保存成功！页面即将刷新对齐最新场地...", true);
                    setTimeout(() => location.reload(), 800);
                }} else {{
                    await customAlert(data.info || "未知错误", "error", "保存配置失败");
                }}
            }} catch(e) {{
                await customAlert("保存配置请求出错: " + e, "error");
            }}
        }}

        async function startSchedulerTask() {{
            const payload = getSchedulerPayload();
            showToast("⏳ 正在开启定时预约任务...", true);
            try {{
                const res = await fetch("/api/scheduler/start", {{
                    method: "POST",
                    headers: {{"Content-Type": "application/json"}},
                    body: JSON.stringify(payload)
                }});
                const data = await res.json();
                if (data.success) {{
                    showToast(data.info || "🎉 定时预约已开启！将在明早 07:00 准点抢票", true);
                    fetchSchedulerStatus();
                    setTimeout(() => location.reload(), 1000);
                }} else {{
                    await customAlert(data.info || "未知错误", "error", "开启定时预约失败");
                }}
            }} catch(e) {{
                await customAlert("开启定时预约请求出错: " + e, "error");
            }}
        }}

        async function stopSchedulerTask() {{
            if (!await customConfirm("确认取消当前正在预约的早7点自动预约任务吗？", "取消定时预约", {{ isDanger: true, confirmText: "确认取消" }})) return;
            showToast("⏳ 正在取消预约任务...", true);
            try {{
                const res = await fetch("/api/scheduler/stop", {{
                    method: "POST"
                }});
                const data = await res.json();
                if (data.success) {{
                    showToast(data.info || "已取消预约任务", true);
                    fetchSchedulerStatus();
                    setTimeout(() => location.reload(), 800);
                }} else {{
                    await customAlert(data.info || "未知错误", "error", "取消失败");
                }}
            }} catch(e) {{
                await customAlert("取消请求出错: " + e, "error");
            }}
        }}

        async function switchCampus(campus) {{
            const campusName = (campus === "siming" ? "思明校区" : "翔安校区");
            showToast(`⏳ 正在切换至 ${{campusName}} 并加载最新排班...`, true);
            try {{
                const res = await fetch("/api/campus/switch", {{
                    method: "POST",
                    headers: {{"Content-Type": "application/json"}},
                    body: JSON.stringify({{ campus: campus }})
                }});
                const data = await res.json();
                if (data.success) {{
                    showToast(`🎉 ${{data.info || "切换成功"}}`, true);
                    setTimeout(() => {{
                        window.location.reload();
                    }}, 350);
                }} else {{
                    await customAlert("切换校区失败: " + (data.info || "未知错误"), "error");
                }}
            }} catch(e) {{
                await customAlert("切换校区网络异常: " + e, "error");
            }}
        }}

        let currentSnipeRunning = false;
        let snipePollStatusTimer = null;

        function openSnipeModal() {{
            const modal = document.getElementById("snipeModal");
            if (modal) modal.style.display = "flex";
            fetchSnipeStatus();
            if (snipePollStatusTimer) clearInterval(snipePollStatusTimer);
            snipePollStatusTimer = setInterval(fetchSnipeStatus, 1500);
        }}

        function closeSnipeModal() {{
            const modal = document.getElementById("snipeModal");
            if (modal) modal.style.display = "none";
            if (snipePollStatusTimer) {{
                clearInterval(snipePollStatusTimer);
                snipePollStatusTimer = null;
            }}
        }}

        function setSnipeDate(val) {{
            const inp = document.getElementById("snipeDateInput");
            if (inp) inp.value = val;
            const chips = document.querySelectorAll("#snipeDateChips .time-chip");
            chips.forEach(btn => {{
                if (btn.getAttribute("data-val") === val) {{
                    btn.classList.add("active");
                }} else {{
                    btn.classList.remove("active");
                }}
            }});
        }}

        function setSnipeTime(val) {{
            const inp = document.getElementById("snipePrefTimeInput");
            if (inp) inp.value = val;
            const chips = document.querySelectorAll("#snipeTimeChips .time-chip");
            chips.forEach(btn => {{
                if (btn.getAttribute("data-val") === val) {{
                    btn.classList.add("active");
                }} else {{
                    btn.classList.remove("active");
                }}
            }});
        }}

        function setSnipeInterval(val) {{
            const inp = document.getElementById("snipePollInterval");
            if (inp) inp.value = val;
            const chips = document.querySelectorAll("#snipeIntervalChips .time-chip");
            chips.forEach(btn => {{
                if (parseFloat(btn.getAttribute("data-val")) === parseFloat(val)) {{
                    btn.classList.add("active");
                }} else {{
                    btn.classList.remove("active");
                }}
            }});
            const disp = document.getElementById("snipeIntervalDisplay");
            if (disp) {{
                disp.textContent = val + " 秒";
            }}
            showToast(`已设置检测频率为 ${{val}} 秒`, true);
        }}

        async function fetchSnipeStatus() {{
            try {{
                const res = await fetch("/api/snipe/status");
                const data = await res.json();
                const isRunning = !!data.running;
                currentSnipeRunning = isRunning;

                // 1. 同步功能专属栏捡漏监听按钮与活动状态
                const featBtn = document.getElementById("featureSnipeBtn");
                const featActive = document.getElementById("featureSnipeActiveBtn");
                if (isRunning) {{
                    if (featBtn) featBtn.style.display = "none";
                    if (featActive) featActive.style.display = "inline-flex";
                }} else {{
                    if (featBtn) featBtn.style.display = "inline-flex";
                    if (featActive) featActive.style.display = "none";
                }}

                // 2. 同步弹窗内详情卡片与操作按钮
                const infoCard = document.getElementById("snipeInfoCard");
                const btnStop = document.getElementById("btnStopSnipe");
                const btnStart = document.getElementById("btnStartSnipe");
                const infoStadium = document.getElementById("snipeInfoStadium");
                const infoDate = document.getElementById("snipeInfoDate");
                const infoPref = document.getElementById("snipeInfoTime");
                const infoCount = document.getElementById("snipeInfoPollCount");
                const infoDesc = document.getElementById("snipeInfoStatusDesc");

                if (infoStadium && data.stadium_name) infoStadium.innerText = data.stadium_name;
                if (infoDate && data.target_date) infoDate.innerText = data.target_date;
                if (infoPref && data.preferred_time) infoPref.innerText = data.preferred_time;
                if (infoCount) infoCount.innerText = "已探测 " + (data.poll_count || 0) + " 次";
                if (infoDesc && data.status_text) infoDesc.innerText = data.status_text;

                if (isRunning) {{
                    if (infoCard) infoCard.style.display = "block";
                    if (btnStop) btnStop.style.display = "inline-block";
                    if (btnStart) {{
                        btnStart.innerText = "🟢 正在捡漏中";
                        btnStart.disabled = true;
                    }}
                }} else {{
                    if (infoCard) infoCard.style.display = "none";
                    if (btnStop) btnStop.style.display = "none";
                    if (btnStart) {{
                        btnStart.innerText = "🚀 启动捡漏监听";
                        btnStart.disabled = false;
                    }}
                }}
            }} catch(e) {{}}
        }}

        async function startSnipeTask() {{
            const targetDate = (document.getElementById("snipeDateInput").value || "").trim();
            const prefTime = (document.getElementById("snipePrefTimeInput").value || "").trim();
            const pollInterval = parseFloat(document.getElementById("snipePollInterval").value || "2.0");
            const fallbackNearest = document.getElementById("snipeFallbackNearest").checked;

            if (!targetDate) {{
                await customAlert("请先输入或选择目标捡漏日期 (如 2026-09-17)", "warning", "提示");
                return;
            }}
            if (!prefTime) {{
                await customAlert("请先输入或选择目标时段 (如 19:30-21:00)", "warning", "提示");
                return;
            }}

            showToast("⏳ 正在启动实时捡漏监听...", true);
            try {{
                const res = await fetch("/api/snipe/start", {{
                    method: "POST",
                    headers: {{"Content-Type": "application/json"}},
                    body: JSON.stringify({{
                        target_date: targetDate,
                        preferred_time: prefTime,
                        poll_interval: pollInterval,
                        fallback_nearest: fallbackNearest
                    }})
                }});
                const data = await res.json();
                if (data.success) {{
                    showToast(data.info || "🎉 捡漏监听已开启！正在后台持续高频探测退票名额", true);
                    fetchSnipeStatus();
                    if (!snipePollStatusTimer) {{
                        snipePollStatusTimer = setInterval(fetchSnipeStatus, 1500);
                    }}
                }} else {{
                    await customAlert(data.info || "未知错误", "error", "启动失败");
                }}
            }} catch(e) {{
                await customAlert("启动捡漏请求出错: " + e, "error");
            }}
        }}

        async function stopSnipeTask() {{
            if (!await customConfirm("确认停止当前正在进行的捡漏监听任务吗？", "停止捡漏监听", {{ isDanger: true, confirmText: "停止监听" }})) return;
            showToast("⏳ 正在停止捡漏任务...", true);
            try {{
                const res = await fetch("/api/snipe/stop", {{
                    method: "POST"
                }});
                const data = await res.json();
                if (data.success) {{
                    showToast(data.info || "已停止捡漏监听任务", true);
                    fetchSnipeStatus();
                }} else {{
                    await customAlert(data.info || "未知错误", "error", "停止失败");
                }}
            }} catch(e) {{
                await customAlert("停止请求出错: " + e, "error");
            }}
        }}

        async function reloginSession() {{
            showToast("⏳ 正在通过 checkLogin 执行纯 HTTP 自动续登 (无需打开微信)...", true);
            try {{
                const r = await fetch('/api/relogin');
                const data = await r.json();
                if (data.success) {{
                    showToast(data.info || "🎉 纯 HTTP 自动续登成功！最新 Session 已生效", true);
                    setTimeout(() => location.reload(), 900);
                }} else {{
                    await customAlert(data.info || "checkLogin 纯 HTTP 续登未成功，可能长效凭证已过期，请使用扫码登录或点击【手动登录】通过小程序获取凭据", "warning", "续登提醒");
                }}
            }} catch(e) {{
                await customAlert("续登请求出错: " + e, "error");
            }}
        }}

        async function setManualToken() {{
            const token = await customPrompt("请输入最新的 PHPSESSID 字符串 (如 0e3af18a85fad0fc5bbb7071ecbe20c5):", "", "手动输入 Token 凭据");
            if (!token || !token.trim()) return;
            showToast("⏳ 正在验证并保存 Token...", true);
            try {{
                const r = await fetch('/api/set_token', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ token: token.trim() }})
                }});
                const data = await r.json();
                if (data.success) {{
                    await customAlert(data.info, "success", "Token 保存成功");
                    location.reload();
                }} else {{
                    await customAlert(data.info || "验证未通过", "error", "保存失败");
                }}
            }} catch(e) {{
                await customAlert("请求出错: " + e, "error");
            }}
        }}

        async function harvestSession() {{
            const tipMsg = "【💡 手动启动小程序登录说明】\\n\\n" +
                "1. 电脑桌面必须已有【厦大体育】快捷方式图标（.lnk），系统才能自动唤起；\\n" +
                "2. 启动后请确保电脑微信处于登录状态；\\n" +
                "3. 请在打开的小程序主页面中点击【场馆预约】；\\n" +
                "4. 获取登录凭证后系统会自动关闭小程序并刷新页面。\\n\\n" +
                "是否立即启动？";
            if (!await customConfirm(tipMsg, "手动启动小程序登录说明", {{ confirmText: "立即启动小程序", cancelText: "我再看看" }})) return;
            showToast("⏳ 正在唤起小程序，请在窗口中登录并点击【场馆预约】...", true);
            try {{
                const r = await fetch('/api/harvest');
                const data = await r.json();
                if (data.success) {{
                    await customAlert("登录凭证获取成功！新会话已生效，页面即将刷新。", "success", "🎉 登录成功");
                    location.reload();
                }} else {{
                    await customAlert(data.info || "请确认电脑桌面有【厦大体育】快捷方式、微信已登录并点击了【场馆预约】", "error", "凭证获取未成功");
                }}
            }} catch(e) {{
                await customAlert("请求出错: " + e, "error");
            }}
        }}

        async function bookSlot(intervalId, date, timeRange) {{
            if (!await customConfirm(`确认立即抢购【${{date}} ${{timeRange}}】的健身房名额吗？`, "预约确认", {{ confirmText: "立即抢购", cancelText: "取消" }})) return;
            const btn = event ? event.target : null;
            let originText = "";
            if (btn) {{
                btn.disabled = true;
                originText = btn.innerText;
                btn.innerText = "预约提交中...";
            }}

            try {{
                const r = await fetch(`/api/book?interval_id=${{intervalId}}&date=${{date}}&time=${{encodeURIComponent(timeRange)}}`);
                const res = await r.json();
                if (res.success) {{
                    await customAlert(res.info || '场地名额已锁定！请按时前往锻炼。', "success", "🎉 恭喜您预约成功！");
                    location.reload();
                }} else {{
                    // 如果提示凭证失效，先尝试纯 HTTP 自动续期并重试
                    if (res.need_harvest || (res.info && (res.info.includes("登录") || res.info.includes("过期") || res.info.includes("失效")))) {{
                        showToast("⚠️ 凭证失效，正在尝试纯 HTTP 自动续期并重新下单...", true);
                        try {{
                            const relR = await fetch('/api/relogin');
                            const rel = await relR.json();
                            if (rel.success) {{
                                showToast("🎉 续期成功，正在重新提交预约...", true);
                                setTimeout(() => bookSlot(intervalId, date, timeRange), 600);
                                return;
                            }} else {{
                                if (await customConfirm("快速续登未成功，是否启动小程序进行手动登录？", "凭证失效提醒", {{ confirmText: "启动小程序", cancelText: "取消" }})) {{
                                    harvestSession();
                                    return;
                                }}
                            }}
                        }} catch(e) {{}}
                    }}
                    await customAlert(res.info || '名额已被抢完或网络异常', "warning", "预约未成功");
                    if (btn) {{
                        btn.disabled = false;
                        btn.innerText = originText;
                    }}
                }}
            }} catch(err) {{
                await customAlert("请求发生异常: " + err, "error");
                if (btn) {{
                    btn.disabled = false;
                    btn.innerText = originText;
                }}
            }}
        }}
    </script>
</body>
</html>
"""

def render_qr_login_page(is_already_logged_in: bool = False, phpsessid_masked: str = "") -> str:
    """生成企业微信扫码登录页面，手机扫码授权后自动置换凭证并跳转预约大厅"""
    already_in_banner = ""
    if is_already_logged_in:
        already_in_banner = f"""
        <div style="background: #ecfdf5; border: 1px solid #a7f3d0; color: #065f46; padding: 10px 18px; border-radius: 10px; margin-bottom: 20px; font-size: 13px; text-align: center;">
            ✨ 当前系统已存活有效登录态 <strong>({phpsessid_masked})</strong>，您可以直接 
            <a href="/" style="color: #047857; font-weight: 700; text-decoration: underline; margin-left: 4px;">进入预约大厅 →</a>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>厦门大学统一身份认证 · 企业微信扫码登录</title>
    <style>
        :root {{
            --primary: #0f4c81;
            --primary-light: #1976d2;
            --accent: #d4af37;
            --success: #10b981;
            --bg-gradient: linear-gradient(135deg, #0d1b2a 0%, #1b263b 50%, #293241 100%);
            --card-bg: rgba(255, 255, 255, 0.96);
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
        }}
        body {{
            min-height: 100vh;
            background: var(--bg-gradient);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            color: #333;
        }}
        .container {{
            width: 100%;
            max-width: 580px;
            background: var(--card-bg);
            border-radius: 20px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
            overflow: hidden;
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }}
        .header {{
            background: linear-gradient(135deg, var(--primary) 0%, #002244 100%);
            color: white;
            padding: 24px 28px;
            text-align: center;
            border-bottom: 4px solid var(--accent);
        }}
        .header h1 {{
            font-size: 21px;
            font-weight: 700;
            letter-spacing: 1px;
            margin-bottom: 6px;
        }}
        .header p {{
            font-size: 13px;
            opacity: 0.85;
        }}
        .content {{
            padding: 30px 28px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        .qr-box {{
            position: relative;
            width: 240px;
            height: 240px;
            background: #ffffff;
            border: 2px solid #e2e8f0;
            border-radius: 16px;
            padding: 12px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.06);
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 18px;
        }}
        .qr-box img {{
            width: 100%;
            height: 100%;
            object-fit: contain;
            border-radius: 8px;
        }}
        .status-badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 18px;
            border-radius: 30px;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 18px;
            background: #eef2f6;
            color: #475569;
            transition: all 0.3s;
        }}
        .status-badge.scanning {{
            background: #e0f2fe;
            color: #0369a1;
        }}
        .status-badge.confirming {{
            background: #fef3c7;
            color: #b45309;
        }}
        .status-badge.success {{
            background: #dcfce7;
            color: #15803d;
        }}
        .status-badge.expired {{
            background: #fee2e2;
            color: #b91c1c;
        }}
        .pulse-dot {{
            width: 9px;
            height: 9px;
            border-radius: 50%;
            background: currentColor;
            display: inline-block;
            animation: pulse 1.5s infinite;
        }}
        @keyframes pulse {{
            0% {{ transform: scale(0.8); opacity: 0.5; }}
            50% {{ transform: scale(1.2); opacity: 1; }}
            100% {{ transform: scale(0.8); opacity: 0.5; }}
        }}
        .tips {{
            font-size: 13px;
            color: #64748b;
            text-align: center;
            line-height: 1.6;
            max-width: 440px;
            margin-bottom: 16px;
        }}
        .refresh-btn {{
            margin-top: 10px;
            padding: 8px 18px;
            background: #f1f5f9;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            font-size: 13px;
            color: #334155;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .refresh-btn:hover {{
            background: #e2e8f0;
        }}
        .success-card {{
            width: 100%;
            background: #f0fdf4;
            border: 1px solid #bbf7d0;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            display: none;
            animation: fadeIn 0.4s ease;
        }}
        .btn-enter {{
            display: inline-block;
            margin-top: 14px;
            padding: 12px 28px;
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: white;
            text-decoration: none;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 700;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
            transition: all 0.2s;
        }}
        .btn-enter:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(16, 185, 129, 0.4);
        }}
        .nav-links {{
            margin-top: 20px;
            font-size: 13px;
            display: flex;
            gap: 16px;
        }}
        .nav-links a {{
            color: #64748b;
            text-decoration: none;
        }}
        .nav-links a:hover {{
            color: var(--primary-light);
            text-decoration: underline;
        }}
        .toast {{
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
        }}
        .toast.show {{
            opacity: 1;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(8px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>厦门大学统一身份认证</h1>
            <p>企业微信扫码登录 · 凭证自动置换与预约直通</p>
        </div>
        <div class="content">
            {already_in_banner}

            <!-- 二维码区 -->
            <div class="qr-box" id="qrBox">
                <img id="qrImg" src="" alt="二维码加载中...">
            </div>

            <!-- 状态胶囊 -->
            <div class="status-badge scanning" id="statusBadge">
                <span class="pulse-dot"></span>
                <span id="statusText">正在向统一认证中心申请 UUID...</span>
            </div>

            <p class="tips" id="instructionTip">
                请打开手机上的 <strong>企业微信 APP</strong>，点击右上角【+】→【扫一扫】扫描上方二维码。<br>
                扫码后在手机端点击<strong>【确认登录】</strong>，系统将自动换发凭据并进入预约大厅。
            </p>

            <button class="refresh-btn" id="refreshBtn" onclick="refreshQr()" style="display: none;">
                🔄 刷新二维码
            </button>

            <!-- 成功跳转区 -->
            <div class="success-card" id="successCard">
                <div style="font-size: 18px; font-weight: 700; color: #166534; margin-bottom: 6px;">
                    🎉 登录授权成功！
                </div>
                <div style="font-size: 13px; color: #15803d; margin-bottom: 12px;">
                    全套凭据已成功提取并写入配置文件，正在为您跳转至体育馆预约界面...
                </div>
                <div id="countdownTip" style="font-size: 12px; color: #4ade80;">即刻跳转中 (1s)...</div>
                <a href="/" class="btn-enter">🏋️ 立即进入预约大厅</a>
            </div>

            <div class="nav-links">
                <a href="/">← 直接返回预约大厅</a>
                <a href="/api/check">🔍 检测登录状态</a>
            </div>
        </div>
    </div>

    <div class="toast" id="toast"></div>

    <script>
        let pollTimer = null;
        let isCompleted = false;

        function showToast(msg) {{
            const t = document.getElementById("toast");
            t.innerText = msg;
            t.classList.add("show");
            setTimeout(() => t.classList.remove("show"), 2500);
        }}

        async function initQr() {{
            isCompleted = false;
            document.getElementById("successCard").style.display = "none";
            document.getElementById("qrBox").style.display = "flex";
            document.getElementById("instructionTip").style.display = "block";
            document.getElementById("refreshBtn").style.display = "none";
            updateStatus("scanning", "正在向统一认证中心申请 UUID...");

            try {{
                const res = await fetch("/api/qr");
                const data = await res.json();
                if (data.success) {{
                    document.getElementById("qrImg").src = data.qr_image;
                    updateStatus("scanning", "等待手机企业微信扫码...");
                    startPolling();
                }} else {{
                    updateStatus("expired", "初始化失败: " + (data.error || "未知错误"));
                    document.getElementById("refreshBtn").style.display = "inline-block";
                }}
            }} catch (err) {{
                updateStatus("expired", "连接服务器异常: " + err.message);
                document.getElementById("refreshBtn").style.display = "inline-block";
            }}
        }}

        function updateStatus(type, text) {{
            const b = document.getElementById("statusBadge");
            b.className = "status-badge " + type;
            document.getElementById("statusText").innerText = text;
        }}

        function startPolling() {{
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(async () => {{
                if (isCompleted) {{
                    clearInterval(pollTimer);
                    return;
                }}
                try {{
                    const res = await fetch("/api/qr_status");
                    const data = await res.json();

                    if (data.code === "0") {{
                        updateStatus("scanning", data.desc || "等待手机企业微信扫码...");
                    }} else if (data.code === "2") {{
                        updateStatus("confirming", data.desc || "已扫码！请在手机企业微信上点击【确认登录】...");
                    }} else if (data.code === "1" || data.logged_in) {{
                        if (data.logged_in) {{
                            handleSuccess(data.data);
                        }} else {{
                            updateStatus("success", data.desc || "授权成功！正在换取 Token...");
                        }}
                    }} else if (data.code === "3") {{
                        updateStatus("expired", "二维码已过期失效，请点击刷新");
                        clearInterval(pollTimer);
                        document.getElementById("refreshBtn").style.display = "inline-block";
                    }} else if (data.code === "error") {{
                        updateStatus("expired", data.desc || "凭据换发异常");
                        clearInterval(pollTimer);
                        document.getElementById("refreshBtn").style.display = "inline-block";
                    }}
                }} catch (e) {{
                    console.error("轮询异常:", e);
                }}
            }}, 1200);
        }}

        function handleSuccess(resData) {{
            isCompleted = true;
            clearInterval(pollTimer);
            updateStatus("success", "🎉 登录成功！凭据已就绪");
            
            document.getElementById("qrBox").style.display = "none";
            document.getElementById("instructionTip").style.display = "none";
            document.getElementById("refreshBtn").style.display = "none";
            document.getElementById("successCard").style.display = "block";
            showToast("🎉 登录成功！正在进入预约大厅...");

            // 1.5 秒后自动跳转至预约主页
            setTimeout(() => {{
                window.location.href = "/";
            }}, 1500);
        }}

        function refreshQr() {{
            initQr();
        }}

        window.onload = initQr;
    </script>
</body>
</html>
"""

