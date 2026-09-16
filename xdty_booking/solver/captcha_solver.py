import os
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

class CaptchaSolver:
    """
    负责厦大体育 H5 预约 4 位字母验证码的本地识别。
    优先尝试加载 ddddocr 模型（完全离线，识别速度 ~10ms）；
    若未安装或指定 mock，则安全降级，保证不会阻塞程序运行。
    支持自动保存识别过程中的验证码图片以便回溯排查。
    """
    def __init__(self, use_mock: bool = False, mock_result: str = "daxs", save_dir: Optional[str] = "captchas"):
        self.use_mock = use_mock
        self.mock_result = mock_result
        self.save_dir = save_dir
        self._ocr = None

        if self.save_dir:
            os.makedirs(self.save_dir, exist_ok=True)
        
        if not use_mock:
            try:
                # 若运行环境未安装 OpenCV，注入 Mock 模块以防 ddddocr 顶层导入中断
                import sys
                import types
                if "cv2" not in sys.modules:
                    try:
                        import cv2  # noqa: F401
                    except ImportError:
                        sys.modules["cv2"] = types.ModuleType("cv2")

                import ddddocr
                self._ocr = ddddocr.DdddOcr(show_ad=False)
                logger.info("ddddocr 验证码模型初始化成功")
            except ImportError as e:
                logger.warning(f"未检测到或无法加载 ddddocr 库 ({e})，可通过 `pip install ddddocr` 安装以获得自动识别能力")
            except Exception as e:
                logger.warning(f"ddddocr 初始化失败 ({e})，将回退至备用或模拟模式")

    def _save_image(self, image_bytes: bytes, label: str) -> Optional[str]:
        """将验证码二进制数据保存至本地目录"""
        if not self.save_dir or not image_bytes:
            return None
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:21]
            ext = ".png" if image_bytes.startswith(b"\x89PNG") else (".jpg" if image_bytes.startswith(b"\xff\xd8") else ".bin")
            filename = f"{timestamp}_{label}{ext}"
            filepath = os.path.join(self.save_dir, filename)
            with open(filepath, "wb") as f:
                f.write(image_bytes)
            logger.info(f"验证码过程图片已保存至: {filepath}")
            return filepath
        except Exception as e:
            logger.warning(f"验证码图片保存失败: {e}")
            return None

    def solve(self, image_bytes: bytes) -> str:
        """
        输入图片二进制数据，输出 4 位小写字母数字验证码并持久化过程图片
        """
        if self.use_mock:
            self._save_image(image_bytes, f"mock_{self.mock_result}")
            logger.info(f"使用 Mock 验证码: '{self.mock_result}'")
            return self.mock_result

        if self._ocr is None:
            self._save_image(image_bytes, f"nomodel_{self.mock_result}")
            logger.warning(f"识别模型未加载，返回默认占位值: '{self.mock_result}'")
            return self.mock_result

        if not image_bytes or image_bytes.startswith(b"<!DOCTYPE") or image_bytes.startswith(b"<html") or image_bytes.startswith(b"{"):
            self._save_image(image_bytes, "invalid")
            logger.error(f"传入验证码识别的数据不是图片格式 (长度 {len(image_bytes) if image_bytes else 0} 字节): {image_bytes[:80] if image_bytes else b''}")
            return self.mock_result

        try:
            res = self._ocr.classification(image_bytes)
            # 过滤特殊字符并统一为小写
            clean_res = "".join([c for c in res if c.isalnum()]).lower()
            self._save_image(image_bytes, clean_res)
            logger.info(f"验证码自动识别完成: '{clean_res}'")
            return clean_res
        except Exception as e:
            self._save_image(image_bytes, "error")
            logger.error(f"验证码识别发生异常: {e}")
            return self.mock_result
