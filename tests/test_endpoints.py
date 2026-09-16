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

def test_get_stadium_details(mock_client):
    api = XdtyApi(mock_client)
    with patch.object(mock_client.session, 'post') as mock_post:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": 1, "info": "查询成功", "data": {"name": "翔安校区健身房", "user_range": "[67]"}}
        mock_post.return_value = mock_resp

        res = api.get_stadium_details(stadium_id=16)
        assert res["status"] == 1
        assert res["data"]["name"] == "翔安校区健身房"

def test_get_intervals_auto_retry_on_param_error(mock_client):
    api = XdtyApi(mock_client)
    with patch.object(mock_client.session, 'post') as mock_post:
        resp_err = Mock()
        resp_err.status_code = 200
        resp_err.json.return_value = {"status": 0, "info": "参数错误", "data": []}

        resp_det = Mock()
        resp_det.status_code = 200
        resp_det.json.return_value = {"status": 1, "data": {"user_range": "[67]"}}

        resp_ok = Mock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = {"status": 1, "info": "查询成功", "data": {"date_list": [], "time_slot_list": []}}

        mock_post.side_effect = [resp_err, resp_det, resp_ok]

        res = api.get_intervals(venue_id=14, stadium_id=16, category_id=8)
        assert res.status == 1
        assert res.info == "查询成功"
        assert mock_post.call_count == 3

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

def test_generate_captcha_sign():
    # Verify MD5 signature formula
    sign = XdtyApi.generate_captcha_sign(r=0.5, t=1700000000, uid="1073507")
    assert isinstance(sign, str)
    assert len(sign) == 32

def test_get_captcha(mock_client):
    api = XdtyApi(mock_client, uid="1073507")
    with patch.object(mock_client.session, 'get') as mock_get:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "image/png"}
        mock_resp.content = b"\x89PNG\r\n\x1a\nfake_image"
        mock_get.return_value = mock_resp

        data = api.get_captcha()
        assert data.startswith(b"\x89PNG")
        assert mock_get.called
        call_url, call_kwargs = mock_get.call_args
        assert "public/index.php/index/index/captcha" in call_url[0]
        assert "sign" in call_kwargs["params"]
        assert "r" in call_kwargs["params"]
        assert "t" in call_kwargs["params"]

def test_get_uid_auto(mock_client):
    api = XdtyApi(mock_client)
    with patch.object(mock_client.session, 'post') as mock_post:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": 1,
            "info": "查询成功",
            "data": [{"uid": "1073507", "order_id": 123}]
        }
        mock_post.return_value = mock_resp

        uid = api.get_uid()
        assert uid == "1073507"
        assert api._uid == "1073507"

