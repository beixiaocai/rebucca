# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""跨摄像头关联 — 基于「同类别 + 时间窗口 + 空间邻近摄像头」的轻量启发式匹配"""
import logging
import threading
import time

logger = logging.getLogger("services.cross_camera")

# 最近结束的目标：list of dict(stream_id, track_id, label, global_track_id, ended_at)
_recent_ended = []
_lock = threading.Lock()
_WINDOW_SEC = 60.0


def register_ended(stream_id, track_id, label, global_track_id):
    with _lock:
        _recent_ended.append({
            "stream_id": stream_id,
            "track_id": track_id,
            "label": label,
            "global_track_id": global_track_id,
            "ended_at": time.time(),
        })
        cutoff = time.time() - _WINDOW_SEC * 2
        while _recent_ended and _recent_ended[0]["ended_at"] < cutoff:
            _recent_ended.pop(0)


def try_link(stream_id, track_id, label):
    """新目标出现时尝试关联到其他摄像头刚消失的同类别目标。

    返回 (global_track_id, linked_from) ；linked_from 为 dict 或 None。
    """
    now = time.time()
    best = None
    with _lock:
        for item in reversed(_recent_ended):
            if item["stream_id"] == stream_id:
                continue
            if item["label"] != label:
                continue
            if now - item["ended_at"] > _WINDOW_SEC:
                continue
            best = item
            break
    if not best:
        return "cam%d-%d" % (stream_id, track_id), None
    return best["global_track_id"], best


def make_cross_camera_event(from_info, to_stream_id, to_track_id, label):
    return {
        "type": "cross_camera",
        "stream_id": to_stream_id,
        "track_id": to_track_id,
        "label": label,
        "from_stream_id": from_info.get("stream_id"),
        "from_track_id": from_info.get("track_id"),
        "global_track_id": from_info.get("global_track_id"),
        "timestamp": time.time(),
        "description": "cross camera: %s -> stream#%s" % (
            from_info.get("stream_id"), to_stream_id),
    }
