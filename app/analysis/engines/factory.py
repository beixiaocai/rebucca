# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""引擎工厂：按 inference_engine 名分发实例

注册引擎：
- yolo_pytorch : Yolo-PyTorch（ultralytics 原生，全版本全任务，主引擎）
- onnxruntime  : OnnxRuntime
- openvino     : OpenVINO
"""

import logging

from app.analysis.engines.base import BaseEngine, EngineNotAvailableError
from app.analysis.engines.yolo_pytorch_engine import YoloPytorchEngine
from app.analysis.engines.onnx_engine import OnnxEngine
from app.analysis.engines.openvino_engine import OpenVinoEngine
from app.analysis.engines.reid_onnx_engine import ReidOnnxEngine

logger = logging.getLogger("analysis.engines.factory")

_ENGINE_REGISTRY = {
    "yolo_pytorch": YoloPytorchEngine,
    "yolopytorch": YoloPytorchEngine,  # 别名
    "pytorch": YoloPytorchEngine,      # 兼容旧名
    "onnxruntime": OnnxEngine,
    "onnx": OnnxEngine,
    "openvino": OpenVinoEngine,
}

# 设备选项按引擎分组（供前端动态下拉使用）
_DEVICE_OPTIONS = {
    "yolo_pytorch": [
        {"value": "cpu", "label": "CPU"},
        {"value": "cuda", "label": "CUDA (GPU)"},
    ],
    "onnxruntime": [
        {"value": "cpu", "label": "CPU"},
        {"value": "cuda", "label": "CUDA (GPU)"},
    ],
    "openvino": [
        {"value": "cpu", "label": "CPU"},
        {"value": "gpu", "label": "GPU (Intel iGPU/dGPU)"},
    ],
}


def list_engines():
    """返回所有注册引擎的可用性信息"""
    out = []
    seen = set()
    for name, cls in _ENGINE_REGISTRY.items():
        if name in ("yolopytorch", "pytorch", "onnx"):
            continue
        if name in seen:
            continue
        seen.add(name)
        try:
            available = cls.is_available()
            version = cls.version() if available else None
        except Exception as e:
            available = False
            version = None
            logger.warning("list_engines %s err: %s", name, e)
        # 主引擎额外提供 ultralytics 版本与 CUDA 可用性
        item = {"name": name, "available": available, "version": version,
                "devices": _DEVICE_OPTIONS.get(name, _DEVICE_OPTIONS["yolo_pytorch"])}
        if name == "yolo_pytorch" and available:
            try:
                item["ultralytics_version"] = YoloPytorchEngine.ultralytics_version()
                import torch
                item["cuda_available"] = bool(torch.cuda.is_available())
            except Exception:
                pass
        out.append(item)
    return out


def device_options(engine_name):
    return _DEVICE_OPTIONS.get((engine_name or "").lower(), _DEVICE_OPTIONS["yolo_pytorch"])


class EngineFactory(object):

    @staticmethod
    def create(engine_name, **kwargs):
        task_type = (kwargs.get("task_type") or "detect").lower()
        if task_type == "reid":
            eng = (engine_name or "").lower()
            if eng not in ("onnxruntime", "onnx"):
                raise EngineNotAvailableError("ReID models only support onnxruntime")
            if not ReidOnnxEngine.is_available():
                raise EngineNotAvailableError("reid onnxruntime not installed")
            return ReidOnnxEngine(**kwargs)
        cls = _ENGINE_REGISTRY.get((engine_name or "").lower())
        if cls is None:
            raise EngineNotAvailableError("unknown engine: %s" % engine_name)
        if not cls.is_available():
            raise EngineNotAvailableError("engine %s not installed" % engine_name)
        return cls(**kwargs)

    @staticmethod
    def is_available(engine_name):
        cls = _ENGINE_REGISTRY.get((engine_name or "").lower())
        return bool(cls and cls.is_available())

    @staticmethod
    def list_engines():
        return list_engines()

    @staticmethod
    def device_options(engine_name):
        return device_options(engine_name)
