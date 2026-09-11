import json
import logging
from typing import Dict, Any, Optional, List
from xdty_booking.api.client import ApiClient
from xdty_booking.core.models import IntervalResponse

logger = logging.getLogger(__name__)

class XdtyApi:
    """
    厦大体育馆 H5 核心业务接口封装
    """
    def __init__(self, client: ApiClient):
        self.client = client

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

    def get_captcha(self) -> bytes:
        """获取下单图形验证码二进制流"""
        resp = self.client.get("public/index.php/captcha")
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
