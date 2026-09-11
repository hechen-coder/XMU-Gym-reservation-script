import hashlib
import json
import logging
import random
import time
from typing import Dict, Any, Optional, List
from xdty_booking.api.client import ApiClient
from xdty_booking.core.models import IntervalResponse

logger = logging.getLogger(__name__)

class XdtyApi:
    """
    厦大体育馆 H5 核心业务接口封装
    """
    def __init__(self, client: ApiClient, uid: Optional[str] = None):
        self.client = client
        self._uid = str(uid) if uid else None

    def set_uid(self, uid: str):
        """设置当前用户的 UID"""
        if uid:
            self._uid = str(uid)

    def get_uid(self) -> str:
        """
        获取当前会话用户的 UID。
        若未显式指定，则尝试通过 my_subscribe 接口自动查询历史记录提取。
        """
        if self._uid:
            return self._uid
        try:
            res = self.my_subscribe(page=1)
            if isinstance(res, dict) and res.get("data") and len(res["data"]) > 0:
                uid = res["data"][0].get("uid")
                if uid:
                    self._uid = str(uid)
                    logger.info(f"自动获取到当前用户 UID: {self._uid}")
                    return self._uid
        except Exception as e:
            logger.warning(f"自动获取用户 UID 异常: {e}")
        return self._uid or ""

    @staticmethod
    def generate_captcha_sign(r: float, t: int, uid: str) -> str:
        """
        根据前端 SignMD5 规则计算验证码拉取签名：
        1. 包含 r, t, uid 字段
        2. 按 key 字典序升序排序
        3. 拼接 key 和 value，并追加秘钥 'Lptiyu_123!%$'
        4. 计算 32 位小写 MD5
        """
        data = {"r": r, "t": t, "uid": uid}
        keys = sorted(data.keys())
        raw_str = "".join(f"{k}{data[k]}" for k in keys) + "Lptiyu_123!%$"
        return hashlib.md5(raw_str.encode("utf-8")).hexdigest()

    def get_category_stadium(self, category_id: int = 8) -> Dict[str, Any]:
        """查询分类下的体育场馆列表 (例如健身房: category_id=8)"""
        resp = self.client.post("public/index.php/index/Stadium/getCategoryStadium", data={"category_id": category_id})
        return resp.json()

    def get_intervals(self, venue_id: int, stadium_id: int, category_id: int = 8, user_range: str = "[67]") -> IntervalResponse:
        """查询场馆各日期和时段空余场次与 interval_id"""
        resp = self.client.post(
            "public/index.php/stadium/interval/getInterval",
            data={
                "venue_id": venue_id,
                "stadium_id": stadium_id,
                "user_range": user_range,
                "category_id": category_id
            }
        )
        return IntervalResponse.from_dict(resp.json())

    def choose_verify(self, stadium_id: int, venue_id: int, selected_slots: List[Dict[str, Any]], is_academy: int = 1, ids: str = "") -> Dict[str, Any]:
        """选择场次预校验接口 (chooseVerify)"""
        return self.client.post(
            "public/index.php/index/stadium/chooseVerify",
            data={
                "stadium_id": stadium_id,
                "venue_id": venue_id,
                "selected": json.dumps(selected_slots, ensure_ascii=False),
                "is_academy": is_academy,
                "ids": ids
            }
        ).json()

    def get_venue_config(self, stadium_id: int, venue_id: int, category_id: int = 8) -> Dict[str, Any]:
        """获取场馆预约配置 (needRemark, isCanAppoint, verify_phone 等)"""
        return self.client.post(
            "public/index.php/index/Stadium/getVenueConfig",
            data={
                "stadium_id": stadium_id,
                "venue_id": venue_id,
                "category_id": category_id
            }
        ).json()

    def get_captcha(self, uid: Optional[str] = None) -> bytes:
        """
        获取下单图形验证码二进制流 (带 SignMD5 防刷校验)
        接口真实地址: /public/index.php/index/index/captcha
        """
        user_uid = uid or self.get_uid()
        r = random.random()
        t = int(time.time())
        sign = self.generate_captcha_sign(r=r, t=t, uid=user_uid)
        params = {
            "r": r,
            "t": t,
            "sign": sign
        }
        resp = self.client.get("public/index.php/index/index/captcha", params=params)

        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type or resp.content.startswith(b"{"):
            try:
                err = resp.json()
                logger.error(f"获取验证码服务端返回错误: {err}")
            except Exception:
                logger.error(f"获取验证码服务端返回非图片数据: {resp.content[:100]}")

        return resp.content

    def add_order(
        self,
        stadium_id: int,
        venue_id: int,
        stadium_name: str,
        project_name: str,
        area_name: str,
        date: str,
        week: str,
        week_msg: str,
        interval_time: str,
        interval_id: str,
        area_id: str,
        captcha: str,
        category_id: int = 8,
        price: float = 0,
        is_academy: int = 1,
        is_vip: int = 0,
        pay_type: int = 1
    ) -> Dict[str, Any]:
        """
        提交最终预约订单 (addOrder)
        """
        data = {
            "stadium_id": stadium_id,
            "venue_id": venue_id,
            "stadium_name": stadium_name,
            "project_name": project_name,
            "is_academy": is_academy,
            "academy_name": "",
            "mark": "",
            "details[0][date]": date,
            "details[0][week]": week,
            "details[0][week_msg]": week_msg,
            "details[0][area_name]": area_name,
            "details[0][interval_time]": interval_time,
            "details[0][interval_id]": interval_id,
            "details[0][area_id]": area_id,
            "details[0][price]": price,
            "uids": "",
            "captcha": captcha,
            "category_id": category_id,
            "is_vip": is_vip,
            "pay_type": pay_type
        }
        resp = self.client.post("public/index.php/index/Stadium/addOrder", data=data)
        return resp.json()

    def my_subscribe(self, page: int = 1) -> Dict[str, Any]:
        """查询我的预约记录 (同时作为轻量级心跳探针)"""
        resp = self.client.post("public/index.php/index/stadium/mySubscribe", data={"p": page})
        return resp.json()
