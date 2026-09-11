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
from xdty_booking.core.time_sync import TimeSync
from xdty_booking.core.booking_engine import BookingEngine

logger = setup_logger("xdty_main")

def build_cli_parser():
    parser = argparse.ArgumentParser(
        description="厦大体育馆自动预约工具 (xdty.xmu.edu.cn)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py check                     # 检测当前 Session 有效性 (支持自动嗅探自愈)
  python main.py harvest                   # 立即启动方案 A：本地代理自动嗅探截获小程序凭证
  python main.py heartbeat                 # 启动心跳守护进程保持 Session 不超时
  python main.py book                      # 立即执行一次预约抢票
  python main.py schedule                  # 定时对齐服务时间并在准点极速抢票
  python main.py test-captcha              # 测试验证码获取与识别
  python main.py launch-wechat             # 测试 Windows 微信小程序静默唤醒
  python main.py query                     # HTTP 查询当前健身房实时余量与空闲状态
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
        help="指定预约日期 (格式: YYYY-MM-DD，如 2026-09-11，默认按配置文件)"
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
        "action",
        choices=["check", "heartbeat", "book", "schedule", "test-captcha", "launch-wechat", "query", "harvest"],
        help="要执行的操作指令"
    )
    return parser

def ensure_valid_session(cfg, session_mgr, client, config_path: str, timeout: float = 30.0) -> bool:
    """
    检查 Session 登录态：
    1. 若未配置 phpsessid 或 check_alive() 探测失败；
    2. 且配置了 auto_harvest_enabled=True，则自动触发本地轻量代理嗅探捕获流程；
    3. 截获成功后自动刷新内存凭证与 SessionManager。
    """
    is_missing = not bool(cfg.auth.phpsessid)
    is_alive = False if is_missing else session_mgr.check_alive()
    if is_alive:
        return True

    reason = "未配置 PHPSESSID" if is_missing else "当前 PHPSESSID 已失效"
    if not cfg.auth.auto_harvest_enabled:
        logger.warning(f"检测到 {reason}，但 auto_harvest_enabled 未开启，跳过自动嗅探")
        return False

    logger.info(f"检测到 {reason}，且 auto_harvest_enabled=true，立即启动方案 A 自动嗅探闭环...")
    service = HarvestService(cfg, config_path=config_path)
    new_token = service.harvest(timeout=timeout)
    if new_token:
        session_mgr.update_token(new_token)
        client.set_session_token(new_token)
        logger.info("Session 自动嗅探自愈完成！")
        return True
    else:
        logger.error("自动嗅探未成功获取到新凭证，请确认微信已登录且小程序可用")
        return False

def main():
    parser = build_cli_parser()
    args = parser.parse_args()

    # 1. 寻找可用配置文件，若不存在则提示使用示例配置
    config_path = args.config
    if not os.path.exists(config_path):
        example_path = "config/config.example.yaml"
        if os.path.exists(example_path):
            logger.warning(f"未找到 '{config_path}'，将回退读取示例配置 '{example_path}'")
            config_path = example_path
        else:
            logger.error(f"配置文件不存在: {config_path}")
            sys.exit(1)

    cfg = load_config(config_path)

    # 2. 初始化核心组件
    client = ApiClient(base_url=cfg.base_url)
    if cfg.auth.phpsessid:
        client.set_session_token(cfg.auth.phpsessid)
    api = XdtyApi(client, uid=cfg.auth.uid if cfg.auth.uid else None)

    harvest_service = HarvestService(cfg, config_path=config_path)
    session_mgr = SessionManager(
        api,
        phpsessid=cfg.auth.phpsessid,
        on_expired=lambda: harvest_service.harvest(timeout=args.timeout) if cfg.auth.auto_harvest_enabled else None
    )
    solver = CaptchaSolver()
    harvester = WeChatHarvester(appid=cfg.auth.wechat_appid)

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

    elif args.action == "harvest":
        logger.info("手动触发 方案 A：微信小程序本地代理自动嗅探与凭证截获...")
        token = harvest_service.harvest(timeout=args.timeout)
        if token:
            session_mgr.update_token(token)
            client.set_session_token(token)
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
            dates_str = ", ".join([f"{d.date}({d.week})" for d in intervals.date_list])
            print(f"[开放日期] {dates_str}")
            print("=" * 76)

            current_date = None
            for g in intervals.time_slot_list:
                if g.date != current_date:
                    current_date = g.date
                    print(f"\n[日期] {g.date} {g.week_name}")
                    print("-" * 76)

                for s in g.slots:
                    if s.is_available:
                        badge = "[空闲充足]" if s.remaining_capacity > 10 else "[剩余紧张]"
                    else:
                        badge = "[已经约满]"

                    is_pref = (g.time_range == cfg.target.preferred_time)
                    pref_mark = " *【目标时段】" if is_pref else ""
                    print(f"  时段: {g.time_range:<13} | {badge} | 剩余: {s.remaining_capacity:>2}人 (已约 {s.selected:>2}/{s.max_count:<2}){pref_mark}")
            print("\n" + "=" * 76 + "\n")
        except Exception as e:
            logger.error(f"查询场馆空闲状态失败: {e}")

    elif args.action == "book":
        ensure_valid_session(cfg, session_mgr, client, config_path, timeout=args.timeout)
        logger.info("立即触发场次预约流程...")
        engine = BookingEngine(api, solver, cfg)
        if args.watch:
            res = engine.snipe_booking(
                target_date=args.date,
                preferred_time=args.time,
                interval_id=args.interval_id,
                poll_interval=args.poll_interval
            )
        else:
            res = engine.execute_booking(
                target_date=args.date,
                preferred_time=args.time,
                interval_id=args.interval_id
            )
        if res.get("success"):
            logger.info(f"[成功] 预约执行成功: {res.get('info')}")
        else:
            logger.error(f"[失败] 预约未能完成: {res.get('info')}")

    elif args.action == "schedule":
        ensure_valid_session(cfg, session_mgr, client, config_path, timeout=args.timeout)
        target_time_str = cfg.scheduler.target_time
        logger.info(f"进入高精度定时抢票监听模式，目标时刻: 每日 {target_time_str}")
        
        # 校准服务端时间差
        time_offset = TimeSync.get_server_time_offset(cfg.base_url)

        # 计算目标时间戳
        now = datetime.now()
        target_hour, target_minute, target_second = map(int, target_time_str.split(":"))
        target_dt = now.replace(hour=target_hour, minute=target_minute, second=target_second, microsecond=0)
        
        if target_dt <= now:
            # 如果今天目标时间已过，定为次日
            target_dt = target_dt.replace(day=now.day + 1)
        
        target_ts = target_dt.timestamp()
        logger.info(f"距离目标抢票时刻还有 {(target_ts - now.timestamp()):.1f} 秒，等待中...")

        # 启动后台心跳维持 Session
        session_mgr.start_heartbeat_daemon(interval_seconds=cfg.auth.heartbeat_interval_seconds)

        try:
            # 高精度等待直至到达目标时刻 (提前 advance_ms 毫秒)
            TimeSync.wait_until(target_ts, offset=time_offset, advance_ms=cfg.scheduler.advance_ms)
            logger.info("[准点] 到达抢票时刻！立即执行极速抢票！")
            
            engine = BookingEngine(api, solver, cfg)
            res = engine.execute_booking()
            if res.get("success"):
                logger.info(f"[成功] 准点抢票大获全胜: {res.get('info')}")
            else:
                logger.error(f"抢票结果: {res.get('info')}")
        finally:
            session_mgr.stop()

if __name__ == "__main__":
    main()
