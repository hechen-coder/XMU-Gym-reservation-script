# -*- coding: utf-8 -*-
"""
厦大体育馆自动预约工具 (XMU Gym Booking) - 开源社区版 (Community Edition)
面向厦门大学师生的场馆余票查询与自动化接口协议开源研究工具。

提示：
本开源版本面向 Python 开发者与学术技术交流，开放了完整网络通信底层、数据实体与实时余票查询功能。
早 7 点准点并发秒杀、就近时段自适应降级、退票持续捡漏与企业微信扫码直登等全自动功能为【商业桌面专业版】独占。
如需使用开箱即用的免安装桌面客户端，请前往 GitHub Releases 页面下载：
https://github.com/hechen-coder/XMU-Gym-reservation-script/releases
"""

import os
import sys
import argparse

# 解决 Windows 控制台编码问题
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from xdty_booking.config import load_config
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.utils.logger import setup_logger

logger = setup_logger("xdty_community")


def print_pro_banner(feature_name: str):
    print("")
    print("=" * 72)
    print("               【商业专业版专属特性提示】")
    print(f"  [*] 您当前尝试执行的功能「{feature_name}」为【桌面专业版】独占能力！")
    print("-" * 72)
    print("  桌面专业版 (Release EXE) 包含以下全自动硬核特性：")
    print("    * 07:00:00 准点毫秒级并发秒抢 (睡前挂机，06:55 自动自检自愈)")
    print("    * 黄金时段满额时【就近时段智能自适应降级保护】(绝不空手归)")
    print("    * 持续退票秒级捡漏监控 (有人退票瞬间自动回捞锁定)")
    print("    * 纯 Python 企业微信扫码直登 (免装 PC 微信客户端，3秒直达)")
    print("    * 微信 PushPlus / 邮件 秒发卡片通知")
    print("    * 零环境依赖免安装独立客户端，双击直接运行图形界面")
    print("-" * 72)
    print("  【获取与使用方式】：")
    print("  请直接前往本项目 GitHub Releases 页面下载最新便携版：")
    print("  >>> https://github.com/hechen-coder/XMU-Gym-reservation-script/releases")
    print("=" * 72)
    print("")


def cmd_query(cfg):
    """查询场馆开放日期与各时段实时余量 (开源社区版完全开放)"""
    client = ApiClient(base_url=cfg.base_url)
    if cfg.auth.phpsessid:
        client.set_session_token(cfg.auth.phpsessid)
    else:
        logger.warning("提示: config.yaml 中未检测到 phpsessid，若查询受限请先配置凭据。")

    api = XdtyApi(client)
    logger.info(f"正在查询目标场馆余票信息 (ID: {cfg.target.stadium_id} - {cfg.target.stadium_name})...")

    res = api.get_intervals(
        venue_id=cfg.target.venue_id,
        stadium_id=cfg.target.stadium_id,
        category_id=cfg.target.category_id,
        user_range=cfg.target.user_range
    )
    if not res:
        logger.error("未能获取到场次数据，请检查网络是否连通厦大校园网/VPN。")
        return

    print("")
    print("=" * 70)
    print(f"  场馆名称: {cfg.target.stadium_name} ({cfg.target.area_name})")
    print(f"  可选日期: {', '.join(res.date_list)}")
    print("=" * 70)

    target_date = res.date_list[min(cfg.target.target_date_offset, len(res.date_list) - 1)]
    print(f"\n【日期: {target_date} 各时段余量详情】")
    print(f"{'时段区间':<18} | {'状态':<10} | {'已约/总容量':<12} | {'剩余名额':<8}")
    print("-" * 60)

    for slot in res.time_slot_list:
        status_text = "可预约" if slot.is_available else "已约满"
        cap_info = f"{slot.selected}/{slot.max_count}"
        pref_mark = " (*心仪时段)" if slot.time_text == cfg.target.preferred_time else ""
        print(f"{slot.time_text:<18} | {status_text:<10} | {cap_info:<12} | {slot.remaining_capacity:<8}{pref_mark}")
    print("=" * 70)
    print("")


def main():
    parser = argparse.ArgumentParser(
        description="厦大体育馆自动预约工具 (XMU Gym Booking) - 开源社区版",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", nargs="?", default="query",
                        choices=["query", "check", "schedule", "book", "snipe", "web", "relogin", "harvest"],
                        help="执行动作: query(查询余票) / check(凭证自检) / schedule(早7点秒杀) ...")
    parser.add_argument("--config", default="config/config.yaml", help="配置文件路径")

    args = parser.parse_args()

    # 1. 基础开放功能
    if args.action == "query":
        try:
            cfg = load_config(args.config)
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}，请确保 config/config.yaml 存在。")
            return
        cmd_query(cfg)
        return

    if args.action == "check":
        logger.info("正在执行登录凭证健康自检...")
        try:
            cfg = load_config(args.config)
        except Exception:
            logger.warning("未检测到 config/config.yaml，请参考 config.example.yaml 创建。")
            return
        client = ApiClient(base_url=cfg.base_url)
        if cfg.auth.phpsessid:
            client.set_session_token(cfg.auth.phpsessid)
        api = XdtyApi(client)
        alive, info, _ = api.my_subscribe()
        if alive:
            logger.info("当前登录会话有效！")
        else:
            logger.warning(f"当前会话无效或已过期: {info}")
        return

    # 2. 商业专业版功能引导桩
    pro_features = {
        "schedule": "早 7 点高并发毫秒级准点秒杀与就近降级",
        "book": "毫秒级极速下单与离线验证码自旋重试",
        "snipe": "退票捡漏持续监听与秒级回捞截胡",
        "web": "可视化现代响应式监控大厅与企业微信扫码直登",
        "relogin": "长效 Token 纯 HTTP 自动换票保活",
        "harvest": "本地透明代理安全嗅探闭环"
    }

    if args.action in pro_features:
        print_pro_banner(pro_features[args.action])
        sys.exit(0)


if __name__ == "__main__":
    main()
