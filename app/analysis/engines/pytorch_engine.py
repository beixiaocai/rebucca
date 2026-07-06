# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""PyTorch 引擎实现

支持加载 ultralytics YOLOv8/v5/v7 .pt 模型（依赖 ultralytics 包），
或原生 torch.hub YOLOv5 custom 加载。
依赖：torch, ultralytics（推荐）
"""

import logging
import os

from app.analysis.engines.base import BaseEngine, DetectionResult

logger = logging.getLogger("analysis.engines.pytorch")

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
    import torch
    _TORCH_AVAILABLE = True
except Exception:
    torch = None
    _TORCH_AVAILABLE = False

try:
    from ultralytics import YOLO as _UltralyticsYOLO
    _ULTRALYTICS_AVAILABLE = True
except Exception:
    _UltralyticsYOLO = None
    _ULTRALYTICS_AVAILABLE = False


class PyTorchEngine(BaseEngine):
    ENGINE_NAME = "pytorch"

    def __init__(self, **kwargs):
        super(PyTorchEngine, self).__init__(**kwargs)
        self._model = None
        self._kind = None  # "ultralytics" / "torchhub"

    @staticmethod
    def is_available():
        return _TORCH_AVAILABLE and _CV2_AVAILABLE and _NP_AVAILABLE

    @staticmethod
    def version():
        if not _TORCH_AVAILABLE:
            return None
        try:
            return getattr(torch, "__version__", "unknown")
        except Exception:
            return "unknown"

    @staticmethod
    def ultralytics_available():
        return _ULTRALYTICS_AVAILABLE

    def load(self):
        if not self.is_available():
            logger.warning("PyTorchEngine: 依赖未安装 (torch=%s)", _TORCH_AVAILABLE)
            return False
        if not self.model_file or not os.path.exists(self.model_file):
            logger.warning("PyTorchEngine: 模型文件不存在: %s", self.model_file)
            return False
        if not self.labels:
            self.labels = self._resolve_labels(self.model_file)

        # 优先用 ultralytics 加载 .pt / .engine / .onnx
        if _ULTRALYTICS_AVAILABLE:
            try:
                self._model = _UltralyticsYOLO(self.model_file)
                self._kind = "ultralytics"
                self._loaded = True
                # 推断 input_size
                try:
                    cfg = getattr(self._model, "overrides", {}) or {}
                    imgsz = cfg.get("imgsz", None)
                    if isinstance(imgsz, int) and imgsz > 0:
                        self.input_size = (int(imgsz), int(imgsz))
                except Exception:
                    pass
                logger.info("PyTorchEngine(ultralytics): 已加载 %s, labels=%d", self.model_file, len(self.labels))
                return True
            except Exception as e:
                logger.warning("PyTorchEngine(ultralytics) 加载失败，尝试 torch.hub: %s", e)

        # 退化：torch.hub YOLOv5 custom
        try:
            self._model = torch.hub.load("ultralytics/yolov5", "custom", path=self.model_file, trust_repo=True)
            self._kind = "torchhub"
            self._loaded = True
            logger.info("PyTorchEngine(torchhub): 已加载 %s", self.model_file)
            return True
        except Exception as e:
            logger.error("PyTorchEngine: 加载失败: %s", e)
            self._loaded = False
            self._model = None
            return False

    def detect(self, frame_bgr):
        if not self.ready() or frame_bgr is None or self._model is None:
            return []
        try:
            if self._kind == "ultralytics":
                iw, ih = self.input_size
                res = self._model.predict(frame_bgr, imgsz=max(iw, ih), conf=self.conf_threshold,
                                          iou=self.iou_threshold, verbose=False)
                return self._parse_ultralytics(res, frame_bgr.shape[:2])
            else:
                # torchhub yolov5
                res = self._model(frame_bgr, size=max(self.input_size))
                return self._parse_torchhub(res, frame_bgr.shape[:2])
        except Exception as e:
            logger.warning("PyTorchEngine.detect() err: %s", e)
            return []

    def _parse_ultralytics(self, results, orig_shape):
        out = []
        try:
            r = results[0]
            if hasattr(r, "boxes") and r.boxes is not None:
                boxes = r.boxes.xyxy.cpu().numpy().astype(int)
                confs = r.boxes.conf.cpu().numpy()
                cls_ids = r.boxes.cls.cpu().numpy().astype(int)
                names = getattr(r, "names", {}) or {}
                for (x1, y1, x2, y2), s, cid in zip(boxes, confs, cls_ids):
                    if s < self.conf_threshold:
                        continue
                    label = names.get(int(cid), str(int(cid))) if isinstance(names, dict) else (
                        self.labels[int(cid)] if 0 <= int(cid) < len(self.labels) else str(int(cid)))
                    out.append(DetectionResult(box=[int(x1), int(y1), int(x2), int(y2)],
                                               label=str(label), score=float(s)))
        except Exception as e:
            logger.warning("PyTorchEngine._parse_ultralytics err: %s", e)
        return out

    def _parse_torchhub(self, results, orig_shape):
        out = []
        try:
            df = results.pandas().xyxy[0]
            for _, row in df.iterrows():
                s = float(row["confidence"])
                if s < self.conf_threshold:
                    continue
                out.append(DetectionResult(box=[int(row["xmin"]), int(row["ymin"]), int(row["xmax"]), int(row["ymax"])],
                                           label=str(row["name"]), score=s))
        except Exception as e:
            logger.warning("PyTorchEngine._parse_torchhub err: %s", e)
        return out

    def info(self):
        d = super(PyTorchEngine, self).info()
        d["version"] = self.version()
        d["ultralytics_available"] = _ULTRALYTICS_AVAILABLE
        d["kind"] = self._kind
        d["device"] = "cuda" if (_TORCH_AVAILABLE and torch.cuda.is_available()) else "cpu"
        return d

    def probe(self):
        info = {"engine": self.ENGINE_NAME, "available": self.is_available(),
                "version": self.version(), "ultralytics_available": _ULTRALYTICS_AVAILABLE,
                "input_shape": None, "output_shape": None,
                "labels": self.labels, "model_file": self.model_file}
        if not self.is_available() or not self.model_file or not os.path.exists(self.model_file):
            return info
        try:
            # 仅读文件大小，不实际加载（torch 模型加载慢且占内存）
            info["model_file_size"] = os.path.getsize(self.model_file)
            if not self.labels:
                self.labels = self._resolve_labels(self.model_file)
                info["labels"] = self.labels
        except Exception as e:
            info["error"] = str(e)
        return info
