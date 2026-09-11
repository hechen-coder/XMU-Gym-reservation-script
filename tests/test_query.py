from unittest.mock import MagicMock, patch
from query_gym import query_gym_status, print_gym_status
from xdty_booking.core.models import IntervalResponse

def test_query_gym_status():
    mock_data = {
        "status": 1,
        "info": "查询成功",
        "data": {
            "venue_id": "14",
            "date_list": [
                {"date_int": "2026-09-11", "date": "09月11日", "week_int": "5", "week": "今天"}
            ],
            "column_list": [{"column_id": "67", "name": "爱秋体育馆健身房"}],
            "time_slot_list": [
                {
                    "time_range": "19:30-21:00",
                    "start_time": "19:30",
                    "end_time": "21:00",
                    "date": "2026-09-11",
                    "week": "5",
                    "week_name": "周五",
                    "slots": [
                        {
                            "column_id": "67",
                            "date": "2026-09-11",
                            "area_name": "爱秋体育馆健身房",
                            "interval_id": "3080",
                            "price": 0,
                            "selected": 50,
                            "max_count": 95,
                            "status": "available"
                        }
                    ]
                }
            ]
        }
    }
    interval_resp = IntervalResponse.from_dict(mock_data)

    with patch("query_gym.XdtyApi.get_intervals", return_value=interval_resp):
        res = query_gym_status("config/config.example.yaml")
        assert res["stadium_name"] == "翔安校区健身房"
        assert len(res["groups"]) == 1
        slot = res["groups"][0]["slots"][0]
        assert slot["remaining"] == 45
        assert slot["is_available"] is True
        assert res["groups"][0]["is_preferred"] is True

        # Ensure printing does not raise exception
        print_gym_status(res)

def test_book_gym_slot():
    from query_gym import book_gym_slot
    with patch("query_gym.BookingEngine.execute_booking", return_value={"success": True, "info": "预约成功"}) as mock_exec:
        res = book_gym_slot(interval_id="3080", date="2026-09-12", time_slot="19:30-21:00", config_path="config/config.example.yaml")
        assert res["success"] is True
        mock_exec.assert_called_once_with(target_date="2026-09-12", preferred_time="19:30-21:00", interval_id="3080")

def test_handle_book_with_slot_item():
    import json
    import io
    from query_gym import GymStatusHandler
    from xdty_booking.core.models import SlotItem

    slot = SlotItem(
        column_id="67", date="2026-09-11", area_name="test",
        interval_id="3080", price=0, selected=94, max_count=95, status="available"
    )
    with patch("query_gym.book_gym_slot", return_value={"success": True, "info": "预约成功", "slot": slot}):
        handler = GymStatusHandler.__new__(GymStatusHandler)
        handler.wfile = io.BytesIO()
        handler.send_response = lambda code: setattr(handler, "status_code", code)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None

        handler._handle_book({"interval_id": ["3080"]})
        assert handler.status_code == 200
        resp_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        assert resp_data["success"] is True
        assert resp_data["slot"]["interval_id"] == "3080"

