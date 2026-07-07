# 作者：北小菜
"""ReID 特征提取引擎 — OSNet 系列 ONNX（仅 OnnxRuntime）

输入：人体 crop BGR → resize → ImageNet 归一化 → embedding 向量
输出：512 维 L2 归一化特征（默认 OSNet-AIN x1.0）
"""
import logging
import os

from app.analysis.engines.base import BaseEngine, EngineNotAvailableError

logger = logging.getLogger("analysis.engines.reid_onnx")

try:
    import numpy as np
    _NP = True
except Exception:
    np = None
    _NP = False

try:
    import cv2
    _CV2 = True
except Exception:
    cv2 = None
    _CV2 = False

try:
    import onnxruntime as ort
    _ORT = True
except Exception:
    ort = None
    _ORT = False

REID_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32) if _NP else None
REID_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32) if _NP else None


def _providers_for_device(device):
    d = (device or "cpu").lower()
    if d in ("cuda", "gpu", "0") and _ORT:
        avail = ort.get_available_providers()
        if "CUDAExecutionProvider" in avail:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


class ReidOnnxEngine(BaseEngine):
    """ReID embedding 引擎（batch=1 静态 ONNX）。"""

    ENGINE_NAME = "reid_onnx"

    def __init__(self, **kwargs):
        super(ReidOnnxEngine, self).__init__(**kwargs)
        self.task_type = "reid"
        self._session = None
        self._input_name = None
        self._output_name = None
        self._embedding_dim = 512
        if not self.providers:
            self.providers = _providers_for_device(self.device)

    @staticmethod
    def is_available():
        return _ORT and _CV2 and _NP

    @staticmethod
    def version():
        if not _ORT:
            return None
        try:
            return getattr(ort, "__version__", "unknown")
        except Exception:
            return "unknown"

    def load(self):
        if not self.is_available():
            logger.warning("ReidOnnxEngine: 依赖未安装")
            return False
        if not self.model_file or not os.path.exists(self.model_file):
            logger.warning("ReidOnnxEngine: 模型不存在 %s", self.model_file)
            return False
        try:
            so = ort.SessionOptions()
            so.log_severity_level = 3
            self._session = ort.InferenceSession(
                self.model_file, sess_options=so, providers=self.providers)
            self._input_name = self._session.get_inputs()[0].name
            self._output_name = self._session.get_outputs()[0].name
            out_shape = self._session.get_outputs()[0].shape
            if out_shape and len(out_shape) >= 2 and out_shape[-1]:
                try:
                    self._embedding_dim = int(out_shape[-1])
                except Exception:
                    pass
            self._loaded = True
            logger.info("ReidOnnxEngine: loaded %s providers=%s dim=%d",
                        self.model_file, self._session.get_providers(), self._embedding_dim)
            return True
        except Exception as e:
            logger.error("ReidOnnxEngine load failed: %s", e)
            self._session = None
            self._loaded = False
            return False

    @property
    def session(self):
        return self._session

    def _preprocess_crop(self, frame_bgr, box):
        iw = int(self.input_size[0] or 128)
        ih = int(self.input_size[1] or 256)
        x1, y1, x2, y2 = [int(v) for v in box]
        h, w = frame_bgr.shape[:2]
        x1 = max(0, min(x1, w - 1))
        x2 = max(0, min(x2, w))
        y1 = max(0, min(y1, h - 1))
        y2 = max(0, min(y2, h))
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (iw, ih), interpolation=cv2.INTER_LINEAR)
        arr = resized.astype(np.float32) / 255.0
        arr = (arr - REID_MEAN) / REID_STD
        return np.transpose(arr, (2, 0, 1))[None, ...].astype(np.float32)

    def extract_embeddings(self, frame_bgr, boxes):
        """对多个 bbox 提取 embedding，返回与 boxes 对齐的 (valid_idx, embeddings)。"""
        if not self.ready() or frame_bgr is None:
            return [], np.zeros((0, self._embedding_dim), dtype=np.float32)
        valid_idx = []
        rows = []
        for i, box in enumerate(boxes or []):
            blob = self._preprocess_crop(frame_bgr, box)
            if blob is None:
                continue
            out = self._session.run([self._output_name], {self._input_name: blob})[0]
            vec = np.asarray(out, dtype=np.float32).reshape(-1)
            norm = np.linalg.norm(vec)
            if norm > 1e-12:
                vec = vec / norm
            valid_idx.append(i)
            rows.append(vec)
        if not rows:
            return [], np.zeros((0, self._embedding_dim), dtype=np.float32)
        return valid_idx, np.stack(rows, axis=0)

    def detect(self, frame_bgr):
        """兼容 BaseEngine 接口；ReID 单模型无法对全图直接检测，返回空列表。"""
        return []

    def probe(self):
        info = {
            "engine": self.ENGINE_NAME,
            "available": self.is_available(),
            "version": self.version(),
            "input_shape": None,
            "output_shape": None,
            "labels": [],
            "model_file": self.model_file,
            "task_type": "reid",
            "algorithm_type": self.algorithm_type,
            "device": self.device,
            "embedding_dim": self._embedding_dim,
        }
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
                # ONNX NCHW: [N,C,H,W] → width=shape[-1], height=shape[-2]
                info["input_size_inferred"] = (int(inputs[0].shape[-1]), int(inputs[0].shape[-2]))
            if outputs and outputs[0].shape:
                sh = outputs[0].shape
                if len(sh) >= 2 and sh[-1]:
                    info["embedding_dim"] = int(sh[-1])
        except Exception as e:
            info["error"] = str(e)
        if self.model_file and os.path.isfile(self.model_file):
            info["model_file_size"] = os.path.getsize(self.model_file)
        return info

    def info(self):
        d = super(ReidOnnxEngine, self).info()
        d["version"] = self.version()
        d["task_type"] = "reid"
        d["embedding_dim"] = self._embedding_dim
        d["providers"] = self._session.get_providers() if self._session else []
        return d
