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

    def resolve_target_date(self) -> str:
        """根据配置的日期偏移量换算目标日期 (YYYY-MM-DD)"""
        offset = self.cfg.target.target_date_offset
        target = datetime.now() + timedelta(days=offset)
        return target.strftime("%Y-%m-%d")

    def execute_booking(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        执行一次完整的抢票/预约流程
        """
        date_str = target_date or self.resolve_target_date()
        target = self.cfg.target
        logger.info(f"开始执行场次预约: 日期 {date_str}, 场馆 {target.stadium_name}, 目标时段 {target.preferred_time}")

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

        slot = intervals.find_slot(date=date_str, time_range=target.preferred_time, column_id=str(target.area_id))
        if not slot:
            # 如果指定 area_id 没找到，放宽条件只按时间查找
            slot = intervals.find_slot(date=date_str, time_range=target.preferred_time)

        if not slot:
            err = f"未找到指定时段场次: 日期 {date_str}, 时段 {target.preferred_time}"
            logger.error(err)
            return {"success": False, "info": err}

        logger.info(f"找到目标场次: {slot.area_name} ({slot.date} {target.preferred_time}), 场次ID: {slot.interval_id}, 当前已选: {slot.selected}/{slot.max_count}")

        # 2. 执行选场预校验 (chooseVerify)
        selected_payload = [{
            "date": slot.date,
            "week": "5",
            "week_msg": "",
            "area_name": slot.area_name,
            "interval_time": target.preferred_time,
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
            logger.debug(f"预校验结果: {verify_res}")
        except Exception as e:
            logger.warning(f"预校验调用异常 ({e})，将尝试直接提交")

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

        if not captcha_code:
            captcha_code = "daxs"  # 兜底默认值

        # 4. 提交预约订单并支持即时重试
        retry_count = max(1, self.cfg.scheduler.retry_count)
        last_order_res = {}
        for attempt in range(retry_count):
            logger.info(f"第 {attempt + 1}/{retry_count} 次发起预约提交 (验证码: {captcha_code})...")
            try:
                order_res = self.api.add_order(
                    stadium_id=target.stadium_id,
                    venue_id=target.venue_id,
                    stadium_name=target.stadium_name,
                    project_name=target.project_name,
                    area_name=slot.area_name,
                    date=slot.date,
                    week="5",
                    week_msg="周五",
                    interval_time=target.preferred_time,
                    interval_id=slot.interval_id,
                    area_id=slot.column_id,
                    captcha=captcha_code,
                    category_id=target.category_id,
                    price=slot.price
                )
                last_order_res = order_res
                logger.info(f"预约服务端响应: {order_res}")

                if isinstance(order_res, dict) and order_res.get("status") == 1:
                    logger.info("🎉 预约成功！恭喜！")
                    return {
                        "success": True,
                        "info": order_res.get("info", "预约成功"),
                        "data": order_res.get("data"),
                        "slot": slot
                    }

                # 应对验证码识别错误并秒级重刷
                info_msg = str(order_res.get("info", "")) if isinstance(order_res, dict) else ""
                if "验证码" in info_msg:
                    logger.warning("提示验证码不匹配，正在重新拉取并识别验证码...")
                    try:
                        img_bytes = self.api.get_captcha()
                        captcha_code = self.solver.solve(img_bytes)
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"预约请求发送异常: {e}")

            time.sleep(self.cfg.scheduler.retry_interval_ms / 1000.0)

        info_msg = last_order_res.get("info", "预约未成功") if isinstance(last_order_res, dict) else "请求超时或网络错误"
        logger.error(f"预约最终失败: {info_msg}")
        return {"success": False, "info": info_msg, "raw": last_order_res}
