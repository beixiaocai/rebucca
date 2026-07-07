# 作者：北小菜
"""业务算法管理 — 小模型/大模型 + 后处理业务逻辑"""
import json

from app.views.ViewsBase import *
from django.shortcuts import render

from app.models import BizAlgorithmModel, AlgorithmModel, LLMModel, ZoneModel


def _parse_labels(raw):
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
        return [s.strip() for s in raw.split(",") if s.strip()]
    return []


def _resolve_model_abs_path(model_file):
    """返回模型文件的绝对路径（不存在则返回空串）"""
    if not model_file:
        return ""
    try:
        from app.analysis.worker_pool import resolve_model_path
        p = resolve_model_path(model_file)
        import os as _os
        if p and _os.path.exists(p):
            return p
    except Exception:
        pass
    return ""


def _check_model_file_exists(model_file):
    """检查模型文件是否存在"""
    return bool(_resolve_model_abs_path(model_file))


def _biz_to_dict(b, detail=False):
    labels = _parse_labels(b.target_labels or '[]')
    d = {
        "id": b.id,
        "name": b.name,
        "flow_type": b.flow_type,
        "small_model_id": b.small_model_id,
        "small_model_name": b.small_model.name if b.small_model_id and b.small_model else "",
        "detector_model_id": b.detector_model_id,
        "detector_model_name": b.detector_model.name if b.detector_model_id and b.detector_model else "",
        "target_labels": labels,
        "llm_id": b.llm_id,
        "llm_name": b.llm.name if b.llm_id and b.llm else "",
        "llm_prompt": b.llm_prompt or "",
        "llm_validate": b.llm_validate or "",
        "post_process": b.post_process or BizAlgorithmModel.POST_AREA,
        "ref_angle": float(getattr(b, "ref_angle", 90.0) or 90.0),
        "angle_tolerance": float(getattr(b, "angle_tolerance", 45.0) or 45.0),
        "forward_count_threshold": int(getattr(b, "forward_count_threshold", 0) or 0),
        "reverse_count_threshold": int(getattr(b, "reverse_count_threshold", 0) or 0),
        "state": b.state,
        "create_time": str(b.create_time),
            "zone_count": b.zones.count(),
    }
    # 小模型文件状态
    small = b.small_model if (b.small_model_id and b.small_model) else None
    if small:
        d["small_model_file"] = small.model_file or ""
        d["small_model_engine"] = small.inference_engine or ""
        d["small_model_file_exists"] = _check_model_file_exists(small.model_file or "")
        d["small_model_file_path"] = _resolve_model_abs_path(small.model_file or "")
    else:
        d["small_model_file"] = ""
        d["small_model_engine"] = ""
        d["small_model_file_exists"] = False
        d["small_model_file_path"] = ""
    detector = b.detector_model if (b.detector_model_id and b.detector_model) else None
    if detector:
        d["detector_model_file"] = detector.model_file or ""
        d["detector_model_engine"] = detector.inference_engine or ""
        d["detector_model_file_exists"] = _check_model_file_exists(detector.model_file or "")
    else:
        d["detector_model_file"] = ""
        d["detector_model_engine"] = ""
        d["detector_model_file_exists"] = False
    flow_names = {
        BizAlgorithmModel.FLOW_SMALL: "小模型+后处理",
        BizAlgorithmModel.FLOW_LLM: "大模型+后处理",
        BizAlgorithmModel.FLOW_BOTH: "小模型+大模型+后处理",
        BizAlgorithmModel.FLOW_DETECT_REID: "检测+ReID+后处理",
    }
    d["flow_type_name"] = flow_names.get(b.flow_type, str(b.flow_type))
    post_names = {
        BizAlgorithmModel.POST_AREA: "区域入侵",
        BizAlgorithmModel.POST_LINE_CROSS: "越线检测",
        BizAlgorithmModel.POST_LINE_COUNT: "越线计数",
        BizAlgorithmModel.POST_DIRECTION: "方向入侵",
        BizAlgorithmModel.POST_DENSITY: "密度报警",
        BizAlgorithmModel.POST_DWELL: "滞留报警",
    }
    d["post_process_name"] = post_names.get(d["post_process"], d["post_process"])
    return d


def _validate_biz_fields(params, biz_id=0):
    name = (params.get("name") or "").strip()
    if not name:
        raise ValueError("算法名称不能为空")
    try:
        flow_type = int(params.get("flow_type", 1))
    except Exception:
        flow_type = 1
    if flow_type not in (1, 2, 3, 4):
        raise ValueError("无效的流程类型")

    small_model_id = None
    detector_model_id = None
    llm_id = None
    target_labels = []
    llm_prompt = (params.get("llm_prompt") or "").strip()
    llm_validate = (params.get("llm_validate") or "").strip()
    post_process = (params.get("post_process") or BizAlgorithmModel.POST_AREA).strip()

    if flow_type in (BizAlgorithmModel.FLOW_SMALL, BizAlgorithmModel.FLOW_BOTH):
        try:
            small_model_id = int(params.get("small_model_id", 0))
        except Exception:
            small_model_id = 0
        if small_model_id <= 0:
            raise ValueError("请选择小模型")
        sm = AlgorithmModel.objects.filter(id=small_model_id, state=1).first()
        if not sm:
            raise ValueError("小模型不存在或已禁用")
        if (getattr(sm, "task_type", "") or "detect").lower() == "reid":
            raise ValueError("ReID 模型请使用「检测+ReID+后处理」流程，并同时选择 YOLO 检测小模型")
        target_labels = _parse_labels(params.get("target_labels"))
        if not target_labels:
            raise ValueError("请至少选择一个检测目标")

    if flow_type == BizAlgorithmModel.FLOW_DETECT_REID:
        try:
            detector_model_id = int(params.get("detector_model_id", 0))
        except Exception:
            detector_model_id = 0
        try:
            small_model_id = int(params.get("small_model_id", 0))
        except Exception:
            small_model_id = 0
        if detector_model_id <= 0:
            raise ValueError("请选择检测小模型 (YOLO)")
        if small_model_id <= 0:
            raise ValueError("请选择 ReID 小模型 (OSNet)")
        if detector_model_id == small_model_id:
            raise ValueError("检测小模型与 ReID 小模型不能相同")
        det = AlgorithmModel.objects.filter(id=detector_model_id, state=1).first()
        if not det:
            raise ValueError("检测小模型不存在或已禁用")
        if (getattr(det, "task_type", "") or "detect").lower() != "detect":
            raise ValueError("检测小模型必须是 YOLO 检测模型 (task_type=detect)")
        reid = AlgorithmModel.objects.filter(id=small_model_id, state=1).first()
        if not reid:
            raise ValueError("ReID 小模型不存在或已禁用")
        if (getattr(reid, "task_type", "") or "").lower() != "reid":
            raise ValueError("ReID 小模型必须是 OSNet ReID 模型 (task_type=reid)")
        target_labels = _parse_labels(params.get("target_labels"))
        if not target_labels:
            raise ValueError("请至少选择一个检测目标")
        det_labels = _parse_labels(det.labels or "[]")
        invalid = [lb for lb in target_labels if lb not in det_labels]
        if invalid:
            raise ValueError("检测目标不在检测小模型标签列表中：%s" % "、".join(invalid))

    if flow_type in (BizAlgorithmModel.FLOW_LLM, BizAlgorithmModel.FLOW_BOTH):
        try:
            llm_id = int(params.get("llm_id", 0))
        except Exception:
            llm_id = 0
        if llm_id <= 0:
            raise ValueError("请选择大模型")
        if not LLMModel.objects.filter(id=llm_id, state=1).exists():
            raise ValueError("大模型不存在或已禁用")
        if not llm_prompt:
            raise ValueError("请输入大模型提示词")
        if not llm_validate:
            raise ValueError("请输入提示词校验值")

    valid_posts = (
        BizAlgorithmModel.POST_AREA,
        BizAlgorithmModel.POST_LINE_CROSS,
        BizAlgorithmModel.POST_LINE_COUNT,
        BizAlgorithmModel.POST_DIRECTION,
        BizAlgorithmModel.POST_DENSITY,
        BizAlgorithmModel.POST_DWELL,
    )
    if post_process not in valid_posts:
        raise ValueError("无效的后处理逻辑")

    try:
        forward_count_threshold = int(params.get("forward_count_threshold", 0) or 0)
    except Exception:
        forward_count_threshold = 0
    try:
        reverse_count_threshold = int(params.get("reverse_count_threshold", 0) or 0)
    except Exception:
        reverse_count_threshold = 0
    forward_count_threshold = max(0, forward_count_threshold)
    reverse_count_threshold = max(0, reverse_count_threshold)
    if post_process == BizAlgorithmModel.POST_LINE_COUNT:
        if forward_count_threshold <= 0 and reverse_count_threshold <= 0:
            raise ValueError("越线计数至少设置一个方向的报警阈值（大于 0）")

    # DIRECTION 后处理参数
    try:
        ref_angle = float(params.get("ref_angle", 90.0))
    except Exception:
        ref_angle = 90.0
    try:
        angle_tolerance = float(params.get("angle_tolerance", 45.0))
    except Exception:
        angle_tolerance = 45.0

    return {
        "name": name,
        "flow_type": flow_type,
        "small_model_id": small_model_id,
        "detector_model_id": detector_model_id,
        "target_labels": json.dumps(target_labels, ensure_ascii=False),
        "llm_id": llm_id,
        "llm_prompt": llm_prompt,
        "llm_validate": llm_validate,
        "post_process": post_process,
        "ref_angle": ref_angle,
        "angle_tolerance": angle_tolerance,
        "forward_count_threshold": forward_count_threshold,
        "reverse_count_threshold": reverse_count_threshold,
        "state": int(params.get("state", 1)),
    }


def algorithm_index(request):
    return render(request, 'app/algorithm/index.html', {})


def algorithm_openIndex(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = []
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            qs = BizAlgorithmModel.objects.select_related('small_model', 'detector_model', 'llm').order_by('-id')
            state = request.GET.get('state', '').strip()
            if state != '':
                qs = qs.filter(state=int(state))
            flow = request.GET.get('flow_type', '').strip()
            if flow != '':
                qs = qs.filter(flow_type=int(flow))
            data = [_biz_to_dict(b) for b in qs]
            ret = True
            msg = LANG_VIEWS_T(request, "msg_success")
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def algorithm_openCheckModels(request):
    """检查所有小模型的模型文件是否存在，返回就绪列表与缺失列表。
    用于前端进入页面时全局告警提示，便于排查具体哪个模型成功/失败。
    """
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {"missing": [], "ok_list": [], "total": 0, "ok_count": 0}
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                qs = AlgorithmModel.objects.filter(state=1).order_by('id')
                total = 0
                ok = 0
                missing = []
                ok_list = []
                for a in qs:
                    total += 1
                    mf = a.model_file or ""
                    exists = _check_model_file_exists(mf)
                    item = {
                        "id": a.id,
                        "name": a.name,
                        "model_file": mf,
                        "engine": a.inference_engine or "",
                    }
                    if exists:
                        ok += 1
                        item["hint"] = "模型文件就绪"
                        ok_list.append(item)
                    else:
                        item["hint"] = "模型文件未配置" if not mf else "模型文件不存在"
                        missing.append(item)
                data = {"missing": missing, "ok_list": ok_list, "total": total, "ok_count": ok}
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def algorithm_openOptions(request):
    """表单下拉：小模型列表、大模型列表、后处理选项"""
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {}
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            small_models = []
            for a in AlgorithmModel.objects.filter(state=1).order_by('-is_default', 'name'):
                labels = _parse_labels(a.labels or '[]')
                small_models.append({
                    "id": a.id,
                    "name": a.name,
                    "labels": labels,
                    "algorithm_type": a.algorithm_type,
                    "task_type": a.task_type,
                    "model_file": a.model_file or "",
                    "model_file_exists": _check_model_file_exists(a.model_file or ""),
                    "engine": a.inference_engine or "",
                })
            llms = [{"id": x.id, "name": x.name, "model_name": x.model_name}
                    for x in LLMModel.objects.filter(state=1).order_by('sort', 'id')]
            data = {
                "small_models": small_models,
                "llms": llms,
                "post_processes": [
                    {"value": BizAlgorithmModel.POST_AREA, "label": "区域入侵"},
                    {"value": BizAlgorithmModel.POST_LINE_CROSS, "label": "越线检测"},
                    {"value": BizAlgorithmModel.POST_LINE_COUNT, "label": "越线计数"},
                    {"value": BizAlgorithmModel.POST_DIRECTION, "label": "方向入侵"},
                    {"value": BizAlgorithmModel.POST_DENSITY, "label": "密度报警"},
                    {"value": BizAlgorithmModel.POST_DWELL, "label": "滞留报警"},
                ],
                "flow_types": [
                    {"value": 1, "label": "小模型 + 后处理"},
                    {"value": 2, "label": "大模型 + 后处理"},
                    {"value": 3, "label": "小模型 + 大模型 + 后处理"},
                    {"value": 4, "label": "检测小模型 + ReID小模型 + 后处理"},
                ],
            }
            ret = True
            msg = LANG_VIEWS_T(request, "msg_success")
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def algorithm_openAdd(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                fields = _validate_biz_fields(params)
                BizAlgorithmModel.objects.create(**fields)
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def algorithm_openEdit(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                bid = int(params.get("id", 0))
                b = BizAlgorithmModel.objects.get(id=bid)
                fields = _validate_biz_fields(params, biz_id=bid)
                for k, v in fields.items():
                    setattr(b, k, v)
                b.save()
                _reload_affected_pipelines(b)
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def algorithm_openDel(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {"referenced_zones": []}
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                bid = int(params.get("id", 0))
                b = BizAlgorithmModel.objects.get(id=bid)
                ref_zones = list(
                    b.zones.select_related('stream').order_by('id')
                )
                if ref_zones:
                    # 列出引用该算法的布控名称，便于用户排查并先解除绑定
                    names = []
                    for z in ref_zones:
                        sname = z.stream.nickname if z.stream else ("#%s" % z.stream_id)
                        names.append("%s/%s" % (sname, z.name))
                    data["referenced_zones"] = names
                    raise ValueError("该算法已被 %d 个布控引用，请先解除绑定后再删除（%s）"
                                     % (len(ref_zones), "、".join(names)))
                b.delete()
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def _reload_affected_pipelines(biz):
    try:
        from app.analysis.manager import AnalysisManager
        mgr = AnalysisManager()
        stream_ids = set()
        for z in biz.zones.select_related('stream').all():
            if z.stream_id:
                stream_ids.add(z.stream_id)
        for sid in stream_ids:
            if mgr.is_running(sid):
                mgr.reload_zones(sid)
    except Exception:
        pass


def algorithm_openAssignContext(request):
    """分配布控：列出全部区域及是否已绑定该算法"""
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {}
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parseGetParams(request)
            try:
                bid = int(params.get("biz_algorithm_id", 0) or params.get("id", 0))
                biz = BizAlgorithmModel.objects.get(id=bid)
                zones = []
                for z in ZoneModel.objects.select_related('stream').order_by('stream_id', 'id'):
                    selected = z.algorithms.filter(id=bid).exists()
                    zones.append({
                        "id": z.id,
                        "stream_id": z.stream_id,
                        "stream_name": z.stream.nickname if z.stream else "",
                        "zone_name": z.name,
                        "state": z.state,
                        "selected": selected,
                    })
                data = {
                    "biz_algorithm": _biz_to_dict(biz),
                    "zones": zones,
                }
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def algorithm_openAssignZones(request):
    """将业务算法绑定到布控区域（增删仅影响本算法）"""
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                bid = int(params.get("biz_algorithm_id", 0) or params.get("id", 0))
                biz = BizAlgorithmModel.objects.get(id=bid)
                zone_ids = params.get("zone_ids") or []
                if isinstance(zone_ids, str):
                    try:
                        zone_ids = json.loads(zone_ids)
                    except Exception:
                        zone_ids = [s for s in zone_ids.split(",") if s.strip()]
                zone_ids = {int(x) for x in zone_ids if str(x).strip()}

                affected_streams = set()
                blocked_zones = []
                to_remove = []  # 先收集待解绑区域，校验通过后统一执行
                # 取消未选中的绑定
                for z in ZoneModel.objects.filter(algorithms=biz).prefetch_related('algorithms'):
                    if z.id not in zone_ids:
                        if z.algorithms.count() <= 1:
                            blocked_zones.append(z.name or ("#%s" % z.id))
                            continue
                        to_remove.append(z)
                        affected_streams.add(z.stream_id)
                if blocked_zones:
                    raise ValueError(
                        LANG_VIEWS_T(request, "zone_algo_required")
                        + " (" + "、".join(blocked_zones) + ")"
                    )
                # 校验通过，统一执行解绑
                for z in to_remove:
                    z.algorithms.remove(biz)
                # 添加新绑定
                if zone_ids:
                    for z in ZoneModel.objects.filter(id__in=zone_ids):
                        if not z.algorithms.filter(id=bid).exists():
                            z.algorithms.add(biz)
                        affected_streams.add(z.stream_id)

                try:
                    from app.analysis.manager import AnalysisManager
                    mgr = AnalysisManager()
                    for sid in affected_streams:
                        if sid and mgr.is_running(sid):
                            mgr.reload_zones(sid)
                except Exception:
                    pass

                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})
