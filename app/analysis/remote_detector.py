# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""远程推理代理 — 摄像头子进程通过 Queue 向主进程 InferenceProcessPool 发起推理"""
import logging
import threading
import uuid

logger = logging.getLogger("analysis.remote_detector")

# 同一 resp_queue 只能有一个 drain 线程，否则多 RemoteDetector 会抢响应导致丢包
_drainers = {}
_drainers_lock = threading.Lock()


class _SharedResponseDrainer(object):
    def __init__(self, resp_queue):
        self._resp_q = resp_queue
        self._pending = {}
        self._lock = threading.Lock()
        self._started = False

    def ensure_started(self):
        if self._started:
            return
        self._started = True
        threading.Thread(
            target=self._loop, name="remote-det-drain-%s" % id(self._resp_q), daemon=True,
        ).start()

    def register(self, req_id):
        evt = {"event": threading.Event(), "resp": None}
        with self._lock:
            self._pending[req_id] = evt
        return evt

    def unregister(self, req_id):
        with self._lock:
            self._pending.pop(req_id, None)

    def _loop(self):
        import queue as _q
        while True:
            try:
                msg = self._resp_q.get(timeout=1.0)
            except _q.Empty:
                continue
            if not msg:
                continue
            req_id = msg.get("req_id")
            with self._lock:
                item = self._pending.pop(req_id, None)
            if item:
                item["resp"] = msg
                item["event"].set()
            elif req_id:
                logger.debug("remote_detector: 无匹配 pending req_id=%s", req_id)


def _get_drainer(resp_queue):
    key = id(resp_queue)
    with _drainers_lock:
        drainer = _drainers.get(key)
        if drainer is None:
            drainer = _SharedResponseDrainer(resp_queue)
            _drainers[key] = drainer
        return drainer


class RemoteDetector(object):
    ENGINE_NAME = "remote_pool"

    def __init__(self, algorithm_spec, req_queue, resp_queue, timeout=10.0):
        self._spec = algorithm_spec
        self._req_q = req_queue
        self._resp_q = resp_queue
        self._timeout = timeout
        self._drainer = _get_drainer(resp_queue)

    def ready(self):
        return self._req_q is not None and self._resp_q is not None

    def load(self):
        return True

    def detect(self, frame):
        if not self.ready():
            return []
        self._drainer.ensure_started()
        try:
            import cv2
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                return []
            jpeg = buf.tobytes()
        except Exception:
            return []

        req_id = str(uuid.uuid4())
        evt = self._drainer.register(req_id)
        try:
            self._req_q.put({
                "req_id": req_id,
                "algorithm": self._spec,
                "jpeg": jpeg,
            }, timeout=2.0)
        except Exception:
            self._drainer.unregister(req_id)
            return []

        if not evt["event"].wait(timeout=self._timeout):
            self._drainer.unregister(req_id)
            return []
        resp = evt.get("resp") or {}
        if not resp.get("ok"):
            return []
        return resp.get("detections") or []
