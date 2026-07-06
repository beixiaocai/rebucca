# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""
NvrView 模块 — 24/7 录像 + FFmpeg 截图
"""
import os
import time
import subprocess
from datetime import timedelta
from app.views.ViewsBase import *
from app.utils.Utils import buildPageLabels
from app.utils.LanguageUtils import LANG_VIEWS_T
from django.http import HttpResponse
from django.shortcuts import render


def record_index(request):
    params = f_parseGetParams(request)
    stream_id = int(params.get("stream_id", 0) or 0)
    stream_name = ""
    record_enable = 0
    is_recording = False
    if stream_id:
        from app.models import StreamModel
        stream = StreamModel.objects.filter(id=stream_id).first()
        if stream:
            stream_name = stream.nickname or stream.name or ("#" + str(stream_id))
            record_enable = int(stream.record_enable or 0)
            try:
                from app.recording.manager import get_recording_manager
                is_recording = get_recording_manager().is_recording(stream_id)
            except Exception:
                pass
        else:
            stream_id = 0
    if not stream_id:
        from django.shortcuts import redirect
        return redirect("/stream/index")
    return render(request, "app/record/index.html", {
        "stream_id": stream_id,
        "stream_name": stream_name,
        "record_enable": record_enable,
        "is_recording": is_recording,
    })


def _sync_stream_recording(stream):
    """根据 record_enable 与转发状态同步录像进程（关闭录像时停止进程，保留历史文件）"""
    try:
        from app.recording.manager import get_recording_manager
        mgr = get_recording_manager()
        if int(stream.record_enable or 0) == 1 and int(stream.forward_state or 0) == 1:
            mgr.start_stream(stream)
        else:
            mgr.stop_stream(stream.id)
    except Exception as e:
        g_logger.warning("sync recording stream=%s err: %s" % (stream.id, str(e)))


def _get_stream(params):
    from app.models import StreamModel
    sid = int(params.get("stream_id") or params.get("id") or 0)
    app = (params.get("app") or "").strip()
    name = (params.get("name") or "").strip()
    if sid:
        return StreamModel.objects.filter(id=sid).first()
    if app and name:
        return StreamModel.objects.filter(app=app, name=name).first()
    return None


def api_openVideoIsRecording(request):
    if request.method != 'GET':
        return f_responseJson({"code": 0, "msg": LANG_VIEWS_T(request, "msg_method_not_supported")})
    __check_ret, __check_msg = f_checkRequestSafe(request)
    if not __check_ret:
        return f_responseJson({"code": 0, "msg": __check_msg})
    params = f_parseGetParams(request)
    stream = _get_stream(params)
    if not stream:
        return f_responseJson({"code": 0, "msg": "stream not found"})
    from app.recording.manager import get_recording_manager
    mgr = get_recording_manager()
    return f_responseJson({
        "code": 1000, "msg": "ok",
        "is_recording": mgr.is_recording(stream.id),
        "record_enable": stream.record_enable,
    })


def api_openStartRecordVideo(request):
    if request.method != 'POST':
        return f_responseJson({"code": 0, "msg": LANG_VIEWS_T(request, "msg_method_not_supported")})
    __check_ret, __check_msg = f_checkRequestSafe(request)
    if not __check_ret:
        return f_responseJson({"code": 0, "msg": __check_msg})
    params = f_parsePostParams(request)
    stream = _get_stream(params)
    if not stream:
        return f_responseJson({"code": 0, "msg": "stream not found"})
    stream.record_enable = 1
    stream.save(update_fields=["record_enable"])
    from app.recording.manager import get_recording_manager
    ok, info = get_recording_manager().start_stream(stream)
    return f_responseJson({"code": 1000 if ok else 0, "msg": info})


def api_openStopRecordVideo(request):
    if request.method != 'POST':
        return f_responseJson({"code": 0, "msg": LANG_VIEWS_T(request, "msg_method_not_supported")})
    __check_ret, __check_msg = f_checkRequestSafe(request)
    if not __check_ret:
        return f_responseJson({"code": 0, "msg": __check_msg})
    params = f_parsePostParams(request)
    stream = _get_stream(params)
    if not stream:
        return f_responseJson({"code": 0, "msg": "stream not found"})
    stream.record_enable = 0
    stream.save(update_fields=["record_enable"])
    from app.recording.manager import get_recording_manager
    ok, info = get_recording_manager().stop_stream(stream.id)
    return f_responseJson({"code": 1000 if ok else 0, "msg": info})


def _scan_disk_recordings(stream_id=None):
    """从磁盘扫描录像分段（FFmpeg segment 输出）"""
    items = []
    try:
        base = g_config.storageRecordDir
    except Exception:
        return items
    if not base or not os.path.isdir(base):
        return items
    for root, _dirs, files in os.walk(base):
        for fn in files:
            if not fn.lower().endswith((".mp4", ".ts", ".mkv")):
                continue
            fp = os.path.join(root, fn)
            try:
                st = os.stat(fp)
            except Exception:
                continue
            sid = 0
            parts = fn.split("_", 1)
            if parts and parts[0].isdigit():
                sid = int(parts[0])
            if stream_id and sid != int(stream_id):
                continue
            from datetime import datetime
            start = datetime.fromtimestamp(st.st_mtime)
            items.append({
                "id": 0,
                "stream_id": sid,
                "stream_name": "",
                "file_path": fp,
                "start_time": str(start),
                "end_time": str(start),
                "duration": 0,
                "file_size": st.st_size,
                "file_exists": True,
            })
    items.sort(key=lambda x: x["start_time"], reverse=True)
    return items


def api_openRecordIndex(request):
    """分页列出录像分段"""
    if request.method != 'GET':
        return f_responseJson({"code": 0, "msg": LANG_VIEWS_T(request, "msg_method_not_supported")})
    __check_ret, __check_msg = f_checkRequestSafe(request)
    if not __check_ret:
        return f_responseJson({"code": 0, "msg": __check_msg})
    from app.models import RecordingModel, StreamModel
    params = f_parseGetParams(request)
    page = int(params.get('p', 1) or 1)
    ps = int(params.get('ps', 20) or 20)
    sid = params.get('stream_id')
    stream_filter = int(sid) if sid else None

    qs = RecordingModel.objects.all().order_by('-start_time')
    if stream_filter:
        qs = qs.filter(stream_id=stream_filter)
    db_rows = list(qs.select_related('stream')[:500])
    data = []
    seen_paths = set()
    for r in db_rows:
        seen_paths.add(r.file_path)
        data.append({
            "id": r.id,
            "stream_id": r.stream_id,
            "stream_name": (r.stream.nickname if r.stream else ""),
            "file_path": r.file_path,
            "start_time": str(r.start_time),
            "end_time": str(r.end_time),
            "duration": r.duration,
            "file_size": r.file_size,
            "file_exists": os.path.isfile(r.file_path) if r.file_path else False,
        })
    for item in _scan_disk_recordings(stream_filter):
        if item["file_path"] in seen_paths:
            continue
        if item["stream_id"]:
            try:
                s = StreamModel.objects.filter(id=item["stream_id"]).first()
                if s:
                    item["stream_name"] = s.nickname or s.name
            except Exception:
                pass
        data.append(item)
    data.sort(key=lambda x: x.get("start_time", ""), reverse=True)
    count = len(data)
    skip = (page - 1) * ps
    page_rows = data[skip:skip + ps]
    page_num = int(count / ps) + (1 if count % ps else 0)
    page_data = {
        "page": page, "page_size": ps, "page_num": max(1, page_num), "count": count,
        "pageLabels": buildPageLabels(page=page, page_num=max(1, page_num), lang=f_parseRequestLang(request)),
    }
    return f_responseJson({"code": 1000, "msg": "ok", "data": page_rows, "pageData": page_data})


def api_openRecordFile(request):
    if request.method != 'GET':
        return HttpResponse(b"method not allowed", status=405)
    __check_ret, __check_msg = f_checkRequestSafe(request)
    if not __check_ret:
        return HttpResponse(__check_msg.encode("utf-8"), status=403)
    params = f_parseGetParams(request)
    rid = int(params.get("id", 0) or 0)
    fpath = (params.get("path") or "").strip()
    fp = None
    if rid:
        from app.models import RecordingModel
        try:
            rec = RecordingModel.objects.get(id=rid)
            fp = rec.file_path
        except Exception:
            return HttpResponse(b"not found", status=404)
    elif fpath and os.path.isfile(fpath):
        try:
            base = g_config.storageRecordDir
            if base and os.path.commonpath([os.path.abspath(fpath), os.path.abspath(base)]) == os.path.abspath(base):
                fp = fpath
        except Exception:
            pass
    if not fp or not os.path.isfile(fp):
        return HttpResponse(b"file missing", status=404)
    with open(fp, "rb") as f:
        data = f.read()
    resp = HttpResponse(data, content_type="video/mp4")
    resp["Content-Disposition"] = 'inline; filename="%s"' % os.path.basename(fp)
    return resp


def api_openRecordDel(request):
    if request.method != 'POST':
        return f_responseJson({"code": 0, "msg": LANG_VIEWS_T(request, "msg_method_not_supported")})
    __check_ret, __check_msg = f_checkRequestSafe(request)
    if not __check_ret:
        return f_responseJson({"code": 0, "msg": __check_msg})
    params = f_parsePostParams(request)
    rid = int(params.get("id", 0) or 0)
    fpath = (params.get("path") or "").strip()
    if not rid and not fpath:
        return f_responseJson({"code": 0, "msg": "missing id or path"})
    from app.models import RecordingModel
    try:
        if rid:
            rec = RecordingModel.objects.get(id=rid)
            fp = rec.file_path
            rec.delete()
        else:
            fp = fpath
            base = g_config.storageRecordDir
            if not base or not os.path.isfile(fp):
                return f_responseJson({"code": 0, "msg": "file missing"})
            if os.path.commonpath([os.path.abspath(fp), os.path.abspath(base)]) != os.path.abspath(base):
                return f_responseJson({"code": 0, "msg": "invalid path"})
            RecordingModel.objects.filter(file_path=fp).delete()
        if fp and os.path.isfile(fp):
            os.remove(fp)
        return f_responseJson({"code": 1000, "msg": LANG_VIEWS_T(request, "msg_success")})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})


def api_openSnapShot(request):
    if request.method != 'POST':
        return f_responseJson({"code": 0, "msg": LANG_VIEWS_T(request, "msg_method_not_supported")})
    __check_ret, __check_msg = f_checkRequestSafe(request)
    if not __check_ret:
        return f_responseJson({"code": 0, "msg": __check_msg})
    return f_responseJson({"code": 0, "msg": LANG_VIEWS_T(request, "nvr_snapshot_removed")})


def api_openSnap(request):
    try:
        params = f_parseGetParams(request)
        app = params.get("app", "").strip()
        name = params.get("name", "").strip()
        force = str(params.get("force", "0")).strip() == "1"
        if not app or not name:
            return HttpResponse(b"missing app or name", status=400, content_type="text/plain")
        snap_dir = os.path.join(g_config.storageDir, "snapshots")
        safe_app = "".join(c for c in app if c.isalnum() or c in ("_", "-", "."))
        safe_name = "".join(c for c in name if c.isalnum() or c in ("_", "-", "."))
        if not safe_app or not safe_name:
            safe_app = app.replace("/", "_").replace("\\", "_")
            safe_name = name.replace("/", "_").replace("\\", "_")
        snap_path = os.path.join(snap_dir, "%s_%s.jpg" % (safe_app, safe_name))
        if not force and os.path.exists(snap_path):
            mtime = os.path.getmtime(snap_path)
            if (time.time() - mtime) < 30:
                with open(snap_path, "rb") as f:
                    data = f.read()
                if len(data) > 100:
                    return HttpResponse(data, content_type="image/jpeg")
        rtsp_url = g_zlm.get_rtspUrl(app=app, name=name, request_ip="127.0.0.1")
        if not rtsp_url:
            return HttpResponse(b"no stream url available", status=404, content_type="text/plain")
        os.makedirs(snap_dir, exist_ok=True)
        if os.path.exists(snap_path):
            os.remove(snap_path)
        ffmpeg_cmd = g_config.ffmpeg
        command = '"{ffmpeg}" -loglevel quiet -rtsp_transport tcp -i "{rtsp_url}" -frames:v 1 "{snap_path}"'.format(
            ffmpeg=ffmpeg_cmd, rtsp_url=rtsp_url, snap_path=snap_path)
        subprocess.run(command, shell=True, timeout=10, capture_output=True)
        if os.path.exists(snap_path):
            with open(snap_path, "rb") as f:
                data = f.read()
            if len(data) > 100:
                return HttpResponse(data, content_type="image/jpeg")
        return HttpResponse(b"snap failed", status=404, content_type="text/plain")
    except subprocess.TimeoutExpired:
        return HttpResponse(b"snap timeout", status=404, content_type="text/plain")
    except Exception as e:
        return HttpResponse(("snap exception: " + str(e)).encode("utf-8"), status=500, content_type="text/plain")
