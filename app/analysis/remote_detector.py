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

    def __init__(self, algorithm_spec, req_queue, resp_queue, timeout=30.0):
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
            orig_h, orig_w = frame.shape[:2]
            send = self._maybe_downscale(frame)
            ok, buf = cv2.imencode(".jpg", send, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
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
            logger.warning("RemoteDetector 推理超时 algo=%s", self._spec.get("name"))
            return []
        resp = evt.get("resp") or {}
        if not resp.get("ok"):
            return []
        detections = resp.get("detections") or []
        self._rescale_detections(detections, orig_w, orig_h, send.shape[1], send.shape[0])
        return detections

    @staticmethod
    def _rescale_detections(detections, orig_w, orig_h, sent_w, sent_h):
        """若发送前做过降采样，把检测坐标从小图空间还原回原图空间。

        否则框坐标会落在缩放图坐标系，画到原图快照上时位置偏左上、尺寸偏小，
        导致报警管理图片中识别框位置异常。
        """
        if not detections or sent_w <= 0 or sent_h <= 0:
            return
        if sent_w == orig_w and sent_h == orig_h:
            return
        sx = float(orig_w) / float(sent_w)
        sy = float(orig_h) / float(sent_h)
        for d in detections:
            if not isinstance(d, dict):
                continue
            b = d.get("box")
            if b and len(b) == 4:
                try:
                    d["box"] = [int(round(float(b[0]) * sx)), int(round(float(b[1]) * sy)),
                                int(round(float(b[2]) * sx)), int(round(float(b[3]) * sy))]
                except Exception:
                    pass
            kp = d.get("keypoints")
            if isinstance(kp, list):
                fixed = []
                for p in kp:
                    try:
                        if len(p) >= 3:
                            fixed.append([float(p[0]) * sx, float(p[1]) * sy, float(p[2])])
                        elif len(p) == 2:
                            fixed.append([float(p[0]) * sx, float(p[1]) * sy])
                        else:
                            fixed.append(p)
                    except Exception:
                        fixed.append(p)
                d["keypoints"] = fixed
            poly = d.get("mask_polygon")
            if isinstance(poly, list):
                fixed = []
                for p in poly:
                    try:
                        fixed.append([float(p[0]) * sx, float(p[1]) * sy])
                    except Exception:
                        fixed.append(p)
                d["mask_polygon"] = fixed

    def _maybe_downscale(self, frame):
        try:
            import cv2
            h, w = frame.shape[:2]
            max_side = max(
                int(self._spec.get("input_width", 640) or 640),
                int(self._spec.get("input_height", 640) or 640),
                640,
            ) * 2
            longest = max(h, w)
            if longest <= max_side:
                return frame
            scale = float(max_side) / float(longest)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            return cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
        except Exception:
            return frame
