"""应用资源与用户数据目录；保留便携版的原有配置和授权位置。"""

import os
import shutil
import sys
from pathlib import Path


def application_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def data_dir():
    app = application_dir()
    if getattr(sys, "frozen", False) and (app / "installed-mode").exists():
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "XMU_Gym_Booking"
    return app


def log_dir():
    import tempfile
    candidates = [data_dir() / "logs", Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "XMU_Gym_Booking" / "logs"]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=str(candidate)):
                pass
            return candidate
        except OSError:
            continue
    raise PermissionError("日志目录不可写，请将完整便携包解压到用户可写目录")


def prepare_data_dir():
    app, target = application_dir(), data_dir()
    target.mkdir(parents=True, exist_ok=True)
    # 迁移仅复制、从不覆盖已有数据。保留原始文件作为升级回退依据。
    if target != app:
        for relative in ("config", "license.lic", "data"):
            source, destination = app / relative, target / relative
            if source.is_file() and not destination.exists():
                shutil.copy2(str(source), str(destination))
            elif source.is_dir():
                for item in source.rglob("*"):
                    output = destination / item.relative_to(source)
                    if item.is_file() and not output.exists():
                        output.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(item), str(output))
    config = target / "config"
    config.mkdir(exist_ok=True)
    roots = (app, Path(getattr(sys, "_MEIPASS", str(app))))
    for name in ("config.example.yaml", "config.advanced.example.yaml"):
        destination = config / name
        if not destination.exists():
            for root in roots:
                source = root / "config" / name
                if source.is_file():
                    shutil.copy2(str(source), str(destination))
                    break
    # 在启动业务模块前验证可写性，不悄悄把便携数据移到另一处。
    import tempfile
    with tempfile.TemporaryFile(dir=str(target)):
        pass
    return target
