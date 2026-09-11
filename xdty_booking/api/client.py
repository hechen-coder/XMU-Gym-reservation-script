import requests
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
        "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows "
        "WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541721) "
        "XWEB/19027 miniProgram/wx81a2b2fa90759cb7"
    ),
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://xdty.xmu.edu.cn",
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
}

class ApiClient:
    """
    HTTP 连接客户端：
    1. 维持统一的 requests.Session、Cookie 状态与长连接
    2. 严格对齐微信小程序 H5 WebView 的 User-Agent 与 Headers
    """
    def __init__(self, base_url: str = "https://xdty.xmu.edu.cn/bdlp_h5_fitness_test"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.session.cookies.set("Path", "/")
        self.session.cookies.set("login_type", "4")
        self.session.cookies.set("COOKIE_IS_APP_UI", "0")

    def set_session_token(self, phpsessid: str):
        """设置或更新 PHPSESSID cookie"""
        self.session.cookies.set("PHPSESSID", phpsessid)

    def post(self, path: str, data: Optional[Dict[str, Any]] = None, referer: Optional[str] = None) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {}
        if referer:
            headers["referer"] = referer
        return self.session.post(url, data=data, headers=headers, timeout=10)

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, referer: Optional[str] = None) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {}
        if referer:
            headers["referer"] = referer
        return self.session.get(url, params=params, headers=headers, timeout=10)
