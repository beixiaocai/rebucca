# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""OnnxRuntime 引擎实现 —— YOLO 5/8/11/26 + 全任务 + 设备支持

依赖：onnxruntime, opencv-python, numpy
推理设备：
  cpu -> CPUExecutionProvider
  cuda/gpu -> CUDAExecutionProvider（不可用回退 CPU）
"""
import logging
import os

from app.analysis.engines.base import BaseEngine, DetectionResult

logger = logging.getLogger("analysis.engines.onnx")

try:
    import numpy as np
    _NP_AVAILABLE = True
except Exception:
    np = None
    _NP_AVAILABLE = False

try:
    import cv2
    _CV2_AVAILABLE = True
except Exception:
    cv2 = None
    _CV2_AVAILABLE = False

try:
    import onnxruntime as ort
    _ORT_AVAILABLE = True
except Exception:
    ort = None
    _ORT_AVAILABLE = False


def _providers_for_device(device):
    d = (device or "cpu").lower()
    if d in ("cuda", "gpu", "0") and _ORT_AVAILABLE:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


class OnnxEngine(BaseEngine):
    ENGINE_NAME = "onnxruntime"

    def __init__(self, **kwargs):
        super(OnnxEngine, self).__init__(**kwargs)
        self._session = None
        self._input_name = None
        self._output_names = None
        self.task_type = (kwargs.get("task_type") or "detect").lower()
        self.device = kwargs.get("device") or "cpu"
        if not self.providers:
            self.providers = _providers_for_device(self.device)

    @staticmethod
    def is_available():
        return _ORT_AVAILABLE and _CV2_AVAILABLE and _NP_AVAILABLE

    @staticmethod
    def version():
        if not _ORT_AVAILABLE:
            return None
        try:
            return getattr(ort, "__version__", "unknown")
        except Exception:
            return "unknown"

    def load(self):
        if not self.is_available():
            logger.warning("OnnxEngine: 依赖未安装 (ort=%s cv2=%s np=%s)", _ORT_AVAILABLE, _CV2_AVAILABLE, _NP_AVAILABLE)
            return False
        if not self.model_file or not os.path.exists(self.model_file):
            logger.warning("OnnxEngine: 模型文件不存在: %s", self.model_file)
            return False
        if not self.labels:
            self.labels = self._resolve_labels(self.model_file)
        try:
            so = ort.SessionOptions()
            so.log_severity_level = 3
            self._session = ort.InferenceSession(self.model_file, sess_options=so, providers=self.providers)
            self._input_name = self._session.get_inputs()[0].name
            self._output_names = [o.name for o in self._session.get_outputs()]
            self._loaded = True
            logger.info("OnnxEngine: 已加载 %s, task=%s, labels=%d, providers=%s",
                        self.model_file, self.task_type, len(self.labels), self._session.get_providers())
            return True
        except Exception as e:
            logger.error("OnnxEngine: 加载失败: %s", e)
            self._loaded = False
            self._session = None
            return False

    def _preprocess(self, frame_bgr):
        iw, ih = self.input_size
        resized = cv2.resize(frame_bgr, (iw, ih))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        blob = rgb.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[None, ...]
        return blob

    def detect(self, frame_bgr):
        if not self.ready() or frame_bgr is None:
            return []
        try:
            h, w = frame_bgr.shape[:2]
            blob = self._preprocess(frame_bgr)
            outputs = self._session.run(self._output_names, {self._input_name: blob})
            from app.analysis.engines.yolo_postprocess import decode_outputs
            results = decode_outputs(
                outputs=outputs,
                algorithm_type=self.algorithm_type,
                task_type=self.task_type,
                labels=self.labels,
                input_size=self.input_size,
                conf_threshold=self.conf_threshold,
                iou_threshold=self.iou_threshold,
                orig_size=(w, h),
            )
            return [DetectionResult(**r) for r in results]
        except Exception as e:
            logger.warning("OnnxEngine.detect() err: %s", e)
            return []

    def info(self):
        d = super(OnnxEngine, self).info()
        d["version"] = self.version()
        d["task_type"] = self.task_type
        d["device"] = self.device
        d["providers"] = self._session.get_providers() if self._session else []
        d["cuda_available"] = ("CUDAExecutionProvider" in (self._session.get_providers() if self._session else []))
        return d

    def probe(self):
        info = {"engine": self.ENGINE_NAME, "available": self.is_available(),
                "version": self.version(), "input_shape": None, "output_shape": None,
                "labels": self.labels, "model_file": self.model_file,
                "task_type": self.task_type, "device": self.device}
        if not self.is_available() or not self.model_file or not os.path.exists(self.model_file):
            return info
        try:
            so = ort.SessionOptions()
            so.log_severity_level = 3
            sess = ort.InferenceSession(self.model_file, sess_options=so, providers=["CPUExecutionProvider"])
            inputs = sess.get_inputs()
            outputs = sess.get_outputs()
            info["input_shape"] = list(inputs[0].shape) if inputs else None
            info["output_shape"] = [list(o.shape) for o in outputs] if outputs else None
            if inputs and len(inputs[0].shape) >= 4:
                info["input_size_inferred"] = (int(inputs[0].shape[-1]), int(inputs[0].shape[-2]))
            if not self.labels:
                self.labels = self._resolve_labels(self.model_file)
                info["labels"] = self.labels
        except Exception as e:
            info["error"] = str(e)
        return info
