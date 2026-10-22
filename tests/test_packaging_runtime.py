"""发布隔离和真实本地 HTTP 回归，不访问学校接口、不运行组件安装器。"""

import errno
import importlib.util
import json
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.request import ProxyHandler, build_opener

import pytest

from xdty_booking.runtime.http_server import LocalService, create_loopback_server
from xdty_booking.web.server import create_web_service


def load_packaging(name):
    path = Path(__file__).resolve().parents[1] / "packaging" / (name + ".py")
    spec = importlib.util.spec_from_file_location("test_packaging_" + name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_health_does_not_resolve_chinese_hostname_or_touch_business():
    with patch("socket.getfqdn", side_effect=UnicodeDecodeError("utf-8", b"\xcc", 0, 1, "invalid")), \
            patch("xdty_booking.web.server.query_gym_status", side_effect=AssertionError("business access")), \
            patch("xdty_booking.web.server.start_login_monitor", side_effect=AssertionError("monitor access")):
        service = create_web_service(port=0)
        try:
            service.start(timeout=2)
            with build_opener(ProxyHandler({})).open(service.url + "/healthz", timeout=2) as response:
                data = json.load(response)
            assert data["instance_id"] == service.server.instance_id
            assert data["app"] == "XMU_Gym_Booking"
        finally:
            service.close()
        assert not service.thread.is_alive()


def test_auto_port_keeps_bound_socket_and_does_not_steal_occupied_port():
    first = create_web_service(port=0)
    second = create_web_service(port=first.server.server_port, auto_port=True)
    try:
        assert first.server.server_port != second.server.server_port
        with pytest.raises(OSError):
            create_web_service(port=first.server.server_port, auto_port=False)
    finally:
        second.close()
        first.close()


def test_permission_failure_is_not_silently_reclassified():
    with patch("xdty_booking.runtime.http_server.LoopbackHTTPServer", side_effect=PermissionError(errno.EACCES, "denied")):
        with pytest.raises(PermissionError):
            create_web_service(auto_port=True)


def test_health_rejects_wrong_instance_and_closes_server():
    service = create_web_service(port=0)
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"app":"other","instance_id":"other"}'
    opener = MagicMock()
    opener.open.return_value = response
    with patch("xdty_booking.runtime.http_server.build_opener", return_value=opener):
        with pytest.raises(RuntimeError, match="其他应用实例"):
            service.start(timeout=2)
    assert not service.thread.is_alive()


def test_service_thread_error_is_reported_and_closed():
    service = create_web_service(port=0)
    with patch.object(service.server, "serve_forever", side_effect=RuntimeError("server failed")):
        with pytest.raises(RuntimeError):
            service.start(timeout=1)
    assert service.server.socket.fileno() == -1


def test_remote_bind_is_rejected():
    with pytest.raises(ValueError):
        create_web_service(host="0.0.0.0")


def test_missing_runtime_never_automatically_opens_browser():
    launcher = load_packaging("launcher")
    with patch.object(launcher, "check_single_instance", return_value=True), \
            patch.object(launcher, "release_single_instance") as release, \
            patch("xdty_booking.runtime.windows.runtime_version", return_value=""), \
            patch("xdty_booking.runtime.windows.repair_choice", return_value="exit"), \
            patch.object(launcher.webbrowser, "open") as browser, \
            patch("xdty_booking.web.server.create_web_service") as create:
        launcher.launch_desktop_window()
    browser.assert_not_called()
    create.assert_not_called()
    release.assert_called_once()


def test_gui_failure_goes_to_repair_not_browser():
    launcher = load_packaging("launcher")
    service = MagicMock()
    service.thread.is_alive.return_value = True
    with patch.object(launcher, "check_single_instance", return_value=True), \
            patch.object(launcher, "release_single_instance"), \
            patch("xdty_booking.runtime.windows.runtime_version", return_value="100.0.0.0"), \
            patch("xdty_booking.runtime.windows.repair_choice", return_value="exit") as repair, \
            patch("xdty_booking.web.server.create_web_service", return_value=service), \
            patch.object(launcher, "_run_gui", side_effect=RuntimeError("GUI failed")), \
            patch.object(launcher.webbrowser, "open") as browser:
        launcher.launch_desktop_window()
    repair.assert_called_once()
    browser.assert_not_called()
    service.close.assert_called_once()


def test_browser_requires_explicit_user_choice():
    launcher = load_packaging("launcher")
    service = MagicMock()
    with patch.object(launcher, "check_single_instance", return_value=True), \
            patch.object(launcher, "release_single_instance"), \
            patch("xdty_booking.runtime.windows.runtime_version", return_value=""), \
            patch("xdty_booking.runtime.windows.repair_choice", return_value="browser"), \
            patch("xdty_booking.web.server.create_web_service", return_value=service), \
            patch.object(launcher, "_browser_session") as browser:
        launcher.launch_desktop_window()
    service.start.assert_called_once()
    browser.assert_called_once_with(service)


def test_new_builds_preserve_all_existing_dist_files(tmp_path):
    builder = load_packaging("build_release")
    old = tmp_path / "dist" / "XMU_Gym_Booking"
    old.mkdir(parents=True)
    exe = old / "XMU_Gym_Booking.exe"
    exe.write_bytes(b"old portable app")
    archive = old.parent / "old-version.zip"
    archive.write_bytes(b"old release")
    snapshot = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in (exe, archive)}
    first, _ = builder.prepare_workspace("1.2.3", root=tmp_path)
    second, _ = builder.prepare_workspace("1.2.3", root=tmp_path)
    assert first != second
    assert snapshot == {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in (exe, archive)}


def test_release_version_cannot_escape_output_directory(tmp_path):
    builder = load_packaging("build_release")
    with pytest.raises(ValueError):
        builder.prepare_workspace("../../dist", root=tmp_path)


def test_source_staging_never_touches_development_security_files(tmp_path):
    builder = load_packaging("build_release")
    source = Path(builder.PROJECT_ROOT) / "xdty_booking" / "security" / "auth.py"
    before = source.read_bytes()
    stage = builder.stage_sources(tmp_path)
    (stage / "xdty_booking" / "security" / "auth.py").write_bytes(b"staging only")
    assert source.read_bytes() == before
    assert not (stage / "config" / "config.yaml").exists()


def test_checksums_include_only_current_artifacts(tmp_path):
    builder = load_packaging("build_release")
    old = tmp_path / "old.zip"
    old.write_bytes(b"old")
    current = tmp_path / "current.zip"
    current.write_bytes(b"new")
    builder.generate_sha256sums([current], tmp_path)
    content = (tmp_path / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert "current.zip" in content and "old.zip" not in content


def test_setup_is_required_before_creating_release_directory():
    builder = load_packaging("build_release")
    with patch.object(builder, "check_dependencies", return_value={}), \
            patch.object(builder, "find_iscc", return_value=None), \
            patch.object(builder, "prepare_workspace") as prepare:
        with pytest.raises(RuntimeError, match="Inno Setup"):
            builder.main([])
    prepare.assert_not_called()


def test_explicit_inno_compiler_path_can_contain_spaces(tmp_path):
    builder = load_packaging("build_release")
    compiler = tmp_path / "Inno Setup 6" / "ISCC.exe"
    compiler.parent.mkdir()
    compiler.write_bytes(b"test compiler")
    assert builder.find_iscc(compiler) == str(compiler.resolve())
    with pytest.raises(FileNotFoundError):
        builder.find_iscc(compiler.parent / "missing.exe")


def test_lightweight_build_rejects_offline_installer_without_creating_output(tmp_path):
    builder = load_packaging("build_release")
    offline = tmp_path / "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
    offline.write_bytes(b"test offline installer")
    with patch.object(builder, "check_dependencies", return_value={}), \
            patch.object(builder, "find_iscc", return_value="ISCC.exe"), \
            patch.object(builder, "prepare_workspace") as prepare:
        with pytest.raises(ValueError, match="Bootstrapper"):
            builder.main(["--runtime-installer", str(offline)])
    prepare.assert_not_called()


def test_installed_data_migration_is_copy_only(tmp_path):
    from xdty_booking.runtime import paths
    app, data = tmp_path / "app", tmp_path / "user"
    (app / "config").mkdir(parents=True)
    (app / "license.lic").write_text("license", encoding="utf-8")
    (app / "config" / "config.yaml").write_text("old", encoding="utf-8")
    (data / "config").mkdir(parents=True)
    (data / "config" / "config.yaml").write_text("current", encoding="utf-8")
    with patch.object(paths, "application_dir", return_value=app), patch.object(paths, "data_dir", return_value=data):
        paths.prepare_data_dir()
    assert (data / "license.lic").read_text() == "license"
    assert (app / "license.lic").read_text() == "license"
    assert (data / "config" / "config.yaml").read_text() == "current"


def test_runtime_installation_verifies_signature_and_result(tmp_path):
    from xdty_booking.runtime import windows
    installer = tmp_path / "prerequisites" / windows.RUNTIME_INSTALLER
    installer.parent.mkdir()
    installer.write_bytes(b"test only")
    with patch.object(windows, "verify_microsoft_installer", side_effect=RuntimeError("untrusted")), \
            patch.object(windows.subprocess, "run") as run:
        with pytest.raises(RuntimeError, match="untrusted"):
            windows.install_runtime(tmp_path)
    run.assert_not_called()


def test_repair_restart_limit_prevents_loop():
    launcher = load_packaging("launcher")
    with patch.dict("os.environ", {"XMU_REPAIR_RESTARTS": "2"}), patch("subprocess.Popen") as launch:
        with pytest.raises(RuntimeError):
            launcher._restart_application()
    launch.assert_not_called()


def test_frozen_self_test_failure_blocks_release_without_touching_original(tmp_path):
    builder = load_packaging("build_release")
    target = tmp_path / "app"
    target.mkdir()
    (target / "XMU_Gym_Booking.exe").write_bytes(b"test only")
    work, output = tmp_path / "work", tmp_path / "output"
    work.mkdir()
    output.mkdir()

    def failed_test(command, **kwargs):
        (output / "self-test.json").write_text('{"ok":false}', encoding="utf-8")
        return MagicMock(returncode=1)

    with patch.object(builder.subprocess, "run", side_effect=failed_test):
        with pytest.raises(RuntimeError, match="self-test failed"):
            builder.smoke_test_payload(target, output, work)
    assert (target / "XMU_Gym_Booking.exe").read_bytes() == b"test only"
    assert not (target / "config").exists()


def test_gui_repair_restarts_instead_of_reusing_failed_clr():
    launcher = load_packaging("launcher")
    service = MagicMock()
    service.thread.is_alive.return_value = True
    with patch.object(launcher, "check_single_instance", return_value=True), \
            patch.object(launcher, "release_single_instance"), \
            patch("xdty_booking.runtime.windows.runtime_version", return_value="100.0.0.0"), \
            patch("xdty_booking.runtime.windows.repair_choice", return_value="retry"), \
            patch("xdty_booking.web.server.create_web_service", return_value=service), \
            patch.object(launcher, "_run_gui", side_effect=RuntimeError("GUI failed")) as gui, \
            patch.object(launcher, "_restart_application") as restart:
        launcher.launch_desktop_window()
    gui.assert_called_once()
    service.close.assert_called_once()
    restart.assert_called_once()
