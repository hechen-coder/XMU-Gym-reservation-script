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
    with patch.object(harvester, 'find_and_activate_window', return_value=False):
        with patch.object(harvester, 'find_desktop_shortcut', return_value=None):
            with patch.object(harvester, 'launch_by_protocol', return_value=False):
                with patch.object(harvester, 'find_wechat_appex', return_value=None):
                    ok = harvester.launch_miniprogram()
                    assert ok is False

def test_wechat_harvester_launch_by_protocol():
    harvester = WeChatHarvester(appid="wx81a2b2fa90759cb7")
    with patch.object(harvester, 'find_and_activate_window', return_value=False):
        with patch.object(harvester, 'find_desktop_shortcut', return_value=None):
            with patch("os.startfile") as mock_startfile:
                ok = harvester.launch_miniprogram()
                assert ok is True
                mock_startfile.assert_called_once_with("weixin://launchapplet/?app_id=wx81a2b2fa90759cb7")

def test_wechat_harvester_launch_by_window():
    harvester = WeChatHarvester()
    with patch.object(harvester, 'find_and_activate_window', return_value=True):
        ok = harvester.launch_miniprogram()
        assert ok is True

def test_wechat_harvester_launch_by_shortcut():
    harvester = WeChatHarvester()
    with patch.object(harvester, 'find_and_activate_window', return_value=False):
        with patch.object(harvester, 'find_desktop_shortcut', return_value="C:\\mock\\厦大体育.lnk"):
            with patch("os.startfile") as mock_startfile:
                ok = harvester.launch_miniprogram()
                assert ok is True
                mock_startfile.assert_called_once_with("C:\\mock\\厦大体育.lnk")

def test_find_wechat_appex_from_process():
    harvester = WeChatHarvester()
    mock_proc = Mock()
    mock_proc.info = {"name": "WeChatAppEx.exe", "exe": "C:\\Tencent\\xwechat\\WeChatAppEx.exe"}
    with patch("psutil.process_iter", return_value=[mock_proc]):
        with patch("os.path.isfile", return_value=True):
            found = harvester.find_wechat_appex()
            assert found == "C:\\Tencent\\xwechat\\WeChatAppEx.exe"

def test_find_wechat_appex_from_directory_scan():
    harvester = WeChatHarvester()
    with patch("psutil.process_iter", return_value=[]):
        with patch("os.path.exists", return_value=True):
            with patch("os.path.isfile", return_value=False):
                with patch("os.walk", return_value=[("C:\\AppData\\Tencent\\xwechat\\runtime", [], ["WeChatAppEx.exe"])]):
                    found = harvester.find_wechat_appex()
                    assert found is not None
                    assert "WeChatAppEx.exe" in found

