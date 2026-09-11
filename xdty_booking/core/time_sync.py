import time
import requests
import email.utils
import logging

logger = logging.getLogger(__name__)

class TimeSync:
    """
    通过服务端 HTTP Date 响应头精确校准本地与服务端的时间偏差 (毫秒级精度)
    """
    @staticmethod
    def get_server_time_offset(url: str = "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test") -> float:
        try:
            t0 = time.time()
            resp = requests.head(url, timeout=5)
            t1 = time.time()
            rtt = t1 - t0
            date_str = resp.headers.get("Date")
            if date_str:
                server_timestamp = email.utils.parsedate_to_datetime(date_str).timestamp()
                # 预估收到响应头瞬间的服务端时间 (补偿 1/2 RTT 网络延时)
                estimated_server_time = server_timestamp + (rtt / 2.0)
                offset = estimated_server_time - t1
                logger.info(f"服务端时间校准成功，时间差偏移: {offset * 1000.0:+.1f} ms")
                return offset
        except Exception as e:
            logger.warning(f"服务端时间校准未成功 ({e})，将默认使用系统本地时间")
        return 0.0

    @staticmethod
    def wait_until(target_timestamp: float, offset: float = 0.0, advance_ms: int = 200):
        """
        高精度等待直至目标时刻（考虑时间偏移与提前探测毫秒数）
        """
        effective_target = target_timestamp - offset - (advance_ms / 1000.0)
        while True:
            now = time.time()
            remaining = effective_target - now
            if remaining <= 0:
                break
            elif remaining > 0.1:
                # 粗粒度休眠节省 CPU
                time.sleep(remaining - 0.05)
            else:
                # 毫秒级自旋等待，确保极速触发
                pass
