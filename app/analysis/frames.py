# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""帧源：从 ZLMediaKit 输出的 RTSP 流取帧（纯 Python · OpenCV）"""
import logging

logger = logging.getLogger("analysis.frames")

try:
    import cv2
    _CV2_AVAILABLE = True
except Exception as e:
    logger.warning("frames: OpenCV 未安装，取帧能力不可用: %s" % str(e))
    cv2 = None
    _CV2_AVAILABLE = False


class FrameSource(object):
    """从 RTSP URL 持续读取帧；可选降帧到目标 FPS"""

    def __init__(self, rtsp_url, target_fps=5, reconnect_interval=5):
        self.rtsp_url = rtsp_url
        self.target_fps = max(1, int(target_fps))
        self.reconnect_interval = reconnect_interval
        self._cap = None
        self._src_fps = 25
        self._frame_skip = 0
        self._last_grab_time = 0.0
        self._closed = False

    def open(self):
        if not _CV2_AVAILABLE:
            raise RuntimeError("OpenCV 不可用，无法取帧")
        self._cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if not self._cap or not self._cap.isOpened():
            raise RuntimeError("打开流失败: %s" % self.rtsp_url)
        self._src_fps = float(self._cap.get(cv2.CAP_PROP_FPS)) or 25.0
        self._frame_skip = max(0, int(self._src_fps / self.target_fps) - 1)
        logger.info("FrameSource.open() url=%s src_fps=%.1f target_fps=%d skip=%d"
                    % (self.rtsp_url, self._src_fps, self.target_fps, self._frame_skip))
        return True

    def read(self):
        """返回 (ok, frame_bgr)；失败自动重连一次"""
        if self._closed:
            return False, None
        if self._cap is None or not self._cap.isOpened():
            self.open()
        try:
            ok = True
            for _ in range(self._frame_skip + 1):
                ok = self._cap.grab()
                if not ok:
                    break
            if not ok:
                return self._reconnect_and_read()
            ret, frame = self._cap.retrieve()
            return ret, frame
        except Exception as e:
            logger.warning("FrameSource.read() error: %s" % str(e))
            return self._reconnect_and_read()

    def _reconnect_and_read(self):
        try:
            if self._cap:
                self._cap.release()
            self._cap = None
            self.open()
            ret, frame = self._cap.read()
            return ret, frame
        except Exception as e:
            logger.error("FrameSource reconnect failed: %s" % str(e))
            return False, None

    def close(self):
        self._closed = True
        try:
            if self._cap:
                self._cap.release()
        except Exception:
            pass
        self._cap = None

    @staticmethod
    def is_available():
        return _CV2_AVAILABLE
