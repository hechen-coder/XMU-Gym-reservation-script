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
    def remaining_capacity(self) -> int:
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
        body = data.get("data", {})
        dates = [DateItem(**d) for d in body.get("date_list", [])]
        groups = []
        for g in body.get("time_slot_list", []):
            slots = [SlotItem(
                column_id=str(s.get("column_id", "")),
                date=s.get("date", ""),
                area_name=s.get("area_name", ""),
                interval_id=str(s.get("interval_id", "")),
                price=float(s.get("price", 0)),
                selected=int(s.get("selected", 0)),
                select_type=int(s.get("select_type", 1)),
                max_count=int(s.get("max_count", 0)),
                status=s.get("status", ""),
                is_lock=int(s.get("is_lock", 0)),
                lock_reason=s.get("lock_reason", "")
            ) for s in g.get("slots", [])]
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
            status=data.get("status", 0),
            info=data.get("info", ""),
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
