import os
import sys
import time
import argparse
from datetime import datetime

# Windows 控制台字符编码兼容配置，防止 emoji 等特殊字符抛出 UnicodeEncodeError (仅在交互式控制台下应用)
if sys.platform == "win32" and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from xdty_booking.config import load_config
from xdty_booking.utils.logger import setup_logger
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.auth.session_manager import SessionManager
from xdty_booking.auth.wechat_harvester import WeChatHarvester
from xdty_booking.auth.harvester_service import HarvestService
from xdty_booking.solver.captcha_solver import CaptchaSolver
from xdty_booking.core.booking_engine import BookingEngine
from xdty_booking.core.scheduler import BookingScheduler
from xdty_booking.notify.notifier import Notifier
from xdty_booking.web.server import run_server

logger = setup_logger("xdty_main")

def build_cli_parser():
    parser = argparse.ArgumentParser(
        description="厦大体育馆自动预约工具 (xdty.xmu.edu.cn)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py schedule                  # 早上 07:00 准点抢次日名额 (提前自检自愈+就近时段降级+通知)
  python main.py web [--port 8080]         # 启动 Web 平台 (企业微信扫码登录+实时查询+一键预约抢票)
  python main.py book                      # 立即执行一次预约抢票 (首选满则自动就近降级)
  python main.py book --watch              # 开启捡漏监听秒杀 (断线/过期自动自愈，出票立马秒杀)
  python main.py snipe                     # 捡漏秒杀快捷指令
  python main.py query                     # 终端表格查询当前健身房实时余量与空闲状态
  python main.py check                     # 检测当前 Session 有效性 (支持自动续登自愈)
  python main.py relogin                   # 方案 A：纯 HTTP 调用 checkLogin 换取新 Session
  python main.py harvest                   # 启动本地代理自动嗅探截获小程序凭证 (兜底)
  python main.py heartbeat                 # 启动心跳守护进程保持 Session 不超时
  python main.py test-notify               # 发送测试通知，验证微信/邮件推送配置
  python main.py test-captcha              # 测试验证码获取与离线识别
  python main.py launch-wechat             # 测试 Windows 微信小程序静默唤醒
"""
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="配置文件路径 (默认: config/config.yaml)"
    )
    parser.add_argument(
        "--date",
        default=None,
        help="指定预约日期 (格式: YYYY-MM-DD，如 2026-09-12，默认按配置文件)"
    )
    parser.add_argument(
        "--time",
        default=None,
        help="指定预约时段 (如 19:30-21:00，默认按配置文件 preferred_time)"
    )
    parser.add_argument(
        "--interval-id",
        default=None,
        help="直接指定场次 ID 进行预约 (如 3080)"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="开启捡漏监听模式 (不断循环检测，一旦有人退票立刻自动秒抢)"
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="捡漏模式下的检测间隔秒数 (默认: 2.0 秒)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="自动嗅探截获等待超时秒数 (默认: 30.0 秒)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Web 服务监听端口 (默认: 8080)"
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="禁用首选时段满额时的自动就近时段降级"
    )
    parser.add_argument(
        "--target-time",
        default=None,
        help="覆盖指定的定时抢票目标时刻 (如 07:00:00 或 17:05:00，默认读取配置文件 scheduler.target_time)"
    )
    parser.add_argument(
        "action",
        choices=[
            "check", "relogin", "heartbeat", "book", "schedule", "test-captcha",
            "launch-wechat", "query", "harvest", "web", "snipe", "test-notify", "probe-session"
        ],
        help="要执行的操作指令"
    )
    return parser

def ensure_valid_session(cfg, session_mgr, client, config_path: str, timeout: float = 30.0) -> bool:
    """
    检查并确保 Session 登录态有效：
    1. 若已有 phpsessid 且 check_alive() 探测成功，直接返回 True；
    2. 否则进入双阶自愈策略：
       - 第 1 阶：优先尝试纯 HTTP checkLogin 自动续登（无需打开微信，秒级换取新 Cookie）；
       - 第 2 阶：若 checkLogin 失败（如 Token 彻底过期），且开启了 auto_harvest_enabled，
                 则启动微信小程序冷启动自动嗅探兜底；
    3. 成功后同步更新内存凭证与配置文件。
    """
    is_missing = not bool(cfg.auth.phpsessid)
    is_alive = False if is_missing else session_mgr.check_alive()
    if is_alive:
        return True

    reason = "未配置 PHPSESSID" if is_missing else "当前 PHPSESSID 已失效"
    logger.warning(f"检测到 {reason}，开始执行双阶自愈策略...")

    # 第 1 阶：纯 HTTP checkLogin 自动续登
    if cfg.auth.auth_params and cfg.auth.auth_params.get("token"):
        logger.info("尝试第 1 阶自愈：纯 HTTP checkLogin 自动续登...")
        new_phpsessid = session_mgr.refresh_session_via_check_login()
        if new_phpsessid:
            cfg.auth.phpsessid = new_phpsessid
            client.set_session_token(new_phpsessid)
            logger.info("✅ 第 1 阶全 HTTP 续登成功！登录态已完全恢复。")
            return True
        else:
            logger.warning("第 1 阶 HTTP checkLogin 续登未成功（可能 Token 过期或参数变动）。")
    else:
        logger.info("未配置 auth_params 或缺少 token，跳过第 1 阶纯 HTTP 续登。")

    # 第 2 阶：PC 微信静默唤醒与本地嗅探兜底
    if not cfg.auth.auto_harvest_enabled:
        logger.warning(f"auto_harvest_enabled 未开启，无法执行第 2 阶微信自动化兜底")
        return False

    logger.info("启动第 2 阶自愈：PC 微信静默自动化嗅探兜底...")
    service = HarvestService(cfg, config_path=config_path)
    new_token = service.harvest(timeout=timeout)
    if new_token:
        session_mgr.update_token(new_token)
        client.set_session_token(new_token)
        cfg.auth.phpsessid = new_token
        logger.info("✅ 第 2 阶微信自动化自愈完成！")
        return True
    else:
        logger.error("第 2 阶微信自动化自愈未成功获取到新凭证，请确认微信已登录且小程序可用")
        return False

def main():
    parser = build_cli_parser()
    args = parser.parse_args()

    # 1. 寻找可用配置文件，若不存在则由模板自动生成
    config_path = args.config
    if not os.path.exists(config_path):
        dir_name = os.path.dirname(config_path)
        example_path = os.path.join(dir_name, "config.example.yaml") if dir_name else "config/config.example.yaml"
        if not os.path.exists(example_path):
            example_path = "config/config.example.yaml"
        if os.path.exists(example_path):
            if os.path.basename(config_path) == "config.yaml":
                import shutil
                try:
                    shutil.copy(example_path, config_path)
                    logger.info(f"💡 首次运行检测：已自动为您生成默认配置文件 '{config_path}'！")
                except Exception as e:
                    logger.warning(f"自动生成配置文件失败: {e}，将回退读取示例配置")
                    config_path = example_path
            else:
                logger.warning(f"未找到 '{config_path}'，将回退读取示例配置 '{example_path}'")
                config_path = example_path
        else:
            logger.error(f"配置文件不存在: {config_path}")
            sys.exit(1)

    cfg = load_config(config_path)
    logger.info(f"📄 已加载配置文件: {config_path}")

    # 2. 初始化核心组件
    client = ApiClient(base_url=cfg.base_url)
    if cfg.auth.phpsessid:
        client.set_session_token(cfg.auth.phpsessid)
    api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)

    harvest_service = HarvestService(cfg, config_path=config_path)
    session_mgr = SessionManager(
        api,
        phpsessid=cfg.auth.phpsessid,
        auth_params=cfg.auth.auth_params,
        config_path=config_path,
        on_expired=lambda: harvest_service.harvest(timeout=args.timeout) if cfg.auth.auto_harvest_enabled else None
    )
    solver = CaptchaSolver()
    harvester = WeChatHarvester(appid=cfg.auth.wechat_appid)
    notifier = Notifier(cfg.notify)

    # 授权防护拦截：对于执行预约、抢票、秒杀等商业核心功能，在客户发布版下强控授权
    if args.action in ("schedule", "book", "snipe", "harvest", "relogin"):
        from xdty_booking.security.auth import check_license
        from xdty_booking.security.hwid import copy_hwid_to_clipboard
        auth_res = check_license()
        if not auth_res.is_licensed:
            copy_hwid_to_clipboard()
            print("\n" + "=" * 72)
            print("                【软件未授权激活提示】")
            print("  当前客户端尚未激活或授权已到期，无法执行预约抢票与秒杀功能。")
            print(f"  本机唯一机器识别码 (HWID): {auth_res.hwid}")
            print("  (已自动将机器码复制至剪贴板，可直接在微信/QQ中粘贴发送给作者)")
            print("-" * 72)
            print("  【激活方法】：")
            print("  1. 请将上方机器码发送给作者获取您的专属授权文件 (license.lic) 或激活码。")
            print("  2. 将获得的 license.lic 放入程序同级目录下即可直接生效；")
            print("     或者双击运行【启动网页版.bat】，在弹出的网页激活窗口中粘贴激活码。")
            print("=" * 72 + "\n")
            sys.exit(1)

    # 3. 分发执行操作
    if args.action == "check":
        logger.info("正在检测当前 Session 登录态与有效性...")
        alive = session_mgr.check_alive()
        if alive:
            logger.info("✅ Session 登录态有效！已成功连通预约系统。")
        else:
            logger.warning("❌ Session 无效或已过期！尝试自愈...")
            if ensure_valid_session(cfg, session_mgr, client, config_path, timeout=args.timeout):
                logger.info("✅ Session 自愈成功，当前登录态恢复有效！")
            else:
                logger.error("❌ Session 自愈未完成，请检查微信或网络状态。")

    elif args.action == "relogin":
        logger.info("正在执行 方案 A：纯 HTTP 调用 checkLogin 强制换取新 Session...")
        new_token = session_mgr.refresh_session_via_check_login()
        if new_token:
            client.set_session_token(new_token)
            cfg.auth.phpsessid = new_token
            logger.info(f"🎉 纯 HTTP 自动续登成功！最新 PHPSESSID: {new_token}")
        else:
            logger.error("❌ checkLogin 续登失败，请检查 auth_params 配置或使用 harvest 重新截获。")

    elif args.action == "harvest":
        logger.info("手动触发 方案 A：微信小程序本地代理自动嗅探与凭证截获...")
        token = harvest_service.harvest(timeout=args.timeout)
        if token:
            session_mgr.update_token(token)
            client.set_session_token(token)
            cfg.auth.phpsessid = token
            logger.info(f"✅ [成功] 自动截获并更新 PHPSESSID: {token}")
        else:
            logger.error("❌ [失败] 自动嗅探未能成功截获凭证")

    elif args.action == "heartbeat":
        ensure_valid_session(cfg, session_mgr, client, config_path, timeout=args.timeout)
        logger.info("启动 Session 心跳保活模式（按 Ctrl+C 退出）...")
        try:
            session_mgr.heartbeat_loop(cfg.auth.heartbeat_interval_seconds)
        except KeyboardInterrupt:
            logger.info("接收到退出信号，已停止心跳保活。")

    elif args.action == "test-captcha":
        logger.info("正在拉取验证码图片...")
        try:
            img_bytes = api.get_captcha()
            code = solver.solve(img_bytes)
            logger.info(f"验证码识别完成: 【{code}】")
        except Exception as e:
            logger.error(f"验证码拉取或识别失败: {e}")

    elif args.action == "launch-wechat":
        logger.info("测试唤醒 Windows PC 微信小程序...")
        ok = harvester.launch_miniprogram(executable_path=cfg.auth.wechat_appex_path or None)
        if ok:
            logger.info("微信小程序唤醒指令已成功发出。")
        else:
            logger.error("未能成功唤醒微信小程序，请检查 WeChatAppEx 路径。")

    elif args.action == "test-notify":
        logger.info("正在发送测试通知以验证配置...")
        if not notifier.is_enabled():
            logger.warning("当前配置中 notify.enabled=false。将临时尝试向配置通道发送测试消息...")
            notifier.cfg.enabled = True
        res = notifier.send_test()
        logger.info(f"通知测试结果: {res}")

    elif args.action == "probe-session":
        from tools.probe_phpsessid import run_once, run_watch
        if args.watch:
            run_watch(interval_seconds=int(args.poll_interval) if args.poll_interval > 10 else 3600, config_path=config_path)
        else:
            run_once(config_path=config_path)

    elif args.action == "query":
        ensure_valid_session(cfg, session_mgr, client, config_path, timeout=args.timeout)
        logger.info(f"正在通过 HTTP 查询场馆 [{cfg.target.stadium_name}] 的空闲与余量状态...")
        try:
            intervals = api.get_intervals(
                venue_id=cfg.target.venue_id,
                stadium_id=cfg.target.stadium_id,
                category_id=cfg.target.category_id,
                user_range=cfg.target.user_range
            )
            print("\n" + "=" * 76)
            print(f"[场馆查询] {cfg.target.stadium_name}（{cfg.target.area_name}）实时空闲状态")
            dates_str = ", ".join([f"{d.date}({d.week})" for d in getattr(intervals, 'date_list', [])])
            print(f"[开放日期] {dates_str}")
            print("=" * 76)

            current_date = None
            for g in getattr(intervals, 'time_slot_list', []):
                if g.date != current_date:
                    current_date = g.date
                    print(f"\n[日期] {g.date} {g.week_name}")
                    print("-" * 76)

                for s in g.slots:
                    if s.is_available:
                        badge = "[空闲充足]" if s.remaining_capacity > 10 else "[剩余紧张]"
                        rem_text = f"剩余: {s.remaining_capacity:>2}人 (已约 {s.selected:>2}/{s.max_count:<2})"
                    elif getattr(s, "is_locked", False) or s.status == "locked" or (s.selected == 0 and not s.is_available):
                        badge = "[课程占用]"
                        rem_text = f"教学课程占用 · 暂不开放个人预约 (0/{s.max_count:<2})"
                    else:
                        badge = "[已经约满]"
                        rem_text = f"名额已约满 (已约 {s.selected:>2}/{s.max_count:<2})"

                    is_pref = (g.time_range == cfg.target.preferred_time)
                    pref_mark = " *【目标时段】" if is_pref else ""
                    print(f"  时段: {g.time_range:<13} | {badge} | {rem_text}{pref_mark}")
            print("\n" + "=" * 76 + "\n")
        except Exception as e:
            logger.error(f"查询场馆空闲状态失败: {e}")

    elif args.action == "web":
        run_server(port=args.port, config_path=config_path)

    elif args.action in ("book", "snipe"):
        ensure_valid_session(cfg, session_mgr, client, config_path, timeout=args.timeout)
        engine = BookingEngine(
            api=api,
            captcha_solver=solver,
            config=cfg,
            notifier=notifier,
            on_session_expired=lambda: ensure_valid_session(cfg, session_mgr, client, config_path, timeout=args.timeout)
        )
        is_watch_mode = args.watch or (args.action == "snipe")
        use_fallback = not args.no_fallback

        if is_watch_mode:
            logger.info("启动捡漏秒杀监听模式...")
            res = engine.snipe_booking(
                target_date=args.date,
                preferred_time=args.time,
                interval_id=args.interval_id,
                poll_interval=args.poll_interval,
                fallback_nearest=use_fallback
            )
        else:
            logger.info("执行单次场次预约流程...")
            res = engine.execute_booking(
                target_date=args.date,
                preferred_time=args.time,
                interval_id=args.interval_id,
                fallback_nearest=use_fallback
            )

        if res.get("success"):
            logger.info(f"🎉 [成功] 预约执行成功: {res.get('info')}")
        else:
            logger.error(f"❌ [失败] 预约未能完成: {res.get('info')}")

    elif args.action == "schedule":
        # 定时预约模式：启动时不立即强行嗅探自愈，由调度器在抢票前预检时刻 (默认前5分钟) 自动自检自愈
        scheduler = BookingScheduler(
            config=cfg,
            session_mgr=session_mgr,
            client=client,
            api=api,
            solver=solver,
            config_path=config_path,
            notifier=notifier
        )
        scheduler.run(target_time=args.target_time)

if __name__ == "__main__":
    main()
