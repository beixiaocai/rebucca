# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""Rebucca · 布控管理 Web 层

页面：
- /control/index            布控管理（按摄像头绘制多边形区域）

API：
- /control/openIndex/openAdd/openEdit/openDel/openPageData/openRecentAlarms
"""
from app.views.ViewsBase import *
from django.shortcuts import render

from app.models import StreamModel, ZoneModel, AlarmModel
import time as _time

CONTROL_ALARM_EVENT_TYPES = ('entered_zone', 'loiter')

# ---------- 状态接口内存缓存 ----------
# 布控页/控制面板高频轮询 openStatus，原始实现每次都遍历所有运行实例 +
# 查 DB，布控执行时叠加 SQLite 锁会导致页面卡顿。
# 这里加一个带 TTL 的进程内缓存，多个请求共享同一份快照。
_STATUS_CACHE = {"lite": {"t": 0, "data": None}, "full": {"t": 0, "data": None}}
_STATUS_CACHE_TTL = 2.0  # 秒：缓存有效期，2s 内重复请求直接返回缓存


def _get_cached_status(lite=False):
    key = "lite" if lite else "full"
    entry = _STATUS_CACHE.get(key)
    now = _time.time()
    if entry and entry["data"] is not None and (now - entry["t"]) < _STATUS_CACHE_TTL:
        return entry["data"]
    return None


def _set_cached_status(data, lite=False):
    key = "lite" if lite else "full"
    _STATUS_CACHE[key] = {"t": _time.time(), "data": data}


def _parse_control_detect_rate(params):
    try:
        interval = float(params.get("detect_interval_sec", 1) or 1)
    except (TypeError, ValueError):
        interval = 1.0
    try:
        frames = int(params.get("detect_frames", 1) or 1)
    except (TypeError, ValueError):
        frames = 1
    interval = max(0.1, min(86400.0, interval))
    frames = max(1, min(999, frames))
    return interval, frames


def _control_to_dict(z):
    algos = []
    try:
        algos = [{"id": a.id, "name": a.name} for a in z.algorithms.all().order_by('id')]
    except Exception:
        pass
    stream = getattr(z, "stream", None)
    interval = max(0.1, float(getattr(z, "detect_interval_sec", 1) or 1))
    frames = max(1, int(getattr(z, "detect_frames", 1) or 1))
    return {
        "id": z.id,
        "stream_id": z.stream_id,
        "stream_name": (stream.nickname if stream else ""),
        "name": z.name,
        "coordinates": z.coordinates,
        "is_required": z.is_required,
        "loiter_threshold": z.loiter_threshold,
        "detect_interval_sec": interval,
        "detect_frames": frames,
        "color": z.color,
        "line_a": getattr(z, "line_a", "") or "",
        "line_b": getattr(z, "line_b", "") or "",
        "density_threshold": int(getattr(z, "density_threshold", 0) or 0),
        "algorithms": algos,
        "algorithm_ids": [a["id"] for a in algos],
        "create_time": str(z.create_time),
    }


def _control_queryset(stream_id=None):
    qs = ZoneModel.objects.select_related("stream").prefetch_related("algorithms").order_by("-id")
    if stream_id:
        qs = qs.filter(stream_id=int(stream_id))
    return qs


def build_analysis_status_data(lite=False):
    """汇总分析运行状态；lite 模式跳过引擎探测等重操作，供布控页轮询。"""
    # 命中缓存则直接返回，避免每次都遍历运行实例 + 查 DB
    cached = _get_cached_status(lite=lite)
    if cached is not None:
        return cached
    from app.analysis.manager import AnalysisManager
    m = AnalysisManager()
    shared_inference = m._use_shared_inference() and m._use_multiprocess()
    multi_process = m._use_multiprocess()
    running = []
    for sid in m.list_running():
        info = m.get_pipeline_info(sid)
        if info:
            running.append(info)
    # 收集运行中 pipeline 的 stream_name 映射，供引擎实例详情使用
    stream_name_map = {}
    for r in running:
        sid = r.get("stream_id")
        if sid:
            stream_name_map[sid] = r.get("stream_name") or r.get("algorithm_name") or ("#%s" % sid)
    algo_usage = {}
    for r in running:
        sid = r.get("stream_id")
        sname = stream_name_map.get(sid, "")
        for d in (r.get("detectors") or []):
            aid = d.get("algorithm_id")
            if aid is None:
                continue
            u = algo_usage.setdefault(
                aid,
                {
                    "algorithm_id": aid,
                    "algorithm_name": d.get("algorithm_name", ""),
                    "engine": d.get("engine", ""),
                    "stream_count": 0,
                    "stream_names": [],
                },
            )
            u["stream_count"] += 1
            if sname and sname not in u["stream_names"]:
                u["stream_names"].append(sname)
    # 补充小模型详情 + 反查业务算法
    if algo_usage:
        try:
            from app.models import AlgorithmModel, BizAlgorithmModel
            sm_qs = AlgorithmModel.objects.filter(id__in=list(algo_usage.keys()))
            sm_map = {sm.id: sm for sm in sm_qs}
            # 反查业务算法（通过 small_model 外键）
            biz_qs = BizAlgorithmModel.objects.filter(
                small_model_id__in=list(algo_usage.keys()), state=1
            ).select_related("small_model")
            biz_by_sm = {}
            for ba in biz_qs:
                biz_by_sm.setdefault(ba.small_model_id, []).append({
                    "id": ba.id, "name": ba.name, "flow_type": ba.flow_type,
                })
            for aid, u in algo_usage.items():
                sm = sm_map.get(aid)
                if sm:
                    u["model_file"] = sm.model_file
                    u["task_type"] = sm.task_type
                    u["device"] = sm.device
                    u["input_size"] = [sm.input_width, sm.input_height]
                    u["conf_threshold"] = sm.conf_threshold
                    u["iou_threshold"] = sm.iou_threshold
                    u["algorithm_type"] = sm.algorithm_type
                    u["small_model_state"] = sm.state
                u["biz_algorithms"] = biz_by_sm.get(aid, [])
                u["instance_enabled"] = m.is_algo_instance_enabled(aid)
        except Exception as e:
            import logging
            logging.getLogger("app").warning("build_analysis_status_data 补充详情失败: %s" % str(e))
    local_instances = m._worker_pool.instance_info()
    inference_workers_alive = 0
    inference_workers_config = 0
    if shared_inference:
        try:
            from app.analysis.inference_pool import get_inference_pool
            pool = get_inference_pool()
            inference_workers_alive = pool.instance_count()
            inference_workers_config = pool.num_workers
        except Exception:
            inference_workers_alive = 0
    else:
        try:
            from app.utils.GlobalUtils import g_config
            inference_workers_config = int(getattr(g_config, "analysisInferenceWorkers", 2))
        except Exception:
            inference_workers_config = 2
    if shared_inference:
        engine_total = len(algo_usage) if algo_usage else inference_workers_alive
    else:
        engine_total = len(local_instances)
    # 所有业务算法的实例化开关状态
    algo_instance_states = []
    try:
        from app.models import BizAlgorithmModel
        disabled = m.get_disabled_algos()
        for ba in BizAlgorithmModel.objects.filter(state=1).order_by("id"):
            sm = ba.small_model
            algo_instance_states.append({
                "id": ba.id,
                "name": ba.name,
                "flow_type": ba.flow_type,
                "small_model_id": sm.id if sm else None,
                "small_model_name": sm.name if sm else "",
                "engine": sm.inference_engine if sm else "",
                "instance_enabled": (sm.id not in disabled) if sm else True,
            })
    except Exception:
        pass
    data = {
        "running_streams": running,
        "running_count": len(running),
        "total_streams": StreamModel.objects.count(),
        "engine_instances": list(algo_usage.values()),
        "engine_instance_total": engine_total,
        "engine_instances_local": len(local_instances),
        "inference_shared": shared_inference,
        "inference_workers_alive": inference_workers_alive,
        "analysis_fps_avg": (
            round(sum(r.get("analysis_fps", 0) for r in running) / len(running), 1) if running else 0.0
        ),
        "inference_config": {
            "shared": bool(shared_inference),
            "multi_process": bool(multi_process),
            "workers": inference_workers_config,
            "workers_alive": inference_workers_alive,
        },
        "algo_instance_states": algo_instance_states,
    }
    if not lite:
        from app.analysis.engines.factory import EngineFactory
        from app.analysis.motion import MotionDetector
        data["engines"] = EngineFactory.list_engines()
        data["motion_available"] = MotionDetector.is_available()
    _set_cached_status(data, lite=lite)
    return data


def invalidate_analysis_status_cache():
    """供启停分析、热更新后主动失效缓存，确保下次请求拿到最新状态。"""
    _STATUS_CACHE["lite"]["data"] = None
    _STATUS_CACHE["full"]["data"] = None


def control_index(request):
    return render(request, 'app/control/index.html', {})


def control_openIndex(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = []
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            stream_id = request.GET.get('stream_id')
            qs = _control_queryset(stream_id) if stream_id else _control_queryset()
            data = [_control_to_dict(z) for z in qs]
            ret = True
            msg = LANG_VIEWS_T(request, "msg_success")
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def control_openPageData(request):
    """布控页一次性加载：区域列表 + 摄像头下拉 + 分析概览"""
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {}
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                stream_id = request.GET.get('stream_id')
                zones = [_control_to_dict(z) for z in _control_queryset(stream_id)]
                streams = list(
                    StreamModel.objects.order_by("-id").values("id", "app", "name", "code", "nickname")
                )
                analysis = build_analysis_status_data(lite=True)
                alarm_qs = AlarmModel.objects.filter(event_type__in=CONTROL_ALARM_EVENT_TYPES)
                if stream_id:
                    alarm_qs = alarm_qs.filter(stream_id=int(stream_id))
                data = {
                    "zones": zones,
                    "streams": streams,
                    "analysis": analysis,
                    "recent_alarm_count": alarm_qs.count(),
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


def control_openAdd(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                stream_id = int(params.get("stream_id", 0))
                if stream_id <= 0:
                    app = (params.get("stream_app") or params.get("app") or "").strip()
                    name = (params.get("stream_name") or params.get("name") or "").strip()
                    if app and name:
                        stream = StreamModel.objects.get(app=app, name=name)
                        stream_id = stream.id
                    else:
                        raise ValueError(LANG_VIEWS_T(request, "zone_form_incomplete"))
                else:
                    stream = StreamModel.objects.get(id=stream_id)
                algo_ids_req = params.get("algorithm_ids") or []
                if isinstance(algo_ids_req, str):
                    try:
                        import json as _json2
                        algo_ids_req = _json2.loads(algo_ids_req)
                    except Exception:
                        algo_ids_req = [s for s in algo_ids_req.split(",") if s]
                if not algo_ids_req:
                    raise ValueError(LANG_VIEWS_T(request, "zone_algo_required"))
                detect_interval_sec, detect_frames = _parse_control_detect_rate(params)
                zone = ZoneModel(
                    stream=stream,
                    name=params.get("name", "").strip(),
                    coordinates=params.get("coordinates", "[]"),
                    is_required=int(params.get("is_required", 0)),
                    loiter_threshold=int(params.get("loiter_threshold", 0)),
                    detect_interval_sec=detect_interval_sec,
                    detect_frames=detect_frames,
                    color=params.get("color", "#169F85"),
                    line_a=params.get("line_a", ""),
                    line_b=params.get("line_b", ""),
                    density_threshold=int(params.get("density_threshold", 0) or 0),
                )
                zone.save()
                algo_ids = params.get("algorithm_ids") or []
                if isinstance(algo_ids, str):
                    try:
                        import json as _json
                        algo_ids = _json.loads(algo_ids)
                    except Exception:
                        algo_ids = [s for s in algo_ids.split(",") if s]
                if algo_ids:
                    from app.models import BizAlgorithmModel
                    qs = BizAlgorithmModel.objects.filter(id__in=[int(x) for x in algo_ids], state=1)
                    zone.algorithms.set(qs)
                try:
                    from app.analysis.manager import AnalysisManager
                    AnalysisManager().reload_zones(stream_id)
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


def control_openEdit(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                zid = int(params.get("id", 0))
                z = ZoneModel.objects.get(id=zid)
                if "name" in params:
                    z.name = params["name"].strip()
                if "coordinates" in params:
                    z.coordinates = params["coordinates"]
                if "is_required" in params:
                    z.is_required = int(params["is_required"])
                if "loiter_threshold" in params:
                    z.loiter_threshold = int(params["loiter_threshold"])
                if "detect_interval_sec" in params or "detect_frames" in params:
                    interval, frames = _parse_control_detect_rate(params)
                    z.detect_interval_sec = interval
                    z.detect_frames = frames
                if "color" in params:
                    z.color = params["color"]
                if "line_a" in params:
                    z.line_a = params.get("line_a", "")
                if "line_b" in params:
                    z.line_b = params.get("line_b", "")
                if "density_threshold" in params:
                    z.density_threshold = int(params.get("density_threshold", 0) or 0)
                z.save()
                if "algorithm_ids" in params:
                    algo_ids = params.get("algorithm_ids") or []
                    if isinstance(algo_ids, str):
                        try:
                            import json as _json
                            algo_ids = _json.loads(algo_ids)
                        except Exception:
                            algo_ids = [s for s in algo_ids.split(",") if s]
                    if not algo_ids:
                        raise ValueError(LANG_VIEWS_T(request, "zone_algo_required"))
                    from app.models import BizAlgorithmModel
                    qs = BizAlgorithmModel.objects.filter(id__in=[int(x) for x in algo_ids], state=1)
                    z.algorithms.set(qs)
                try:
                    from app.analysis.manager import AnalysisManager
                    AnalysisManager().reload_zones(z.stream_id)
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


def control_openDel(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                zid = int(params.get("id", 0))
                z = ZoneModel.objects.get(id=zid)
                sid = z.stream_id
                z.delete()
                try:
                    from app.analysis.manager import AnalysisManager
                    AnalysisManager().reload_zones(sid)
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


def control_openRecentAlarms(request):
    """返回近期报警事件，供布控页展示"""
    from app.views.AnalysisView import _timeline_alarm_fields
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = []
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                import json as _json
                stream_id = request.GET.get('stream_id')
                limit = int(request.GET.get('limit', 12))
                base_qs = AlarmModel.objects.all()
                if stream_id:
                    base_qs = base_qs.filter(stream_id=int(stream_id))
                zone_qs = base_qs.filter(event_type__in=CONTROL_ALARM_EVENT_TYPES).order_by('-timestamp')[:limit]
                items = list(zone_qs)
                out = []
                for t in items[:limit]:
                    try:
                        meta = _json.loads(t.metadata) if t.metadata else {}
                    except Exception:
                        meta = {}
                    out.append({
                        "id": t.id,
                        "stream_id": t.stream_id,
                        "stream_name": (t.stream.nickname if t.stream else ""),
                        "event_type": t.event_type,
                        "label": meta.get("label", ""),
                        "zone_id": meta.get("zone_id"),
                        "box": meta.get("box"),
                        "duration": meta.get("duration"),
                        "snapshot_path": meta.get("snapshot_path", ""),
                        "timestamp": str(t.timestamp),
                        **_timeline_alarm_fields(t, meta),
                    })
                data = out
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})
