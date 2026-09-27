import base64
from urllib.parse import urlparse, parse_qs

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from cas_qr_login.cas_client import CasQrLoginClient, encrypt_password


LOGIN_PAGE = """
<form id="loginFromId" class="loginFromClass">
<input id="execution" name="execution" value="e2s7" />
<input type="hidden" id="pwdEncryptSalt" value="TxkqAE4HelwwRXm5" />
<input id="cllt" name="cllt" value="userNameLogin" />
</form>
"""

ERROR_PAGE = LOGIN_PAGE + '<span id="showErrorTip"><span>您提供的用户名或者密码有误</span></span>'


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None, content=b""):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.content = content

    def json(self):
        import json
        return json.loads(self.text)


class FakeSession:
    """按 URL 片段返回预设响应，并记录 POST 表单。"""
    def __init__(self, routes, post_response):
        self.routes = routes
        self.post_response = post_response
        self.headers = {}
        self.posts = []

    def get(self, url, **kw):
        for key, resp in self.routes.items():
            if key in url:
                return resp
        raise AssertionError(f"未预期的 GET: {url}")

    def post(self, url, data=None, **kw):
        self.posts.append((url, data))
        return self.post_response


class FakeSolver:
    def __init__(self, answer="ab12"):
        self.answer = answer
        self.calls = 0

    def solve(self, image_bytes):
        self.calls += 1
        return self.answer


def _decrypt_like_cas(cipher_b64: str, salt: str) -> str:
    """服务端解密方式：任意 IV 解密后丢弃前 64 字节的随机前缀。"""
    raw = base64.b64decode(cipher_b64)
    dec = Cipher(algorithms.AES(salt.encode()), modes.CBC(b"\x00" * 16)).decryptor()
    plain = dec.update(raw) + dec.finalize()
    pad = plain[-1]
    return plain[64:-pad].decode()


def test_encrypt_password_matches_cas_scheme():
    cipher = encrypt_password("MyP@ss123", "TxkqAE4HelwwRXm5")
    assert cipher != "MyP@ss123"
    assert _decrypt_like_cas(cipher, "TxkqAE4HelwwRXm5") == "MyP@ss123"
    # 每次随机前缀与 IV 不同，密文不应重复
    assert cipher != encrypt_password("MyP@ss123", "TxkqAE4HelwwRXm5")


def _make_client(session, solver=None):
    client = CasQrLoginClient()
    client.session = session
    finished = {}

    def fake_finish(location):
        finished["location"] = location
        return {"success": True, "phpsessid": "abc", "auth_params": {"token": "t"}}

    client._finish_login = fake_finish
    return client, finished


def test_password_login_posts_encrypted_form_and_follows_redirect():
    session = FakeSession(
        routes={
            "/login?skip=skip&service=": FakeResponse(text=LOGIN_PAGE),
            "checkNeedCaptcha.htl": FakeResponse(text='{"isNeed": false}'),
        },
        post_response=FakeResponse(302, headers={"Location": "https://xdty.xmu.edu.cn/x?ticket=ST-1"}),
    )
    client, finished = _make_client(session)

    res = client.password_login("20230001", "MyP@ss123", solver=FakeSolver())

    assert res["success"] is True
    assert finished["location"] == "https://xdty.xmu.edu.cn/x?ticket=ST-1"
    url, form = session.posts[0]
    assert "skip=skip" in url  # 无 skip 时微信 UA 会被 CAS 重定向到微信 OAuth
    assert form["cllt"] == "userNameLogin"
    assert form["execution"] == "e2s7"
    assert form["username"] == "20230001"
    assert form["password"] != "MyP@ss123"
    assert _decrypt_like_cas(form["password"], "TxkqAE4HelwwRXm5") == "MyP@ss123"
    assert form["captcha"] == ""


def test_password_login_solves_captcha_when_required():
    session = FakeSession(
        routes={
            "/login?skip=skip&service=": FakeResponse(text=LOGIN_PAGE),
            "checkNeedCaptcha.htl": FakeResponse(text='{"isNeed": true}'),
            "getCaptcha.htl": FakeResponse(content=b"\x89PNGfake"),
        },
        post_response=FakeResponse(302, headers={"Location": "https://xdty.xmu.edu.cn/x?ticket=ST-1"}),
    )
    solver = FakeSolver("k7m2")
    client, _ = _make_client(session)

    client.password_login("20230001", "MyP@ss123", solver=solver)

    assert solver.calls == 1
    assert session.posts[0][1]["captcha"] == "k7m2"


def test_password_login_raises_with_cas_error_message():
    session = FakeSession(
        routes={
            "/login?skip=skip&service=": FakeResponse(text=LOGIN_PAGE),
            "checkNeedCaptcha.htl": FakeResponse(text='{"isNeed": false}'),
        },
        post_response=FakeResponse(200, text=ERROR_PAGE),
    )
    client, finished = _make_client(session)

    with pytest.raises(RuntimeError, match="用户名或者密码有误"):
        client.password_login("20230001", "wrong", solver=FakeSolver())
    assert "location" not in finished
    assert len(session.posts) == 1  # 密码错误不重试


def test_password_login_retries_on_captcha_error():
    captcha_err = LOGIN_PAGE + '<span id="showErrorTip"><span>验证码错误</span></span>'
    responses = [
        FakeResponse(200, text=captcha_err),
        FakeResponse(302, headers={"Location": "https://xdty.xmu.edu.cn/x?ticket=ST-2"}),
    ]
    session = FakeSession(
        routes={
            "/login?skip=skip&service=": FakeResponse(text=LOGIN_PAGE),
            "checkNeedCaptcha.htl": FakeResponse(text='{"isNeed": true}'),
            "getCaptcha.htl": FakeResponse(content=b"\x89PNGfake"),
        },
        post_response=None,
    )
    session.post = lambda url, data=None, **kw: (session.posts.append((url, data)), responses.pop(0))[1]
    solver = FakeSolver()
    client, finished = _make_client(session)

    client.password_login("20230001", "MyP@ss123", solver=solver)

    assert len(session.posts) == 2
    assert solver.calls == 2
    assert finished["location"].endswith("ST-2")
