# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""单摄像头目标跟踪（轻量 IoU 关联）

设计：参考 Frigate/Norfair 的追踪思路，但用最小依赖实现一个 IoU 关联器，
避免强制引入 norfair。后续可平滑替换为 norfair 或 DeepSORT/ByteTrack 的特征关联。

输出：为每个检测框分配 track_id，并维护其在场状态/累计帧数/最近一帧框。
"""
import logging

logger = logging.getLogger("analysis.tracker")

try:
    import numpy as np  # reserved for future vectorized IoU; not required for operation
    _ = np
except Exception:
    np = None


def _iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
    iw = max(0, ix2 - ix1); ih = max(0, iy2 - iy1)
    inter = iw * ih
    a_area = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    b_area = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = a_area + b_area - inter
    if union <= 0:
        return 0.0
    return float(inter) / float(union)


class Track(object):
    __slots__ = ("track_id", "label", "box", "score", "missed", "hits", "born")

    def __init__(self, track_id, label, box, score, born):
        self.track_id = track_id
        self.label = label
        self.box = box
        self.score = score
        self.missed = 0
        self.hits = 1
        self.born = born


class IoUTracker(object):
    """按类别维护轨迹，IoU 匹配；max_missed 后判定目标消失。"""

    def __init__(self, iou_threshold=0.3, max_missed=8):
        self.iou_threshold = iou_threshold
        self.max_missed = max_missed
        self._tracks = {}  # track_id -> Track
        self._next_id = 1

    def update(self, detections, frame_index):
        """detections: list[dict(box, label, score)]
        返回 list[dict(track_id, label, box, score)] 当前帧仍在场的轨迹"""
        active = {}
        new_tracks = []
        # 贪心匹配
        for det in detections:
            best_id = None
            best_iou = self.iou_threshold
            for tid, tr in self._tracks.items():
                if tr.label != det["label"]:
                    continue
                v = _iou(tr.box, det["box"])
                if v > best_iou:
                    best_iou = v
                    best_id = tid
            if best_id is not None:
                tr = self._tracks[best_id]
                tr.box = det["box"]
                tr.score = det["score"]
                tr.missed = 0
                tr.hits += 1
                active[best_id] = tr
            else:
                tid = self._next_id
                self._next_id += 1
                tr = Track(tid, det["label"], det["box"], det["score"], frame_index)
                self._tracks[tid] = tr
                active[tid] = tr
                new_tracks.append(tid)

        # 未匹配的轨迹累计 missed
        ended = []
        for tid, tr in self._tracks.items():
            if tid in active:
                continue
            tr.missed += 1
            if tr.missed >= self.max_missed:
                ended.append(tid)
        for tid in ended:
            del self._tracks[tid]

        return [{"track_id": t.track_id, "label": t.label, "box": t.box, "score": t.score}
                for t in active.values()], ended, new_tracks, frame_index

    def all_active(self):
        return list(self._tracks.values())

    def reset(self):
        self._tracks.clear()
        self._next_id = 1
