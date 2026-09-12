import re
import ssl
import socket
import select
import logging
import threading
from typing import Optional, Tuple, Callable
from xdty_booking.auth.cert_generator import CertGenerator

logger = logging.getLogger(__name__)

class SnifferProxy:
    """
    轻量级本地透明嗅探代理服务器：
    1. 监听本地端口（默认 127.0.0.1:8889）；
    2. 针对目标域名 xdty.xmu.edu.cn 执行 MITM TLS 解密或 HTTP 嗅探；
    3. 截获返回或携带的 Set-Cookie/Cookie: PHPSESSID=...；
    4. 对所有非目标域名的流量自动进行透明 TCP 双向直连转发，完全不干扰其他程序；
    5. 支持在线实机验证 token_validator，过滤握手空会话，确认有效后才触发捕获完成。
    """
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8889,
        target_domain: str = "xdty.xmu.edu.cn",
        token_validator: Optional[Callable[[str], bool]] = None,
        on_auth_params_captured: Optional[Callable[[dict], None]] = None
    ):
        self.host = host
        self.port = port
        self.target_domain = target_domain
        self.token_validator = token_validator
        self.on_auth_params_captured = on_auth_params_captured
        self.server_sock: Optional[socket.socket] = None
        self.is_running = False
        self.captured_token: Optional[str] = None
        self.captured_auth_params: Optional[dict] = None
        self.captured_event = threading.Event()
        self._server_thread: Optional[threading.Thread] = None

        # 预先生成针对目标域名的证书
        self.cert_generator = CertGenerator(target_domain=self.target_domain)
        self.cert_path, self.key_path = self.cert_generator.generate_cert_and_key()
        self._server_ssl_ctx: Optional[ssl.SSLContext] = None

    def _get_server_ssl_context(self) -> ssl.SSLContext:
        """获取用于向客户端提供 SSL 握手的服务上下文"""
        if self._server_ssl_ctx is None:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(certfile=self.cert_path, keyfile=self.key_path)
            try:
                ctx.set_alpn_protocols(["http/1.1"])
            except Exception:
                pass
            self._server_ssl_ctx = ctx
        return self._server_ssl_ctx

    def start(self):
        """在后台线程中启动代理监听"""
        if self.is_running:
            return

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(128)
        self.server_sock.settimeout(1.0)
        self.is_running = True

        self._server_thread = threading.Thread(target=self._listen_loop, daemon=True, name="SnifferProxyThread")
        self._server_thread.start()
        logger.info(f"本地轻量嗅探代理已就绪，正在监听: http://{self.host}:{self.port}")

    def stop(self):
        """停止代理监听并清理资源"""
        self.is_running = False
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
            self.server_sock = None
        logger.info("本地轻量嗅探代理已关闭")

    def wait_for_token(self, timeout: float = 30.0) -> Optional[str]:
        """阻塞等待截获目标 Token，超时返回 None"""
        logger.info(f"正在监听微信小程序登录请求，等待 PHPSESSID 截获 (超时: {timeout} 秒)...")
        signaled = self.captured_event.wait(timeout=timeout)
        if signaled:
            logger.info(f"🎉 成功截获到最新 PHPSESSID: {self.captured_token}")
            return self.captured_token
        else:
            logger.warning(f"在 {timeout} 秒内未截获到微信小程序的登录 Token")
            return None

    def _listen_loop(self):
        while self.is_running:
            try:
                client_sock, addr = self.server_sock.accept()
                logger.info(f"===> 代理收到客户端连接: {addr}")
            except socket.timeout:
                continue
            except OSError:
                break

            # 每个客户端连接启动独立线程处理
            t = threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True)
            t.start()

    def _handle_client(self, client_sock: socket.socket):
        try:
            client_sock.settimeout(10.0)
            initial_data = b""
            while b"\r\n\r\n" not in initial_data:
                chunk = client_sock.recv(4096)
                if not chunk:
                    break
                initial_data += chunk
                if len(initial_data) > 65536:
                    break

            if not initial_data:
                client_sock.close()
                return

            first_line = initial_data.split(b"\r\n")[0].decode("latin1", errors="ignore")
            logger.info(f"===> 收到客户端报文请求行: {first_line}")
            parts = first_line.split(" ")
            if len(parts) < 2:
                client_sock.close()
                return

            method, target = parts[0], parts[1]

            if method.upper() == "CONNECT":
                # HTTPS 隧道请求: target 通常是 host:port (如 xdty.xmu.edu.cn:443)
                self._handle_https_connect(client_sock, target)
            else:
                # 普通 HTTP 请求
                self._handle_plain_http(client_sock, method, target, initial_data)
        except Exception as e:
            logger.warning(f"===> 代理客户端处理异常: {e}")
            try:
                client_sock.close()
            except Exception:
                pass

    def _parse_host_port(self, target: str, default_port: int = 80) -> Tuple[str, int]:
        if ":" in target:
            h, p = target.rsplit(":", 1)
            try:
                return h, int(p)
            except ValueError:
                return h, default_port
        return target, default_port

    def _handle_https_connect(self, client_sock: socket.socket, target: str):
        host, port = self._parse_host_port(target, 443)

        is_target = (host == self.target_domain) or host.endswith(f".{self.target_domain}")
        logger.info(f"===> 处理 HTTPS CONNECT: host={host}, port={port}, is_target={is_target}")

        if is_target:
            # 针对目标域名：执行 MITM TLS 解密
            self._mitm_target_traffic(client_sock, host, port)
        else:
            # 针对其他域名：透明 TCP 隧道透传
            self._tunnel_passthrough(client_sock, host, port)

    def _tunnel_passthrough(self, client_sock: socket.socket, host: str, port: int):
        """对外部非目标域名建立透明 TCP 隧道"""
        try:
            upstream_sock = socket.create_connection((host, port), timeout=8.0)
            client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        except Exception as e:
            logger.debug(f"透传连接 {host}:{port} 失败: {e}")
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            client_sock.close()
            return

        # 双向套接字管道
        self._pipe_sockets(client_sock, upstream_sock)

    def _mitm_target_traffic(self, client_sock: socket.socket, host: str, port: int):
        """对 xdty.xmu.edu.cn 目标 HTTPS 流量执行中间人解密并嗅探 Set-Cookie"""
        try:
            client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        except Exception as e:
            logger.warning(f"向客户端发送 200 Connection Established 失败: {e}")
            client_sock.close()
            return

        ssl_client = None
        ssl_upstream = None
        try:
            # 1. 服务端 TLS 握手：将 client_sock 包装为 SSL 套接字
            logger.info("===> 开始与客户端执行 TLS 握手...")
            server_ctx = self._get_server_ssl_context()
            ssl_client = server_ctx.wrap_socket(client_sock, server_side=True)
            logger.info("===> 客户端 TLS 握手成功！")

            # 2. 客户端 TLS 连接：连接至真实服务端
            logger.info(f"===> 正在连接真实上游服务器 {host}:{port}...")
            upstream_ctx = ssl.create_default_context()
            upstream_ctx.check_hostname = False
            upstream_ctx.verify_mode = ssl.CERT_NONE
            try:
                upstream_ctx.set_alpn_protocols(["http/1.1"])
            except Exception:
                pass
            raw_upstream = socket.create_connection((host, port), timeout=8.0)
            ssl_upstream = upstream_ctx.wrap_socket(raw_upstream, server_hostname=host)
            logger.info("===> 真实上游 TLS 连接成功！")

            # 3. 循环支持 HTTP/1.1 Keep-Alive 长连接，持续代理并捕获该连接上的所有请求/响应
            while self.is_running:
                request_data = self._read_http_message(ssl_client)
                if not request_data:
                    break

                req_str = request_data.decode("latin1", errors="ignore")
                first_line = req_str.splitlines()[0] if req_str else ""
                logger.info(f"🎯 [捕获目标请求] {first_line}")
                self._inspect_and_extract_auth_params(request_data)
                self._inspect_and_extract_cookie(request_data, source="客户端请求")

                # 4. 发送至真实服务器
                try:
                    ssl_upstream.sendall(request_data)
                    # 5. 接收服务器真实响应
                    response_data = self._read_http_message(ssl_upstream)
                except Exception as e:
                    logger.warning(f"与上游真实服务器通信异常: {e}")
                    break

                if not response_data:
                    break

                self._inspect_and_extract_cookie(response_data, source="服务端响应")
                # 6. 将响应转发回客户端
                try:
                    ssl_client.sendall(response_data)
                except Exception as e:
                    logger.warning(f"向客户端发送响应异常: {e}")
                    break

                # 检查连接关闭指令
                req_lower = req_str.lower()
                resp_headers_str = response_data.split(b"\r\n\r\n")[0].decode("latin1", errors="ignore").lower()
                if "connection: close" in req_lower or "connection: close" in resp_headers_str:
                    break

        except Exception as e:
            logger.error(f"===> MITM 解密流程异常: {e}", exc_info=True)
        finally:
            if ssl_client:
                try:
                    ssl_client.close()
                except Exception:
                    pass
            if ssl_upstream:
                try:
                    ssl_upstream.close()
                except Exception:
                    pass

    def _handle_plain_http(self, client_sock: socket.socket, method: str, target: str, initial_data: bytes):
        """处理普通 HTTP 明文请求"""
        # 提取 Host
        host = ""
        lines = initial_data.split(b"\r\n")
        for line in lines[1:]:
            if line.lower().startswith(b"host:"):
                host = line.split(b":", 1)[1].strip().decode("latin1")
                break

        if not host:
            if target.startswith("http://"):
                without_scheme = target[7:]
                host = without_scheme.split("/")[0]

        host_name, port = self._parse_host_port(host, 80)
        try:
            self._inspect_and_extract_auth_params(initial_data)
            upstream_sock = socket.create_connection((host_name, port), timeout=8.0)
            upstream_sock.sendall(initial_data)

            response_data = self._read_http_message(upstream_sock)
            if response_data:
                self._inspect_and_extract_cookie(response_data)
                client_sock.sendall(response_data)
            upstream_sock.close()
        except Exception as e:
            logger.debug(f"明文 HTTP 转发异常: {e}")
        finally:
            client_sock.close()

    def _read_http_message(self, sock: socket.socket) -> bytes:
        """从套接字读取完整的 HTTP 头部以及相应的 Body"""
        data = b""
        sock.settimeout(5.0)
        try:
            while b"\r\n\r\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if len(data) > 65536:
                    break
        except (socket.timeout, OSError):
            pass

        if b"\r\n\r\n" not in data:
            return data

        header_bytes, body_bytes = data.split(b"\r\n\r\n", 1)
        headers_str = header_bytes.decode("latin1", errors="ignore")

        # 检查 Content-Length
        content_length = None
        for line in headers_str.split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
                break

        if content_length is not None:
            remaining = content_length - len(body_bytes)
            try:
                while remaining > 0:
                    chunk = sock.recv(min(remaining, 4096))
                    if not chunk:
                        break
                    body_bytes += chunk
                    remaining -= len(chunk)
            except (socket.timeout, OSError):
                pass
            return header_bytes + b"\r\n\r\n" + body_bytes

        # 检查是否为 chunked 传输
        if "transfer-encoding: chunked" in headers_str.lower():
            try:
                while not (b"\r\n0\r\n\r\n" in body_bytes or body_bytes.endswith(b"0\r\n\r\n") or body_bytes == b"0\r\n\r\n"):
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    body_bytes += chunk
            except (socket.timeout, OSError):
                pass
            return header_bytes + b"\r\n\r\n" + body_bytes

        # 普通无包体请求（如 GET / HEAD，或 304/204 等无 body 响应）
        return header_bytes + b"\r\n\r\n" + body_bytes

    def _inspect_and_extract_auth_params(self, data: bytes):
        """检查请求报文（Query 或 Body）中是否存在 checkLogin 续登凭据（token, sign, uid 等）"""
        try:
            parts = data.split(b"\r\n\r\n", 1)
            headers_str = parts[0].decode("latin1", errors="ignore")
            body_str = parts[1].decode("latin1", errors="ignore") if len(parts) > 1 else ""

            combined = headers_str + "&" + body_str
            if "token=" in combined and ("checkLogin" in headers_str or "stadium" in headers_str):
                extracted = {}
                for field in [
                    "token", "sign", "uid", "card_id", "student_num",
                    "school_id", "login_type", "user_type", "type", "course_id"
                ]:
                    m = re.search(rf"[?&]{field}=([^&\s\r\n]+)", combined)
                    if m:
                        extracted[field] = m.group(1).strip()

                if "token" in extracted and len(extracted["token"]) >= 16:
                    self.captured_auth_params = extracted
                    logger.info(
                        f"🎯 [命中长效凭据] 成功嗅探到 checkLogin 续登参数: "
                        f"token={extracted['token'][:8]}***, uid={extracted.get('uid', '')}"
                    )
                    if self.on_auth_params_captured:
                        try:
                            self.on_auth_params_captured(extracted)
                        except Exception as e:
                            logger.warning(f"触发 on_auth_params_captured 异常: {e}")
        except Exception as e:
            logger.debug(f"解析 auth_params 异常: {e}")

    def _inspect_and_extract_cookie(self, data: bytes, source: str = "响应"):
        """检查报文（请求头或响应头）中是否存在 PHPSESSID"""
        try:
            header_part = data.split(b"\r\n\r\n")[0].decode("latin1", errors="ignore")
            # 正则匹配 PHPSESSID
            match = re.search(r"PHPSESSID=([a-zA-Z0-9_\-]+)", header_part, re.IGNORECASE)
            if match:
                token = match.group(1)
                # 若配置了实机有效性校验函数，先探测是否真实具备登录态
                if self.token_validator:
                    is_valid = False
                    try:
                        is_valid = self.token_validator(token)
                    except Exception as e:
                        logger.debug(f"验证候选 Token 异常: {e}")

                    if not is_valid:
                        logger.info(f"ℹ️ 嗅探到候选 PHPSESSID: {token[:8]}*** ({source})，但实机探测尚未登录就绪（通常是刚启动时的空白握手会话），继续等待...")
                        return
                    else:
                        logger.info(f"✨ 候选 PHPSESSID: {token[:8]}*** 经实机在线探测【确认登录有效】！")

                self.captured_token = token
                self.captured_event.set()
                logger.info(f"🎯 [命中并确认] 成功从{source}中嗅探到有效凭证: PHPSESSID={token}")
        except Exception as e:
            logger.debug(f"解析 {source} Cookie 异常: {e}")

    def _pipe_sockets(self, s1: socket.socket, s2: socket.socket):
        """在两个套接字之间建立双向透明管道"""
        sockets = [s1, s2]
        try:
            while self.is_running:
                readable, _, exceptional = select.select(sockets, [], sockets, 2.0)
                if exceptional:
                    break
                if not readable:
                    continue
                for s in readable:
                    other = s2 if s is s1 else s1
                    data = s.recv(8192)
                    if not data:
                        return
                    other.sendall(data)
        except Exception:
            pass
        finally:
            try:
                s1.close()
            except Exception:
                pass
            try:
                s2.close()
            except Exception:
                pass
