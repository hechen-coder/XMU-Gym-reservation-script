import io
from PIL import Image, ImageDraw
import pytest
from xdty_booking.solver.captcha_solver import CaptchaSolver

def generate_test_image(text="ABCD") -> bytes:
    img = Image.new("RGB", (100, 40), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def test_captcha_solver_mock():
    solver = CaptchaSolver(use_mock=True, mock_result="daxs")
    result = solver.solve(b"fake_bytes")
    assert result == "daxs"

def test_captcha_solver_fallback_empty():
    solver = CaptchaSolver(use_mock=False)
    # When ddddocr is not installed, it falls back to mock or safe empty string
    img_bytes = generate_test_image("test")
    res = solver.solve(img_bytes)
    assert isinstance(res, str)
