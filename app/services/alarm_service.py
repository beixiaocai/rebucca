# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""报警事件写入"""
import json
import logging
from datetime import datetime

logger = logging.getLogger("services.alarm")

# 报警事件类型（与 pipeline.py _emit_biz_alarm 产生的事件类型对齐）
ALARM_EVENT_TYPES = (
    'entered_zone',   # AREA/DWELL 进入即报
    'loiter',         # AREA 滞留
    'dwell',          # DWELL 滞留
    'line_cross',     # LINE_CROSS 越线
    'line_count',     # LINE_COUNT 越线计数超阈值
    'direction',      # DIRECTION 方向入侵
    'density',        # DENSITY 密度报警
)


def write_alarm(event):
    """将 pipeline 上报的报警事件写入 AlarmModel。

    event 字段约定：
      stream_id, stream_code, type, track_id?, zone_id?, label?, timestamp(unix),
      description?, metadata?
    """
    try:
        from app.models import AlarmModel, StreamModel
        ts = event.get("timestamp")
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts)
        elif isinstance(ts, str):
            dt = datetime.fromisoformat(ts)
        else:
            dt = datetime.now()
        sid = event.get("stream_id")
        stream = None
        if sid:
            try:
                stream = StreamModel.objects.get(id=sid)
            except Exception:
                stream = None
        meta = event.get("metadata") or {}
        for k in ("zone_id", "label", "duration", "track_id", "boxes", "box", "snapshot_path",
                  "global_track_id", "biz_algorithm_id", "biz_algorithm_name", "alarm_reason", "zone_name"):
            if k in event:
                meta[k] = event[k]
        AlarmModel.objects.create(
            stream=stream,
            event_type=event.get("type", "alarm"),
            description=event.get("description", ""),
            timestamp=dt,
            metadata=json.dumps(meta, ensure_ascii=False),
        )
    except Exception as e:
        logger.warning("write_alarm 失败: %s" % str(e))
