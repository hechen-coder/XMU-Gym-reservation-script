import os
import sys
import time
import argparse
from datetime import datetime

from xdty_booking.config import load_config
from xdty_booking.utils.logger import setup_logger
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.auth.session_manager import SessionManager
from xdty_booking.auth.wechat_harvester import WeChatHarvester
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
  python main.py check                     # 检测当前 Session 有效性
  python main.py heartbeat                 # 启动心跳守护进程保持 Session 不超时
  python main.py book                      # 立即执行一次预约抢票
  python main.py schedule                  # 定时对齐服务时间并在准点极速抢票
  python main.py test-captcha              # 测试验证码获取与识别
  python main.py launch-wechat             # 测试 Windows 微信小程序静默唤醒
"""
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="配置文件路径 (默认: config/config.yaml)"
    )
    parser.add_argument(
        "action",
        choices=["check", "heartbeat", "book", "schedule", "test-captcha", "launch-wechat"],
        help="要执行的操作指令"
    )
    return parser

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
    api = XdtyApi(client)
    session_mgr = SessionManager(api, phpsessid=cfg.auth.phpsessid)
    solver = CaptchaSolver()
    harvester = WeChatHarvester(appid=cfg.auth.wechat_appid)

    # 3. 分发执行操作
    if args.action == "check":
        logger.info("正在检测当前 Session 登录态与有效性...")
        alive = session_mgr.check_alive()
        if alive:
            logger.info("✅ Session 登录态有效！已成功连通预约系统。")
        else:
            logger.warning("❌ Session 无效或已过期！请检查 PHPSESSID 或确认当前处于厦大校园网/VPN网络。")

    elif args.action == "heartbeat":
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

    elif args.action == "book":
        logger.info("立即触发场次预约流程...")
        engine = BookingEngine(api, solver, cfg)
        res = engine.execute_booking()
        if res.get("success"):
            logger.info(f"✅ 预约执行成功: {res.get('info')}")
        else:
            logger.error(f"❌ 预约未能完成: {res.get('info')}")

    elif args.action == "schedule":
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
            logger.info("⏰ 到达抢票时刻！立即执行极速抢票！")
            
            engine = BookingEngine(api, solver, cfg)
            res = engine.execute_booking()
            if res.get("success"):
                logger.info(f"🎉 准点抢票大获全胜: {res.get('info')}")
            else:
                logger.error(f"抢票结果: {res.get('info')}")
        finally:
            session_mgr.stop()

if __name__ == "__main__":
    main()
