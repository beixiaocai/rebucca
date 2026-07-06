# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""统一推理引擎抽象层

每个引擎实现 BaseEngine 接口，由 EngineFactory 按 inference_engine 名分发。
所有引擎对外的 detect() 输入为 BGR frame，输出为 list[DetectionResult]，
与 CameraPipeline 兼容。

支持引擎：
- yolo_pytorch (Yolo-PyTorch，主引擎)
- onnxruntime
- openvino
"""

from app.analysis.engines.base import BaseEngine, EngineNotAvailableError, DetectionResult
from app.analysis.engines.factory import EngineFactory

__all__ = [
    "BaseEngine",
    "EngineNotAvailableError",
    "DetectionResult",
    "EngineFactory",
]
