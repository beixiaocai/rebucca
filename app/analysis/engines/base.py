# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""引擎抽象基类与公共数据结构"""

import logging

logger = logging.getLogger("analysis.engines")


class EngineNotAvailableError(RuntimeError):
    """引擎依赖未安装"""


class DetectionResult(dict):
    """单条检测结果：{box:[x1,y1,x2,y2], label:str, score:float}"""

    @property
    def box(self):
        return self.get("box", [0, 0, 0, 0])

    @property
    def label(self):
        return self.get("label", "")

    @property
    def score(self):
        return self.get("score", 0.0)


class BaseEngine(object):
    """所有推理引擎的统一接口。

    子类需实现：
    - is_available() @staticmethod —— 该引擎依赖是否已安装
    - load() —— 加载模型，成功返回 True
    - detect(frame_bgr) —— 输入 BGR frame，输出 list[DetectionResult]
    - info() —— 返回引擎元数据 dict
    """

    ENGINE_NAME = "base"

    def __init__(self, model_file=None, labels=None, input_size=(640, 640),
                 conf_threshold=0.4, iou_threshold=0.5, providers=None,
                 algorithm_type="yolo", algorithm_version="",
                 task_type="detect", device="cpu"):
        self.model_file = model_file or ""
        self.labels = labels or []
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.providers = providers or []
        self.algorithm_type = algorithm_type
        self.algorithm_version = algorithm_version
        self.task_type = (task_type or "detect").lower()
        self.device = device or "cpu"
        self._loaded = False

    @staticmethod
    def is_available():
        raise NotImplementedError

    def load(self):
        raise NotImplementedError

    def ready(self):
        return self._loaded

    def detect(self, frame_bgr):
        raise NotImplementedError

    def info(self):
        return {
            "engine": self.ENGINE_NAME,
            "model_file": self.model_file,
            "input_size": list(self.input_size),
            "labels_count": len(self.labels),
            "conf_threshold": self.conf_threshold,
            "iou_threshold": self.iou_threshold,
            "loaded": self._loaded,
        }

    def _resolve_labels(self, model_file):
        """从 sidecar .labels / .yaml/.names 文件推断标签"""
        import os
        if not model_file:
            return []
        base, _ = os.path.splitext(model_file)
        for ext in (".labels", ".names"):
            p = base + ext
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        return [ln.strip() for ln in f if ln.strip()]
                except Exception as e:
                    logger.warning("%s: 读取 %s 失败: %s", self.ENGINE_NAME, p, e)
        # YOLOv5/v8 yaml
        yaml_p = base + ".yaml"
        if os.path.exists(yaml_p):
            try:
                import yaml
                with open(yaml_p, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                names = cfg.get("names") or []
                if isinstance(names, list):
                    return [str(x) for x in names]
                if isinstance(names, dict):
                    return [str(names[k]) for k in sorted(names.keys())]
            except Exception as e:
                logger.warning("%s: 解析 %s 失败: %s", self.ENGINE_NAME, yaml_p, e)
        return []
