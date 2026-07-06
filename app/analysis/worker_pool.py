# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""检测器缓存池（按算法 ID 缓存引擎实例）

阶段1：每路 pipeline 持有 engine 实例（线程安全由各引擎保证）。
阶段2演进：将推理请求路由到独立的推理子进程池，通过 ZeroMQ 回传结果。
"""
import json
import logging
import os
import threading

logger = logging.getLogger("analysis.worker_pool")


class DetectorWorkerPool(object):
    """按 algorithm_id 缓存 BaseEngine 实例。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._engines = {}  # algorithm_id -> BaseEngine

    def get_detector(self, algorithm):
        """传入 AlgorithmModel 实例（或 dict），返回对应引擎实例（已 load）。

        缓存命中返回已有实例；否则用 EngineFactory 创建并 load，失败返回 None。
        """
        from app.analysis.engines.factory import EngineFactory
        from app.analysis.engines.base import EngineNotAvailableError

        if algorithm is None:
            return None
        # 兼容 dict
        if isinstance(algorithm, dict):
            algo_id = algorithm.get("id")
            engine_name = algorithm.get("inference_engine", "yolo_pytorch")
            model_file = algorithm.get("model_file", "")
            labels = algorithm.get("labels", [])
            if isinstance(labels, str):
                try:
                    labels = json.loads(labels)
                except Exception:
                    labels = []
            input_size = (int(algorithm.get("input_width", 640)), int(algorithm.get("input_height", 640)))
            conf = float(algorithm.get("conf_threshold", 0.4))
            iou = float(algorithm.get("iou_threshold", 0.5))
            algo_type = algorithm.get("algorithm_type", "yolo8")
            task_type = algorithm.get("task_type", "detect")
            device = algorithm.get("device", "cpu")
        else:
            algo_id = getattr(algorithm, "id", None)
            engine_name = algorithm.inference_engine
            model_file = algorithm.model_file
            labels = algorithm.labels
            if isinstance(labels, str):
                try:
                    labels = json.loads(labels)
                except Exception:
                    labels = []
            input_size = (algorithm.input_width, algorithm.input_height)
            conf = algorithm.conf_threshold
            iou = algorithm.iou_threshold
            algo_type = algorithm.algorithm_type
            task_type = getattr(algorithm, "task_type", "detect")
            device = getattr(algorithm, "device", "cpu")

        key = (algo_id, engine_name, model_file, conf, iou, input_size, task_type, device)
        with self._lock:
            det = self._engines.get(key)
            if det is not None:
                return det
            try:
                det = EngineFactory.create(engine_name,
                    model_file=resolve_model_path(model_file),
                    labels=labels,
                    input_size=input_size,
                    conf_threshold=conf,
                    iou_threshold=iou,
                    algorithm_type=algo_type,
                    task_type=task_type,
                    device=device)
                if not det.load():
                    logger.warning("DetectorWorkerPool: 引擎 load 失败 algo=%s engine=%s", algo_id, engine_name)
                    return None
                self._engines[key] = det
                return det
            except EngineNotAvailableError as e:
                logger.warning("DetectorWorkerPool: %s", e)
                return None
            except Exception as e:
                logger.exception("DetectorWorkerPool: 创建引擎异常: %s", e)
                return None

    def clear(self):
        with self._lock:
            self._engines.clear()

    def instance_info(self):
        """返回当前缓存的引擎实例列表"""
        with self._lock:
            out = []
            for key, eng in self._engines.items():
                try:
                    out.append({
                        "algorithm_id": key[0],
                        "engine": eng.ENGINE_NAME,
                        "input_size": list(eng.input_size),
                        "task_type": getattr(eng, "task_type", "detect"),
                        "device": getattr(eng, "device", "cpu"),
                        "ready": eng.ready(),
                    })
                except Exception:
                    pass
            return out

    @property
    def instance_count(self):
        with self._lock:
            return len(self._engines)


# 模型文件路径解析：仅 uploadDir/weight
def resolve_model_path(model_file):
    if not model_file:
        return ""
    mf = str(model_file).strip()
    if os.path.isabs(mf) and os.path.isfile(mf):
        return mf
    weight_dir = get_weight_dir()
    if not weight_dir:
        return ""
    for name in (mf, os.path.basename(mf)):
        cand = os.path.join(weight_dir, name)
        if os.path.isfile(cand):
            return cand
    return ""


def get_weight_dir():
    """返回 uploadDir/weight 绝对路径（不存在则创建）。"""
    d = _get_upload_weight_dir(_get_project_base_dir())
    if d:
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
    return d or ""


def _norm_path(path, base):
    if not path:
        return ""
    p = str(path).strip()
    if not p:
        return ""
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(base, p.replace("\\", "/")))


def _get_project_base_dir():
    """获取项目根目录（不依赖 GlobalUtils，子进程安全）"""
    try:
        from django.conf import settings
        base = getattr(settings, "BASE_DIR", None)
        if base:
            return str(base)
    except Exception:
        pass
    # 兜底：worker_pool.py 位于 <base>/app/analysis/，向上两级
    try:
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except Exception:
        return ""


def _get_upload_weight_dir(base):
    """获取 uploadDir/weight 绝对路径（子进程安全，不依赖 GlobalUtils 单例）。"""
    try:
        from app.utils.GlobalUtils import g_config
        d = getattr(g_config, "uploadAlgorithmWeightDir", None)
        if d:
            return os.path.normpath(str(d))
    except Exception:
        pass
    if not base:
        base = _get_project_base_dir()
    try:
        import json
        cfg_path = os.path.join(base, "config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            upload_dir = cfg.get("uploadDir")
            if upload_dir:
                return os.path.normpath(os.path.join(_norm_path(upload_dir, base), "weight"))
    except Exception:
        pass
    if base:
        return os.path.normpath(os.path.join(base, "static", "upload", "weight"))
    return ""
