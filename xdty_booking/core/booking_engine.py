import time
import logging
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from xdty_booking.api.endpoints import XdtyApi
from xdty_booking.solver.captcha_solver import CaptchaSolver
from xdty_booking.config import AppConfig
from xdty_booking.core.models import SlotItem, TimeSlotGroup
from xdty_booking.notify.notifier import Notifier

logger = logging.getLogger(__name__)

class BookingEngine:
    """
    高并发极速抢票与捡漏执行引擎：
    负责场次查询、智能时段就近降级、预校验 (chooseVerify)、验证码识别与极速提交 (addOrder)、通知联动与自愈。
    """
    def __init__(
        self,
        api: XdtyApi,
        captcha_solver: CaptchaSolver,
        config: AppConfig,
        notifier: Optional[Notifier] = None,
        on_session_expired: Optional[Callable[[], bool]] = None
    ):
        self.api = api
        self.solver = captcha_solver
        self.cfg = config
        self.notifier = notifier
        self.on_session_expired = on_session_expired
        if hasattr(config, "auth") and getattr(config.auth, "uid", None):
            self.api.set_uid(config.auth.uid)

    def resolve_target_date(self) -> str:
        """根据配置的日期偏移量换算目标日期 (YYYY-MM-DD)"""
        offset = self.cfg.target.target_date_offset
        target = datetime.now() + timedelta(days=offset)
        return target.strftime("%Y-%m-%d")

    def _submit_slot(
        self,
        slot: SlotItem,
        group: Optional[TimeSlotGroup] = None,
        mode: str = "预约"
    ) -> Dict[str, Any]:
        """
        提交指定时段的预校验、验证码获取及极速下单流程
        """
        target = self.cfg.target
        week = group.week if group else "5"
        week_name = group.week_name if group else "周五"
        time_range = group.time_range if group else slot.interval_id

        # 1. 执行选场预校验 (chooseVerify)
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
                    "raw": verify_res,
                    "capacity_full": ("满" in info_msg or "超额" in info_msg)
                }
        except Exception as e:
            logger.warning(f"预校验调用异常 ({e})，继续直接提交")

        # 2. 极速获取并识别验证码
        captcha_code = ""
        for i in range(3):
            try:
                img_bytes = self.api.get_captcha()
                captcha_code = self.solver.solve(img_bytes)
                if len(captcha_code) == 4:
                    break
            except Exception as e:
                logger.warning(f"获取/识别验证码重试第 {i+1} 次: {e}")

        # 3. 提交预约订单并支持即时重试
        retry_count = max(1, self.cfg.scheduler.retry_count)
        last_order_res = {}
        for attempt in range(retry_count):
            logger.info(f"第 {attempt + 1}/{retry_count} 次发起预约提交 [{time_range}] (验证码: '{captcha_code}')...")
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
                    logger.info("🎉 [成功] 预约成功！恭喜！")
                    result = {
                        "success": True,
                        "info": order_res.get("info", "预约成功"),
                        "data": order_res.get("data"),
                        "slot": slot
                    }
                    # 触发即时通知
                    if self.notifier and self.notifier.is_enabled():
                        slot_dict = slot.to_dict()
                        slot_dict.update({
                            "stadium_name": target.stadium_name,
                            "time_range": time_range,
                            "mode": mode
                        })
                        try:
                            self.notifier.send_booking_success(slot_dict, order_res)
                        except Exception as ne:
                            logger.error(f"发送预约成功通知异常: {ne}")
                    return result

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
                elif "满" in info_msg or "超额" in info_msg:
                    return {
                        "success": False,
                        "info": info_msg,
                        "raw": last_order_res,
                        "capacity_full": True
                    }

            except Exception as e:
                logger.error(f"预约请求发送异常: {e}")

            time.sleep(self.cfg.scheduler.retry_interval_ms / 1000.0)

        info_msg = last_order_res.get("info", "预约未完成") if isinstance(last_order_res, dict) else "请求超时或网络错误"
        logger.error(f"预约最终未完成: {info_msg}")
        return {
            "success": False,
            "info": info_msg,
            "raw": last_order_res,
            "capacity_full": ("满" in info_msg or "超额" in info_msg)
        }

    def execute_booking(
        self,
        target_date: Optional[str] = None,
        preferred_time: Optional[str] = None,
        interval_id: Optional[str] = None,
        check_availability: bool = False,
        fallback_nearest: Optional[bool] = None,
        mode: str = "预约"
    ) -> Dict[str, Any]:
        """
        执行一次完整的抢票/预约流程。
        若首选时段已满且开启 fallback_nearest，自动降级选取最近时段提交！
        """
        target = self.cfg.target
        target_date_str = target_date or self.resolve_target_date()
        target_time_str = preferred_time or target.preferred_time
        use_fallback = self.cfg.scheduler.fallback_nearest if fallback_nearest is None else fallback_nearest

        logger.info(f"开始执行场次预约: 场馆 [{target.stadium_name}], 目标日期 {target_date_str}, 首选时段 {target_time_str}")

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

        # 2. 如果直接指定了 interval_id，优先以该 ID 预约
        if interval_id:
            group = None
            slot = None
            if hasattr(intervals, "find_by_id"):
                res = intervals.find_by_id(interval_id)
                if isinstance(res, tuple):
                    group, slot = res
            if slot:
                logger.info(f"按指定场次ID [{interval_id}] 预约: {slot.area_name} ({slot.date})")
                return self._submit_slot(slot, group, mode=mode)

        # 3. 匹配首选目标时段
        group = None
        slot = None
        if hasattr(intervals, "find_slot_with_group"):
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

        # 4. 判断首选时段名额
        preferred_available = bool(slot and slot.is_available and (slot.remaining_capacity > 0 or not check_availability))
        
        if slot and preferred_available:
            logger.info(
                f"锁定首选时段: {slot.area_name} ({slot.date} {target_time_str}), "
                f"场次ID: {slot.interval_id}, 剩余名额: {slot.remaining_capacity}人"
            )
            submit_res = self._submit_slot(slot, group, mode=mode)
            if submit_res.get("success"):
                return submit_res

            # 若首选下单失败但不是因为满人，或未开启降级，直接返回
            if not submit_res.get("capacity_full") or not use_fallback:
                return submit_res
            logger.warning(f"首选时段 [{target_time_str}] 下单被拒（名额已满），准备尝试就近降级...")

        # 5. 若首选时段无名额或下单被抢光，执行就近时段降级策略
        if not use_fallback:
            if not slot:
                err = f"未找到指定时段场次: 日期 {target_date_str}, 时段 {target_time_str}"
                logger.error(err)
                return {"success": False, "info": err}
            msg = f"该时段目前无空闲名额 (已约满 {slot.selected}/{slot.max_count})"
            logger.warning(msg)
            return {"success": False, "info": msg, "slot": slot, "full": True}

        logger.info(f"首选时段 [{target_time_str}] 暂无空余名额，启动【就近时段自动降级】算法...")
        candidates = []
        if hasattr(intervals, "find_nearest_available_slots"):
            res_c = intervals.find_nearest_available_slots(
                date=target_date_str,
                preferred_time=target_time_str,
                column_id=str(target.area_id)
            )
            if isinstance(res_c, list):
                candidates = res_c

        if not candidates:
            err = f"未找到指定时段场次: 日期 {target_date_str}, 时段 {target_time_str}"
            logger.error(err)
            return {"success": False, "info": err, "full": True}

        for c_group, c_slot in candidates:
            if slot and c_slot.interval_id == slot.interval_id:
                continue
            logger.info(
                f"⚡ 自动降级尝试就近时段: {c_group.time_range} ({c_slot.area_name}), "
                f"剩余: {c_slot.remaining_capacity}人 (已约 {c_slot.selected}/{c_slot.max_count})..."
            )
            fallback_res = self._submit_slot(c_slot, c_group, mode=f"{mode}(降级:{c_group.time_range})")
            if fallback_res.get("success"):
                fallback_res["fallback"] = True
                return fallback_res

        logger.error(f"日期 {target_date_str} 的所有就近备选时段均尝试完毕，无可用名额")
        return {"success": False, "info": "首选时段及所有就近备选时段均已约满", "full": True}

    def snipe_booking(
        self,
        target_date: Optional[str] = None,
        preferred_time: Optional[str] = None,
        interval_id: Optional[str] = None,
        poll_interval: float = 2.0,
        max_duration_seconds: int = 86400,
        fallback_nearest: bool = False
    ) -> Dict[str, Any]:
        """
        实时监听捡漏秒杀模式：
        高频检测目标场次，一旦有人退票释放名额，立刻毫秒级锁定并提交预约！
        支持长时间监听中的 Session 失效自动自愈与网络容错。
        """
        start_time = time.time()
        attempt = 0
        target_time_str = preferred_time or self.cfg.target.preferred_time
        target_date_str = target_date or self.resolve_target_date()
        logger.info(f"🚀 已启动捡漏监听模式 (目标: {target_date_str} {target_time_str}, 轮询间隔: {poll_interval}秒)...")

        while time.time() - start_time < max_duration_seconds:
            attempt += 1
            res = self.execute_booking(
                target_date=target_date,
                preferred_time=preferred_time,
                interval_id=interval_id,
                check_availability=True,
                fallback_nearest=fallback_nearest,
                mode="捡漏秒杀"
            )
            if res.get("success"):
                logger.info(f"🎉 捡漏成功！已完成预约: {res.get('info')}")
                return res

            if not res.get("full"):
                info_msg = str(res.get("info", ""))
                # 检查是否为 Session 过期或登录凭证失效
                is_session_err = any(k in info_msg for k in ("登录", "失效", "PHPSESSID", "token", "401", "未授权"))
                if is_session_err and self.on_session_expired:
                    logger.warning(f"捡漏监听中检测到 Session 失效 ({info_msg})，触发自动自愈...")
                    try:
                        healed = self.on_session_expired()
                        if healed:
                            logger.info("✅ 捡漏监听 Session 自愈成功，继续监听！")
                            time.sleep(poll_interval)
                            continue
                    except Exception as he:
                        logger.error(f"自愈过程异常: {he}")
                
                logger.warning(f"捡漏检测遇到非满员状态异常: {info_msg}，休眠重试...")

            # 加上轻微随机抖动，防止被 WAF 规则封锁固定频次请求
            jitter = (attempt % 5) * 0.1
            if attempt % 30 == 0:
                logger.info(f"已持续监听 {attempt} 次，目标时段暂无退票，继续监控中...")
            time.sleep(poll_interval + jitter)

        return {"success": False, "info": "捡漏监听超时，未能在规定时间内检测到空余名额"}
