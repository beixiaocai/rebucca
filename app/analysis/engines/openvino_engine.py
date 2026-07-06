# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""OpenVINO 引擎实现 —— YOLO 5/8/11/26 + 全任务 + 设备支持

依赖：openvino, opencv-python, numpy
推理设备：
  cpu -> CPU
  gpu -> GPU
  cuda -> 不适用，回退 CPU（OpenVINO 不走 CUDA）
"""
import logging
import os

from app.analysis.engines.base import BaseEngine, DetectionResult

logger = logging.getLogger("analysis.engines.openvino")

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
    from openvino import Core
    _OV_AVAILABLE = True
except Exception:
    try:
        from openvino.runtime import Core
        _OV_AVAILABLE = True
    except Exception:
        Core = None
        _OV_AVAILABLE = False


def _device_for(device):
    d = (device or "cpu").lower()
    if d in ("gpu", "cuda", "0"):
        return "GPU"
    return "CPU"


class OpenVinoEngine(BaseEngine):
    ENGINE_NAME = "openvino"

    def __init__(self, **kwargs):
        super(OpenVinoEngine, self).__init__(**kwargs)
        self._compiled = None
        self._infer_req = None
        self._input_key = None
        self._output_keys = None
        self.task_type = (kwargs.get("task_type") or "detect").lower()
        self.device = kwargs.get("device") or "cpu"

    @staticmethod
    def is_available():
        return _OV_AVAILABLE and _CV2_AVAILABLE and _NP_AVAILABLE

    @staticmethod
    def version():
        if not _OV_AVAILABLE:
            return None
        try:
            from openvino.runtime import get_version
            return get_version()
        except Exception:
            pass
        try:
            import openvino
            return getattr(openvino, "__version__", "unknown")
        except Exception:
            return "unknown"

    def _resolve_model_path(self):
        if not self.model_file:
            return None
        if self.model_file.lower().endswith(".onnx"):
            return self.model_file
        base, ext = os.path.splitext(self.model_file)
        if ext.lower() == ".xml":
            return self.model_file
        xml_p = base + ".xml"
        if os.path.exists(xml_p):
            return xml_p
        return None

    def load(self):
        if not self.is_available():
            logger.warning("OpenVinoEngine: 依赖未安装")
            return False
        path = self._resolve_model_path()
        if not path or not os.path.exists(path):
            logger.warning("OpenVinoEngine: 模型文件不可用: %s", self.model_file)
            return False
        if not self.labels:
            self.labels = self._resolve_labels(self.model_file)
        try:
            core = Core()
            model = core.read_model(path)
            dev = _device_for(self.device)
            # GPU 不可用时回退 CPU
            try:
                self._compiled = core.compile_model(model, dev)
            except Exception as e:
                logger.warning("OpenVinoEngine: 设备 %s 编译失败，回退 CPU: %s", dev, e)
                self._compiled = core.compile_model(model, "CPU")
                dev = "CPU"
            self._infer_req = self._compiled.create_infer_request()
            self._input_key = list(self._compiled.inputs)[0]
            self._output_keys = list(self._compiled.outputs)
            self._loaded = True
            logger.info("OpenVinoEngine: 已加载 %s, task=%s, device=%s, labels=%d",
                        path, self.task_type, dev, len(self.labels))
            return True
        except Exception as e:
            logger.error("OpenVinoEngine: 加载失败: %s", e)
            self._loaded = False
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
            self._infer_req.infer({self._input_key: blob})
            outputs = []
            out_count = len(self._output_keys)
            for i in range(out_count):
                try:
                    outputs.append(self._infer_req.get_output_tensor(i).data)
                except Exception:
                    try:
                        outputs.append(self._infer_req.get_output_tensor().data)
                    except Exception as e:
                        logger.warning("OpenVinoEngine: 读取输出 tensor[%d] 失败: %s", i, e)
            if not outputs:
                return []
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
            logger.warning("OpenVinoEngine.detect() err: %s", e)
            return []

    def info(self):
        d = super(OpenVinoEngine, self).info()
        d["version"] = self.version()
        d["task_type"] = self.task_type
        d["device"] = _device_for(self.device)
        return d

    def probe(self):
        info = {"engine": self.ENGINE_NAME, "available": self.is_available(),
                "version": self.version(), "input_shape": None, "output_shape": None,
                "labels": self.labels, "model_file": self.model_file,
                "task_type": self.task_type, "device": _device_for(self.device)}
        if not self.is_available() or not self.model_file:
            return info
        path = self._resolve_model_path()
        if not path or not os.path.exists(path):
            info["error"] = "model file not resolvable"
            return info
        try:
            core = Core()
            model = core.read_model(path)
            if model.inputs:
                shape = list(model.inputs[0].shape)
                info["input_shape"] = shape
                if len(shape) >= 4:
                    info["input_size_inferred"] = (int(shape[-1]), int(shape[-2]))
            if model.outputs:
                info["output_shape"] = [list(o.shape) for o in model.outputs]
            if not self.labels:
                self.labels = self._resolve_labels(self.model_file)
                info["labels"] = self.labels
        except Exception as e:
            info["error"] = str(e)
        return info
