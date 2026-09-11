from unittest.mock import patch, Mock
import os
from xdty_booking.auth.wechat_harvester import WeChatHarvester

def test_wechat_harvester_init():
    harvester = WeChatHarvester(appid="wx81a2b2fa90759cb7")
    assert harvester.appid == "wx81a2b2fa90759cb7"

@patch("subprocess.Popen")
def test_wechat_harvester_launch(mock_popen):
    harvester = WeChatHarvester(appid="wx81a2b2fa90759cb7")
    with patch("os.path.exists", return_value=True):
        ok = harvester.launch_miniprogram(executable_path="C:\\mock\\WeChatAppEx.exe")
        assert ok is True
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert "C:\\mock\\WeChatAppEx.exe" in call_args
        assert "--app_id=wx81a2b2fa90759cb7" in call_args

def test_wechat_harvester_launch_not_found():
    harvester = WeChatHarvester()
    with patch.object(harvester, 'find_wechat_appex', return_value=None):
        ok = harvester.launch_miniprogram()
        assert ok is False
