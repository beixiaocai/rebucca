# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""YOLO 共享后处理 —— 按 (algorithm_type, task_type) 分发

支持版本：yolo5 / yolo8 / yolo11 / yolo26
支持任务：detect / segment / classify / pose / obb

输出结构差异：
- yolo5 detect:  output [1, N, 5+nc]  行格式 [cx, cy, w, h, obj, cls_scores...]
- yolo8/11/26 detect: output [1, nc+4, N]  列格式 [cx, cy, w, h, cls_score_0, cls_score_1, ...]  无 obj
- yolo5 segment: outputs[0] [1, N, 5+nc+nm], outputs[1] [1, nm, mh, mw] (protos)
- yolo8/11/26 segment: outputs[0] [1, nc+4+nm, N], outputs[1] [1, nm, mh, mw]
- classify (all): output [1, nc]  top-1 logits
- yolo8/11/26 pose: output [1, nc+4+nk*3, N]  (nk 通常 17)
- yolo8/11/26 obb:  output [1, nc+4+1, N]  末列是角度 (radians)

本模块仅依赖 numpy + opencv，被 OnnxEngine / OpenVinoEngine 复用。
YoloPytorchEngine 直接用 ultralytics 的 Results 对象，不走本模块。
"""

import logging
import numpy as np

logger = logging.getLogger("analysis.engines.yolo_post")

try:
    import cv2
    _CV2 = True
except Exception:
    cv2 = None
    _CV2 = False


def decode_outputs(outputs, algorithm_type, task_type, labels, input_size,
                   conf_threshold, iou_threshold, orig_size, num_classes=None):
    """主入口：返回 list[dict]，每条至少含 box/label/score，按任务附加上下文。

    outputs: list[np.ndarray]  原始模型输出（顺序与 onnx session.get_outputs() 一致）
    """
    try:
        if task_type == "classify":
            return _decode_classify(outputs, labels)
        if task_type == "detect":
            return _decode_detect(outputs, algorithm_type, labels, input_size,
                                  conf_threshold, iou_threshold, orig_size, num_classes)
        if task_type == "segment":
            return _decode_segment(outputs, algorithm_type, labels, input_size,
                                   conf_threshold, iou_threshold, orig_size, num_classes)
        if task_type == "pose":
            return _decode_pose(outputs, algorithm_type, labels, input_size,
                                conf_threshold, iou_threshold, orig_size, num_classes)
        if task_type == "obb":
            return _decode_obb(outputs, algorithm_type, labels, input_size,
                               conf_threshold, iou_threshold, orig_size, num_classes)
        logger.warning("yolo_post: 未知任务类型 %s", task_type)
        return []
    except Exception as e:
        logger.warning("yolo_post decode err: %s", e)
        return []


def _is_v5(algorithm_type):
    return algorithm_type in ("yolo5", "yolov5", "v5")


def _xywh2xyxy(xywh):
    x, y, w, h = xywh[..., 0], xywh[..., 1], xywh[..., 2], xywh[..., 3]
    return np.stack([x - w / 2, y - h / 2, x + w / 2, y + h / 2], axis=-1)


def _nms(boxes, scores, iou_threshold):
    if len(boxes) == 0:
        return []
    boxes_list = boxes.tolist() if hasattr(boxes, "tolist") else [list(b) for b in boxes]
    scores_list = scores.tolist() if hasattr(scores, "tolist") else list(scores)
    if _CV2:
        try:
            idx = cv2.dnn.NMSBoxes(boxes_list, scores_list, 0.0, float(iou_threshold))
            if idx is None or len(idx) == 0:
                return []
            if hasattr(idx, "flatten"):
                idx = idx.flatten()
            return [int(i) for i in idx]
        except Exception as e:
            logger.debug("cv2 NMS fallback: %s", e)
    # OpenCV 不可用或 NMS 失败时的朴素实现
    order = np.argsort(-np.asarray(scores_list, dtype=np.float32))
    suppressed = np.zeros(len(scores_list), dtype=bool)
    keep = []
    boxes_arr = np.asarray(boxes_list, dtype=np.float32)
    for i in order:
        if suppressed[i]:
            continue
        keep.append(int(i))
        for j in order:
            if j == i or suppressed[j]:
                continue
            if _iou(boxes_arr[i], boxes_arr[j]) > float(iou_threshold):
                suppressed[j] = True
    return keep


def _iou(a, b):
    xa, ya = max(a[0], b[0]), max(a[1], b[1])
    xb, yb = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, xb - xa), max(0.0, yb - ya)
    inter = iw * ih
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _scale_box(box, sx, sy, orig_w, orig_h):
    x1 = max(0, min(orig_w - 1, box[0] * sx))
    y1 = max(0, min(orig_h - 1, box[1] * sy))
    x2 = max(0, min(orig_w - 1, box[2] * sx))
    y2 = max(0, min(orig_h - 1, box[3] * sy))
    return [int(x1), int(y1), int(x2), int(y2)]


# ===================== classify =====================
def _decode_classify(outputs, labels):
    out = np.asarray(outputs[0])
    if out.ndim == 2 and out.shape[0] == 1:
        out = out[0]
    if out.ndim != 1:
        # 某些导出会带 batch 维 + 多余维度
        out = out.reshape(-1)
    cid = int(np.argmax(out))
    score = float(out[cid])
    label = labels[cid] if 0 <= cid < len(labels) else str(cid)
    return [{"box": [0, 0, 0, 0], "label": str(label), "score": score, "task": "classify"}]


# ===================== detect =====================
def _decode_detect(outputs, algorithm_type, labels, input_size, conf, iou, orig_size, nc=None):
    arr = np.asarray(outputs[0])
    iw, ih = input_size
    orig_w, orig_h = orig_size
    sx, sy = float(orig_w) / iw, float(orig_h) / ih
    if _is_v5(algorithm_type):
        # [1, N, 5+nc] 或 [N, 5+nc]
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]
        if arr.ndim != 2 or arr.shape[1] < 6:
            return []
        nc = arr.shape[1] - 5 if nc is None else nc
        if nc < 1:
            nc = 1
        objs = arr[:, 4]
        cls_scores = arr[:, 5:5 + nc]
        # score = obj * cls
        scores_all = objs[:, None] * cls_scores  # [N, nc]
        best_cls = np.argmax(scores_all, axis=1)
        best_score = scores_all[np.arange(len(arr)), best_cls]
        mask = best_score >= conf
        if not np.any(mask):
            return []
        xywh = arr[mask, :4]
        boxes_raw = _xywh2xyxy(xywh)
        scores = best_score[mask]
        clses = best_cls[mask]
    else:
        # yolo8/11/26: [1, nc+4, N]  需转置
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]
        if arr.ndim != 2:
            return []
        # 行格式可能是 [4+nc, N] —— 转成 [N, 4+nc]
        if arr.shape[0] < arr.shape[1] and arr.shape[0] >= 4:
            arr = arr.T
        if arr.ndim != 2 or arr.shape[1] < 5:
            return []
        nc = arr.shape[1] - 4 if nc is None else nc
        if nc < 1:
            nc = 1
        boxes_raw = _xywh2xyxy(arr[:, :4])
        cls_scores = arr[:, 4:4 + nc]
        best_cls = np.argmax(cls_scores, axis=1)
        best_score = cls_scores[np.arange(len(arr)), best_cls]
        mask = best_score >= conf
        if not np.any(mask):
            return []
        boxes_raw = boxes_raw[mask]
        scores = best_score[mask]
        clses = best_cls[mask]

    boxes = [_scale_box(b, sx, sy, orig_w, orig_h) for b in boxes_raw]
    keep = _nms(boxes, scores, iou)
    out = []
    for i in keep:
        label = labels[int(clses[i])] if 0 <= int(clses[i]) < len(labels) else str(int(clses[i]))
        out.append({"box": boxes[i], "label": str(label), "score": float(scores[i]), "task": "detect"})
    return out


# ===================== segment =====================
def _decode_segment(outputs, algorithm_type, labels, input_size, conf, iou, orig_size, nc=None):
    arr = np.asarray(outputs[0])
    proto = np.asarray(outputs[1]) if len(outputs) > 1 else None
    iw, ih = input_size
    orig_w, orig_h = orig_size
    sx, sy = float(orig_w) / iw, float(orig_h) / ih
    if _is_v5(algorithm_type):
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]
        if arr.ndim != 2 or arr.shape[1] < 6:
            return []
        nm = arr.shape[1] - 5 - (nc or (arr.shape[1] - 5))
        # 推断 nm：若 nc 已知
        if nc is None:
            # 退化：用 arr.shape[1]-5 / 2 估计（不可靠），优先按 nc 推断
            nm = 32
            nc = arr.shape[1] - 5 - nm
        else:
            nm = arr.shape[1] - 5 - nc
        if nm < 1:
            nm = 32
        objs = arr[:, 4]
        cls_scores = arr[:, 5:5 + nc]
        scores_all = objs[:, None] * cls_scores
        best_cls = np.argmax(scores_all, axis=1)
        best_score = scores_all[np.arange(len(arr)), best_cls]
        mask = best_score >= conf
        if not np.any(mask):
            return []
        xywh = arr[mask, :4]
        boxes_raw = _xywh2xyxy(xywh)
        coeffs = arr[mask, 5 + nc:5 + nc + nm]
        scores = best_score[mask]
        clses = best_cls[mask]
    else:
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]
        if arr.ndim != 2:
            return []
        if arr.shape[0] < arr.shape[1] and arr.shape[0] >= 4:
            arr = arr.T
        if arr.ndim != 2 or arr.shape[1] < 5:
            return []
        if nc is None:
            # 含 mask 系数：列数 = 4 + nc + nm，nm 一般 32
            nm = 32
            nc = arr.shape[1] - 4 - nm
        else:
            nm = arr.shape[1] - 4 - nc
        if nm < 1:
            nm = 32
            nc = arr.shape[1] - 4 - nm
        boxes_raw = _xywh2xyxy(arr[:, :4])
        cls_scores = arr[:, 4:4 + nc]
        coeffs = arr[:, 4 + nc:4 + nc + nm]
        best_cls = np.argmax(cls_scores, axis=1)
        best_score = cls_scores[np.arange(len(arr)), best_cls]
        mask = best_score >= conf
        if not np.any(mask):
            return []
        boxes_raw = boxes_raw[mask]
        coeffs = coeffs[mask]
        scores = best_score[mask]
        clses = best_cls[mask]

    boxes = [_scale_box(b, sx, sy, orig_w, orig_h) for b in boxes_raw]
    keep = _nms(boxes, scores, iou)
    out = []
    for i in keep:
        label = labels[int(clses[i])] if 0 <= int(clses[i]) < len(labels) else str(int(clses[i]))
        item = {"box": boxes[i], "label": str(label), "score": float(scores[i]), "task": "segment"}
        # mask 系数（简化：仅返回系数数组，由上层按需合成；不强制合成完整 mask 避免性能开销）
        try:
            item["mask_coeffs"] = [float(x) for x in coeffs[i]]
        except Exception:
            pass
        out.append(item)
    return out


# ===================== pose =====================
def _decode_pose(outputs, algorithm_type, labels, input_size, conf, iou, orig_size, nc=None):
    arr = np.asarray(outputs[0])
    iw, ih = input_size
    orig_w, orig_h = orig_size
    sx, sy = float(orig_w) / iw, float(orig_h) / ih
    # 仅 yolo8/11/26 pose 普遍为 [1, 4+1+nk*3, N]（4 box + 1 conf + nk*3 kpt）
    if arr.ndim == 3 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.ndim != 2:
        return []
    if arr.shape[0] < arr.shape[1] and arr.shape[0] >= 5:
        arr = arr.T
    if arr.ndim != 2 or arr.shape[1] < 6:
        return []
    # 列布局：[cx, cy, w, h, conf, kpt_x, kpt_y, kpt_conf, ...] —— 标准 ultralytics pose 导出
    confs = arr[:, 4]
    mask = confs >= conf
    if not np.any(mask):
        return []
    arr = arr[mask]
    boxes_raw = _xywh2xyxy(arr[:, :4])
    confs = arr[:, 4]
    # 关键点：剩余列按 [x, y, conf] 三元组
    kpt_cols = arr.shape[1] - 5
    nk = kpt_cols // 3
    kpts = arr[:, 5:5 + nk * 3].reshape(-1, nk, 3) if nk > 0 else None
    boxes = [_scale_box(b, sx, sy, orig_w, orig_h) for b in boxes_raw]
    keep = _nms(boxes, confs, iou)
    out = []
    for i in keep:
        label = labels[0] if labels else "person"
        item = {"box": boxes[i], "label": str(label), "score": float(confs[i]), "task": "pose"}
        if kpts is not None:
            kp = kpts[i]
            # 缩放关键点 xy
            item["keypoints"] = [
                [float(kp[j, 0] * sx), float(kp[j, 1] * sy), float(kp[j, 2])]
                for j in range(nk)
            ]
        out.append(item)
    return out


# ===================== obb =====================
def _decode_obb(outputs, algorithm_type, labels, input_size, conf, iou, orig_size, nc=None):
    arr = np.asarray(outputs[0])
    iw, ih = input_size
    orig_w, orig_h = orig_size
    sx, sy = float(orig_w) / iw, float(orig_h) / ih
    # yolo8/11/26 obb: [1, 4+nc+1, N]  末列角度
    if arr.ndim == 3 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.ndim != 2:
        return []
    if arr.shape[0] < arr.shape[1] and arr.shape[0] >= 5:
        arr = arr.T
    if arr.ndim != 2 or arr.shape[1] < 6:
        return []
    nc = arr.shape[1] - 5 if nc is None else nc
    if nc < 1:
        nc = 1
    boxes_raw = _xywh2xyxy(arr[:, :4])
    cls_scores = arr[:, 4:4 + nc]
    angles = arr[:, 4 + nc]
    best_cls = np.argmax(cls_scores, axis=1)
    best_score = cls_scores[np.arange(len(arr)), best_cls]
    mask = best_score >= conf
    if not np.any(mask):
        return []
    boxes_raw = boxes_raw[mask]
    scores = best_score[mask]
    clses = best_cls[mask]
    angles = angles[mask]
    boxes = [_scale_box(b, sx, sy, orig_w, orig_h) for b in boxes_raw]
    keep = _nms(boxes, scores, iou)
    out = []
    for i in keep:
        label = labels[int(clses[i])] if 0 <= int(clses[i]) < len(labels) else str(int(clses[i]))
        out.append({"box": boxes[i], "label": str(label), "score": float(scores[i]),
                    "task": "obb", "angle": float(angles[i])})
    return out
