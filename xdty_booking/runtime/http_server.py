"""本地 HTTP 服务：不做主机名解析，并确认当前实例真正可响应。"""

import errno
import json
import os
import secrets
import socket
import socketserver
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import ProxyHandler, build_opener


class LoopbackHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class IPv6LoopbackHTTPServer(LoopbackHTTPServer):
    address_family = socket.AF_INET6


def create_loopback_server(handler, port=8080, host="127.0.0.1", auto_port=False):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Web 控制台只允许监听本机回环地址")
    host = "127.0.0.1" if host == "localhost" else host
    server_class = IPv6LoopbackHTTPServer if host == "::1" else LoopbackHTTPServer
    try:
        server = server_class((host, port), handler)
    except OSError as exc:
        if not auto_port or (exc.errno not in (errno.EADDRINUSE, 10048) and
                             getattr(exc, "winerror", None) != 10048):
            raise
        server = server_class((host, 0), handler)
    server.instance_id = secrets.token_hex(24)
    return server


class LocalService:
    """管理已绑定的服务；健康检查不会经过系统代理或业务接口。"""

    def __init__(self, server, on_stop=None):
        self.server = server
        host, port = server.server_address[:2]
        self.url = "http://{}:{}".format("[{}]".format(host) if ":" in host else host, port)
        self.error = None
        self.thread = None
        self._on_stop = on_stop
        self._closed = False

    def start(self, timeout=15.0):
        if self.thread is not None:
            raise RuntimeError("服务已经启动")

        def serve():
            try:
                self.server.serve_forever(poll_interval=0.1)
            except Exception as exc:
                self.error = exc
            finally:
                self.server.server_close()

        self.thread = threading.Thread(target=serve, name="LocalHTTP", daemon=True)
        self.thread.start()
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if not self.thread.is_alive():
                    raise RuntimeError("本地服务线程提前退出") from self.error
                try:
                    with opener.open(self.url + "/healthz", timeout=min(0.5, max(0.01, deadline - time.monotonic()))) as response:
                        data = json.loads(response.read(4096).decode("utf-8"))
                    if data.get("app") == "XMU_Gym_Booking" and data.get("instance_id") == self.server.instance_id:
                        return self
                    raise RuntimeError("健康检查返回了其他应用实例")
                except (OSError, ValueError):
                    time.sleep(0.05)
            raise TimeoutError("本地服务未在限定时间内就绪")
        except Exception:
            self.close()
            raise

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._on_stop:
                self._on_stop()
        finally:
            if self.thread and self.thread.is_alive():
                self.server.shutdown()
                self.thread.join(timeout=3)
            self.server.server_close()
