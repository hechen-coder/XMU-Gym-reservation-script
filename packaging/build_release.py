#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Isolated release builder. Existing dist files are never removed or overwritten."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGING_DIR = PROJECT_ROOT / "packaging"
APP_NAME = "XMU_Gym_Booking"
VERSION = json.loads((PACKAGING_DIR / "version.json").read_text(encoding="utf-8"))["version"]
RUNTIME_NAME = "MicrosoftEdgeWebview2Setup.exe"


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def find_iscc(explicit=None):
    if explicit is not None:
        if not Path(explicit).is_file():
            raise FileNotFoundError("Inno Setup compiler not found: " + str(explicit))
        return str(Path(explicit).resolve())
    candidates = [shutil.which("iscc"), os.environ.get("ISCC_PATH"),
                  r"D:\Inno Setup 6\ISCC.exe",
                  r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
                  r"C:\Program Files\Inno Setup 6\ISCC.exe"]
    return next((str(p) for p in candidates if p and Path(p).is_file()), None)


def check_dependencies(obfuscate=True):
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise RuntimeError("Release builds require Windows x64")
    if sys.version_info[:2] != (3, 8):
        raise RuntimeError("This release baseline requires Python 3.8; no automatic upgrade is performed")
    required = ["PyInstaller", "pyinstaller-hooks-contrib", "pywebview", "pythonnet", "ddddocr",
                "onnxruntime", "Pillow", "numpy", "requests", "PyYAML", "rsa", "cryptography", "psutil"]
    if obfuscate:
        required.append("pyarmor")
    versions = {}
    for name in required:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            raise RuntimeError("Missing build dependency: {}. Install the verified constraints first.".format(name))
    constraints = PACKAGING_DIR / "constraints-python38.txt"
    for line in constraints.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, expected = line.split("==", 1)
            if name in versions and versions[name] != expected:
                raise RuntimeError("Dependency mismatch: {} expected {}, found {}".format(name, expected, versions[name]))
    # Distribution metadata alone does not prove that native extension DLLs load.
    probe = subprocess.run([sys.executable, "-c",
                            "import onnxruntime, ddddocr, clr; "
                            "from cryptography.hazmat.backends.openssl.backend import backend; "
                            "print(backend.openssl_version_text())"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    if probe.returncode:
        raise RuntimeError("Native dependency self-check failed; repair the build environment before publishing:\n" + probe.stderr)
    return versions


def prepare_workspace(version, root=PROJECT_ROOT):
    # mkdir(exist_ok=False) plus an unpredictable suffix prevents same-version overwrite.
    if not version or any(c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-" for c in version):
        raise ValueError("Invalid release version")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    root = Path(root).resolve()
    output = root / "dist" / "releases" / ("v" + version) / run_id
    work = root / "build" / "releases" / run_id
    output.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True, exist_ok=False)
    return output, work


def stage_sources(work):
    stage = Path(work) / "source"
    stage.mkdir(exist_ok=False)
    for folder in ("xdty_booking", "cas_qr_login"):
        for source in (PROJECT_ROOT / folder).rglob("*.py"):
            if "__pycache__" in source.parts:
                continue
            destination = stage / source.relative_to(PROJECT_ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source), str(destination))
    for name in ("main.py", "query_gym.py", "LICENSE"):
        shutil.copy2(str(PROJECT_ROOT / name), str(stage / name))
    for name in ("config.example.yaml", "config.advanced.example.yaml"):
        destination = stage / "config" / name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(str(PROJECT_ROOT / "config" / name), str(destination))
    (stage / "packaging").mkdir()
    for name in ("launcher.py", "XMU_Gym_Booking.spec", "hook-cv2-mock.py", "app_icon.ico", "app.manifest"):
        shutil.copy2(str(PACKAGING_DIR / name), str(stage / "packaging" / name))
    return stage


def build_application(stage, work, output, obfuscate=True, version=VERSION):
    components = version.split("-", 1)[0].split(".")
    numeric = tuple((int(part) if part.isdigit() else 0) for part in components[:4])
    numeric = numeric + (0,) * (4 - len(numeric))
    if any(number > 65535 for number in numeric):
        raise ValueError("Windows version components must be <= 65535")
    version_text = (
        "VSVersionInfo(ffi=FixedFileInfo(filevers={0!r}, prodvers={0!r}, "
        "mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), "
        "kids=[StringFileInfo([StringTable('040904B0', [StringStruct('FileVersion', {1!r}), "
        "StringStruct('ProductVersion', {1!r}), StringStruct('ProductName', 'XMU Gym Booking')])]), "
        "VarFileInfo([VarStruct('Translation', [1033,1200])])])"
    ).format(numeric, version)
    (stage / "packaging" / "version-info.txt").write_text(version_text, encoding="utf-8")
    if obfuscate:
        obf = Path(work) / "obfuscated"
        subprocess.check_call([sys.executable, "-m", "pyarmor.cli", "gen", "-i", "-O", str(obf),
                               "-r", str(stage / "xdty_booking" / "security")], cwd=str(stage))
        generated = obf / "security"
        if not generated.is_dir() or not list(generated.glob("pyarmor_runtime_*")):
            raise RuntimeError("PyArmor output is incomplete; release stopped")
        for source in (stage / "xdty_booking" / "security").glob("*.py"):
            if not (generated / source.name).is_file():
                raise RuntimeError("PyArmor omitted " + source.name)
        shutil.copytree(str(generated), str(stage / "xdty_booking" / "security"), dirs_exist_ok=True)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    subprocess.check_call([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
                           "--distpath", str(output), "--workpath", str(Path(work) / "pyinstaller"),
                           str(stage / "packaging" / "XMU_Gym_Booking.spec")], cwd=str(stage), env=env)
    target = Path(output) / APP_NAME
    if not (target / (APP_NAME + ".exe")).is_file():
        raise RuntimeError("PyInstaller did not produce the application")
    return target


def verify_payload(target):
    target = Path(target)
    required = [APP_NAME + ".exe", "_internal/python38.dll", "config/config.example.yaml",
                "prerequisites/" + RUNTIME_NAME, "_internal/ddddocr/common_old.onnx",
                "_internal/webview/lib/Microsoft.Web.WebView2.Core.dll",
                "_internal/webview/lib/Microsoft.Web.WebView2.WinForms.dll",
                "_internal/webview/lib/runtimes/win-x64/native/WebView2Loader.dll"]
    missing = [name for name in required if not (target / name).is_file()]
    if missing:
        raise RuntimeError("Missing payload files: " + ", ".join(missing))
    forbidden = {"config.yaml", "auth_cookies.json", "session.json", "license.lic", ".auth_state"}
    for path in target.rglob("*"):
        if path.is_file() and (path.name.lower() in forbidden or path.suffix.lower() in (".log", ".key")
                               or (path.suffix.lower() == ".pem" and path.relative_to(target).as_posix() != "_internal/certifi/cacert.pem")):
            raise RuntimeError("Private/runtime file in release: " + str(path.relative_to(target)))


def assemble_payload(target, runtime, metadata):
    target = Path(target)
    config = target / "config"
    config.mkdir(exist_ok=True)
    for name in ("config.example.yaml", "config.advanced.example.yaml"):
        shutil.copy2(str(PROJECT_ROOT / "config" / name), str(config / name))
    prerequisites = target / "prerequisites"
    prerequisites.mkdir()
    shutil.copy2(str(runtime), str(prerequisites / RUNTIME_NAME))
    shutil.copy2(str(PACKAGING_DIR / "app_icon.ico"), str(target / "app_icon.ico"))
    shutil.copy2(str(PACKAGING_DIR / "USER_GUIDE.txt"), str(target / "USER_GUIDE.txt"))
    shutil.copy2(str(PROJECT_ROOT / "LICENSE"), str(target / "LICENSE"))
    (target / "portable-mode").write_text("portable\n", encoding="utf-8")
    (target / "build-info.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    verify_payload(target)
    manifest = {p.relative_to(target).as_posix(): {"size": p.stat().st_size, "sha256": digest(p)}
                for p in sorted(target.rglob("*")) if p.is_file()}
    (target / "file-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def make_portable_zip(target, output, version):
    verify_payload(target)
    destination = Path(output) / (APP_NAME + "_v" + version + "_Portable_Windows_x64.zip")
    with zipfile.ZipFile(str(destination), "x", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(Path(target).rglob("*")):
            if path.is_file():
                archive.write(str(path), APP_NAME + "/" + path.relative_to(target).as_posix())
    return destination


def build_installer(target, output, version, compiler):
    subprocess.check_call([compiler, "/DMyAppVersion=" + version,
                           "/DSourceDir=" + str(Path(target).resolve()),
                           "/DReleaseOutput=" + str(Path(output).resolve()),
                           str(PACKAGING_DIR / "installer.iss")], cwd=str(PACKAGING_DIR))
    destination = Path(output) / (APP_NAME + "_Setup_v" + version + ".exe")
    if not destination.is_file():
        raise RuntimeError("Setup output is missing")
    return destination


def smoke_test_payload(target, output, work):
    # Run a copy: first-run config/logs must never contaminate the distributable tree.
    test_target = Path(work) / "self-test" / APP_NAME
    shutil.copytree(str(target), str(test_target))
    report = Path(output) / "self-test.json"
    process = subprocess.run([str(test_target / (APP_NAME + ".exe")), "self-test", "--output", str(report)],
                             cwd=str(test_target), timeout=120)
    if process.returncode or not report.is_file() or not json.loads(report.read_text(encoding="utf-8")).get("ok"):
        raise RuntimeError("Frozen application self-test failed; see " + str(report))


def generate_sha256sums(artifacts, output):
    destination = Path(output) / "SHA256SUMS.txt"
    with destination.open("x", encoding="utf-8") as stream:
        for path in artifacts:
            stream.write(digest(path) + "  " + Path(path).name + "\n")
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--runtime-installer", type=Path,
                        default=PACKAGING_DIR / "prerequisites" / RUNTIME_NAME)
    parser.add_argument("--iscc", type=Path, help="Explicit path to Inno Setup 6 ISCC.exe")
    parser.add_argument("--portable-only", action="store_true", help="Development ZIP build; not a complete dual-artifact release")
    parser.add_argument("--no-obfuscation", action="store_true", help="Explicitly build without PyArmor and record this in metadata")
    parser.add_argument("--check", action="store_true", help="Validate prerequisites without creating release files")
    args = parser.parse_args(argv)
    versions = check_dependencies(not args.no_obfuscation)
    compiler = find_iscc(args.iscc)
    if not args.portable_only and not compiler:
        raise RuntimeError("Inno Setup 6 is required for ZIP + Setup releases; existing dist is untouched")
    if not args.runtime_installer.is_file():
        raise FileNotFoundError("Provide Microsoft's small Evergreen Bootstrapper using --runtime-installer")
    if args.runtime_installer.name.lower() != RUNTIME_NAME.lower():
        raise ValueError("This lightweight release requires MicrosoftEdgeWebview2Setup.exe (Evergreen Bootstrapper), not the offline installer")
    sys.path.insert(0, str(PROJECT_ROOT))
    from xdty_booking.runtime.windows import verify_microsoft_installer
    verify_microsoft_installer(args.runtime_installer)
    if args.check:
        print("Build prerequisites verified; existing dist is untouched")
        return 0
    output, work = prepare_workspace(args.version)
    metadata = {"version": args.version, "python": sys.version, "architecture": platform.machine(),
                "dependencies": versions, "obfuscated": not args.no_obfuscation,
                "runtime_installer_sha256": digest(args.runtime_installer),
                "runtime_install_mode": "evergreen-bootstrapper-online",
                "created_utc": datetime.now(timezone.utc).isoformat(), "validation": "pending-clean-Windows-QA"}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    metadata["commit"] = commit.stdout.strip() if commit.returncode == 0 else None
    (output / "BUILD_INCOMPLETE").write_text("Do not publish before this build succeeds.\n", encoding="utf-8")
    stage = stage_sources(work)
    target = build_application(stage, work, output, not args.no_obfuscation, args.version)
    assemble_payload(target, args.runtime_installer, metadata)
    smoke_test_payload(target, output, work)
    artifacts = [make_portable_zip(target, output, args.version)]
    if not args.portable_only:
        artifacts.append(build_installer(target, output, args.version, compiler))
    generate_sha256sums(artifacts, output)
    notes = ("# XMU Gym Booking v" + args.version + "\n\n"
             "Portable ZIP: extract the complete directory and run the included EXE.\n"
             "Setup EXE: install the same application and shortcuts.\n"
             "Missing WebView2: use the in-app native repair prompt; no automatic browser fallback.\n"
             "The bundled small Microsoft bootstrapper requires internet only when installing or repairing WebView2.\n"
             "Build completed; clean-Windows UI and OCR acceptance is still required before publishing.\n")
    (output / "release-notes.md").write_text(notes, encoding="utf-8")
    (output / "BUILD_INCOMPLETE").unlink()
    print("Build completed: " + str(output))
    print("Existing dist releases preserved. Clean-Windows acceptance remains required.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("BUILD FAILED: " + str(exc), file=sys.stderr)
        sys.exit(1)
