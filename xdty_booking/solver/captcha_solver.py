import logging
from typing import Optional

logger = logging.getLogger(__name__)

class CaptchaSolver:
    """
    负责厦大体育 H5 预约 4 位字母验证码的本地识别。
    优先尝试加载 ddddocr 模型（完全离线，识别速度 ~10ms）；
    若未安装或指定 mock，则安全降级，保证不会阻塞程序运行。
    """
    def __init__(self, use_mock: bool = False, mock_result: str = "daxs"):
        self.use_mock = use_mock
        self.mock_result = mock_result
        self._ocr = None
        
        if not use_mock:
            try:
                import ddddocr
                self._ocr = ddddocr.DdddOcr(show_ad=False)
                logger.info("ddddocr 验证码模型初始化成功")
            except ImportError:
                logger.warning("未检测到 ddddocr 库，可通过 `pip install ddddocr` 安装以获得自动识别能力")
            except Exception as e:
                logger.warning(f"ddddocr 初始化失败 ({e})，将回退至备用或模拟模式")

    def solve(self, image_bytes: bytes) -> str:
        """
        输入图片二进制数据，输出 4 位小写字母数字验证码
        """
        if self.use_mock or self._ocr is None:
            return self.mock_result

        try:
            res = self._ocr.classification(image_bytes)
            # 过滤特殊字符并统一为小写
            clean_res = "".join([c for c in res if c.isalnum()]).lower()
            logger.info(f"验证码自动识别完成: '{clean_res}'")
            return clean_res
        except Exception as e:
            logger.error(f"验证码识别发生异常: {e}")
            return self.mock_result
