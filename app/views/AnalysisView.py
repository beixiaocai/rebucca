# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""Rebucca · 分析模块 Web 层

页面：
- /control/index           布控管理（见 ControlView）

API：
- /alarm/openIndex/openDel/openBatchDel/openClearAlarms
- /analysis/openStatus/openStart/openStop/openReloadZones
"""
from app.views.ViewsBase import *
from app.utils.Utils import buildPageLabels
from django.shortcuts import render
import json
from datetime import datetime

from app.models import StreamModel, ZoneModel, AlarmModel


def _parse_page_params(request, default_ps=12):
    page = request.GET.get('p', 1)
    page_size = request.GET.get('ps', default_ps)
    try:
        page = int(page)
        if page < 1:
            page = 1
    except Exception:
        page = 1
    try:
        page_size = int(page_size)
        if page_size < 1:
            page_size = default_ps
        elif page_size > 100:
            page_size = 100
    except Exception:
        page_size = default_ps
    return page, page_size


def _build_page_data(request, page, page_size, count):
    page_num = int(count / page_size)
    if count % page_size > 0:
        page_num += 1
    if page_num < 1:
        page_num = 1
    if page > page_num:
        page = page_num
    page_labels = buildPageLabels(page=page, page_num=page_num, lang=f_parseRequestLang(request))
    return {
        "page": page,
        "page_size": page_size,
        "page_num": page_num,
        "count": count,
        "pageLabels": page_labels,
    }


def _alarm_abs_path(rel_path):
    """将 metadata 中的相对路径（相对 static/）转为绝对路径"""
    if not rel_path:
        return ""
    try:
        from django.conf import settings
        base = str(getattr(settings, "BASE_DIR", ""))
        if base:
            return os.path.join(base, "static", rel_path)
    except Exception:
        pass
    return ""


def _delete_snapshot_file(rel_path):
    """删除单个快照文件（相对 static/ 的路径）"""
    p = _alarm_abs_path(rel_path)
    if p and os.path.isfile(p):
        try:
            os.remove(p)
            return True
        except Exception:
            return False
    return False


# ===================== Alarm =====================

def _alarm_to_dict(a):
    """将 AlarmModel 转为前端字典"""
    try:
        meta = json.loads(a.metadata) if a.metadata else {}
    except Exception:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    reason = meta.get("alarm_reason") or a.description or ""
    return {
        "id": a.id,
        "stream_id": a.stream_id,
        "stream_name": (a.stream.nickname if a.stream else ""),
        "event_type": a.event_type,
        "timestamp": str(a.timestamp),
        "metadata": a.metadata,
        "biz_algorithm_id": meta.get("biz_algorithm_id"),
        "biz_algorithm_name": meta.get("biz_algorithm_name") or "",
        "alarm_reason": reason,
        "zone_name": meta.get("zone_name") or "",
        "snapshot_path": meta.get("snapshot_path") or "",
        "description": reason or a.description or "",
    }


def alarm_openIndex(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = []
    page_data = {}
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            page, page_size = _parse_page_params(request, default_ps=20)
            qs = AlarmModel.objects.all().order_by('-id')
            stream_id = request.GET.get('stream_id')
            if stream_id:
                qs = qs.filter(stream_id=int(stream_id))
            event_type = request.GET.get('event_type')
            if event_type:
                qs = qs.filter(event_type=event_type)
            count = qs.count()
            skip = (page - 1) * page_size
            data = [_alarm_to_dict(a) for a in qs[skip:skip + page_size]]
            page_data = _build_page_data(request, page, page_size, count)
            ret = True
            msg = LANG_VIEWS_T(request, "msg_success")
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data, "pageData": page_data})


def alarm_openDel(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                aid = int(params.get("id", 0))
                if aid <= 0:
                    raise ValueError(LANG_VIEWS_T(request, "msg_invalid_parameter"))
                obj = AlarmModel.objects.filter(id=aid).first()
                if not obj:
                    raise ValueError(LANG_VIEWS_T(request, "msg_not_found"))
                try:
                    meta = json.loads(obj.metadata) if obj.metadata else {}
                    snap = meta.get("snapshot_path", "")
                    if snap:
                        _delete_snapshot_file(snap)
                except Exception:
                    pass
                obj.delete()
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def alarm_openBatchDel(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    deleted = 0
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                ids_raw = params.get("ids", "[]")
                ids = json.loads(ids_raw) if isinstance(ids_raw, str) else ids_raw
                if not isinstance(ids, list) or not ids:
                    raise ValueError(LANG_VIEWS_T(request, "msg_invalid_parameter"))
                qs = AlarmModel.objects.filter(id__in=ids)
                for obj in qs:
                    try:
                        meta = json.loads(obj.metadata) if obj.metadata else {}
                        snap = meta.get("snapshot_path", "")
                        if snap:
                            _delete_snapshot_file(snap)
                    except Exception:
                        pass
                deleted, _ = qs.delete()
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": {"deleted": deleted}})


def alarm_openClearAlarms(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    deleted = 0
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                qs = AlarmModel.objects.all()
                for obj in qs:
                    try:
                        meta = json.loads(obj.metadata) if obj.metadata else {}
                        snap = meta.get("snapshot_path", "")
                        if snap:
                            _delete_snapshot_file(snap)
                    except Exception:
                        pass
                deleted, _ = qs.delete()
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": {"deleted": deleted}})


# ===================== 分析控制 =====================

def analysis_openStatus(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {}
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                lite = str(request.GET.get("lite", "")).lower() in ("1", "true", "yes")
                from app.views.ControlView import build_analysis_status_data
                data = build_analysis_status_data(lite=lite)
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def analysis_openStart(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                sid = int(params.get("stream_id", 0))
                if sid <= 0:
                    raise ValueError(LANG_VIEWS_T(request, "msg_invalid_parameter"))
                enabled = ZoneModel.objects.filter(stream_id=sid, state=1).exists()
                if not enabled:
                    raise ValueError(LANG_VIEWS_T(request, "zone_analysis_need_enabled"))
                stream = StreamModel.objects.get(id=sid)
                from app.analysis.manager import AnalysisManager
                ok, info = AnalysisManager().start(stream)
                ret = ok
                msg = info
                if ok:
                    from app.views.ControlView import invalidate_analysis_status_cache
                    invalidate_analysis_status_cache()
                    msg = LANG_VIEWS_T(request, "zone_analysis_started")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def analysis_openStop(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                sid = int(params.get("stream_id", 0))
                from app.analysis.manager import AnalysisManager
                ok, info = AnalysisManager().stop(sid)
                ret = ok
                msg = info if not ok else LANG_VIEWS_T(request, "zone_analysis_stopped")
                if ok:
                    from app.views.ControlView import invalidate_analysis_status_cache
                    invalidate_analysis_status_cache()
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def analysis_openReloadZones(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                sid = int(params.get("stream_id", 0))
                from app.analysis.manager import AnalysisManager
                ok = AnalysisManager().reload_zones(sid)
                ret = ok
                msg = LANG_VIEWS_T(request, "msg_success") if ok else "pipeline not running"
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def analysis_openUpdateInferenceConfig(request):
    """热更新推理引擎配置（不持久化到 config.json）。
    POST 参数：
      - shared: 0/1 切换共享推理开关
      - workers: int 调整共享推理 worker 数
    两者至少传一个；切换 shared 会重启所有运行中的 pipeline。
    """
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                shared = params.get("shared", None)
                workers = params.get("workers", None)
                if shared is None and workers is None:
                    raise ValueError("至少需要传 shared 或 workers 参数")
                from app.analysis.manager import AnalysisManager
                ok, info = AnalysisManager().set_inference_config(
                    shared=shared, workers=workers)
                ret = ok
                msg = info
                if ok:
                    from app.views.ControlView import invalidate_analysis_status_cache
                    invalidate_analysis_status_cache()
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def analysis_openToggleAlgoInstance(request):
    """切换业务算法的实例化开关（内存，重启丢失，立即生效）。
    POST 参数：
      - algorithm_id: int 业务算法绑定的小模型 ID
      - enabled: 0/1
    """
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                algo_id = int(params.get("algorithm_id", 0))
                enabled = int(params.get("enabled", 1)) == 1
                if algo_id <= 0:
                    raise ValueError(LANG_VIEWS_T(request, "msg_invalid_parameter"))
                from app.analysis.manager import AnalysisManager
                ok, info = AnalysisManager().set_algo_instance_enabled(algo_id, enabled)
                ret = ok
                msg = info
                if ok:
                    from app.views.ControlView import invalidate_analysis_status_cache
                    invalidate_analysis_status_cache()
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def analysis_openRestartAlgoInstance(request):
    """重启使用指定算法的所有 pipeline（重新加载引擎）。
    POST 参数：
      - algorithm_id: int 小模型 ID
    """
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                algo_id = int(params.get("algorithm_id", 0))
                if algo_id <= 0:
                    raise ValueError(LANG_VIEWS_T(request, "msg_invalid_parameter"))
                from app.analysis.manager import AnalysisManager
                ok, info = AnalysisManager().restart_algo_instance(algo_id)
                ret = ok
                msg = info
                if ok:
                    from app.views.ControlView import invalidate_analysis_status_cache
                    invalidate_analysis_status_cache()
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def analysis_openRestartInferencePool(request):
    """重启整个推理池（清除所有引擎缓存）。"""
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                from app.analysis.manager import AnalysisManager
                ok, info = AnalysisManager().restart_inference_pool()
                ret = ok
                msg = info
                if ok:
                    from app.views.ControlView import invalidate_analysis_status_cache
                    invalidate_analysis_status_cache()
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})
