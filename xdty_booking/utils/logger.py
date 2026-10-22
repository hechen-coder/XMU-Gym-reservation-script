import logging
import sys
from logging.handlers import RotatingFileHandler

class SafeStreamHandler(logging.StreamHandler):
    """防止在 Windows GBK/cp936 终端下因 emoji 或特殊字符抛出 UnicodeEncodeError"""
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            try:
                stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                encoding = getattr(stream, "encoding", "utf-8") or "utf-8"
                safe_msg = msg.encode(encoding, errors="replace").decode(encoding)
                stream.write(safe_msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

def setup_logger(name: str = "xdty_booking", level: int = logging.INFO) -> logging.Logger:
    """创建并配置统一的控制台与格式化日志器（同时输出到控制台和 booking.log 文件）"""
    root_logger = logging.getLogger()
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    if not root_logger.handlers:
        root_logger.setLevel(level)
        handler = SafeStreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    # 确保同时写入 logs/booking.log 文件，保持根目录整洁，方便桌面端托盘直接查看
    has_file_handler = any(isinstance(h, logging.FileHandler) and
                           h.baseFilename.endswith("booking.log") for h in root_logger.handlers)
    if not has_file_handler:
        try:
            import os
            if getattr(sys, "frozen", False):
                from xdty_booking.runtime.paths import data_dir
                app_dir = str(data_dir())
            else:
                app_dir = os.getcwd()
            if getattr(sys, "frozen", False):
                from xdty_booking.runtime.paths import log_dir
                logs_dir = str(log_dir())
            else:
                logs_dir = os.path.join(app_dir, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            log_path = os.path.join(logs_dir, "booking.log")
            file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024,
                                              backupCount=3, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception:
            pass

    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger
