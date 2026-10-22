"""冻结产物离线自检：真实加载原生库、OCR 模型和本地 HTTP，不调用预约接口。"""

import io
import json
import platform
import sys
import traceback
from pathlib import Path


def run_self_test(output):
    results = {"python": sys.version, "architecture": platform.machine(), "checks": {}}

    def check(name, operation):
        try:
            results["checks"][name] = {"ok": True, "detail": operation()}
        except Exception:
            results["checks"][name] = {"ok": False, "detail": traceback.format_exc()}

    def crypto():
        from cryptography.hazmat.backends.openssl.backend import backend
        return backend.openssl_version_text()

    def ocr():
        import ddddocr
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (120, 40), "white")
        ImageDraw.Draw(image).text((10, 10), "abcd", fill="black")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        model = ddddocr.DdddOcr(show_ad=False)
        value = model.classification(stream.getvalue())
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError("真实模型推理未返回识别结果")
        return {"prediction": value, "inference": "real ONNX model"}

    def local_http():
        from xdty_booking.web.server import create_web_service
        service = create_web_service(port=0)
        try:
            service.start(timeout=5)
            return "loopback health check passed"
        finally:
            service.close()

    def licensing():
        from xdty_booking.security.auth import get_public_key
        if get_public_key() is None:
            raise RuntimeError("授权验签模块加载失败")
        return "public-key module loaded; no activation or HWID collection"

    check("cryptography", crypto)
    check("ocr", ocr)
    check("local_http", local_http)
    check("security_module", licensing)
    results["ok"] = all(result["ok"] for result in results["checks"].values())
    Path(output).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if results["ok"] else 1
