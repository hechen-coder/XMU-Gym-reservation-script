import os
import sys
import json
import datetime
import tempfile
import logging
from typing import Tuple

# Windows Anaconda 运行环境兼容修复：将 Library\bin 注入 PATH 以确保 OpenSSL DLL 正常加载
if sys.platform == "win32":
    dll_dir = os.path.join(sys.prefix, "Library", "bin")
    if os.path.exists(dll_dir) and dll_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = dll_dir + ";" + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory") and os.path.exists(dll_dir):
        try:
            os.add_dll_directory(dll_dir)
        except Exception:
            pass

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False
    x509 = None
    NameOID = None
    hashes = None
    serialization = None
    rsa = None

logger = logging.getLogger(__name__)

class CertGenerator:
    """
    轻量自签名 SSL/TLS 证书生成器，用于针对特定域名（如 xdty.xmu.edu.cn）的本地透明嗅探解密。
    若检测到本机系统已安装并信任了抓包根证书（如 Reqable CA），自动复用该 CA 进行签发，
    使微信 Chromium 内核无须任何提示或证书错误直接无缝信任！
    """
    def __init__(self, target_domain: str = "xdty.xmu.edu.cn"):
        self.target_domain = target_domain
        self.cert_dir = os.path.join(tempfile.gettempdir(), "xdty_proxy_certs")
        os.makedirs(self.cert_dir, exist_ok=True)
        self.cert_path = os.path.join(self.cert_dir, f"{target_domain}.crt")
        self.key_path = os.path.join(self.cert_dir, f"{target_domain}.key")

    def generate_cert_and_key(self) -> Tuple[str, str]:
        """
        生成带有 Subject Alternative Name (SAN) 的私钥与证书文件，返回 (cert_path, key_path)
        """
        if not HAS_CRYPTOGRAPHY:
            raise ImportError(
                "未检测到 cryptography 证书加密库，透明嗅探代理证书生成失败！\n"
                "请确保已正确安装依赖: pip install cryptography"
            )
        # 1. 优先尝试探测本机是否已有系统受信任的抓包 CA（如 Reqable）
        reqable_bin = os.path.expandvars(r"%APPDATA%\Reqable\certificate\capture.bin")
        if os.path.exists(reqable_bin):
            try:
                with open(reqable_bin, "r", encoding="utf-8") as f:
                    d = json.load(f)
                ca_cert = x509.load_pem_x509_certificate(d["cert"].encode())
                ca_key = serialization.load_pem_private_key(d["pkey"].encode(), password=None)

                # 使用受信任 CA 动态签发目标域名证书
                server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                subject = x509.Name([
                    x509.NameAttribute(NameOID.COMMON_NAME, self.target_domain)
                ])
                san_names = [
                    x509.DNSName(self.target_domain),
                    x509.DNSName("*.xmu.edu.cn"),
                    x509.DNSName("localhost"),
                ]
                now = datetime.datetime.utcnow()
                server_cert = (
                    x509.CertificateBuilder()
                    .subject_name(subject)
                    .issuer_name(ca_cert.subject)
                    .public_key(server_key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(now - datetime.timedelta(days=1))
                    .not_valid_after(now + datetime.timedelta(days=365))
                    .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
                    .sign(ca_key, hashes.SHA256())
                )

                with open(self.key_path, "wb") as f:
                    f.write(server_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.TraditionalOpenSSL,
                        encryption_algorithm=serialization.NoEncryption(),
                    ))

                with open(self.cert_path, "wb") as f:
                    # 写入服务器证书以及 CA 证书链
                    f.write(server_cert.public_bytes(serialization.Encoding.PEM))
                    f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

                logger.info(f"已复用本机已信任的根 CA 签发 {self.target_domain} 证书（无缝受信任）")
                return self.cert_path, self.key_path
            except Exception as e:
                logger.warning(f"复用系统信任 CA 异常，降级为独立自签名: {e}")

        # 2. 兜底方案：生成独立自签名 CA 与域名证书
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"CN"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"XDTY Local Sniffer Proxy"),
            x509.NameAttribute(NameOID.COMMON_NAME, self.target_domain),
        ])

        san_names = [
            x509.DNSName(self.target_domain),
            x509.DNSName("*.xmu.edu.cn"),
            x509.DNSName("localhost"),
        ]

        now = datetime.datetime.utcnow()
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None),
                critical=True,
            )
            .sign(private_key, hashes.SHA256())
        )

        with open(self.key_path, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        with open(self.cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        logger.debug(f"已生成针对 {self.target_domain} 的临时自签名证书: {self.cert_path}")
        return self.cert_path, self.key_path
