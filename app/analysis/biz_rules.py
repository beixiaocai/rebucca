# 作者：北小菜
"""业务算法后处理 — 区域入侵(AREA) / 越线(LINE_CROSS) / 方向(DIRECTION) / 密度(DENSITY) / 滞留(DWELL)"""
import logging
import math

logger = logging.getLogger("analysis.biz_rules")

# 后处理类型常量（与 models.BizAlgorithmModel.POST_* 保持一致）
POST_AREA = "AREA"
POST_LINE_CROSS = "LINE_CROSS"
POST_DIRECTION = "DIRECTION"
POST_DENSITY = "DENSITY"
POST_DWELL = "DWELL"

# 支持小模型流程（flow_type 1/3）的后处理白名单
SMALL_FLOW_POSTS = (POST_AREA, POST_LINE_CROSS, POST_DIRECTION, POST_DENSITY, POST_DWELL)
# 支持大模型流程（flow_type 2）的后处理白名单（大模型主要做语义判断，几何类后处理意义有限）
LLM_FLOW_POSTS = (POST_AREA,)


def _norm_label(label):
    return (label or "").strip().lower()


def _targets_hit(track, biz_rule):
    """目标类别命中 + 小模型来源匹配（所有后处理通用前置条件）"""
    targets = biz_rule.get("target_labels") or []
    if not targets:
        return False
    label = _norm_label(track.get("label"))
    target_set = {_norm_label(t) for t in targets}
    if label not in target_set:
        return False
    sm_id = biz_rule.get("small_model_id")
    track_algo = track.get("algorithm_id")
    if sm_id and track_algo is not None and int(track_algo) != int(sm_id):
        return False
    return True


def track_matches_area_rule(track, biz_rule):
    """小模型流程：目标类别命中 + AREA 后处理"""
    if not biz_rule or biz_rule.get("post_process") != POST_AREA:
        return False
    flow = int(biz_rule.get("flow_type") or 1)
    if flow not in (1, 3):
        return False
    return _targets_hit(track, biz_rule)


def track_matches_line_cross_rule(track, biz_rule):
    """越线检测：目标类别命中 + LINE_CROSS 后处理
    注：真正的跨线判断由 pipeline 维护目标轨迹历史后调用 cross_line_segment 完成，
    此处仅做"该目标是否参与越线后处理"的静态筛选。
    """
    if not biz_rule or biz_rule.get("post_process") != POST_LINE_CROSS:
        return False
    flow = int(biz_rule.get("flow_type") or 1)
    if flow not in (1, 3):
        return False
    return _targets_hit(track, biz_rule)


def track_matches_direction_rule(track, biz_rule):
    """方向入侵：目标类别命中 + DIRECTION 后处理
    注：实际方向判断由 pipeline 计算目标位移向量后调用 direction_match 完成。
    """
    if not biz_rule or biz_rule.get("post_process") != POST_DIRECTION:
        return False
    flow = int(biz_rule.get("flow_type") or 1)
    if flow not in (1, 3):
        return False
    return _targets_hit(track, biz_rule)


def track_matches_density_rule(track, biz_rule):
    """密度报警：DENSITY 后处理
    注：密度统计是"区域级"而非"目标级"，pipeline 在 _check_zones 中独立处理，
    此函数仅用于过滤目标类别（参与计数的类别需命中 target_labels）。
    """
    if not biz_rule or biz_rule.get("post_process") != POST_DENSITY:
        return False
    flow = int(biz_rule.get("flow_type") or 1)
    if flow not in (1, 3):
        return False
    return _targets_hit(track, biz_rule)


def track_matches_dwell_rule(track, biz_rule):
    """滞留报警：DWELL 后处理（与 AREA 滞留类似，但作为独立后处理类型）"""
    if not biz_rule or biz_rule.get("post_process") != POST_DWELL:
        return False
    flow = int(biz_rule.get("flow_type") or 1)
    if flow not in (1, 3):
        return False
    return _targets_hit(track, biz_rule)


# ---------- 几何辅助 ----------

def cross_line_segment(prev_pt, cur_pt, line_a, line_b):
    """判断线段 prev_pt→cur_pt 是否跨过有向线段 line_a→line_b（含方向判定）
    返回: True 表示跨过且方向匹配（从左侧到右侧，方向沿线段方向看）
    """
    if not prev_pt or not cur_pt or not line_a or not line_b:
        return False
    try:
        x1, y1 = float(prev_pt[0]), float(prev_pt[1])
        x2, y2 = float(cur_pt[0]), float(cur_pt[1])
        ax, ay = float(line_a[0]), float(line_a[1])
        bx, by = float(line_b[0]), float(line_b[1])
    except (TypeError, ValueError, IndexError):
        return False
    # 用叉积判断两点是否在有向线段两侧
    def cross(ox, oy, px, py, qx, qy):
        return (px - ox) * (qy - oy) - (py - oy) * (qx - ox)
    c1 = cross(ax, ay, bx, by, x1, y1)
    c2 = cross(ax, ay, bx, by, x2, y2)
    if c1 == 0 or c2 == 0 or c1 * c2 > 0:
        return False  # 同侧或在线上，未跨过
    # 跨过线段，进一步要求方向：从 c1>0 一侧到 c2<0 一侧（即沿线段方向看的左侧→右侧）
    return c1 > 0 > c2


def direction_match(dx, dy, ref_angle_deg, tolerance_deg=45.0):
    """判断位移向量 (dx,dy) 的方向是否落在 [ref_angle-tol, ref_angle+tol] 内
    角度约定：0°=向右(东)，90°=向下(南，图像坐标系)，180°=向左(西)，270°=向上(北)
    """
    if dx == 0 and dy == 0:
        return False
    ang = math.degrees(math.atan2(dy, dx)) % 360
    lo = (ref_angle_deg - tolerance_deg) % 360
    hi = (ref_angle_deg + tolerance_deg) % 360
    if lo <= hi:
        return lo <= ang <= hi
    return ang >= lo or ang <= hi


def zone_has_llm_flow(zone_cfg):
    for ba in (zone_cfg or {}).get("biz_algorithms") or []:
        if int(ba.get("flow_type") or 0) in (2, 3):
            return True
    return False


def llm_rules_for_zone(zone_cfg):
    """流程2：返回该区域内使用大模型 + AREA 后处理的规则"""
    rules = []
    for ba in (zone_cfg or {}).get("biz_algorithms") or []:
        if int(ba.get("flow_type") or 0) == 2 and ba.get("post_process") == POST_AREA:
            if ba.get("llm") and ba.get("llm_prompt"):
                rules.append(ba)
    return rules


def matched_area_rules(track, zone_cfg):
    """返回与当前目标匹配的 AREA 业务算法"""
    rules = (zone_cfg or {}).get("biz_algorithms") or []
    if not rules:
        return []
    area_rules = [r for r in rules if r.get("post_process") == POST_AREA
                  and int(r.get("flow_type") or 0) in (1, 3)]
    return [r for r in area_rules if track_matches_area_rule(track, r)]


def matched_rules_for_track(track, zone_cfg):
    """统一调度：返回与当前目标匹配的所有业务算法（含 AREA/LINE_CROSS/DIRECTION/DENSITY/DWELL）
    pipeline 在目标进入区域时调用此函数获取命中的业务算法。
    """
    rules = (zone_cfg or {}).get("biz_algorithms") or []
    if not rules:
        return []
    matched = []
    for r in rules:
        post = r.get("post_process")
        flow = int(r.get("flow_type") or 0)
        if flow not in (1, 3):
            continue
        if post == POST_AREA and track_matches_area_rule(track, r):
            matched.append(r)
        elif post == POST_LINE_CROSS and track_matches_line_cross_rule(track, r):
            matched.append(r)
        elif post == POST_DIRECTION and track_matches_direction_rule(track, r):
            matched.append(r)
        elif post == POST_DENSITY and track_matches_density_rule(track, r):
            matched.append(r)
        elif post == POST_DWELL and track_matches_dwell_rule(track, r):
            matched.append(r)
    return matched


def build_alarm_context(event_type, track, zone_cfg, biz_rule=None):
    """生成报警元数据：所属业务算法、报警原因等"""
    zone_name = (zone_cfg or {}).get("name") or ""
    label = (track or {}).get("label") or ""
    biz_name = (biz_rule or {}).get("name") or ""
    biz_id = (biz_rule or {}).get("id")
    flow_type = int((biz_rule or {}).get("flow_type") or 0)
    post = (biz_rule or {}).get("post_process") or POST_AREA

    post_label_map = {
        POST_AREA: "区域入侵",
        POST_LINE_CROSS: "越线检测",
        POST_DIRECTION: "方向入侵",
        POST_DENSITY: "密度报警",
        POST_DWELL: "滞留报警",
    }
    post_label = post_label_map.get(post, post)

    if event_type == "entered_zone":
        if flow_type == 2:
            reason = "大模型区域分析：在布控「%s」检测到异常" % (zone_name or "—")
        elif flow_type == 3:
            reason = "小模型+大模型：目标「%s」进入「%s」，大模型校验通过" % (label or "—", zone_name or "—")
        elif biz_rule:
            targets = "、".join(biz_rule.get("target_labels") or []) or "—"
            reason = "%s：目标「%s」进入「%s」（检测目标：%s）" % (post_label, label or "—", zone_name or "—", targets)
        else:
            reason = "目标「%s」进入布控「%s」" % (label or "—", zone_name or "—")
    elif event_type == "loiter" or event_type == "dwell":
        threshold = int((zone_cfg or {}).get("loiter_threshold") or 0)
        dur = (track or {}).get("duration")
        dur_txt = ("，已停留 %.0f 秒" % dur) if dur else ("，阈值 %d 秒" % threshold if threshold else "")
        if biz_rule:
            reason = "%s：目标「%s」在「%s」超时%s" % (post_label, label or "—", zone_name or "—", dur_txt)
        else:
            reason = "%s：目标「%s」在「%s」%s" % (post_label, label or "—", zone_name or "—", dur_txt.strip("，"))
    elif event_type == "line_cross":
        if biz_rule:
            reason = "%s：目标「%s」跨过布控「%s」的警戒线" % (post_label, label or "—", zone_name or "—")
        else:
            reason = "目标「%s」越线" % (label or "—")
    elif event_type == "direction":
        if biz_rule:
            reason = "%s：目标「%s」在「%s」按设定方向移动" % (post_label, label or "—", zone_name or "—")
        else:
            reason = "目标「%s」方向匹配" % (label or "—")
    elif event_type == "density":
        count = (track or {}).get("density_count") or 0
        threshold = int((zone_cfg or {}).get("density_threshold") or 0)
        if biz_rule:
            reason = "%s：「%s」目标数 %d ≥ 阈值 %d" % (post_label, zone_name or "—", count, threshold)
        else:
            reason = "密度告警：%d 个目标" % count
    elif event_type == "motion":
        return {}
    else:
        reason = event_type or ""

    if not biz_name and biz_rule:
        biz_name = "业务算法#%s" % biz_id if biz_id else ""

    return {
        "zone_name": zone_name,
        "biz_algorithm_id": biz_id,
        "biz_algorithm_name": biz_name,
        "alarm_reason": reason,
    }
