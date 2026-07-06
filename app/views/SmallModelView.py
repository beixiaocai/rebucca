# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""小模型管理 Web 层

页面：/smallmodel/index
API：
- /smallmodel/openIndex            GET 列表
- /smallmodel/openAdd              POST 新增
- /smallmodel/openEdit             POST 编辑
- /smallmodel/openDel              POST 删除
- /smallmodel/openUploadModel      POST(multipart) 上传模型文件
- /smallmodel/openProbe            POST 探测模型 shape/labels
- /smallmodel/openEngines          GET 本机可用引擎列表
- /smallmodel/openSetActive        POST 设为默认算法
- /smallmodel/openAssignStreams    POST 把算法分配给多个摄像头
"""
import os
import json
import uuid

from app.views.ViewsBase import *
from app.utils.Utils import buildPageLabels
from django.shortcuts import render
from django.conf import settings
from django.http import HttpResponse

from app.models import StreamModel, AlgorithmModel


def _algo_to_dict(a, include_streams=False):
    labels = a.labels or '[]'
    try:
        labels_list = json.loads(labels) if isinstance(labels, str) else labels
    except Exception:
        labels_list = []
    d = {
        "id": a.id,
        "name": a.name,
        "algorithm_type": a.algorithm_type,
        "task_type": a.task_type,
        "inference_engine": a.inference_engine,
        "device": a.device,
        "model_file": a.model_file,
        "model_file_size": a.model_file_size,
        "input_width": a.input_width,
        "input_height": a.input_height,
        "conf_threshold": a.conf_threshold,
        "iou_threshold": a.iou_threshold,
        "labels": labels_list,
        "is_default": a.is_default,
        "state": a.state,
        "create_time": str(a.create_time),
        "stream_count": a.streams.count() if include_streams else 0,
    }
    return d


def _algo_parse_page_params(request, default_ps=10):
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


def _algo_build_page_data(request, page, page_size, count):
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


def smallmodel_openIndex(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = []
    page_data = {}
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parseGetParams(request)
            page, page_size = _algo_parse_page_params(request, default_ps=10)
            qs = AlgorithmModel.objects.all().order_by('-is_default', '-id')
            engine = params.get('engine', '').strip()
            if engine:
                qs = qs.filter(inference_engine=engine)
            state = params.get('state', '').strip()
            if state != '':
                qs = qs.filter(state=int(state))
            count = qs.count()
            skip = (page - 1) * page_size
            data = [_algo_to_dict(a, include_streams=True) for a in qs[skip:skip + page_size]]
            page_data = _algo_build_page_data(request, page, page_size, count)
            ret = True
            msg = LANG_VIEWS_T(request, "msg_success")
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data, "pageData": page_data})


def _parse_algo_params(params):
    """从 POST 参数构造 AlgorithmModel 字段 dict"""
    out = {}
    if "name" in params:
        out["name"] = (params.get("name") or "").strip()
    if "algorithm_type" in params:
        out["algorithm_type"] = (params.get("algorithm_type") or "yolo8").strip()
    if "task_type" in params:
        out["task_type"] = (params.get("task_type") or "detect").strip()
    if "inference_engine" in params:
        out["inference_engine"] = (params.get("inference_engine") or "yolo_pytorch").strip()
    if "device" in params:
        out["device"] = (params.get("device") or "cpu").strip()
    if "model_file" in params:
        out["model_file"] = (params.get("model_file") or "").strip()
    if "input_width" in params:
        try:
            out["input_width"] = int(params.get("input_width", 640))
        except Exception:
            pass
    if "input_height" in params:
        try:
            out["input_height"] = int(params.get("input_height", 640))
        except Exception:
            pass
    if "conf_threshold" in params:
        try:
            out["conf_threshold"] = float(params.get("conf_threshold", 0.4))
        except Exception:
            pass
    if "iou_threshold" in params:
        try:
            out["iou_threshold"] = float(params.get("iou_threshold", 0.5))
        except Exception:
            pass
    if "labels" in params:
        lb = params.get("labels")
        if isinstance(lb, list):
            out["labels"] = json.dumps([str(x).strip() for x in lb if str(x).strip()], ensure_ascii=False)
        elif isinstance(lb, str):
            # 英文逗号分隔：支持中文类别（只要用英文逗号隔开就是一个类别）
            try:
                arr = json.loads(lb)
                if isinstance(arr, list):
                    out["labels"] = json.dumps([str(x).strip() for x in arr if str(x).strip()], ensure_ascii=False)
                else:
                    out["labels"] = "[]"
            except Exception:
                items = [s.strip() for s in lb.split(",") if s.strip()]
                if items:
                    out["labels"] = json.dumps(items, ensure_ascii=False)
                else:
                    out["labels"] = "[]"
    if "state" in params:
        try:
            out["state"] = int(params.get("state", 1))
        except Exception:
            pass
    if "is_default" in params:
        try:
            out["is_default"] = int(params.get("is_default", 0))
        except Exception:
            pass
    if "model_file_size" in params:
        try:
            out["model_file_size"] = int(params.get("model_file_size", 0))
        except Exception:
            pass
    return out


def smallmodel_index(request):
    return render(request, 'app/smallmodel/index.html', {})


def smallmodel_test(request):
    return render(request, 'app/smallmodel/test.html', {})


def smallmodel_openDetail(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {}
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parseGetParams(request)
            try:
                aid = int(params.get("id", 0))
                a = AlgorithmModel.objects.get(id=aid)
                data = _algo_to_dict(a, include_streams=True)
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def _test_upload_dir():
    from app.services.algorithm_test_service import upload_dir
    return upload_dir()


def smallmodel_openTestStart(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {}
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                aid = int(request.POST.get("algorithm_id", 0) or 0)
                a = AlgorithmModel.objects.get(id=aid)
                f = request.FILES.get("file")
                if not f:
                    msg = LANG_VIEWS_T(request, "alg_no_file")
                elif not a.model_file:
                    msg = LANG_VIEWS_T(request, "alg_no_model_file")
                else:
                    ext = os.path.splitext(f.name)[1].lower()
                    allowed = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v")
                    if ext not in allowed:
                        msg = LANG_VIEWS_T(request, "alg_unsupported_ext") + ": " + ext
                    else:
                        fname = "%s_%s%s" % (uuid.uuid4().hex[:12], aid, ext)
                        dest = os.path.join(_test_upload_dir(), fname)
                        with open(dest, "wb") as out:
                            for chunk in f.chunks():
                                out.write(chunk)
                        from app.services.algorithm_test_service import start_test
                        task_id = start_test(a, dest, f.name)
                        data = {"task_id": task_id}
                        ret = True
                        msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def smallmodel_openTestStatus(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {}
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parseGetParams(request)
            task_id = (params.get("task_id") or "").strip()
            if not task_id:
                msg = "missing task_id"
            else:
                from app.services.algorithm_test_service import get_task
                t = get_task(task_id)
                if not t:
                    msg = "task not found"
                else:
                    data = {
                        "task_id": t.get("id"),
                        "status": t.get("status"),
                        "progress": t.get("progress", 0),
                        "message": t.get("message", ""),
                        "report": t.get("report"),
                        "output_url": t.get("output_url", ""),
                        "output_type": t.get("output_type", ""),
                        "error": t.get("error", ""),
                    }
                    ret = True
                    msg = LANG_VIEWS_T(request, "msg_success")
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def smallmodel_openTestOutput(request):
    """返回算法测试渲染结果（图片/视频），避免运行时生成的 static 文件无法通过 /static/ 访问。"""
    if request.method != 'GET':
        return HttpResponse(b"method not allowed", status=405)
    __check_ret, __check_msg = f_checkRequestSafe(request)
    if not __check_ret:
        return HttpResponse(__check_msg.encode("utf-8"), status=403)
    params = f_parseGetParams(request)
    task_id = (params.get("task_id") or "").strip()
    from app.services.algorithm_test_service import resolve_output_file
    fp, ctype = resolve_output_file(task_id)
    if not fp:
        return HttpResponse(b"not found", status=404)
    try:
        with open(fp, "rb") as f:
            data = f.read()
    except Exception:
        return HttpResponse(b"read error", status=500)
    resp = HttpResponse(data, content_type=ctype)
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp["Content-Disposition"] = 'inline; filename="%s"' % os.path.basename(fp)
    return resp


def smallmodel_openTestClearTemp(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {}
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                from app.services.algorithm_test_service import clear_temp_files
                data = clear_temp_files()
                ret = True
                msg = LANG_VIEWS_T(request, "alg_test_clear_ok")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def smallmodel_openAdd(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                fields = _parse_algo_params(params)
                if not fields.get("name"):
                    msg = LANG_VIEWS_T(request, "alg_name_required")
                else:
                    a = AlgorithmModel.objects.create(**fields)
                    if fields.get("is_default") == 1:
                        AlgorithmModel.objects.exclude(id=a.id).update(is_default=0)
                    ret = True
                    msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def smallmodel_openEdit(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                aid = int(params.get("id", 0))
                a = AlgorithmModel.objects.get(id=aid)
                fields = _parse_algo_params(params)
                for k, v in fields.items():
                    setattr(a, k, v)
                a.save()
                if a.is_default == 1:
                    AlgorithmModel.objects.exclude(id=a.id).update(is_default=0)
                # 热更新：若该算法被某路正在跑的摄像头使用，重载其 pipeline
                try:
                    from app.analysis.manager import AnalysisManager
                    mgr = AnalysisManager()
                    for s in a.streams.all():
                        if mgr.is_running(s.id):
                            mgr.stop(s.id)
                            mgr.start(s)
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


def smallmodel_openDel(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                aid = int(params.get("id", 0))
                a = AlgorithmModel.objects.get(id=aid)
                # 先收集使用该算法的摄像头（解绑前查询，否则 update 后反向关系为空）
                affected_streams = list(a.streams.values_list('id', flat=True))
                # 检查是否有业务算法引用此小模型
                from app.models import BizAlgorithmModel
                ref_count = BizAlgorithmModel.objects.filter(small_model_id=aid).count()
                if ref_count > 0:
                    raise ValueError(LANG_VIEWS_T(request, "smallmodel_in_use_by_biz"))
                # 停止使用该算法的 pipeline（必须在解绑前完成）
                try:
                    from app.analysis.manager import AnalysisManager
                    mgr = AnalysisManager()
                    for sid in affected_streams:
                        if mgr.is_running(sid):
                            mgr.stop(sid)
                except Exception:
                    pass
                # 解绑摄像头
                StreamModel.objects.filter(algorithm_id=aid).update(algorithm=None)
                a.delete()
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def _models_dir():
    from app.analysis.worker_pool import get_weight_dir
    return get_weight_dir()


def smallmodel_openUploadModel(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {}
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                f = request.FILES.get("file")
                if not f:
                    msg = LANG_VIEWS_T(request, "alg_no_file")
                else:
                    ext = os.path.splitext(f.name)[1].lower()
                    allowed = (".onnx", ".pt", ".xml", ".bin", ".engine", ".model", ".yaml", ".labels", ".names")
                    if ext and ext not in allowed:
                        msg = LANG_VIEWS_T(request, "alg_unsupported_ext") + ": " + ext
                    else:
                        # 文件名：年月日时分秒_原文件名（保留原名称，前面拼时间戳避免冲突）
                        from datetime import datetime
                        ts = datetime.now().strftime("%Y%m%d%H%M%S")
                        # 安全处理原文件名：去掉路径分隔符，保留扩展名
                        raw_name = os.path.basename(f.name)
                        # 限制总长度，避免文件名过长
                        name_part = os.path.splitext(raw_name)[0]
                        if len(name_part) > 60:
                            name_part = name_part[:60]
                        fname = "%s_%s%s" % (ts, name_part, ext)
                        dest = os.path.join(_models_dir(), fname)
                        with open(dest, "wb") as out:
                            for chunk in f.chunks():
                                out.write(chunk)
                        size = os.path.getsize(dest)
                        # 清理旧模型文件：未被任何启用算法引用的文件
                        try:
                            _cleanup_unused_model_files(exclude=fname)
                        except Exception as e:
                            import logging
                            logging.getLogger("app").warning("清理旧模型文件失败: %s" % str(e))
                        # 相对路径
                        data = {
                            "model_file": fname,
                            "model_file_size": size,
                            "filename": f.name,
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


def _cleanup_unused_model_files(exclude=None):
    """清理未被任何启用算法引用的模型文件（保留 exclude 指定的刚上传文件）。"""
    models_dir = _models_dir()
    if not os.path.isdir(models_dir):
        return 0
    # 收集所有算法（含禁用）引用的模型文件名，避免删除被禁用算法的模型文件
    used_files = set()
    for a in AlgorithmModel.objects.all():
        if a.model_file:
            used_files.add(os.path.basename(a.model_file))
    removed = 0
    allowed_ext = (".onnx", ".pt", ".xml", ".bin", ".engine", ".model", ".yaml", ".labels", ".names")
    for fn in os.listdir(models_dir):
        fp = os.path.join(models_dir, fn)
        if not os.path.isfile(fp):
            continue
        ext = os.path.splitext(fn)[1].lower()
        if ext not in allowed_ext:
            continue
        if exclude and fn == exclude:
            continue
        if fn in used_files:
            continue
        try:
            os.remove(fp)
            removed += 1
        except Exception:
            pass
    return removed


def smallmodel_openProbe(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {}
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                engine_name = (params.get("engine") or "onnxruntime").strip()
                model_file = (params.get("model_file") or "").strip()
                if not model_file:
                    msg = LANG_VIEWS_T(request, "alg_no_model_file")
                else:
                    from app.analysis.worker_pool import resolve_model_path
                    abs_path = resolve_model_path(model_file)
                    if not abs_path:
                        msg = LANG_VIEWS_T(request, "alg_no_model_file")
                    else:
                        from app.analysis.engines.factory import EngineFactory, list_engines
                        from app.analysis.engines.base import EngineNotAvailableError
                        try:
                            eng = EngineFactory.create(engine_name, model_file=abs_path)
                            data = eng.probe()
                            ret = True
                            msg = LANG_VIEWS_T(request, "msg_success")
                        except EngineNotAvailableError as e:
                            msg = LANG_VIEWS_T(request, "engine_not_installed") + ": " + str(e)
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def smallmodel_openEngines(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = []
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                from app.analysis.engines.factory import list_engines, device_options
                data = list_engines()
                # 附带 device_options 便于前端直接渲染
                for item in data:
                    item["device_options"] = device_options(item["name"])
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def smallmodel_openSetActive(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                aid = int(params.get("id", 0))
                a = AlgorithmModel.objects.get(id=aid)
                AlgorithmModel.objects.exclude(id=aid).update(is_default=0)
                a.is_default = 1
                a.save()
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def smallmodel_openAssignStreams(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                aid = int(params.get("algorithm_id", 0))
                a = AlgorithmModel.objects.get(id=aid)
                stream_ids = params.get("stream_ids") or []
                if isinstance(stream_ids, str):
                    try:
                        stream_ids = json.loads(stream_ids)
                    except Exception:
                        stream_ids = [s for s in stream_ids.split(",") if s]
                # 先解绑所有当前使用该算法的摄像头
                StreamModel.objects.filter(algorithm_id=aid).update(algorithm=None)
                # 再绑新选的
                restarted = []
                for sid in stream_ids:
                    try:
                        s = StreamModel.objects.get(id=int(sid))
                        # 若该路正在跑，需重启以应用新算法
                        try:
                            from app.analysis.manager import AnalysisManager
                            if AnalysisManager().is_running(s.id):
                                AnalysisManager().stop(s.id)
                                restarted.append(s.id)
                        except Exception:
                            pass
                        s.algorithm = a
                        s.save()
                    except Exception:
                        pass
                # 重启刚才停掉的
                for sid in restarted:
                    try:
                        s = StreamModel.objects.get(id=sid)
                        AnalysisManager().start(s)
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
