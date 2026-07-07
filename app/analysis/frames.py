# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""帧源：从 ZLMediaKit 输出的 RTSP 流取帧（纯 Python · OpenCV）"""
import logging
import time

logger = logging.getLogger("analysis.frames")

try:
    import cv2
    _CV2_AVAILABLE = True
except Exception as e:
    logger.warning("frames: OpenCV 未安装，取帧能力不可用: %s" % str(e))
    cv2 = None
    _CV2_AVAILABLE = False


class FrameSource(object):
    """从 RTSP URL 持续读取帧；失败时按间隔自动重连。"""

    HEALTH_CONNECTING = "connecting"
    HEALTH_OK = "ok"
    HEALTH_RECONNECTING = "reconnecting"
    HEALTH_DISCONNECTED = "disconnected"

    def __init__(self, rtsp_url, target_fps=5, reconnect_interval=3.0):
        self.rtsp_url = rtsp_url
        self.target_fps = max(1, int(target_fps))
        self.reconnect_interval = max(1.0, float(reconnect_interval))
        self._cap = None
        self._src_fps = 25
        self._frame_skip = 0
        self._closed = False
        self._health = self.HEALTH_CONNECTING
        self._last_ok_ts = 0.0
        self._last_reconnect_ts = 0.0
        self._reconnect_fail_count = 0
        self._total_reconnects = 0

    def health_snapshot(self):
        stalled_sec = 0.0
        if self._last_ok_ts > 0:
            stalled_sec = max(0.0, time.time() - self._last_ok_ts)
        return {
            "stream_health": self._health,
            "last_frame_ts": self._last_ok_ts,
            "stalled_sec": round(stalled_sec, 1),
            "reconnect_fail_count": self._reconnect_fail_count,
            "total_reconnects": self._total_reconnects,
        }

    def open(self):
        if not _CV2_AVAILABLE:
            raise RuntimeError("OpenCV 不可用，无法取帧")
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if not self._cap or not self._cap.isOpened():
            self._health = self.HEALTH_DISCONNECTED
            raise RuntimeError("打开流失败: %s" % self.rtsp_url)
        self._src_fps = float(self._cap.get(cv2.CAP_PROP_FPS)) or 25.0
        self._frame_skip = max(0, int(self._src_fps / self.target_fps) - 1)
        self._health = self.HEALTH_OK
        logger.info(
            "FrameSource.open() url=%s src_fps=%.1f target_fps=%d skip=%d",
            self.rtsp_url, self._src_fps, self.target_fps, self._frame_skip,
        )
        return True

    def read(self):
        """返回 (ok, frame_bgr)；失败时进入重连流程"""
        if self._closed:
            return False, None
        if self._cap is None or not self._cap.isOpened():
            return self._reconnect_and_read()
        try:
            ok = True
            for _ in range(self._frame_skip + 1):
                ok = self._cap.grab()
                if not ok:
                    break
            if not ok:
                return self._reconnect_and_read()
            ret, frame = self._cap.retrieve()
            if not ret or frame is None:
                return self._reconnect_and_read()
            self._last_ok_ts = time.time()
            self._health = self.HEALTH_OK
            self._reconnect_fail_count = 0
            return True, frame
        except Exception as e:
            logger.warning("FrameSource.read() error: %s" % str(e))
            return self._reconnect_and_read()

    def _reconnect_and_read(self):
        now = time.time()
        self._health = self.HEALTH_RECONNECTING
        if now - self._last_reconnect_ts < self.reconnect_interval:
            return False, None
        self._last_reconnect_ts = now
        self._reconnect_fail_count += 1
        try:
            if self._cap:
                self._cap.release()
            self._cap = None
            self.open()
            self._total_reconnects += 1
            logger.info(
                "FrameSource 重连成功 url=%s (累计重连 %d 次)",
                self.rtsp_url, self._total_reconnects,
            )
            ret, frame = self._cap.read()
            if ret and frame is not None:
                self._last_ok_ts = time.time()
                self._health = self.HEALTH_OK
                self._reconnect_fail_count = 0
                return True, frame
        except Exception as e:
            logger.warning(
                "FrameSource 重连失败 #%d url=%s: %s",
                self._reconnect_fail_count, self.rtsp_url, str(e),
            )
        self._health = self.HEALTH_DISCONNECTED
        return False, None

    def close(self):
        self._closed = True
        self._health = self.HEALTH_DISCONNECTED
        try:
            if self._cap:
                self._cap.release()
        except Exception:
            pass
        self._cap = None

    @staticmethod
    def is_available():
        return _CV2_AVAILABLE
