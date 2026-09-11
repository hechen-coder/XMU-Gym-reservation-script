import logging
import sys

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
    """创建并配置统一的控制台与格式化日志器"""
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        root_logger.setLevel(level)
        handler = SafeStreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger
