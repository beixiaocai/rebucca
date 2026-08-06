# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
from datetime import datetime, timedelta

from django.shortcuts import render
from django.db.models import Count
from django.db.models.functions import TruncDate

from app.views.ViewsBase import *
from app.models import AlarmModel, StreamModel


def index(request):
    """报警管理页面：集中展示与处理进入区域/滞留/运动等报警事件及快照"""
    return render(request, 'app/alarm/index.html', {})


def dashboard(request):
    """报警统计看板页面"""
    return render(request, 'app/alarm/dashboard.html', {})


# 报警事件类型中文名（与 services/alarm_service.ALARM_EVENT_TYPES 对齐）
_ALARM_TYPE_NAMES = {
    'entered_zone': '区域入侵',
    'loiter': '滞留',
    'dwell': '滞留报警',
    'line_cross': '越线检测',
    'line_count': '越线计数',
    'direction': '方向入侵',
    'density': '密度报警',
    'alarm': '报警',
}


def _stream_display_name(s):
    return (getattr(s, 'nickname', '') or getattr(s, 'name', '') or ('#%s' % s.id))


def _build_alarm_stats(request):
    """聚合报警统计数据。days 仅支持 7 / 30。"""
    try:
        days = int(request.GET.get('days', 7))
    except Exception:
        days = 7
    days = 30 if days >= 30 else 7

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=6)  # 近7天（含今天）

    total = AlarmModel.objects.count()
    today = AlarmModel.objects.filter(timestamp__gte=today_start).count()
    week = AlarmModel.objects.filter(timestamp__gte=week_start).count()
    stream_count = (AlarmModel.objects.exclude(stream_id__isnull=True)
                    .values('stream_id').distinct().count())

    # 近 days 天每日趋势（无报警的日期补 0）
    trend_start = today_start - timedelta(days=days - 1)
    tq = (AlarmModel.objects.filter(timestamp__gte=trend_start)
          .annotate(d=TruncDate('timestamp'))
          .values('d').annotate(c=Count('id')))
    tmap = {}
    for row in tq:
        d = row['d']
        key = d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)[:10]
        tmap[key] = row['c']
    trend = []
    for i in range(days):
        d = trend_start + timedelta(days=i)
        key = d.strftime('%Y-%m-%d')
        trend.append({"date": d.strftime('%m-%d'), "full": key, "count": tmap.get(key, 0)})

    # 报警类型分布
    ty = AlarmModel.objects.values('event_type').annotate(c=Count('id')).order_by('-c')
    by_type = []
    for r in ty:
        et = r['event_type'] or 'unknown'
        by_type.append({"type": et, "name": _ALARM_TYPE_NAMES.get(et, et), "count": r['c']})

    # TOP 报警摄像头
    top = (AlarmModel.objects.exclude(stream_id__isnull=True)
           .values('stream_id').annotate(c=Count('id')).order_by('-c')[:8])
    sids = [r['stream_id'] for r in top]
    smap = {s.id: _stream_display_name(s) for s in StreamModel.objects.filter(id__in=sids)}
    top_streams = [{"stream_id": r['stream_id'],
                    "name": smap.get(r['stream_id'], '#%s' % r['stream_id']),
                    "count": r['c']} for r in top]

    return {
        "today": today,
        "week": week,
        "total": total,
        "stream_count": stream_count,
        "days": days,
        "trend": trend,
        "by_type": by_type,
        "top_streams": top_streams,
    }


def api_openStats(request):
    """报警统计聚合接口"""
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {}
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                data = _build_alarm_stats(request)
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})
