import base64
import logging
import random
import re
import time
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse, parse_qs, quote
import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)

_AES_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"


def encrypt_password(password: str, salt: str) -> str:
    """
    复刻 CAS 页面 encrypt.js 的 encryptPassword：
    AES-CBC(key=pwdEncryptSalt, iv=随机 16 字符) 加密 "随机 64 字符 + 密码"，PKCS7 填充后 Base64。
    IV 不随表单提交，服务端任意 IV 解密后丢弃前 64 字节即可还原密码。
    """
    if not salt:
        return password
    rand = lambda n: "".join(random.choice(_AES_CHARS) for _ in range(n))
    padder = padding.PKCS7(128).padder()
    data = padder.update((rand(64) + password).encode("utf-8")) + padder.finalize()
    enc = Cipher(algorithms.AES(salt.encode("utf-8")), modes.CBC(rand(16).encode("utf-8"))).encryptor()
    return base64.b64encode(enc.update(data) + enc.finalize()).decode("ascii")

class CasQrLoginClient:
    """
    厦门大学统一身份认证 (CAS / IDS) 纯代码扫码登录客户端
    彻底脱离微信客户端，纯 HTTP/HTTPS 模拟完成企业微信扫码登录与全套凭据置换。
    
    CAS 状态码规则（金智教育官方 qrcode.js）：
    - 0: 等待扫码
    - 2: 已扫描二维码（等待手机端点击【确认登录】）
    - 1: 手机端已点击【确认登录】（授权成功，此时才可提交表单！）
    - 3: 二维码失效超时
    """

    CAS_BASE = "https://ids.xmu.edu.cn/authserver"
    XDTY_BASE = "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test"
    DEFAULT_SERVICE = "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test/public/index.php/index/login/xmLogin"

    def __init__(self):
        self.session = requests.Session()
        # 必须设置 trust_env = False，避免本机代理软件 (如 Clash/VPN) 劫持校园内网流量
        self.session.trust_env = False
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
                "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
                "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
                "UnifiedPCWindowsWechat(0xf2541721) XWEB/19027 miniProgram/wx81a2b2fa90759cb7"
            )
        })
        self.uuid: Optional[str] = None
        self.execution: str = "e1s1"
        self.service_url: str = self.DEFAULT_SERVICE
        self.service_param: str = self.DEFAULT_SERVICE
        self.login_page_url: Optional[str] = None
        self.qr_image_bytes: Optional[bytes] = None
        self.auth_params: Optional[Dict[str, str]] = None
        self.phpsessid: Optional[str] = None
        self.user_info: Optional[Dict[str, Any]] = None

    def init_qr_session(self) -> Tuple[str, bytes]:
        """
        初始化扫码会话，生成 uuid 并拉取二维码图片
        :return: (uuid, qr_image_bytes)
        """
        logger.info("正在初始化 CAS 统一身份认证会话...")
        
        # 1. 访问体育馆 xmLogin 触发初始化（获取预设 PHPSESSID Cookie）
        try:
            init_resp = self.session.get(self.DEFAULT_SERVICE, allow_redirects=False, timeout=8)
            if "Location" in init_resp.headers:
                logger.info("体育馆初始化完成重定向")
        except Exception as e:
            logger.warning("访问体育馆初始接口异常 (继续尝试直连 CAS): %s", type(e).__name__)

        # 2. 构造规范 service 参数，加载 CAS 登录页面
        self.service_url = self.DEFAULT_SERVICE
        encoded_service = quote(self.service_url, safe="")
        self.login_page_url = f"{self.CAS_BASE}/login?skip=skip&type=qrLogin&service={encoded_service}"
        
        cas_page_resp = self.session.get(self.login_page_url, timeout=10)
        
        # 提取页面中真实的 execution 状态码
        m_exec = re.search(r'name=["\']execution["\']\s+value=["\']([^"\']+)["\']', cas_page_resp.text)
        if m_exec:
            self.execution = m_exec.group(1)
        
        # 提取页面中注册的 var service
        m_serv = re.search(r'var\s+service\s*=\s*\[["\']([^"\']+)["\']\]', cas_page_resp.text)
        if m_serv:
            self.service_param = m_serv.group(1).replace(r'\/', '/')
        else:
            self.service_param = self.service_url

        logger.info("获取 CAS 登录上下文完成")

        # 3. 请求 /qrCode/getToken 获取唯一 UUID
        token_url = f"{self.CAS_BASE}/qrCode/getToken?ts={int(time.time() * 1000)}"
        token_resp = self.session.get(
            token_url,
            headers={"Referer": self.login_page_url},
            timeout=8
        )
        self.uuid = token_resp.text.strip()
        logger.info("成功分配二维码会话 UUID")

        # 4. 下载官方二维码图片
        code_img_url = f"{self.CAS_BASE}/qrCode/getCode?uuid={self.uuid}"
        img_resp = self.session.get(
            code_img_url,
            headers={"Referer": self.login_page_url},
            timeout=8
        )
        self.qr_image_bytes = img_resp.content
        logger.info(f"二维码图片拉取成功，大小: {len(self.qr_image_bytes)} 字节")

        return self.uuid, self.qr_image_bytes

    def get_qr_image_base64(self) -> str:
        """获取 Base64 格式二维码图片，供前端直接渲染"""
        if not self.qr_image_bytes:
            raise ValueError("尚未初始化二维码会话，请先调用 init_qr_session()")
        b64_str = base64.b64encode(self.qr_image_bytes).decode("ascii")
        return f"data:image/png;base64,{b64_str}"

    def check_status(self) -> Tuple[str, str]:
        """
        向 CAS 轮询扫码状态
        :return: (code, description)
            '0': 等待扫码
            '2': 已扫码，等待手机端点击【确认登录】
            '1': 手机端已确认授权（成功！）
            '3': 二维码已超时失效
        """
        if not self.uuid:
            return "-1", "会话尚未初始化"

        status_url = f"{self.CAS_BASE}/qrCode/getStatus.htl?ts={int(time.time() * 1000)}&uuid={self.uuid}"
        try:
            resp = self.session.get(
                status_url,
                headers={"Referer": self.login_page_url},
                timeout=5
            )
            code = resp.text.strip()
            desc_map = {
                "0": "等待手机企业微信扫码...",
                "2": "已扫码！请在手机企业微信上点击【确认登录】...",
                "1": "手机端已确认授权！正在换取票据与凭证...",
                "3": "二维码已失效，请刷新重新获取",
            }
            return code, desc_map.get(code, f"未知状态码: {code}")
        except Exception as e:
            logger.warning("轮询状态异常: %s", type(e).__name__)
            return "-1", "网络轮询异常"

    def exchange_and_login(self) -> Dict[str, Any]:
        """
        在 status 为 1 (手机端确认授权) 时调用：
        提交表单 -> 跟随重定向换发 ST 票据 -> 体育馆验票 -> 捕获长效 auth_params -> checkLogin 获取最新 PHPSESSID
        :return: 包含 phpsessid, auth_params, user_info 的字典
        """
        logger.info("开始执行 CAS 票据提交与凭据换发流程...")

        # 1. 提交 qrLoginForm 表单，严格按照 qrcode.js 进行参数拼接
        encoded_service_param = quote(self.service_param, safe="")
        post_url = f"{self.CAS_BASE}/login?display=qrLogin&service={encoded_service_param}"
        payload = {
            "lt": "",
            "uuid": self.uuid,
            "cllt": "qrLogin",
            "dllt": "generalLogin",
            "execution": self.execution,
            "_eventId": "submit",
            "rmShown": "1"
        }
        headers = {
            "Origin": "https://ids.xmu.edu.cn",
            "Referer": f"{self.CAS_BASE}/login?type=qrLogin&service={encoded_service_param}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        resp = self.session.post(post_url, data=payload, headers=headers, allow_redirects=False, timeout=10)
        logger.info(f"CAS 表单提交响应状态: {resp.status_code}")
        return self._finish_login(resp.headers.get("Location"))

    def password_login(self, username: str, password: str, solver=None, max_captcha_retry: int = 3) -> Dict[str, Any]:
        """
        统一身份认证账号密码登录（cllt=userNameLogin）：
        加载登录页取 execution/pwdEncryptSalt -> 按需识别图形验证码 -> AES 加密密码提交 -> 复用重定向换票流程。
        验证码错误会重试；用户名/密码错误直接抛出，避免触发 CAS 账号锁定。
        """
        if solver is None:
            from xdty_booking.solver.captcha_solver import CaptchaSolver
            solver = CaptchaSolver(save_dir="captchas")

        encoded_service = quote(self.DEFAULT_SERVICE, safe="")
        login_url = f"{self.CAS_BASE}/login?skip=skip&service={encoded_service}"  # skip 避免微信 UA 被转到微信 OAuth
        self.login_page_url = login_url
        page = self.session.get(login_url, timeout=10).text
        m_exec = re.search(r'name=["\']execution["\']\s+value=["\']([^"\']+)["\']', page)
        m_salt = re.search(r'id=["\']pwdEncryptSalt["\']\s+value=["\']([^"\']+)["\']', page)
        execution = m_exec.group(1) if m_exec else "e1s1"
        salt = m_salt.group(1) if m_salt else ""

        need_captcha = False
        try:
            r = self.session.get(
                f"{self.CAS_BASE}/checkNeedCaptcha.htl?username={quote(username)}&_={int(time.time() * 1000)}",
                headers={"Referer": login_url}, timeout=8
            )
            need_captcha = bool(r.json().get("isNeed"))
        except Exception as e:
            raise RuntimeError("无法确认 CAS 是否需要验证码") from e

        for attempt in range(1, max_captcha_retry + 1):
            captcha = ""
            if need_captcha:
                img = self.session.get(
                    f"{self.CAS_BASE}/getCaptcha.htl?{int(time.time() * 1000)}",
                    headers={"Referer": login_url}, timeout=8
                ).content
                captcha = solver.solve(img)
                if not captcha:
                    raise RuntimeError("CAS 图形验证码识别失败")
                logger.info("CAS 图形验证码识别完成 (第 %s 次)", attempt)

            payload = {
                "username": username,
                "password": encrypt_password(password, salt),
                "captcha": captcha,
                "_eventId": "submit",
                "cllt": "userNameLogin",
                "dllt": "generalLogin",
                "lt": "",
                "execution": execution,
            }
            resp = self.session.post(
                login_url, data=payload,
                headers={"Origin": "https://ids.xmu.edu.cn", "Referer": login_url,
                         "Content-Type": "application/x-www-form-urlencoded"},
                allow_redirects=False, timeout=10
            )
            logger.info(f"CAS 账号密码表单提交响应状态: {resp.status_code}")
            if resp.status_code in (301, 302, 303, 307) and resp.headers.get("Location"):
                return self._finish_login(resp.headers["Location"])

            m_err = re.search(r'id=["\']showErrorTip["\'][^>]*>\s*(?:<span[^>]*>)?([^<]+)', resp.text)
            err = m_err.group(1).strip() if m_err else f"CAS 未返回重定向 (HTTP {resp.status_code})"
            m_exec = re.search(r'name=["\']execution["\']\s+value=["\']([^"\']+)["\']', resp.text)
            if m_exec:
                execution = m_exec.group(1)
            if "验证码" in err and attempt < max_captcha_retry:
                logger.warning(f"CAS 提示验证码错误，重试: {err}")
                need_captcha = True
                continue
            raise RuntimeError(f"CAS 登录失败: {err}")
        raise RuntimeError("CAS 登录失败: 验证码重试次数用尽")

    def _finish_login(self, first_location: Optional[str]) -> Dict[str, Any]:
        """跟随重定向链换发 ST -> 体育馆验票 -> 捕获 auth_params -> checkLogin 获取 PHPSESSID -> 探活"""
        # 2. 跟随重定向链，直到捕获 xdLogin.html 中的 auth_params
        curr_url = first_location
        captured_auth_params = {}
        max_hops = 12

        while curr_url and max_hops > 0:
            max_hops -= 1
            logger.info("CAS 重定向跳步 [%s]", 12 - max_hops)

            # 检查 URL 是否命中了带有凭证的 landing page
            if "xdLogin.html" in curr_url or "token=" in curr_url:
                parsed = urlparse(curr_url)
                qs = parse_qs(parsed.query)
                captured_auth_params = {k: v[0] for k, v in qs.items()}
                logger.info(f"🎉 成功从重定向 URL 中捕获到全套长效 auth_params！包含键: {list(captured_auth_params.keys())}")
                break

            r_next = self.session.get(curr_url, allow_redirects=False, timeout=10)

            if r_next.is_redirect or r_next.status_code in (301, 302, 303, 307):
                curr_url = r_next.headers.get("Location")
            else:
                break

        if not captured_auth_params:
            raise RuntimeError("未能从重定向链路中捕获到 auth_params")

        self.auth_params = captured_auth_params

        # 3. 使用抓到的 auth_params 调用体育馆 checkLogin 接口，换取最新、合法的真实 32 位 PHPSESSID
        logger.info("正在使用捕获到的 auth_params 执行 checkLogin 换发正式 32 位 PHPSESSID...")
        valid_sessid = self._do_check_login(captured_auth_params)
        if valid_sessid:
            self.phpsessid = valid_sessid
            logger.info("🎉 成功获取并激活正式 PHPSESSID: %s***", self.phpsessid[:8])
        else:
            raise RuntimeError("调用 checkLogin 换取正式 32 位 PHPSESSID 失败，服务端未下发合法会话")

        # 4. 执行实机探活与用户信息查询
        self.user_info = self._fetch_user_profile()
        if self.user_info.get("status") != "有效 (Alive)":
            raise RuntimeError("登录后会话验证失败")

        return {
            "success": True,
            "phpsessid": self.phpsessid,
            "auth_params": self.auth_params,
            "user_info": self.user_info,
            "message": "登录成功！凭据已全部就绪。"
        }

    def _do_check_login(self, auth_params: Dict[str, str]) -> Optional[str]:
        """
        发起 checkLogin 请求换票：
        严格遵循前端 common.js 规范：
        1. 必须在无旧 PHPSESSID Cookie 的干净环境下请求（消除 ST- 临时票据 Cookie 干扰）；
        2. 必须保留 auth_params 中服务端签发时的原始 timestamp 和 nonce，确保 sign 签名 100% 匹配；
        3. 服务端验签通过后，下发全新的 32 位 Hex PHPSESSID。
        """
        payload = dict(auth_params)
        payload["term_id"] = ""
        payload["id"] = ""

        check_url = f"{self.XDTY_BASE}/public/index.php/index/Index/checkLogin"
        referer = (
            f"{self.XDTY_BASE}/view/main/login/xdLogin.html?"
            f"timestamp={payload.get('timestamp','')}&nonce={payload.get('nonce','')}&token={payload.get('token', '')}"
        )

        clean_session = requests.Session()
        clean_session.trust_env = False
        clean_session.headers.update(self.session.headers)

        try:
            r = clean_session.post(
                check_url,
                data=payload,
                headers={
                    "Referer": referer,
                    "X-Requested-With": "XMLHttpRequest"
                },
                timeout=8
            )
            res_json = r.json()
            logger.info("checkLogin 响应状态: %s", res_json.get("status"))

            # 从响应中提取全新下发的真实 32 位 PHPSESSID
            new_sessid = r.cookies.get("PHPSESSID")
            if not new_sessid:
                sc = r.headers.get("Set-Cookie", "")
                m = re.search(r"PHPSESSID=([a-zA-Z0-9_\-]+)", sc)
                if m:
                    new_sessid = m.group(1)

            if new_sessid and not new_sessid.startswith("ST-"):
                # 同步回主 session
                self.session.cookies.set("PHPSESSID", new_sessid, domain="xdty.xmu.edu.cn", path="/")
                return new_sessid

            if res_json.get("status") == 1 and new_sessid:
                return new_sessid

            logger.warning("checkLogin 校验未通过或未下发有效会话")
            return None
        except Exception as e:
            logger.error("调用 checkLogin 异常: %s", type(e).__name__)
            return None

    def _fetch_user_profile(self) -> Dict[str, Any]:
        """通过 mySubscribe 接口探测会话健康度与预约信息"""
        if not self.phpsessid:
            return {"status": "未知", "msg": "未持有 PHPSESSID"}

        probe_url = f"{self.XDTY_BASE}/public/index.php/index/stadium/mySubscribe"
        try:
            r = self.session.post(
                probe_url,
                data={"p": "1"},
                headers={
                    "Referer": f"{self.XDTY_BASE}/view/stadium/personal-center.html",
                    "Cookie": f"PHPSESSID={self.phpsessid}; login_type=4"
                },
                timeout=6
            )
            res = r.json()
            return {
                "status": "有效 (Alive)" if res.get("status") == 1 else "异常",
                "api_response": res
            }
        except Exception as e:
            return {"status": "探测异常", "error": str(e)}
