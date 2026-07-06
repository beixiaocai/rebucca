# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""全局分析管理器（单例）

阶段2：每路摄像头在独立子进程中运行 CameraPipeline；YOLO 推理可选走
主进程 InferenceProcessPool（共享 GPU/模型内存）。事件经 Queue → EventBridge 写库。
"""
import json
import logging
import multiprocessing as mp
import threading
import time

from app.analysis.pipeline import CameraPipeline
from app.analysis.motion import MotionDetector
from app.analysis.worker_pool import DetectorWorkerPool
from app.analysis.process_worker import pipeline_process_main, PipelineProcessHandle
from app.analysis.event_bridge import get_event_bridge

logger = logging.getLogger("analysis.manager")


def _snapshot_storage_paths():
    """主进程解析报警快照目录，注入子进程（子进程不可 import GlobalUtils）。"""
    import os
    from framework.settings import BASE_DIR
    from app.utils.GlobalUtils import g_config
    static_dir = os.path.join(str(BASE_DIR), "static")
    alarm_dir = getattr(g_config, "storageAlarmDir", "") or os.path.join(static_dir, "storage", "alarm")
    return alarm_dir, static_dir


def _algorithm_to_spec(a):
    labels = a.labels
    if isinstance(labels, str):
        try:
            labels = json.loads(labels)
        except Exception:
            labels = []
    return {
        "id": a.id,
        "name": a.name,
        "inference_engine": a.inference_engine,
        "model_file": a.model_file,
        "labels": labels,
        "input_width": a.input_width,
        "input_height": a.input_height,
        "conf_threshold": a.conf_threshold,
        "iou_threshold": a.iou_threshold,
        "algorithm_type": a.algorithm_type,
        "task_type": getattr(a, "task_type", "detect"),
        "device": getattr(a, "device", "cpu"),
    }


def _biz_algo_to_zone_dict(ba):
    labels = ba.target_labels or '[]'
    try:
        labels_list = json.loads(labels) if isinstance(labels, str) else labels
    except Exception:
        labels_list = []
    llm_cfg = None
    if ba.llm_id and ba.llm:
        llm_cfg = {
            "id": ba.llm_id,
            "api_url": ba.llm.api_url,
            "api_key": ba.llm.api_key,
            "model_name": ba.llm.model_name,
            "timeout": ba.llm.timeout,
            "inference_tool": ba.llm.inference_tool or "OpenAI",
        }
    return {
        "id": ba.id,
        "name": ba.name or "",
        "flow_type": ba.flow_type,
        "small_model_id": ba.small_model_id,
        "target_labels": labels_list,
        "llm_id": ba.llm_id,
        "llm_prompt": ba.llm_prompt or "",
        "llm_validate": ba.llm_validate or "",
        "post_process": ba.post_process or "AREA",
        "ref_angle": float(getattr(ba, "ref_angle", 90.0) or 90.0),
        "angle_tolerance": float(getattr(ba, "angle_tolerance", 45.0) or 45.0),
        "llm": llm_cfg,
    }


class AnalysisManager(object):
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super(AnalysisManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._pipelines = {}      # stream_id -> handle dict
        self._lock = threading.RLock()
        self._worker_pool = DetectorWorkerPool()
        self._mp_ctx = mp.get_context("spawn")
        self._status_manager = self._mp_ctx.Manager()
        self._status_dict = self._status_manager.dict()
        self._infer_req_q = self._mp_ctx.Queue(maxsize=128)
        self._infer_resp_q = self._mp_ctx.Queue(maxsize=128)
        self._infer_forwarder_running = True
        self._infer_forwarder = threading.Thread(
            target=self._inference_forwarder_loop, name="infer-forwarder", daemon=True)
        self._infer_forwarder.start()
        self._disabled_algos = set()  # 禁用实例化的业务算法 ID 集合（内存，重启丢失）
        get_event_bridge()
        self._configure_from_settings()

    def _use_multiprocess(self):
        try:
            from app.utils.GlobalUtils import g_config
            mode = int(getattr(g_config, "analysisProcessMode", 1))
            return mode >= 1
        except Exception:
            return True

    def _use_shared_inference(self):
        try:
            from app.utils.GlobalUtils import g_config
            return bool(getattr(g_config, "analysisSharedInference", True))
        except Exception:
            return True

    def set_inference_config(self, shared=None, workers=None):
        """热更新推理配置（不持久化）。
        - shared: 切换共享推理开关；切换后需重启所有运行中的 pipeline
        - workers: 调整共享推理 worker 数；调整后重启 inference_pool
        返回 (ok, msg)
        """
        from app.utils.GlobalUtils import g_config
        old_shared = self._use_shared_inference()
        old_workers = int(getattr(g_config, "analysisInferenceWorkers", 2))
        shared_changed = False
        workers_changed = False
        if shared is not None:
            try:
                new_shared = bool(int(shared))
            except Exception:
                new_shared = old_shared
            if new_shared != old_shared:
                g_config.analysisSharedInference = new_shared
                shared_changed = True
        if workers is not None:
            try:
                new_workers = max(1, min(32, int(workers)))
            except Exception:
                new_workers = old_workers
            if new_workers != old_workers:
                g_config.analysisInferenceWorkers = new_workers
                workers_changed = True
        # 重启推理池（worker 数变了，或从非共享切到共享）
        if workers_changed or (shared_changed and self._use_shared_inference()):
            try:
                from app.analysis.inference_pool import shutdown_inference_pool, get_inference_pool
                shutdown_inference_pool()
                if self._use_shared_inference():
                    get_inference_pool()  # 会按新 worker 数重建
            except Exception as e:
                logger.warning("重启推理池失败: %s" % str(e))
        # shared 切换后重启所有运行中的 pipeline，让新模式生效
        if shared_changed:
            with self._lock:
                sids = list(self._pipelines.keys())
            for sid in sids:
                try:
                    from app.models import StreamModel as _SM
                    s = _SM.objects.get(id=sid)
                    self.stop(sid)
                    self.start(s)
                except Exception as e:
                    logger.warning("shared 切换重启 pipeline sid=%s 失败: %s" % (sid, str(e)))
        if not shared_changed and not workers_changed:
            return True, "配置未变化"
        return True, "配置已热生效"

    def set_algo_instance_enabled(self, algo_id, enabled):
        """设置业务算法的实例化开关（内存，重启丢失）。立即生效，无需重启 pipeline。"""
        try:
            aid = int(algo_id)
        except Exception:
            return False, "invalid algorithm_id"
        with self._lock:
            if enabled:
                self._disabled_algos.discard(aid)
            else:
                self._disabled_algos.add(aid)
        return True, "ok"

    def is_algo_instance_enabled(self, algo_id):
        try:
            aid = int(algo_id)
        except Exception:
            return True
        return aid not in self._disabled_algos

    def get_disabled_algos(self):
        with self._lock:
            return set(self._disabled_algos)

    def restart_algo_instance(self, algo_id):
        """重启使用指定算法的所有 pipeline（重新加载引擎）。
        algo_id 是小模型 AlgorithmModel.id。
        """
        try:
            aid = int(algo_id)
        except Exception:
            return False, "invalid algorithm_id"
        with self._lock:
            sids = []
            for sid, item in list(self._pipelines.items()):
                algo_ids = item.get("algorithm_ids") or []
                if aid in algo_ids:
                    sids.append(sid)
        if not sids:
            return True, "没有运行中的 pipeline 使用该算法"
        restarted = 0
        for sid in sids:
            try:
                from app.models import StreamModel as _SM
                s = _SM.objects.get(id=sid)
                self.stop(sid)
                self.start(s)
                restarted += 1
            except Exception as e:
                logger.warning("restart_algo_instance sid=%s 失败: %s" % (sid, str(e)))
        return True, "已重启 %d 路 pipeline" % restarted

    def restart_inference_pool(self):
        """重启整个推理池（清除所有 worker 子进程内的引擎缓存）。"""
        try:
            from app.analysis.inference_pool import shutdown_inference_pool, get_inference_pool
            shutdown_inference_pool()
            if self._use_shared_inference():
                get_inference_pool()
            return True, "推理池已重启，所有引擎缓存已清除"
        except Exception as e:
            return False, str(e)

    def _inference_forwarder_loop(self):
        from app.analysis.inference_pool import get_inference_pool
        import queue as _q
        pool = get_inference_pool()
        while self._infer_forwarder_running:
            try:
                msg = self._infer_req_q.get(timeout=0.5)
            except _q.Empty:
                continue
            if msg is None:
                break
            req_id = msg.get("req_id")
            try:
                jpeg = msg.get("jpeg")
                algo = msg.get("algorithm") or {}
                # 禁用实例化的算法直接返回空结果，跳过推理
                algo_id = algo.get("id", 0)
                try:
                    if algo_id and int(algo_id) in self._disabled_algos:
                        self._infer_resp_q.put({"req_id": req_id, "ok": True, "detections": []})
                        continue
                except Exception:
                    pass
                # 直接透传 JPEG bytes 给推理池，避免主进程 imdecode + imencode 双重编解码，
                # 消除主进程 GIL 占用（解码在 worker 子进程内完成）。
                dets = pool.detect_jpeg(jpeg, algo)
                self._infer_resp_q.put({"req_id": req_id, "ok": True, "detections": dets})
            except Exception as e:
                logger.warning("推理转发失败: %s", e)
                try:
                    self._infer_resp_q.put({"req_id": req_id, "ok": False, "error": str(e)})
                except Exception:
                    pass

    def _configure_from_settings(self):
        try:
            from app.models import AlgorithmModel
            default = AlgorithmModel.objects.filter(is_default=1, state=1).first()
            if default:
                self._default_algorithm = default
                self._target_fps = 5
                return
        except Exception as e:
            logger.warning("AnalysisManager 读取默认 AlgorithmModel 失败: %s" % str(e))
        try:
            from app.utils.GlobalUtils import g_config
            self._target_fps = int(getattr(g_config, "analysisTargetFps", 5))
        except Exception:
            self._target_fps = 5
        self._default_algorithm = None

    @staticmethod
    def build_rtsp_url(stream):
        try:
            from app.utils.GlobalUtils import g_config
            ip = getattr(g_config, "externalHost", "127.0.0.1") or "127.0.0.1"
            if ip == "0.0.0.0":
                ip = "127.0.0.1"
            port = getattr(g_config, "mediaRtspPort", 10554)
            app = getattr(stream, "app", "live") or "live"
            name = getattr(stream, "name", getattr(stream, "code", "stream")) or "stream"
            return "rtsp://%s:%s/%s/%s" % (ip, int(port), app, name)
        except Exception as e:
            logger.warning("build_rtsp_url 失败: %s" % str(e))
            return ""

    @staticmethod
    def _zone_analyze_fps(interval_sec, detect_frames):
        interval = max(0.1, float(interval_sec or 1))
        frames = max(1, int(detect_frames or 1))
        return float(frames) / interval

    @staticmethod
    def _compute_analyze_fps(stream_id, fallback=None):
        """取该摄像头所有启用布控中最高的算法分析频率（帧/秒）"""
        try:
            from app.models import ZoneModel
            qs = ZoneModel.objects.filter(stream_id=stream_id, state=1)
            max_fps = 0.0
            for z in qs:
                max_fps = max(max_fps, AnalysisManager._zone_analyze_fps(
                    getattr(z, "detect_interval_sec", 1),
                    getattr(z, "detect_frames", 1),
                ))
            if max_fps > 0:
                return max_fps
        except Exception as e:
            logger.warning("_compute_analyze_fps err stream=%s: %s" % (stream_id, str(e)))
        if fallback is not None and fallback > 0:
            return float(fallback)
        return 1.0

    @staticmethod
    def _load_zones(stream_id):
        try:
            from app.models import ZoneModel
            qs = ZoneModel.objects.filter(stream_id=stream_id, state=1).prefetch_related(
                'algorithms', 'algorithms__small_model', 'algorithms__llm')
            zones = []
            for z in qs:
                try:
                    coords = json.loads(z.coordinates)
                except Exception:
                    coords = []
                # LINE_CROSS 警戒线端点（归一化坐标 JSON）
                line_a = None
                line_b = None
                try:
                    la = getattr(z, "line_a", "") or ""
                    if la:
                        line_a = json.loads(la)
                    lb = getattr(z, "line_b", "") or ""
                    if lb:
                        line_b = json.loads(lb)
                except Exception:
                    line_a = line_b = None
                biz_list = []
                biz_ids = []
                small_ids = set()
                for ba in z.algorithms.filter(state=1):
                    biz_ids.append(ba.id)
                    biz_list.append(_biz_algo_to_zone_dict(ba))
                    if ba.small_model_id:
                        small_ids.add(ba.small_model_id)
                interval = max(0.1, float(getattr(z, "detect_interval_sec", 1) or 1))
                frames = max(1, int(getattr(z, "detect_frames", 1) or 1))
                zones.append({
                    "id": z.id,
                    "name": z.name,
                    "coords": coords,
                    "is_required": z.is_required,
                    "loiter_threshold": z.loiter_threshold,
                    "detect_interval_sec": interval,
                    "detect_frames": frames,
                    "line_a": line_a,
                    "line_b": line_b,
                    "density_threshold": int(getattr(z, "density_threshold", 0) or 0),
                    "algorithm_ids": biz_ids,
                    "biz_algorithms": biz_list,
                    "small_model_ids": sorted(small_ids),
                })
            return zones
        except Exception as e:
            logger.warning("加载 Zone 失败 stream=%s: %s" % (stream_id, str(e)))
            return []

    def _resolve_algorithms_for_stream(self, stream):
        try:
            from app.models import ZoneModel, AlgorithmModel
            algos = []
            seen = set()
            for z in ZoneModel.objects.filter(stream_id=stream.id, state=1).prefetch_related(
                    'algorithms__small_model'):
                for ba in z.algorithms.filter(state=1):
                    sm = ba.small_model
                    if sm and sm.state == 1 and sm.id not in seen:
                        seen.add(sm.id)
                        algos.append(sm)
            sa = getattr(stream, "algorithm", None)
            if sa is not None and sa.state == 1 and sa.id not in seen:
                seen.add(sa.id)
                algos.append(sa)
            if not algos:
                d = AlgorithmModel.objects.filter(is_default=1, state=1).first()
                if d:
                    algos.append(d)
            return algos
        except Exception as e:
            logger.warning("_resolve_algorithms_for_stream err: %s" % str(e))
            return []

    def _fallback_engine_from_config(self):
        try:
            from app.utils.GlobalUtils import g_config
            model_path = getattr(g_config, "analysisDetectorModel", "") or ""
            if not model_path:
                return None
            labels = getattr(g_config, "analysisDetectorLabels", [])
            if isinstance(labels, str):
                labels = [x.strip() for x in labels.split(",") if x.strip()]
            conf = float(getattr(g_config, "analysisConfThreshold", 0.4))
            from app.analysis.engines.onnx_engine import OnnxEngine
            eng = OnnxEngine(model_path=model_path, labels=labels, conf_threshold=conf)
            if eng.load():
                return eng
        except Exception as e:
            logger.warning("config fallback engine err: %s" % str(e))
        return None

    def _start_process(self, stream, url, zones, algos, detectors_legacy=None):
        sid = stream.id
        event_queue = self._mp_ctx.Queue(maxsize=256)
        cmd_queue = self._mp_ctx.Queue(maxsize=16)
        bridge = get_event_bridge()
        bridge.register_queue(event_queue)

        algo_specs = [_algorithm_to_spec(a) for a in algos]
        analyze_fps = self._compute_analyze_fps(sid, fallback=self._target_fps)
        storage_alarm_dir, static_dir = _snapshot_storage_paths()
        config = {
            "stream_id": sid,
            "stream_code": getattr(stream, "code", str(sid)),
            "rtsp_url": url,
            "target_fps": self._target_fps,
            "analyze_fps": analyze_fps,
            "zones": zones,
            "algorithms": algo_specs,
            "use_shared_inference": self._use_shared_inference(),
            "storage_alarm_dir": storage_alarm_dir,
            "static_dir": static_dir,
        }
        proc = self._mp_ctx.Process(
            target=pipeline_process_main,
            args=(config, event_queue, cmd_queue, self._status_dict,
                  self._infer_req_q, self._infer_resp_q),
            name="pipeline-%s" % sid,
            daemon=True,
        )
        proc.start()
        handle = PipelineProcessHandle(sid, proc, event_queue, cmd_queue, self._status_dict)
        self._pipelines[sid] = {
            "handle": handle,
            "process": proc,
            "event_queue": event_queue,
            "mode": "process",
            "running": True,
            "pipeline": None,
            "thread": None,
            "algorithm_ids": sorted([a.id for a in algos]),
        }
        return True, "started (process)"

    def _start_thread(self, stream, url, zones, algos):
        sid = stream.id
        detectors = []
        algo_names = []
        for a in algos:
            eng = self._worker_pool.get_detector(a)
            if eng:
                detectors.append({"algorithm_id": a.id, "algorithm_name": a.name, "engine": eng})
                algo_names.append(a.name)
        if not algos:
            eng = self._fallback_engine_from_config()
            if eng:
                detectors.append({"algorithm_id": 0, "algorithm_name": "config-fallback", "engine": eng})
                algo_names.append("config-fallback")

        motion = MotionDetector()
        analyze_fps = self._compute_analyze_fps(sid, fallback=self._target_fps)
        storage_alarm_dir, static_dir = _snapshot_storage_paths()
        pipeline = CameraPipeline(
            stream_id=sid,
            stream_code=getattr(stream, "code", str(sid)),
            rtsp_url=url,
            detectors=detectors,
            motion=motion,
            target_fps=self._target_fps,
            analyze_fps=analyze_fps,
            on_event=self._on_event,
            on_track_snapshot=self._on_track_snapshot,
            zone_polygons=zones,
            storage_alarm_dir=storage_alarm_dir,
            static_dir=static_dir,
        )
        pipeline._algorithm_name = ", ".join(algo_names) if algo_names else "motion-only"
        t = threading.Thread(target=pipeline.run, name="pipeline-%s" % sid, daemon=True)
        self._pipelines[sid] = {
            "pipeline": pipeline,
            "thread": t,
            "running": True,
            "mode": "thread",
            "algorithm_ids": sorted([a.id for a in algos]),
        }
        t.start()
        return True, "started (thread)"

    def start(self, stream):
        sid = stream.id
        with self._lock:
            item = self._pipelines.get(sid)
            if item and item.get("running"):
                alive = True
                if item.get("mode") == "process":
                    proc = item.get("process")
                    alive = proc is not None and proc.is_alive()
                else:
                    th = item.get("thread")
                    alive = th is not None and th.is_alive()
                if alive:
                    return True, "already running"
                # 僵尸条目：进程/线程已退出但未清理
                try:
                    if item.get("mode") == "process":
                        eq = item.get("event_queue")
                        if eq:
                            get_event_bridge().unregister_queue(eq)
                    else:
                        pipe = item.get("pipeline")
                        if pipe:
                            pipe.stop()
                except Exception:
                    pass
                self._pipelines.pop(sid, None)
            url = self.build_rtsp_url(stream)
            if not url:
                return False, "no rtsp url"
            algos = self._resolve_algorithms_for_stream(stream)
            zones = self._load_zones(sid)
            if self._use_multiprocess():
                ok, msg = self._start_process(stream, url, zones, algos)
            else:
                ok, msg = self._start_thread(stream, url, zones, algos)
            if ok:
                time.sleep(0.35)
                if not self.is_running(sid):
                    self._purge_pipeline(sid)
                    return False, "analysis subprocess exited (check OpenCV / RTSP / log)"
            return ok, msg

    def stop(self, stream_id):
        with self._lock:
            item = self._pipelines.get(stream_id)
            if not item:
                return False, "not running"
            if item.get("mode") == "process":
                handle = item.get("handle")
                if handle:
                    handle.stop()
                eq = item.get("event_queue")
                if eq:
                    get_event_bridge().unregister_queue(eq)
            else:
                item["pipeline"].stop()
                item["thread"].join(timeout=3)
            item["running"] = False
            self._pipelines.pop(stream_id, None)
            return True, "stopped"

    def is_running(self, stream_id):
        with self._lock:
            item = self._pipelines.get(stream_id)
            return self._is_pipeline_alive(item)

    def _is_pipeline_alive(self, item):
        if not item or not item.get("running"):
            return False
        if item.get("mode") == "process":
            proc = item.get("process")
            return proc is not None and proc.is_alive()
        th = item.get("thread")
        if th is not None and not th.is_alive():
            return False
        pipe = item.get("pipeline")
        if pipe is not None and not getattr(pipe, "_running", False):
            return False
        return True

    def _purge_pipeline(self, stream_id):
        item = self._pipelines.pop(stream_id, None)
        if not item:
            return
        try:
            if item.get("mode") == "process":
                eq = item.get("event_queue")
                if eq:
                    get_event_bridge().unregister_queue(eq)
                handle = item.get("handle")
                if handle:
                    try:
                        handle.stop(timeout=1)
                    except Exception:
                        pass
            else:
                pipe = item.get("pipeline")
                if pipe:
                    try:
                        pipe.stop()
                    except Exception:
                        pass
        except Exception:
            pass

    def list_running(self):
        with self._lock:
            alive = []
            for sid, item in list(self._pipelines.items()):
                if self._is_pipeline_alive(item):
                    alive.append(sid)
                else:
                    self._purge_pipeline(sid)
            return alive

    def get_pipeline_info(self, stream_id):
        with self._lock:
            item = self._pipelines.get(stream_id)
            if not item:
                return None
            if item.get("mode") == "process":
                handle = item.get("handle")
                if handle:
                    st = handle.status()
                    if st:
                        return st
                return {"stream_id": stream_id, "running": self.is_running(stream_id), "analysis_fps": 0.0}
            pipe = item.get("pipeline")
            if not pipe:
                return None
            try:
                return pipe.status()
            except Exception as e:
                logger.warning("get_pipeline_info err: %s" % str(e))
                return {"stream_id": stream_id, "running": True, "analysis_fps": 0.0}

    def reload_zones(self, stream_id):
        with self._lock:
            item = self._pipelines.get(stream_id)
            if not item:
                return False
            zones = self._load_zones(stream_id)
            analyze_fps = self._compute_analyze_fps(stream_id, fallback=self._target_fps)
            new_small_ids = sorted({sid for z in zones for sid in z.get("small_model_ids", []) if sid})
            cur_algo_ids = sorted(item.get("algorithm_ids") or [])
            if item.get("mode") == "process":
                if new_small_ids != cur_algo_ids:
                    handle = item.get("handle")
                    if handle:
                        handle.stop()
                    eq = item.get("event_queue")
                    if eq:
                        get_event_bridge().unregister_queue(eq)
                    self._pipelines.pop(stream_id, None)
                    try:
                        from app.models import StreamModel as _SM
                        s = _SM.objects.get(id=stream_id)
                        self.start(s)
                    except Exception as e:
                        logger.warning("reload_zones 重启失败 stream=%s: %s" % (stream_id, str(e)))
                else:
                    handle = item.get("handle")
                    if handle:
                        handle.reload_zones(zones, analyze_fps=analyze_fps)
                return True
            pipe = item.get("pipeline")
            if not pipe:
                return False
            pipe.zone_polygons = zones
            pipe.set_analyze_fps(analyze_fps)
            pipe.reset_zone_runtime_state()
            if new_small_ids != cur_algo_ids:
                pipe.stop()
                item["running"] = False
                try:
                    item["thread"].join(timeout=3)
                except Exception:
                    pass
                self._pipelines.pop(stream_id, None)
                try:
                    from app.models import StreamModel as _SM
                    s = _SM.objects.get(id=stream_id)
                    self.start(s)
                except Exception as e:
                    logger.warning("reload_zones 重启失败 stream=%s: %s" % (stream_id, str(e)))
            return True

    def _on_event(self, event):
        try:
            from app.services.alarm_service import write_alarm, ALARM_EVENT_TYPES
            etype = event.get("type", "")
            if etype in ALARM_EVENT_TYPES:
                write_alarm(event)
        except Exception as e:
            logger.exception("事件处理失败: %s ev=%s" % (str(e), str(event)[:200]))

    def _on_track_snapshot(self, stream_id, frame_index, active, has_motion):
        # 已停用：不再写追踪快照
        pass

    @staticmethod
    def _severity_for(event):
        t = event.get("type")
        if t in ("loiter", "cross_camera"):
            return 1
        if t in ("entered_zone", "left_zone", "object_start"):
            return 2
        return 3
