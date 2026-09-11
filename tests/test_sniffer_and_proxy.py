import os
import re
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from xdty_booking.auth.cert_generator import CertGenerator
from xdty_booking.auth.proxy_manager import WindowsProxyManager
from xdty_booking.auth.sniffer_proxy import SnifferProxy
from xdty_booking.auth.harvester_service import HarvestService
from xdty_booking.config import save_phpsessid, AppConfig, AuthConfig

def test_cert_generator():
    """测试自签名证书生成器是否能生成有效的 crt 与 key 文件"""
    gen = CertGenerator(target_domain="xdty.xmu.edu.cn")
    crt_path, key_path = gen.generate_cert_and_key()

    assert os.path.exists(crt_path)
    assert os.path.exists(key_path)

    with open(crt_path, "r", encoding="utf-8") as f:
        crt_content = f.read()
    with open(key_path, "r", encoding="utf-8") as f:
        key_content = f.read()

    assert "-----BEGIN CERTIFICATE-----" in crt_content
    assert "-----BEGIN RSA PRIVATE KEY-----" in key_content or "-----BEGIN PRIVATE KEY-----" in key_content

def test_save_phpsessid():
    """测试持久化回写 PHPSESSID 到配置文件"""
    yaml_content = """# 厦大体育馆自动预约配置文件示例
base_url: "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test"

auth:
  # 抓包或微信中获取的当前有效 PHPSESSID
  phpsessid: "old_token_123456"
  uid: "1073507"
  auto_harvest_enabled: true
"""
    with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".yaml", encoding="utf-8") as tmp:
        tmp.write(yaml_content)
        tmp_path = tmp.name

    try:
        new_token = "new_token_9876543210abcdef"
        success = save_phpsessid(tmp_path, new_token)
        assert success is True

        with open(tmp_path, "r", encoding="utf-8") as f:
            updated_content = f.read()

        assert f'phpsessid: "{new_token}"' in updated_content
        assert "# 厦大体育馆自动预约配置文件示例" in updated_content
        assert 'uid: "1073507"' in updated_content
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def test_sniffer_proxy_cookie_extraction():
    """测试 SnifferProxy 嗅探提取 Set-Cookie 中的 PHPSESSID"""
    proxy = SnifferProxy(host="127.0.0.1", port=18889)

    # 模拟真实 xdty.xmu.edu.cn loginByCode 响应
    mock_response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/json; charset=utf-8\r\n"
        b"Set-Cookie: PHPSESSID=93dec63b6bea28bfc3f0030543f3a0c9; path=/\r\n"
        b"Strict-Transport-Security: max-age=31536000\r\n\r\n"
        b'{"status": 1, "info": "login ok"}'
    )

    proxy._inspect_and_extract_cookie(mock_response)

    assert proxy.captured_token == "93dec63b6bea28bfc3f0030543f3a0c9"
    assert proxy.captured_event.is_set()

def test_sniffer_proxy_timeout():
    """测试 SnifferProxy 在超时时间内未收到 Token 的返回"""
    proxy = SnifferProxy(host="127.0.0.1", port=18890)
    token = proxy.wait_for_token(timeout=0.1)
    assert token is None

def test_windows_proxy_manager_context():
    """测试 WindowsProxyManager 上下文管理器的执行与还原"""
    mgr = WindowsProxyManager(proxy_server="127.0.0.1:8889")

    # 模拟环境验证 apply 与 restore 调用流
    with patch.object(mgr, "apply", wraps=mgr.apply) as mock_apply, \
         patch.object(mgr, "restore", wraps=mgr.restore) as mock_restore:
        with mgr:
            assert mock_apply.called
        assert mock_restore.called

def test_harvester_service_workflow():
    """测试 HarvestService 完整执行流（编排流程、捕获成功、持久化与收尾）"""
    cfg = AppConfig(
        auth=AuthConfig(
            phpsessid="",
            auto_harvest_enabled=True,
            wechat_appid="wx81a2b2fa90759cb7"
        )
    )

    with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".yaml", encoding="utf-8") as tmp:
        tmp.write("auth:\n  phpsessid: ''\n")
        tmp_path = tmp.name

    try:
        service = HarvestService(cfg, config_path=tmp_path, proxy_port=18891)

        with patch("xdty_booking.auth.harvester_service.WeChatHarvester.kill_miniprogram") as mock_kill, \
             patch("xdty_booking.auth.harvester_service.WeChatHarvester.launch_miniprogram", return_value=True) as mock_launch, \
             patch("xdty_booking.auth.harvester_service.WindowsProxyManager.apply") as mock_proxy_apply, \
             patch("xdty_booking.auth.harvester_service.WindowsProxyManager.restore") as mock_proxy_restore, \
             patch("xdty_booking.auth.harvester_service.SnifferProxy.start") as mock_proxy_start, \
             patch("xdty_booking.auth.harvester_service.SnifferProxy.stop") as mock_proxy_stop, \
             patch("xdty_booking.auth.harvester_service.SnifferProxy.wait_for_token", return_value="mock_captured_sessid"):

            token = service.harvest(timeout=5.0)

            assert token == "mock_captured_sessid"
            assert cfg.auth.phpsessid == "mock_captured_sessid"
            assert mock_kill.call_count >= 2  # 启动前杀一次，收尾杀一次
            assert mock_launch.called
            assert mock_proxy_apply.called
            assert mock_proxy_restore.called
            assert mock_proxy_start.called
            assert mock_proxy_stop.called
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
