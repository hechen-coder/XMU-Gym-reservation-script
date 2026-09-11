import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.solver.captcha_solver import CaptchaSolver
from xdty_booking.config import AppConfig

logger = logging.getLogger(__name__)

class BookingEngine:
    """
    高并发极速抢票引擎：
    负责场次查询、预校验 (chooseVerify)、验证码识别与极速提交 (addOrder)。
    """
    def __init__(self, api: XdtyApi, captcha_solver: CaptchaSolver, config: AppConfig):
        self.api = api
        self.solver = captcha_solver
        self.cfg = config
        if hasattr(config, "auth") and getattr(config.auth, "uid", None):
            self.api.set_uid(config.auth.uid)

    def resolve_target_date(self) -> str:
        """根据配置的日期偏移量换算目标日期 (YYYY-MM-DD)"""
        offset = self.cfg.target.target_date_offset
        target = datetime.now() + timedelta(days=offset)
        return target.strftime("%Y-%m-%d")

    def execute_booking(
        self,
        target_date: Optional[str] = None,
        preferred_time: Optional[str] = None,
        interval_id: Optional[str] = None,
        check_availability: bool = False
    ) -> Dict[str, Any]:
        """
        执行一次完整的抢票/预约流程
        支持指定 target_date, preferred_time 或直接通过 interval_id 快速预约
        """
        target = self.cfg.target
        target_date_str = target_date or self.resolve_target_date()
        target_time_str = preferred_time or target.preferred_time

        logger.info(f"开始执行场次预约: 场馆 [{target.stadium_name}], 目标日期 {target_date_str}, 时段 {target_time_str}")

        # 1. 查询场次
        try:
            intervals = self.api.get_intervals(
                venue_id=target.venue_id,
                stadium_id=target.stadium_id,
                category_id=target.category_id,
                user_range=target.user_range
            )
        except Exception as e:
            err = f"查询场次列表网络异常: {e}"
            logger.error(err)
            return {"success": False, "info": err}

        # 匹配目标场次及其所属分组 (获取真实周几信息)
        group = None
        slot = None
        if interval_id and hasattr(intervals, "find_by_id"):
            res = intervals.find_by_id(interval_id)
            if isinstance(res, tuple):
                group, slot = res

        if not slot and hasattr(intervals, "find_slot_with_group"):
            res = intervals.find_slot_with_group(
                date=target_date_str,
                time_range=target_time_str,
                column_id=str(target.area_id)
            )
            if isinstance(res, tuple):
                group, slot = res
            else:
                res = intervals.find_slot_with_group(
                    date=target_date_str,
                    time_range=target_time_str
                )
                if isinstance(res, tuple):
                    group, slot = res

        if not slot and hasattr(intervals, "find_slot"):
            slot = intervals.find_slot(
                date=target_date_str,
                time_range=target_time_str,
                column_id=str(target.area_id)
            )
            if not slot:
                slot = intervals.find_slot(
                    date=target_date_str,
                    time_range=target_time_str
                )

        if not slot:
            err = f"未找到指定时段场次: 日期 {target_date_str}, 时段 {target_time_str}" + (f", interval_id={interval_id}" if interval_id else "")
            logger.error(err)
            return {"success": False, "info": err}

        week = group.week if group else "5"
        week_name = group.week_name if group else "周五"
        time_range = group.time_range if group else target_time_str

        logger.info(
            f"锁定目标场次: {slot.area_name} ({slot.date} {week_name} {time_range}), "
            f"场次ID: {slot.interval_id}, 当前已选: {slot.selected}/{slot.max_count}"
        )

        # 检查可用名额（可选校验）
        if check_availability and not slot.is_available:
            msg = f"该时段目前无空闲名额 (已约满 {slot.selected}/{slot.max_count})"
            logger.warning(msg)
            return {"success": False, "info": msg, "slot": slot, "full": True}

        # 2. 执行选场预校验 (chooseVerify)，动态传入真实的周几
        selected_payload = [{
            "date": slot.date,
            "week": week,
            "week_msg": week_name,
            "area_name": slot.area_name,
            "interval_time": time_range,
            "interval_id": slot.interval_id,
            "area_id": slot.column_id,
            "price": str(int(slot.price))
        }]
        try:
            verify_res = self.api.choose_verify(
                stadium_id=target.stadium_id,
                venue_id=target.venue_id,
                selected_slots=selected_payload
            )
            logger.info(f"预校验结果: {verify_res}")
            if isinstance(verify_res, dict) and verify_res.get("status") == 0:
                info_msg = verify_res.get("info", "选场预校验未通过")
                logger.warning(f"服务端预校验未通过: {info_msg}")
                return {
                    "success": False,
                    "info": info_msg,
                    "slot": slot,
                    "raw": verify_res
                }
        except Exception as e:
            logger.warning(f"预校验调用异常 ({e})，继续直接提交")

        # 3. 极速获取并识别验证码
        captcha_code = ""
        for i in range(3):
            try:
                img_bytes = self.api.get_captcha()
                captcha_code = self.solver.solve(img_bytes)
                if len(captcha_code) == 4:
                    break
            except Exception as e:
                logger.warning(f"获取/识别验证码重试第 {i+1} 次: {e}")

        # 4. 提交预约订单并支持即时重试
        retry_count = max(1, self.cfg.scheduler.retry_count)
        last_order_res = {}
        for attempt in range(retry_count):
            logger.info(f"第 {attempt + 1}/{retry_count} 次发起预约提交 (验证码: '{captcha_code}')...")
            try:
                order_res = self.api.add_order(
                    stadium_id=target.stadium_id,
                    venue_id=target.venue_id,
                    stadium_name=target.stadium_name,
                    project_name=target.project_name,
                    area_name=slot.area_name,
                    date=slot.date,
                    week=week,
                    week_msg=week_name,
                    interval_time=time_range,
                    interval_id=slot.interval_id,
                    area_id=slot.column_id,
                    captcha=captcha_code,
                    category_id=target.category_id,
                    price=slot.price
                )
                last_order_res = order_res
                logger.info(f"服务端响应: {order_res}")

                if isinstance(order_res, dict) and order_res.get("status") == 1:
                    logger.info("[成功] 预约成功！恭喜！")
                    return {
                        "success": True,
                        "info": order_res.get("info", "预约成功"),
                        "data": order_res.get("data"),
                        "slot": slot
                    }

                # 若服务端提示验证码错误，立即重新拉取并重试
                info_msg = str(order_res.get("info", "")) if isinstance(order_res, dict) else ""
                if "验证码" in info_msg:
                    logger.warning("提示验证码不匹配，正在重新获取新验证码...")
                    try:
                        time.sleep(0.2)
                        img_bytes = self.api.get_captcha()
                        captcha_code = self.solver.solve(img_bytes)
                        logger.info(f"重新拉取并识别出新验证码: '{captcha_code}'")
                    except Exception as e:
                        logger.error(f"重新获取验证码发生异常: {e}")
                elif "频繁" in info_msg:
                    time.sleep(1.0)

            except Exception as e:
                logger.error(f"预约请求发送异常: {e}")

            time.sleep(self.cfg.scheduler.retry_interval_ms / 1000.0)

        info_msg = last_order_res.get("info", "预约未成功") if isinstance(last_order_res, dict) else "请求超时或网络错误"
        logger.error(f"预约最终未完成: {info_msg}")
        return {"success": False, "info": info_msg, "raw": last_order_res}

    def snipe_booking(
        self,
        target_date: Optional[str] = None,
        preferred_time: Optional[str] = None,
        interval_id: Optional[str] = None,
        poll_interval: float = 2.0,
        max_duration_seconds: int = 3600
    ) -> Dict[str, Any]:
        """
        实时监听捡漏模式：
        高频检测目标场次，一旦有人退票释放名额，立刻毫秒级锁定并提交预约！
        """
        start_time = time.time()
        attempt = 0
        logger.info(f"🚀 已启动捡漏监听模式 (轮询间隔: {poll_interval}秒，最大监听: {max_duration_seconds}秒)...")

        while time.time() - start_time < max_duration_seconds:
            attempt += 1
            res = self.execute_booking(
                target_date=target_date,
                preferred_time=preferred_time,
                interval_id=interval_id,
                check_availability=True
            )
            if res.get("success"):
                logger.info(f"🎉 捡漏成功！已完成预约: {res.get('info')}")
                return res

            if not res.get("full"):
                # 如果失败原因不是已约满（如 Session 失效或网络断开），直接返回
                logger.warning(f"捡漏异常中断: {res.get('info')}")
                return res

            logger.info(f"第 {attempt} 次检测: 目标场次已满，{poll_interval} 秒后继续监听...")
            time.sleep(poll_interval)

        return {"success": False, "info": "捡漏监听超时，未能在规定时间内检测到空余名额"}
