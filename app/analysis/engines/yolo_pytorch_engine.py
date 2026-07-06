# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""Yolo-PyTorch 引擎（主引擎，最高准确率）

基于 ultralytics 包，原生支持 YOLOv5/v8/v11/YOLO26 全部任务：
detect / segment / classify / pose / obb

依赖：torch, ultralytics, opencv-python, numpy
推理设备：cpu / cuda / cuda:0 / 0 / gpu
"""
import logging
import os

from app.analysis.engines.base import BaseEngine, DetectionResult

logger = logging.getLogger("analysis.engines.yolo_pytorch")

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


def _normalize_device(device, algorithm_type):
    """把模型字段 device 归一化为 ultralytics 可接受的 device 字符串。

    cpu -> 'cpu'
    cuda -> 'cuda'（如可用）否则回退 'cpu'
    gpu -> 'cuda'（OpenVINO 风格命名兼容）
    """
    if not device:
        return "cpu"
    d = str(device).lower().strip()
    if d in ("cpu", ""):
        return "cpu"
    if d in ("cuda", "gpu", "cuda:0", "0"):
        if _TORCH_AVAILABLE and torch.cuda.is_available():
            return "cuda:0" if d in ("gpu", "0") else "cuda"
        logger.warning("YoloPytorchEngine: CUDA 不可用，回退 CPU")
        return "cpu"
    return d


class YoloPytorchEngine(BaseEngine):
    ENGINE_NAME = "yolo_pytorch"

    def __init__(self, **kwargs):
        super(YoloPytorchEngine, self).__init__(**kwargs)
        self._model = None
        self.task_type = (kwargs.get("task_type") or "detect").lower()
        self.device = kwargs.get("device") or "cpu"

    @staticmethod
    def is_available():
        return _TORCH_AVAILABLE and _ULTRALYTICS_AVAILABLE and _CV2_AVAILABLE and _NP_AVAILABLE

    @staticmethod
    def version():
        if not _TORCH_AVAILABLE:
            return None
        try:
            return getattr(torch, "__version__", "unknown")
        except Exception:
            return "unknown"

    @staticmethod
    def ultralytics_version():
        if not _ULTRALYTICS_AVAILABLE:
            return None
        try:
            import ultralytics
            return getattr(ultralytics, "__version__", "unknown")
        except Exception:
            return "unknown"

    def load(self):
        if not self.is_available():
            logger.warning("YoloPytorchEngine: 依赖未安装 (torch=%s ultralytics=%s cv2=%s np=%s)",
                           _TORCH_AVAILABLE, _ULTRALYTICS_AVAILABLE, _CV2_AVAILABLE, _NP_AVAILABLE)
            return False
        if not self.model_file or not os.path.exists(self.model_file):
            logger.warning("YoloPytorchEngine: 模型文件不存在: %s", self.model_file)
            return False
        if not self.labels:
            self.labels = self._resolve_labels(self.model_file)
        try:
            self._model = _UltralyticsYOLO(self.model_file, task=self.task_type)
            # 推断 input_size
            try:
                cfg = getattr(self._model, "overrides", {}) or {}
                imgsz = cfg.get("imgsz", None)
                if isinstance(imgsz, int) and imgsz > 0:
                    self.input_size = (int(imgsz), int(imgsz))
                elif isinstance(imgsz, (list, tuple)) and len(imgsz) >= 1:
                    s = int(imgsz[0])
                    self.input_size = (s, s)
            except Exception:
                pass
            # 预热（小尺寸 dummy），让模型迁移到目标设备
            try:
                dev = _normalize_device(self.device, self.algorithm_type)
                dummy = np.zeros((self.input_size[1], self.input_size[0], 3), dtype=np.uint8)
                self._model.predict(dummy, imgsz=max(self.input_size), device=dev,
                                    conf=self.conf_threshold, iou=self.iou_threshold,
                                    verbose=False, save=False)
            except Exception as e:
                logger.warning("YoloPytorchEngine 预热失败（忽略）: %s", e)
            self._loaded = True
            logger.info("YoloPytorchEngine: 已加载 %s task=%s device=%s labels=%d",
                        self.model_file, self.task_type, _normalize_device(self.device, self.algorithm_type),
                        len(self.labels))
            return True
        except Exception as e:
            logger.error("YoloPytorchEngine: 加载失败: %s", e)
            self._loaded = False
            self._model = None
            return False

    def detect(self, frame_bgr):
        if not self.ready() or frame_bgr is None or self._model is None:
            return []
        try:
            dev = _normalize_device(self.device, self.algorithm_type)
            iw, ih = self.input_size
            results = self._model.predict(frame_bgr, imgsz=max(iw, ih), device=dev,
                                          conf=self.conf_threshold, iou=self.iou_threshold,
                                          verbose=False, save=False)
            return self._parse_results(results)
        except Exception as e:
            logger.warning("YoloPytorchEngine.detect() err: %s", e)
            return []

    def _parse_results(self, results):
        out = []
        try:
            r = results[0]
            task = self.task_type
            if task == "classify":
                probs = getattr(r, "probs", None)
                if probs is not None:
                    cid = int(probs.top1)
                    score = float(probs.top1conf)
                    names = getattr(r, "names", {}) or {}
                    label = names.get(cid, str(cid)) if isinstance(names, dict) else (
                        self.labels[cid] if 0 <= cid < len(self.labels) else str(cid))
                    out.append(DetectionResult(box=[0, 0, 0, 0], label=str(label), score=score, task="classify"))
                return out
            # 其余任务都有 boxes
            boxes_obj = getattr(r, "boxes", None)
            names = getattr(r, "names", {}) or {}
            if boxes_obj is not None:
                try:
                    xyxy = boxes_obj.xyxy.cpu().numpy()
                    confs = boxes_obj.conf.cpu().numpy()
                    cls_ids = boxes_obj.cls.cpu().numpy().astype(int)
                    for (b, s, cid) in zip(xyxy, confs, cls_ids):
                        if s < self.conf_threshold:
                            continue
                        label = names.get(int(cid), str(int(cid))) if isinstance(names, dict) else (
                            self.labels[int(cid)] if 0 <= int(cid) < len(self.labels) else str(int(cid)))
                        item = DetectionResult(box=[int(b[0]), int(b[1]), int(b[2]), int(b[3])],
                                               label=str(label), score=float(s), task=task)
                        out.append(item)
                except Exception as e:
                    logger.warning("YoloPytorchEngine parse boxes err: %s", e)

            # segment: masks
            if task == "segment":
                masks_obj = getattr(r, "masks", None)
                if masks_obj is not None and out:
                    try:
                        # masks_obj.xy 是 list of (N,2) 多边形点（原图坐标）
                        polys = masks_obj.xy
                        for i, p in enumerate(polys):
                            if i < len(out):
                                out[i]["mask_polygon"] = [[float(x), float(y)] for x, y in p]
                    except Exception as e:
                        logger.warning("YoloPytorchEngine parse masks err: %s", e)

            # pose: keypoints
            if task == "pose":
                kp_obj = getattr(r, "keypoints", None)
                if kp_obj is not None and out:
                    try:
                        kpts = kp_obj.xy.cpu().numpy()  # [N, nk, 2]
                        confs = kp_obj.conf.cpu().numpy()  # [N, nk]
                        for i in range(min(len(kpts), len(out))):
                            kp = kpts[i]
                            kc = confs[i]
                            out[i]["keypoints"] = [
                                [float(kp[j, 0]), float(kp[j, 1]), float(kc[j])]
                                for j in range(len(kp))
                            ]
                    except Exception as e:
                        logger.warning("YoloPytorchEngine parse keypoints err: %s", e)

            # obb: rotated boxes + angle
            if task == "obb":
                obb_obj = getattr(r, "obb", None)
                if obb_obj is not None and out:
                    try:
                        # obb.theta: [N] radians
                        thetas = obb_obj.theta.cpu().numpy()
                        for i in range(min(len(thetas), len(out))):
                            out[i]["angle"] = float(thetas[i])
                    except Exception as e:
                        logger.warning("YoloPytorchEngine parse obb err: %s", e)
        except Exception as e:
            logger.warning("YoloPytorchEngine._parse_results err: %s", e)
        return out

    def info(self):
        d = super(YoloPytorchEngine, self).info()
        d["version"] = self.version()
        d["ultralytics_version"] = self.ultralytics_version()
        d["task_type"] = self.task_type
        d["device"] = _normalize_device(self.device, self.algorithm_type)
        d["cuda_available"] = bool(_TORCH_AVAILABLE and torch.cuda.is_available())
        return d

    def probe(self):
        info = {"engine": self.ENGINE_NAME, "available": self.is_available(),
                "version": self.version(), "ultralytics_version": self.ultralytics_version(),
                "cuda_available": bool(_TORCH_AVAILABLE and torch.cuda.is_available()),
                "input_shape": None, "output_shape": None,
                "labels": self.labels, "model_file": self.model_file,
                "task_type": self.task_type, "device": self.device}
        if not self.is_available() or not self.model_file or not os.path.exists(self.model_file):
            return info
        try:
            info["model_file_size"] = os.path.getsize(self.model_file)
            if not self.labels:
                self.labels = self._resolve_labels(self.model_file)
                info["labels"] = self.labels
            # 尝试读取 ultralytics yaml 的 imgsz 与 task
            base, _ = os.path.splitext(self.model_file)
            for p in (base + ".yaml", os.path.join(os.path.dirname(self.model_file), "model.yaml")):
                if os.path.exists(p):
                    try:
                        import yaml
                        with open(p, "r", encoding="utf-8") as f:
                            cfg = yaml.safe_load(f) or {}
                        if "imgsz" in cfg:
                            s = int(cfg["imgsz"]) if not isinstance(cfg["imgsz"], (list, tuple)) else int(cfg["imgsz"][0])
                            info["input_size_inferred"] = (s, s)
                        if "task" in cfg and not self.task_type:
                            info["task_type"] = str(cfg["task"])
                    except Exception:
                        pass
                    break
        except Exception as e:
            info["error"] = str(e)
        return info
