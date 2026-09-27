#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
单实例运行防护与多进程拦截测试 (Single Instance Mutex & Port Conflict Tests)
"""

import sys
from pathlib import Path
import importlib.util
from unittest.mock import MagicMock, patch
import pytest

# 动态加载 packaging/launcher.py，避免与 site-packages 中的 third-party 'packaging' 库冲突
launcher_path = Path(__file__).resolve().parent.parent / "packaging" / "launcher.py"
spec = importlib.util.spec_from_file_location("packaging_launcher", str(launcher_path))
launcher_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher_mod)

check_single_instance = launcher_mod.check_single_instance
release_single_instance = launcher_mod.release_single_instance

from xdty_booking.web.server import run_server


def test_check_single_instance_first_run():
    """测试首次运行应用能够正常获取互斥体并返回 True"""
    launcher_mod._SINGLE_INSTANCE_MUTEX = None

    mock_kernel32 = MagicMock()
    mock_kernel32.CreateMutexW.return_value = 12345
    mock_kernel32.GetLastError.return_value = 0

    mock_ctypes = MagicMock()
    mock_ctypes.windll.kernel32 = mock_kernel32

    with patch.object(sys, "platform", "win32"), patch.dict("sys.modules", {"ctypes": mock_ctypes}):
        result = check_single_instance(show_dialog=False)
        assert result is True
        assert launcher_mod._SINGLE_INSTANCE_MUTEX == 12345

    # 清理仍需在模拟 Windows 环境内执行。
    with patch.object(sys, "platform", "win32"), patch.dict("sys.modules", {"ctypes": mock_ctypes}):
        release_single_instance()
    assert launcher_mod._SINGLE_INSTANCE_MUTEX is None


def test_check_single_instance_already_running():
    """测试二次启动时检测到已打开，激活前台窗口并返回 False 且显示提示"""
    launcher_mod._SINGLE_INSTANCE_MUTEX = None

    ERROR_ALREADY_EXISTS = 183
    mock_kernel32 = MagicMock()
    mock_kernel32.CreateMutexW.return_value = 99999
    mock_kernel32.GetLastError.return_value = ERROR_ALREADY_EXISTS

    mock_user32 = MagicMock()
    mock_user32.FindWindowW.return_value = 54321

    mock_ctypes = MagicMock()
    mock_ctypes.windll.kernel32 = mock_kernel32
    mock_ctypes.windll.user32 = mock_user32

    with patch.object(sys, "platform", "win32"), patch.dict("sys.modules", {"ctypes": mock_ctypes}):
        result = check_single_instance(app_title="厦大体育馆自动预约工具", show_dialog=True)
        assert result is False
        # 验证是否查找已有窗口并调用 ShowWindow 激活
        mock_user32.FindWindowW.assert_called_once_with(None, "厦大体育馆自动预约工具")
        mock_user32.ShowWindow.assert_called_once_with(54321, 9)
        mock_user32.SetForegroundWindow.assert_called_once_with(54321)
        # 验证是否弹出提示信息
        mock_user32.MessageBoxW.assert_called_once()
        args, _ = mock_user32.MessageBoxW.call_args
        assert "已在运行中（已打开）" in args[1]


def test_check_single_instance_non_windows():
    """测试在非 Windows 系统上直接放行返回 True"""
    with patch.object(sys, "platform", "darwin"):
        assert check_single_instance() is True


def test_run_server_port_conflict():
    """测试 Web 服务端口被占用时优雅处理 OSError 异常而不崩溃"""
    with patch("xdty_booking.web.server.ThreadingHTTPServer", side_effect=OSError(10048, "Address already in use")):
        # 不应抛出异常，而是优雅返回
        run_server(port=8080)
