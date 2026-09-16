from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple

@dataclass
class SlotItem:
    column_id: str
    date: str
    area_name: str
    interval_id: str
    price: float
    selected: int
    max_count: int
    status: str
    select_type: int = 1
    is_lock: int = 0
    lock_reason: str = ""

    @property
    def is_available(self) -> bool:
        return self.status == "available" and self.selected < self.max_count

    @property
    def is_locked(self) -> bool:
        return self.status == "locked" or self.select_type == 0 or (self.status != "available" and self.selected == 0)

    @property
    def remaining_capacity(self) -> int:
        if self.is_locked:
            return 0
        return max(0, self.max_count - self.selected)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "column_id": self.column_id,
            "date": self.date,
            "area_name": self.area_name,
            "interval_id": self.interval_id,
            "price": self.price,
            "selected": self.selected,
            "max_count": self.max_count,
            "status": self.status,
            "select_type": self.select_type,
            "is_lock": self.is_lock,
            "lock_reason": self.lock_reason,
            "is_available": self.is_available,
            "is_locked": self.is_locked,
            "remaining_capacity": self.remaining_capacity
        }

@dataclass
class TimeSlotGroup:
    time_range: str
    start_time: str
    end_time: str
    date: str
    week: str
    week_name: str
    slots: List[SlotItem]

@dataclass
class DateItem:
    date_int: str
    date: str
    week_int: str
    week: str

@dataclass
class IntervalResponse:
    status: int
    info: str
    venue_id: str
    date_list: List[DateItem]
    time_slot_list: List[TimeSlotGroup]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntervalResponse":
        if not isinstance(data, dict):
            return cls(status=0, info="响应格式异常", venue_id="", date_list=[], time_slot_list=[])

        body = data.get("data")
        if not isinstance(body, dict):
            body = {}

        raw_dates = body.get("date_list", [])
        dates = []
        if isinstance(raw_dates, list):
            for d in raw_dates:
                if isinstance(d, dict):
                    dates.append(DateItem(**d))

        groups = []
        raw_groups = body.get("time_slot_list", [])
        if isinstance(raw_groups, list):
            for g in raw_groups:
                if not isinstance(g, dict):
                    continue
                raw_slots = g.get("slots", [])
                slots = []
                if isinstance(raw_slots, list):
                    for s in raw_slots:
                        if not isinstance(s, dict):
                            continue
                        slots.append(SlotItem(
                            column_id=str(s.get("column_id", "")),
                            date=s.get("date", ""),
                            area_name=s.get("area_name", ""),
                            interval_id=str(s.get("interval_id", "")),
                            price=float(s.get("price", 0) or 0),
                            selected=int(s.get("selected", 0) or 0),
                            select_type=int(s.get("select_type", 1) or 1),
                            max_count=int(s.get("max_count", 0) or 0),
                            status=s.get("status", ""),
                            is_lock=int(s.get("is_lock", 0) or 0),
                            lock_reason=s.get("lock_reason", "")
                        ))
                groups.append(TimeSlotGroup(
                    time_range=g.get("time_range", ""),
                    start_time=g.get("start_time", ""),
                    end_time=g.get("end_time", ""),
                    date=g.get("date", ""),
                    week=str(g.get("week", "")),
                    week_name=g.get("week_name", ""),
                    slots=slots
                ))
        return cls(
            status=int(data.get("status", 0)),
            info=str(data.get("info", "")),
            venue_id=str(body.get("venue_id", "")),
            date_list=dates,
            time_slot_list=groups
        )

    def find_slot_with_group(
        self,
        date: Optional[str] = None,
        time_range: Optional[str] = None,
        column_id: Optional[str] = None,
        interval_id: Optional[str] = None
    ) -> Optional[Tuple[TimeSlotGroup, SlotItem]]:
        for g in self.time_slot_list:
            if date and g.date != date:
                continue
            if time_range and g.time_range != time_range:
                continue
            for slot in g.slots:
                if interval_id and slot.interval_id != str(interval_id):
                    continue
                if column_id and slot.column_id != str(column_id):
                    continue
                return g, slot
        return None

    def find_slot(self, date: str, time_range: str, column_id: Optional[str] = None) -> Optional[SlotItem]:
        res = self.find_slot_with_group(date=date, time_range=time_range, column_id=column_id)
        return res[1] if res else None

    def find_by_id(self, interval_id: str) -> Optional[Tuple[TimeSlotGroup, SlotItem]]:
        return self.find_slot_with_group(interval_id=str(interval_id))

    def find_nearest_available_slots(
        self,
        date: str,
        preferred_time: str,
        column_id: Optional[str] = None
    ) -> List[Tuple[TimeSlotGroup, SlotItem]]:
        """
        在指定日期查找所有可用场次（is_available=True 且 remaining_capacity > 0），
        按场次开始时间与 preferred_time 开始时间的绝对时差（分钟）升序排序返回。
        """
        pref_minutes = parse_time_to_minutes(preferred_time)
        candidates = []
        for g in self.time_slot_list:
            if date and g.date != date:
                continue
            group_minutes = parse_time_to_minutes(g.start_time or g.time_range)
            distance = abs(group_minutes - pref_minutes)
            for slot in g.slots:
                if column_id and slot.column_id != str(column_id):
                    continue
                if slot.is_available and slot.remaining_capacity > 0:
                    candidates.append((distance, g, slot))

        candidates.sort(key=lambda item: item[0])
        return [(c[1], c[2]) for c in candidates]

def parse_time_to_minutes(time_str: str) -> int:
    """将 HH:MM 或 HH:MM-HH:MM 字符串解析为从 00:00 起的分钟数"""
    if not time_str:
        return 0
    start = time_str.split("-")[0].strip()
    parts = start.split(":")
    if len(parts) >= 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return 0
    return 0
