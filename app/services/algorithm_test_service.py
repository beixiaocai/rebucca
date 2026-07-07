# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""算法离线测试：异步任务 + 进度 + 渲染输出（临时文件存 storage/temp）"""
import os
import re
import time
import uuid
import shutil
import threading
import logging
import subprocess

logger = logging.getLogger("services.algorithm_test")

try:
    import cv2
    _CV2 = True
except Exception:
    cv2 = None
    _CV2 = False

try:
    import numpy as np
    _NP = True
except Exception:
    np = None
    _NP = False

_TASKS = {}
_TASK_LOCK = threading.Lock()
_MAX_TASKS = 200
_MAX_FILE_BYTES = 100 * 1024 * 1024
_MAX_VIDEO_FRAMES = 600
_MAX_VIDEO_SECONDS = 60.0

_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
_VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}


def temp_root():
    """算法测试临时根目录：{storageTempDir}/algorithm_test"""
    try:
        from app.utils.GlobalUtils import g_config
        root = os.path.join(g_config.storageTempDir, "algorithm_test")
    except Exception:
        from django.conf import settings
        root = os.path.join(str(settings.BASE_DIR), "static", "storage", "temp", "algorithm_test")
    try:
        os.makedirs(root, exist_ok=True)
    except Exception:
        pass
    return root


def upload_dir():
    d = os.path.join(temp_root(), "_uploads")
    os.makedirs(d, exist_ok=True)
    return d


def task_dir(task_id):
    if not re.fullmatch(r"[a-f0-9]{32}", task_id or ""):
        raise ValueError("invalid task_id")
    d = os.path.join(temp_root(), task_id)
    os.makedirs(d, exist_ok=True)
    return d


def _cleanup_tasks():
    now = time.time()
    with _TASK_LOCK:
        stale = [k for k, v in _TASKS.items() if now - v.get("created_at", now) > 3600]
        for k in stale:
            _TASKS.pop(k, None)
        if len(_TASKS) > _MAX_TASKS:
            keys = sorted(_TASKS.keys(), key=lambda k: _TASKS[k].get("created_at", 0))
            for k in keys[: len(_TASKS) - _MAX_TASKS]:
                _TASKS.pop(k, None)


def _task_update(task_id, **kwargs):
    with _TASK_LOCK:
        t = _TASKS.get(task_id)
        if t:
            t.update(kwargs)


def get_task(task_id):
    with _TASK_LOCK:
        t = _TASKS.get(task_id)
        return dict(t) if t else None


def output_url_for_task(task_id):
    return "/smallmodel/openTestOutput?task_id=%s" % task_id


def resolve_output_file(task_id):
    if not re.fullmatch(r"[a-f0-9]{32}", task_id or ""):
        return None, None
    base = os.path.join(temp_root(), task_id)
    for name, ctype in (("output.mp4", "video/mp4"), ("output.jpg", "image/jpeg"), ("output.png", "image/png")):
        fp = os.path.join(base, name)
        if os.path.isfile(fp) and os.path.getsize(fp) > 0:
            return fp, ctype
    return None, None


def clear_temp_files():
    """清理算法测试产生的全部临时文件，并清空内存任务表。"""
    roots = [temp_root()]
    try:
        from django.conf import settings
        legacy = os.path.join(str(settings.BASE_DIR), "static", "storage", "test")
        if os.path.isdir(legacy):
            roots.append(legacy)
    except Exception:
        pass
    removed = 0
    bytes_freed = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            fp = os.path.join(root, name)
            try:
                if os.path.isfile(fp):
                    bytes_freed += os.path.getsize(fp)
                    os.remove(fp)
                    removed += 1
                elif os.path.isdir(fp):
                    for dirpath, _, filenames in os.walk(fp):
                        for fn in filenames:
                            try:
                                fpath = os.path.join(dirpath, fn)
                                bytes_freed += os.path.getsize(fpath)
                                removed += 1
                            except Exception:
                                pass
                    shutil.rmtree(fp, ignore_errors=True)
            except Exception as e:
                logger.warning("clear temp remove %s err: %s", fp, e)
    with _TASK_LOCK:
        _TASKS.clear()
    return {"files_removed": removed, "bytes_freed": bytes_freed}


def _ffmpeg_path():
    try:
        from app.utils.GlobalUtils import g_config
        return getattr(g_config, "ffmpeg", None) or "ffmpeg"
    except Exception:
        return "ffmpeg"


def _encode_video_h264(raw_path, final_path):
    """将 OpenCV 输出的视频转码为浏览器可播的 H.264 MP4。"""
    if not os.path.isfile(raw_path) or os.path.getsize(raw_path) <= 0:
        return False
    tmp = final_path + ".part.mp4"
    cmd = [
        _ffmpeg_path(), "-y", "-loglevel", "error",
        "-i", raw_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        tmp,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=600)
        if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
            if os.path.isfile(final_path):
                os.remove(final_path)
            os.replace(tmp, final_path)
            if os.path.abspath(raw_path) != os.path.abspath(final_path) and os.path.isfile(raw_path):
                os.remove(raw_path)
            return True
        if r.stderr:
            logger.warning("ffmpeg encode stderr: %s", r.stderr.decode("utf-8", errors="ignore")[:500])
    except Exception as e:
        logger.warning("ffmpeg encode failed: %s", e)
    if os.path.isfile(tmp):
        try:
            os.remove(tmp)
        except Exception:
            pass
    if os.path.isfile(raw_path) and not os.path.isfile(final_path):
        try:
            shutil.copy2(raw_path, final_path)
            return os.path.getsize(final_path) > 0
        except Exception:
            pass
    return os.path.isfile(final_path) and os.path.getsize(final_path) > 0


def _open_video_writer(out_path, fps, w, h):
    for codec in ("avc1", "mp4v", "XVID"):
        fourcc = cv2.VideoWriter_fourcc(*codec)
        writer = cv2.VideoWriter(out_path, fourcc, fps, (w, h))
        if writer.isOpened():
            return writer
        writer.release()
    return None


def _color_for_label(label, idx=0):
    palette = [
        (22, 159, 133), (59, 130, 246), (234, 88, 12), (168, 85, 247),
        (220, 38, 38), (14, 165, 233), (132, 204, 22), (236, 72, 153),
    ]
    if label:
        h = sum(ord(c) for c in str(label)) % len(palette)
        return palette[h]
    return palette[idx % len(palette)]


def draw_detections(frame_bgr, detections, task_type="detect"):
    if not _CV2 or frame_bgr is None:
        return frame_bgr
    img = frame_bgr.copy()
    h, w = img.shape[:2]
    for i, det in enumerate(detections or []):
        color = _color_for_label(det.get("label"), i)
        task = (det.get("task") or task_type or "detect").lower()
        if task == "classify":
            continue
        poly = det.get("mask_polygon")
        if poly and len(poly) >= 3:
            pts = np.array([(int(p[0]), int(p[1])) for p in poly], dtype=np.int32)
            overlay = img.copy()
            cv2.fillPoly(overlay, [pts], color)
            cv2.addWeighted(overlay, 0.35, img, 0.65, 0, img)
            cv2.polylines(img, [pts], True, color, 2)
        box = det.get("box") or [0, 0, 0, 0]
        x1, y1, x2, y2 = [int(v) for v in box[:4]]
        if x2 > x1 and y2 > y1:
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        label = str(det.get("label") or "")
        score = det.get("score")
        txt = label + (" %.2f" % score if isinstance(score, (int, float)) else "")
        if txt.strip():
            (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            ty = max(0, y1 - 6)
            cv2.rectangle(img, (x1, max(0, ty - th - 4)), (x1 + tw + 8, ty + 2), color, -1)
            cv2.putText(img, txt, (x1 + 4, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        kpts = det.get("keypoints")
        if kpts:
            for kp in kpts:
                if len(kp) >= 3 and kp[2] > 0.3:
                    cv2.circle(img, (int(kp[0]), int(kp[1])), 3, color, -1)
    if task_type == "classify" and detections:
        y = 28
        for i, det in enumerate(detections[:8]):
            txt = "%s %.2f" % (det.get("label", ""), float(det.get("score") or 0))
            cv2.putText(img, txt, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(img, txt, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, _color_for_label(det.get("label"), i), 1, cv2.LINE_AA)
            y += 26
    cv2.rectangle(img, (w - 130, 6), (w - 6, 28), (22, 159, 133), -1)
    cv2.putText(img, "ALGO TEST", (w - 122, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def _summarize_detections(all_dets):
    summary = {}
    for det in all_dets:
        lb = str(det.get("label") or "unknown")
        sc = float(det.get("score") or 0)
        if lb not in summary:
            summary[lb] = {"label": lb, "count": 0, "max_score": sc, "score_sum": 0.0}
        summary[lb]["count"] += 1
        summary[lb]["max_score"] = max(summary[lb]["max_score"], sc)
        summary[lb]["score_sum"] += sc
    out = []
    for lb, s in sorted(summary.items(), key=lambda x: -x[1]["count"]):
        out.append({
            "label": lb,
            "count": s["count"],
            "max_score": round(s["max_score"], 4),
            "avg_score": round(s["score_sum"] / max(1, s["count"]), 4),
        })
    return out


def _resolve_model_abs(model_file):
    """与推理池一致：仅 uploadDir/weight。"""
    if not model_file:
        return ""
    try:
        from app.analysis.worker_pool import resolve_model_path
        p = resolve_model_path(model_file)
        if p and os.path.isfile(p):
            return p
    except Exception as e:
        logger.warning("_resolve_model_abs: %s", e)
    return ""


def _build_engine(algo, abs_model):
    import json
    from app.analysis.engines.factory import EngineFactory
    labels = algo.labels or "[]"
    try:
        labels_list = json.loads(labels) if isinstance(labels, str) else (labels or [])
    except Exception:
        labels_list = []
    return EngineFactory.create(
        algo.inference_engine,
        model_file=abs_model,
        labels=labels_list,
        input_size=(algo.input_width or 640, algo.input_height or 640),
        conf_threshold=float(algo.conf_threshold or 0.4),
        iou_threshold=float(algo.iou_threshold or 0.5),
        algorithm_type=algo.algorithm_type or "yolo8",
        task_type=algo.task_type or "detect",
        device=algo.device or "cpu",
    )


_PERSON_LABELS = frozenset({"person", "Person", "行人", "0"})


def _filter_person_detections(dets):
    out = []
    for d in dets or []:
        lb = str(d.get("label") or "")
        if lb in _PERSON_LABELS or lb.lower() == "person":
            out.append(d)
    return out


def _iou_box(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


class _ReidTrack(object):
    __slots__ = ("track_id", "box", "label", "score", "embedding", "embedding_hist", "missed", "hits", "_hist_max")

    def __init__(self, track_id, box, label, score, embedding, hist_max=5):
        self.track_id = track_id
        self.box = box
        self.label = label
        self.score = score
        self.embedding = embedding
        self.embedding_hist = [embedding.copy()]
        self.missed = 0
        self.hits = 1
        self._hist_max = hist_max

    def update(self, box, score, emb):
        self.box = box
        self.score = score
        self.embedding = emb
        self.embedding_hist.append(emb.copy())
        if len(self.embedding_hist) > self._hist_max:
            self.embedding_hist.pop(0)
        self.missed = 0
        self.hits += 1

    def mean_embedding(self):
        if not self.embedding_hist:
            return self.embedding
        return np.mean(np.stack(self.embedding_hist, axis=0), axis=0)


class _SimpleReIDTracker(object):
    def __init__(self, iou_thr=0.3, emb_thr=0.5, max_missed=8):
        self.iou_thr = iou_thr
        self.emb_thr = emb_thr
        self.max_missed = max_missed
        self.tracks = {}
        self._next_id = 1

    def update(self, detections, embeddings):
        assigned = set()
        active_ids = []
        for det, emb in zip(detections, embeddings):
            best_id, best_score = None, self.emb_thr
            for tid, tr in self.tracks.items():
                if tr.label != det.get("label"):
                    continue
                iou = _iou_box(tr.box, det.get("box") or [0, 0, 0, 0])
                if iou < self.iou_thr:
                    continue
                sim = float(np.dot(tr.mean_embedding(), emb))
                if sim > best_score:
                    best_score = sim
                    best_id = tid
            if best_id is not None:
                self.tracks[best_id].update(det.get("box"), det.get("score"), emb)
                assigned.add(best_id)
                active_ids.append(best_id)
            else:
                tid = self._next_id
                self._next_id += 1
                tr = _ReidTrack(tid, det.get("box"), det.get("label"), det.get("score"), emb)
                self.tracks[tid] = tr
                assigned.add(tid)
                active_ids.append(tid)
        for tid, tr in list(self.tracks.items()):
            if tid in assigned:
                continue
            tr.missed += 1
            if tr.missed >= self.max_missed:
                del self.tracks[tid]
        return active_ids


def _draw_reid_frame(frame_bgr, tracker, active_ids):
    img = frame_bgr.copy()
    for tid in active_ids:
        tr = tracker.tracks.get(tid)
        if not tr:
            continue
        x1, y1, x2, y2 = [int(v) for v in tr.box]
        color = (0, 200, 80) if tr.hits >= 3 else (0, 180, 255)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        txt = "id=%d %s %.2f" % (tid, tr.label, float(tr.score or 0))
        cv2.putText(img, txt, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    h, w = img.shape[:2]
    cv2.rectangle(img, (w - 130, 6), (w - 6, 28), (22, 159, 133), -1)
    cv2.putText(img, "REID TEST", (w - 122, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def _process_reid_frame(detector_engine, reid_engine, tracker, frame_bgr, sim_samples):
    dets = detector_engine.detect(frame_bgr)
    persons = _filter_person_detections(dets)
    boxes = [p.get("box") for p in persons if p.get("box")]
    valid_idx, embeddings = reid_engine.extract_embeddings(frame_bgr, boxes)
    matched_dets = [persons[i] for i in valid_idx]
    emb_rows = [embeddings[j] for j in range(len(valid_idx))]
    active_ids = tracker.update(matched_dets, emb_rows) if matched_dets else []
    for tid in active_ids:
        tr = tracker.tracks.get(tid)
        if tr and tr.hits >= 2:
            sim_samples.append(float(np.dot(tr.embedding, tr.mean_embedding())))
    vis = _draw_reid_frame(frame_bgr, tracker, active_ids)
    return vis, len(persons), len(valid_idx), active_ids


def _run_reid_test(task_id, algo, detector_algo, input_path, media_type, out_dir, t0):
    abs_reid = _resolve_model_abs(algo.model_file)
    abs_det = _resolve_model_abs(detector_algo.model_file)
    if not abs_reid or not abs_det:
        raise RuntimeError("model file not found")
    reid_engine = _build_engine(algo, abs_reid)
    det_engine = _build_engine(detector_algo, abs_det)
    if not reid_engine.load() or not det_engine.load():
        raise RuntimeError("engine load failed")
    tracker = _SimpleReIDTracker()
    sim_samples = []
    infer_ms = 0.0
    emb_total = 0
    person_total = 0
    track_peak = 0
    all_dets = []

    if media_type == "image":
        _task_update(task_id, progress=15, message="processing image (detect+reid)")
        frame = cv2.imread(input_path)
        if frame is None:
            raise RuntimeError("cannot read image")
        h, w = frame.shape[:2]
        t_inf = time.time()
        vis, pc, ec, active_ids = _process_reid_frame(det_engine, reid_engine, tracker, frame, sim_samples)
        infer_ms = (time.time() - t_inf) * 1000
        person_total += pc
        emb_total += ec
        track_peak = max(track_peak, len(active_ids))
        for tid in active_ids:
            tr = tracker.tracks.get(tid)
            if tr:
                all_dets.append({
                    "label": tr.label,
                    "score": tr.score,
                    "box": tr.box,
                    "track_id": tr.track_id,
                    "task": "reid",
                })
        out_path = os.path.join(out_dir, "output.jpg")
        if not cv2.imwrite(out_path, vis, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
            raise RuntimeError("failed to write output image")
        report = {
            "media_type": "image",
            "input_size": [w, h],
            "frame_count": 1,
            "processed_frames": 1,
            "inference_ms_total": round(infer_ms, 2),
            "inference_ms_avg": round(infer_ms, 2),
            "detection_count": person_total,
            "embedding_count": emb_total,
            "track_count": track_peak,
            "reid_sim_mean": round(float(np.mean(sim_samples)), 4) if sim_samples else None,
            "detections_summary": _summarize_detections(all_dets),
            "detections": all_dets[:100],
            "engine": algo.inference_engine,
            "device": algo.device,
            "task_type": "reid",
            "detector_id": detector_algo.id,
            "detector_name": detector_algo.name,
            "elapsed_ms": round((time.time() - t0) * 1000, 2),
        }
        _task_update(
            task_id, status="done", progress=100, message="done",
            report=report, output_url=output_url_for_task(task_id), output_type="image",
        )
        return

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError("cannot open video")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    if fps <= 0 or fps > 120:
        fps = 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if w <= 0 or h <= 0:
        raise RuntimeError("invalid video dimensions")
    if total <= 0:
        total = int(fps * 10)
    max_frames = min(total, _MAX_VIDEO_FRAMES, max(1, int(fps * _MAX_VIDEO_SECONDS)))
    raw_path = os.path.join(out_dir, "output_raw.mp4")
    final_path = os.path.join(out_dir, "output.mp4")
    writer = _open_video_writer(raw_path, fps, w, h)
    if writer is None:
        raise RuntimeError("cannot create video writer")
    idx = 0
    processed = 0
    while idx < max_frames:
        ret, frame = cap.read()
        if not ret or frame is None:
            break
        t_inf = time.time()
        vis, pc, ec, active_ids = _process_reid_frame(det_engine, reid_engine, tracker, frame, sim_samples)
        infer_ms += (time.time() - t_inf) * 1000
        person_total += pc
        emb_total += ec
        track_peak = max(track_peak, len(active_ids))
        for tid in active_ids:
            tr = tracker.tracks.get(tid)
            if tr:
                all_dets.append({
                    "label": tr.label,
                    "score": tr.score,
                    "box": tr.box,
                    "track_id": tr.track_id,
                    "task": "reid",
                })
        writer.write(vis)
        processed += 1
        idx += 1
        pct = 15 + int(70 * idx / max(1, max_frames))
        _task_update(task_id, progress=min(85, pct), message="reid frame %d / %d" % (idx, max_frames))
    cap.release()
    writer.release()
    if processed <= 0:
        raise RuntimeError("no video frames processed")
    if not os.path.isfile(raw_path) or os.path.getsize(raw_path) <= 0:
        raise RuntimeError("raw video missing")
    _task_update(task_id, progress=88, message="encoding video (H.264)")
    if not _encode_video_h264(raw_path, final_path):
        raise RuntimeError("video encode failed")
    report = {
        "media_type": "video",
        "input_size": [w, h],
        "frame_count": total,
        "processed_frames": processed,
        "fps": round(fps, 2),
        "inference_ms_total": round(infer_ms, 2),
        "inference_ms_avg": round(infer_ms / max(1, processed), 2),
        "detection_count": person_total,
        "embedding_count": emb_total,
        "track_count": track_peak,
        "reid_sim_mean": round(float(np.mean(sim_samples)), 4) if sim_samples else None,
        "detections_summary": _summarize_detections(all_dets[:200]),
        "detections": all_dets[:50],
        "engine": algo.inference_engine,
        "device": algo.device,
        "task_type": "reid",
        "detector_id": detector_algo.id,
        "detector_name": detector_algo.name,
        "elapsed_ms": round((time.time() - t0) * 1000, 2),
        "output_video": True,
    }
    _task_update(
        task_id, status="done", progress=100, message="done",
        report=report, output_url=output_url_for_task(task_id), output_type="video",
    )


def _run_test(task_id, algo, input_path, media_type, out_dir, detector_algo=None):
    t0 = time.time()
    try:
        _task_update(task_id, status="running", progress=5, message="loading model")
        task_type = (algo.task_type or "detect").lower()
        if task_type == "reid":
            if not detector_algo:
                raise RuntimeError("ReID test requires detector model")
            _run_reid_test(task_id, algo, detector_algo, input_path, media_type, out_dir, t0)
            return

        abs_model = _resolve_model_abs(algo.model_file)
        if not abs_model:
            raise RuntimeError("model file not found: %s" % (algo.model_file or ""))
        engine = _build_engine(algo, abs_model)
        if not engine.load():
            raise RuntimeError("engine load failed")

        task_type = (algo.task_type or "detect").lower()
        all_dets = []
        infer_ms = 0.0
        processed = 0

        if media_type == "image":
            _task_update(task_id, progress=15, message="processing image")
            frame = cv2.imread(input_path)
            if frame is None:
                raise RuntimeError("cannot read image")
            h, w = frame.shape[:2]
            t_inf = time.time()
            dets = engine.detect(frame)
            infer_ms = (time.time() - t_inf) * 1000
            all_dets.extend([dict(d) for d in dets])
            out_img = draw_detections(frame, dets, task_type)
            out_path = os.path.join(out_dir, "output.jpg")
            if not cv2.imwrite(out_path, out_img, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
                raise RuntimeError("failed to write output image")
            if not os.path.isfile(out_path) or os.path.getsize(out_path) <= 0:
                raise RuntimeError("output image file missing")
            processed = 1
            report = {
                "media_type": "image",
                "input_size": [w, h],
                "frame_count": 1,
                "processed_frames": 1,
                "inference_ms_total": round(infer_ms, 2),
                "inference_ms_avg": round(infer_ms, 2),
                "detection_count": len(all_dets),
                "detections_summary": _summarize_detections(all_dets),
                "detections": all_dets[:100],
                "engine": algo.inference_engine,
                "device": algo.device,
                "task_type": task_type,
                "elapsed_ms": round((time.time() - t0) * 1000, 2),
            }
            _task_update(
                task_id, status="done", progress=100, message="done",
                report=report, output_url=output_url_for_task(task_id), output_type="image",
            )
            return

        # video：逐帧推理渲染 → 合成视频 → ffmpeg 转 H.264
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise RuntimeError("cannot open video")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        if fps <= 0 or fps > 120:
            fps = 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if w <= 0 or h <= 0:
            raise RuntimeError("invalid video dimensions")
        if total <= 0:
            total = int(fps * 10)
        max_frames = min(total, _MAX_VIDEO_FRAMES, max(1, int(fps * _MAX_VIDEO_SECONDS)))

        raw_path = os.path.join(out_dir, "output_raw.mp4")
        final_path = os.path.join(out_dir, "output.mp4")
        writer = _open_video_writer(raw_path, fps, w, h)
        if writer is None:
            raise RuntimeError("cannot create video writer")

        idx = 0
        while idx < max_frames:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            t_inf = time.time()
            dets = engine.detect(frame)
            infer_ms += (time.time() - t_inf) * 1000
            all_dets.extend([dict(d) for d in dets])
            vis = draw_detections(frame, dets, task_type)
            writer.write(vis)
            processed += 1
            idx += 1
            pct = 15 + int(70 * idx / max(1, max_frames))
            _task_update(task_id, progress=min(85, pct), message="rendering frame %d / %d" % (idx, max_frames))

        cap.release()
        writer.release()
        if processed <= 0:
            raise RuntimeError("no video frames processed")
        if not os.path.isfile(raw_path) or os.path.getsize(raw_path) <= 0:
            raise RuntimeError("raw video missing")

        _task_update(task_id, progress=88, message="encoding video (H.264)")
        if not _encode_video_h264(raw_path, final_path):
            raise RuntimeError("video encode failed")

        _task_update(task_id, progress=95, message="saving result")
        report = {
            "media_type": "video",
            "input_size": [w, h],
            "frame_count": total,
            "processed_frames": processed,
            "fps": round(fps, 2),
            "inference_ms_total": round(infer_ms, 2),
            "inference_ms_avg": round(infer_ms / max(1, processed), 2),
            "detection_count": len(all_dets),
            "detections_summary": _summarize_detections(all_dets),
            "detections": all_dets[:50],
            "engine": algo.inference_engine,
            "device": algo.device,
            "task_type": task_type,
            "elapsed_ms": round((time.time() - t0) * 1000, 2),
            "output_video": True,
        }
        _task_update(
            task_id, status="done", progress=100, message="done",
            report=report, output_url=output_url_for_task(task_id), output_type="video",
        )
    except Exception as e:
        logger.exception("algorithm test task %s failed", task_id)
        _task_update(task_id, status="error", progress=100, message=str(e), error=str(e))


def start_test(algo, uploaded_path, original_name, detector_algo=None):
    if not _CV2 or not _NP:
        raise RuntimeError("opencv/numpy not available")
    task_type = (algo.task_type or "detect").lower()
    if task_type == "reid" and not detector_algo:
        raise RuntimeError("ReID test requires detector model")
    ext = os.path.splitext(original_name or uploaded_path)[1].lower()
    if ext in _IMAGE_EXT:
        media_type = "image"
    elif ext in _VIDEO_EXT:
        media_type = "video"
    else:
        raise RuntimeError("unsupported media type: %s" % ext)
    size = os.path.getsize(uploaded_path)
    if size > _MAX_FILE_BYTES:
        raise RuntimeError("file too large (max %d MB)" % (_MAX_FILE_BYTES // (1024 * 1024)))

    _cleanup_tasks()
    task_id = uuid.uuid4().hex
    out_dir = task_dir(task_id)
    input_path = os.path.join(out_dir, "input" + ext)
    try:
        shutil.move(uploaded_path, input_path)
    except Exception:
        shutil.copy2(uploaded_path, input_path)
        try:
            os.remove(uploaded_path)
        except Exception:
            pass

    with _TASK_LOCK:
        _TASKS[task_id] = {
            "id": task_id,
            "status": "pending",
            "progress": 0,
            "message": "queued",
            "report": None,
            "output_url": "",
            "output_type": "",
            "error": "",
            "algorithm_id": algo.id,
            "created_at": time.time(),
        }

    th = threading.Thread(
        target=_run_test,
        args=(task_id, algo, input_path, media_type, out_dir, detector_algo),
        daemon=True,
    )
    th.start()
    return task_id
