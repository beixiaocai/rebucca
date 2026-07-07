# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""共享推理子进程池 — 多路摄像头复用同一组 YOLO 引擎，避免每路重复加载模型。

阶段2架构：
- 主进程启动 N 个 InferenceWorker 子进程（默认 1，可配置 analysisInferenceWorkers）
- 子进程内按 algorithm_id 缓存引擎实例
- 请求/响应通过 multiprocessing.Queue 传递；帧以 JPEG 压缩跨进程（体积可控）
"""
import json
import logging
import multiprocessing as mp
import os
import queue
import threading
import time
import uuid

logger = logging.getLogger("analysis.inference_pool")

_POOL = None
_POOL_LOCK = threading.Lock()


def _resolve_model_path(model_file):
    from app.analysis.worker_pool import resolve_model_path
    return resolve_model_path(model_file)


def _inference_worker_loop(req_queue, resp_queue, worker_id):
    """子进程推理循环（不 import Django ORM）"""
    from app.utils.Logger import LOG_FORMAT
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    engines = {}
    log = logging.getLogger("analysis.inference_worker.%s" % worker_id)
    log.info("推理 worker 启动")

    while True:
        try:
            msg = req_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        if msg is None or msg.get("cmd") == "stop":
            break
        req_id = msg.get("req_id")
        try:
            algo = msg.get("algorithm") or {}
            jpeg = msg.get("jpeg")
            if not jpeg:
                resp_queue.put({"req_id": req_id, "ok": False, "error": "no frame"})
                continue
            import cv2
            import numpy as np
            arr = np.frombuffer(jpeg, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                resp_queue.put({"req_id": req_id, "ok": False, "error": "decode failed"})
                continue

            algo_id = algo.get("id", 0)
            key = (
                algo_id,
                algo.get("inference_engine", ""),
                algo.get("model_file", ""),
                float(algo.get("conf_threshold", 0.4)),
                float(algo.get("iou_threshold", 0.5)),
                int(algo.get("input_width", 640)),
                int(algo.get("input_height", 640)),
                algo.get("task_type", "detect"),
                algo.get("device", "cpu"),
            )
            eng = engines.get(key)
            if eng is None:
                from app.analysis.engines.factory import EngineFactory
                labels = algo.get("labels", [])
                if isinstance(labels, str):
                    try:
                        labels = json.loads(labels)
                    except Exception:
                        labels = []
                eng = EngineFactory.create(
                    algo.get("inference_engine", "yolo_pytorch"),
                    model_file=_resolve_model_path(algo.get("model_file", "")),
                    labels=labels,
                    input_size=(int(algo.get("input_width", 640)), int(algo.get("input_height", 640))),
                    conf_threshold=float(algo.get("conf_threshold", 0.4)),
                    iou_threshold=float(algo.get("iou_threshold", 0.5)),
                    algorithm_type=algo.get("algorithm_type", "yolo8"),
                    task_type=algo.get("task_type", "detect"),
                    device=algo.get("device", "cpu"),
                )
                if not eng.load():
                    resp_queue.put({"req_id": req_id, "ok": False, "error": "engine load failed"})
                    continue
                engines[key] = eng

            results = eng.detect(frame)
            for r in results:
                r["algorithm_id"] = algo_id
                r["algorithm_name"] = algo.get("name", "")
            resp_queue.put({"req_id": req_id, "ok": True, "detections": results})
        except Exception as e:
            log.exception("推理异常: %s", e)
            resp_queue.put({"req_id": req_id, "ok": False, "error": str(e)})

    for eng in engines.values():
        try:
            if hasattr(eng, "unload"):
                eng.unload()
        except Exception:
            pass
    log.info("推理 worker 退出")


class InferenceProcessPool(object):
    """主进程侧推理池客户端"""

    def __init__(self, num_workers=1):
        self.num_workers = max(1, int(num_workers))
        self._req_queue = mp.Queue(maxsize=64)
        self._resp_queue = mp.Queue(maxsize=64)
        self._workers = []
        self._pending = {}
        self._lock = threading.Lock()
        self._running = False
        self._drain_thread = None
        self._timeout_count = 0
        self._last_timeout_ts = 0.0

    def start(self):
        if self._running:
            alive = sum(1 for p in self._workers if p.is_alive())
            if alive > 0:
                return
            logger.warning("InferenceProcessPool 标记运行中但 worker 已死，重新启动")
            self.stop()
        ctx = mp.get_context("spawn")
        self._req_queue = ctx.Queue(maxsize=64)
        self._resp_queue = ctx.Queue(maxsize=64)
        for i in range(self.num_workers):
            p = ctx.Process(
                target=_inference_worker_loop,
                args=(self._req_queue, self._resp_queue, i),
                name="inference-worker-%d" % i,
                daemon=True,
            )
            p.start()
            self._workers.append(p)
        self._running = True
        self._drain_thread = threading.Thread(target=self._drain_responses, name="inference-drain", daemon=True)
        self._drain_thread.start()
        logger.info("InferenceProcessPool 已启动 workers=%d", self.num_workers)

    def _drain_responses(self):
        while self._running:
            try:
                resp = self._resp_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            req_id = resp.get("req_id")
            with self._lock:
                evt = self._pending.pop(req_id, None)
            if evt:
                evt["resp"] = resp
                evt["event"].set()

    def detect(self, frame, algorithm, timeout=30.0):
        """同步推理：将 frame + algorithm dict 发往子进程，等待结果"""
        if not self._running:
            self.start()
        try:
            import cv2
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                return []
            jpeg = buf.tobytes()
        except Exception as e:
            logger.warning("帧编码失败: %s", e)
            return []
        return self.detect_jpeg(jpeg, algorithm, timeout=timeout)

    def _ensure_workers_alive(self):
        if not self._workers:
            if self._running:
                self.stop()
            self.start()
            return
        alive = sum(1 for p in self._workers if p.is_alive())
        if alive == 0:
            logger.warning("推理 worker 已全部退出，正在重启 InferenceProcessPool")
            self.stop()
            self.start()

    def detect_jpeg(self, jpeg, algorithm, timeout=30.0):
        """同步推理：直接传已编码的 JPEG bytes，跳过主进程 imencode/imdecode，
        消除 _inference_forwarder_loop 中的双重编解码与主进程 GIL 占用。"""
        self._ensure_workers_alive()
        if not self._running:
            self.start()
        if not jpeg:
            return []
        req_id = str(uuid.uuid4())
        evt = {"event": threading.Event(), "resp": None}
        with self._lock:
            self._pending[req_id] = evt

        algo_payload = algorithm if isinstance(algorithm, dict) else _algorithm_to_dict(algorithm)
        try:
            self._req_queue.put({"req_id": req_id, "algorithm": algo_payload, "jpeg": jpeg}, timeout=2.0)
        except Exception as e:
            with self._lock:
                self._pending.pop(req_id, None)
            logger.warning("推理请求入队失败: %s", e)
            return []

        if not evt["event"].wait(timeout=timeout):
            with self._lock:
                self._pending.pop(req_id, None)
                self._timeout_count += 1
                self._last_timeout_ts = time.time()
            logger.warning("推理超时 req_id=%s (累计 %d)", req_id, self._timeout_count)
            return []
        resp = evt.get("resp") or {}
        if not resp.get("ok"):
            logger.warning("推理失败: %s", resp.get("error"))
            return []
        return resp.get("detections") or []

    def status(self):
        self._ensure_workers_alive()
        alive = sum(1 for p in self._workers if p.is_alive())
        with self._lock:
            tc = self._timeout_count
            lts = self._last_timeout_ts
        degraded = alive > 0 and tc >= 3 and (time.time() - lts) < 120
        return {
            "workers": self.num_workers,
            "workers_alive": alive,
            "running": self._running,
            "timeout_count": tc,
            "inference_degraded": degraded,
        }

    def instance_count(self):
        """共享推理 worker 进程数（模型在 worker 内按需加载，非 worker_pool 计数）。"""
        return sum(1 for p in self._workers if p.is_alive())

    def stop(self):
        self._running = False
        for _ in self._workers:
            try:
                self._req_queue.put({"cmd": "stop"}, timeout=1.0)
            except Exception:
                pass
        for p in self._workers:
            try:
                p.join(timeout=3)
                if p.is_alive():
                    p.terminate()
            except Exception:
                pass
        self._workers = []
        logger.info("InferenceProcessPool 已停止")


def _algorithm_to_dict(a):
    labels = a.labels
    if isinstance(labels, str):
        try:
            labels = json.loads(labels)
        except Exception:
            labels = []
    return {
        "id": a.id,
        "name": a.name,
        "inference_engine": a.inference_engine,
        "model_file": a.model_file,
        "labels": labels,
        "input_width": a.input_width,
        "input_height": a.input_height,
        "conf_threshold": a.conf_threshold,
        "iou_threshold": a.iou_threshold,
        "algorithm_type": a.algorithm_type,
        "task_type": getattr(a, "task_type", "detect"),
        "device": getattr(a, "device", "cpu"),
    }


def get_inference_pool(num_workers=None):
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            n = num_workers
            if n is None:
                try:
                    from app.utils.GlobalUtils import g_config
                    n = int(getattr(g_config, "analysisInferenceWorkers", 1))
                except Exception:
                    n = 1
            _POOL = InferenceProcessPool(num_workers=n)
            _POOL.start()
        return _POOL


def shutdown_inference_pool():
    global _POOL
    with _POOL_LOCK:
        if _POOL:
            _POOL.stop()
            _POOL = None
