# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""24/7 录像管理 — FFmpeg 分段录制 + retention 清理"""
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger("recording.manager")

_MANAGER = None
_MANAGER_LOCK = threading.Lock()


class RecordingManager(object):
    def __init__(self):
        self._lock = threading.RLock()
        self._processes = {}  # stream_id -> {"proc": Popen, "path": str}
        self._retention_thread = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._retention_thread = threading.Thread(
            target=self._retention_loop, name="recording-retention", daemon=True)
        self._retention_thread.start()
        threading.Thread(target=self._auto_start_loop, name="recording-autostart", daemon=True).start()
        logger.info("RecordingManager 已启动")

    def _auto_start_loop(self):
        time.sleep(5)
        try:
            from app.models import StreamModel
            for s in StreamModel.objects.filter(record_enable=1, forward_state=1):
                self.start_stream(s)
        except Exception as e:
            logger.warning("录像自动启动失败: %s", e)

    def _segment_seconds(self):
        try:
            from app.utils.GlobalUtils import g_config
            return int(getattr(g_config, "recordingSegmentSeconds", 600))
        except Exception:
            return 600

    def _record_dir(self, stream):
        from app.utils.GlobalUtils import g_config
        base = getattr(g_config, "storageRecordDir", "") or os.path.join(
            getattr(g_config, "storageDir", ""), "record")
        code = "".join(c for c in str(stream.code or stream.id) if c.isalnum() or c in "_-")
        day = datetime.now().strftime("%Y%m%d")
        d = os.path.join(base, code, day)
        os.makedirs(d, exist_ok=True)
        return d

    def _rtsp_url(self, stream):
        from app.analysis.manager import AnalysisManager
        return AnalysisManager.build_rtsp_url(stream)

    def start_stream(self, stream):
        sid = stream.id
        with self._lock:
            if sid in self._processes:
                proc = self._processes[sid].get("proc")
                if proc and proc.poll() is None:
                    return True, "already recording"
            url = self._rtsp_url(stream)
            if not url:
                return False, "no rtsp url"
            out_dir = self._record_dir(stream)
            seg = self._segment_seconds()
            pattern = os.path.join(out_dir, "%s_%%Y%%m%%d_%%H%%M%%S.mp4" % sid)
            try:
                from app.utils.GlobalUtils import g_config
                ffmpeg = g_config.ffmpeg
            except Exception:
                ffmpeg = "ffmpeg"
            cmd = [
                ffmpeg, "-loglevel", "warning", "-rtsp_transport", "tcp",
                "-i", url,
                "-c", "copy", "-f", "segment",
                "-segment_time", str(seg),
                "-reset_timestamps", "1",
                "-strftime", "1",
                pattern,
            ]
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                return False, str(e)
            self._processes[sid] = {"proc": proc, "path": out_dir, "stream": stream}
            logger.info("录像启动 stream=%s dir=%s", sid, out_dir)
            return True, "started"

    def stop_stream(self, stream_id):
        with self._lock:
            item = self._processes.pop(stream_id, None)
            if not item:
                return False, "not recording"
            proc = item.get("proc")
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            return True, "stopped"

    def is_recording(self, stream_id):
        with self._lock:
            item = self._processes.get(stream_id)
            if not item:
                return False
            proc = item.get("proc")
            return proc is not None and proc.poll() is None

    def list_recording(self):
        with self._lock:
            return [sid for sid, item in self._processes.items()
                    if item.get("proc") and item["proc"].poll() is None]

    def _retain_days(self):
        try:
            from app.utils.GlobalUtils import g_config
            return int(getattr(g_config, "recordingRetainDays", 7))
        except Exception:
            return 7

    def _retain_gb(self):
        try:
            from app.utils.GlobalUtils import g_config
            return float(getattr(g_config, "recordingRetainGb", 0))
        except Exception:
            return 0

    def _retention_loop(self):
        while self._running:
            try:
                self._run_retention()
            except Exception as e:
                logger.warning("retention 异常: %s", e)
            time.sleep(3600)

    def _run_retention(self):
        from app.utils.GlobalUtils import g_config
        base = getattr(g_config, "storageRecordDir", "")
        if not base or not os.path.isdir(base):
            return
        days = self._retain_days()
        cutoff = datetime.now() - timedelta(days=max(1, days))
        deleted = 0
        for root, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith((".mp4", ".ts", ".mkv")):
                    continue
                fp = os.path.join(root, fn)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(fp))
                    if mtime < cutoff:
                        os.remove(fp)
                        deleted += 1
                        self._delete_recording_row(fp)
                except Exception:
                    pass
        max_gb = self._retain_gb()
        if max_gb > 0:
            self._enforce_size_cap(base, max_gb)
        if deleted:
            logger.info("retention 删除 %d 个过期录像文件", deleted)

    def _enforce_size_cap(self, base, max_gb):
        files = []
        for root, _d, fns in os.walk(base):
            for fn in fns:
                if fn.endswith((".mp4", ".ts", ".mkv")):
                    fp = os.path.join(root, fn)
                    try:
                        files.append((os.path.getmtime(fp), os.path.getsize(fp), fp))
                    except Exception:
                        pass
        files.sort()
        total = sum(x[1] for x in files)
        limit = int(max_gb * (1024 ** 3))
        while total > limit and files:
            _mt, sz, fp = files.pop(0)
            try:
                os.remove(fp)
                total -= sz
                self._delete_recording_row(fp)
            except Exception:
                pass

    def _delete_recording_row(self, filepath):
        try:
            from app.models import RecordingModel
            RecordingModel.objects.filter(file_path=filepath).delete()
        except Exception:
            pass

    def index_recording_file(self, stream_id, filepath, start_time, duration, file_size):
        try:
            from app.models import StreamModel, RecordingModel
            stream = StreamModel.objects.get(id=stream_id)
            RecordingModel.objects.create(
                stream=stream,
                file_path=filepath,
                start_time=start_time,
                end_time=start_time + timedelta(seconds=duration) if duration else start_time,
                duration=duration or 0,
                file_size=file_size or 0,
            )
        except Exception as e:
            logger.debug("index recording: %s", e)


def get_recording_manager():
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = RecordingManager()
            _MANAGER.start()
        return _MANAGER
