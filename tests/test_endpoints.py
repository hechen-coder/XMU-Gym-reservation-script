import json
import pytest
from unittest.mock import Mock, patch
from xdty_booking.api.client import ApiClient
from xdty_booking.api.endpoints import XdtyApi

@pytest.fixture
def mock_client():
    client = ApiClient(base_url="https://xdty.xmu.edu.cn/bdlp_h5_fitness_test")
    client.set_session_token("mock_sess_8f4ada1aad7d11f1909f0242ac110002")
    return client

def test_api_client_cookies_and_headers(mock_client):
    assert mock_client.session.cookies.get("login_type") == "4"
    assert mock_client.session.cookies.get("PHPSESSID") == "mock_sess_8f4ada1aad7d11f1909f0242ac110002"
    assert "MicroMessenger" in mock_client.session.headers["user-agent"]
    assert mock_client.session.headers["x-requested-with"] == "XMLHttpRequest"

def test_get_category_stadium(mock_client):
    api = XdtyApi(mock_client)
    with patch.object(mock_client.session, 'post') as mock_post:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": 1,
            "info": "查询成功",
            "data": {
                "category_id": "8",
                "stadium": [
                    {"id": 16, "name": "翔安校区健身房", "venue_id": 14}
                ]
            }
        }
        mock_post.return_value = mock_resp

        res = api.get_category_stadium(category_id=8)
        assert res["status"] == 1
        assert res["data"]["stadium"][0]["name"] == "翔安校区健身房"

def test_get_intervals(mock_client):
    api = XdtyApi(mock_client)
    with patch.object(mock_client.session, 'post') as mock_post:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": 1,
            "info": "查询成功",
            "data": {
                "venue_id": "14",
                "date_list": [{"date_int": "2026-09-11", "date": "09月11日", "week_int": "5", "week": "今天"}],
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
                                "selected": 94,
                                "max_count": 95,
                                "status": "available"
                            }
                        ]
                    }
                ]
            }
        }
        mock_post.return_value = mock_resp

        res = api.get_intervals(venue_id=14, stadium_id=16, category_id=8)
        assert res.status == 1
        slot = res.find_slot("2026-09-11", "19:30-21:00")
        assert slot is not None
        assert slot.interval_id == "3080"

def test_choose_verify(mock_client):
    api = XdtyApi(mock_client)
    with patch.object(mock_client.session, 'post') as mock_post:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": 1, "info": "", "data": []}
        mock_post.return_value = mock_resp

        res = api.choose_verify(stadium_id=16, venue_id=14, selected_slots=[{"interval_id": "3080"}])
        assert res["status"] == 1
        post_data = mock_post.call_args[1]["data"]
        assert "selected" in post_data
        assert json.loads(post_data["selected"])[0]["interval_id"] == "3080"

def test_add_order(mock_client):
    api = XdtyApi(mock_client)
    with patch.object(mock_client.session, 'post') as mock_post:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": 1, "info": "预约成功", "data": []}
        mock_post.return_value = mock_resp

        result = api.add_order(
            stadium_id=16,
            venue_id=14,
            stadium_name="翔安校区健身房",
            project_name="健身房",
            area_name="爱秋体育馆健身房",
            date="2026-09-11",
            week="5",
            week_msg="周五",
            interval_time="19:30-21:00",
            interval_id="3080",
            area_id="67",
            captcha="daxs"
        )
        assert result["status"] == 1
        assert result["info"] == "预约成功"
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["data"]["captcha"] == "daxs"
        assert call_kwargs["data"]["stadium_id"] == 16
        assert call_kwargs["data"]["details[0][interval_id]"] == "3080"

def test_my_subscribe(mock_client):
    api = XdtyApi(mock_client)
    with patch.object(mock_client.session, 'post') as mock_post:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": 1, "info": "查询成功", "data": []}
        mock_post.return_value = mock_resp

        res = api.my_subscribe(page=1)
        assert res["status"] == 1
        assert mock_post.call_args[1]["data"]["p"] == 1
