# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""向后兼容 shim：保留 ObjectDetector 名称，内部委托给 OnnxEngine

旧代码 `from app.analysis.detector import ObjectDetector` 仍可工作，
新代码请直接使用 `app.analysis.engines.EngineFactory`。
"""
import logging

from app.analysis.engines.onnx_engine import OnnxEngine

logger = logging.getLogger("analysis.detector")


class ObjectDetector(OnnxEngine):
    """已废弃：等价于 OnnxEngine（detect 任务）。保留以兼容旧 import。"""

    def __init__(self, model_path=None, labels=None, input_size=(640, 640),
                 conf_threshold=0.4, iou_threshold=0.5, providers=None):
        super(ObjectDetector, self).__init__(
            model_file=model_path or "",
            labels=labels,
            input_size=input_size,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            providers=providers,
            task_type="detect",
            device="cpu",
            algorithm_type="yolo8",
        )
        if model_path:
            self.load()
