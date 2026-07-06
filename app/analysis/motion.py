# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""运动检测（OpenCV 背景减除 + 形态学优化）

参考 Frigate 的运动门控思路：先做轻量运动检测，只在有运动的区域跑目标检测。
"""
import logging

logger = logging.getLogger("analysis.motion")

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


class MotionDetector(object):
    """基于 MOG2 背景减除的运动检测器，输出运动框列表"""

    def __init__(self,
                 frame_width=320,
                 frame_height=180,
                 min_area=80,
                 max_area_ratio=0.6,
                 variance_threshold=25,
                 history=100,
                 contrast_threshold=0.4):
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.min_area = min_area
        self.max_area_ratio = max_area_ratio
        self.contrast_threshold = contrast_threshold
        self._bg = None
        if _CV2_AVAILABLE:
            self._bg = cv2.createBackgroundSubtractorMOG2(
                history=history, varThreshold=variance_threshold, detectShadows=False)
        self._frame_area = frame_width * frame_height
        self._max_area = self._frame_area * max_area_ratio

    def detect(self, frame_bgr):
        """返回 list[dict(box=[x1,y1,x2,y2], area=int)]（坐标基于原始 frame 尺寸）"""
        if not _CV2_AVAILABLE or not _NP_AVAILABLE or frame_bgr is None:
            return []
        try:
            h, w = frame_bgr.shape[:2]
            # 缩放降低计算量
            small = cv2.resize(frame_bgr, (self.frame_width, self.frame_height), interpolation=cv2.INTER_AREA)
            # 对比度过低帧跳过（避免夜视噪声误报）
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if cv2.mean(gray)[0] < 8 or self._low_contrast(gray):
                return []
            mask = self._bg.apply(small)
            mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)[1]
            mask = cv2.dilate(mask, None, iterations=2)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, None, iterations=1)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            sx = float(w) / self.frame_width
            sy = float(h) / self.frame_height
            boxes = []
            for c in contours:
                a = cv2.contourArea(c)
                if a < self.min_area or a > self._max_area:
                    continue
                x, y, bw, bh = cv2.boundingRect(c)
                x1 = int(x * sx); y1 = int(y * sy)
                x2 = int((x + bw) * sx); y2 = int((y + bh) * sy)
                boxes.append({"box": [x1, y1, x2, y2], "area": int(a)})
            return boxes
        except Exception as e:
            logger.warning("MotionDetector.detect() error: %s" % str(e))
            return []

    def _low_contrast(self, gray):
        try:
            if float(np.std(gray)) < self.contrast_threshold:
                return True
        except Exception:
            return False
        return False

    @staticmethod
    def is_available():
        return _CV2_AVAILABLE and _NP_AVAILABLE
