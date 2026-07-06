# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""Rebucca 分析子进程入口

每路摄像头在独立进程中运行 CameraPipeline，绕过 GIL，与主进程通过 Queue 通信：
- event_queue: 子 → 主，上报检测/区域/追踪事件
- cmd_queue:   主 → 子，stop / reload_zones
- status_dict: 共享状态（Manager.dict），供 openStatus 读取 FPS
"""
import json
import logging
import multiprocessing as mp
import os
import queue
import time

logger = logging.getLogger("analysis.process_worker")


def _algorithm_spec_from_dict(d):
    return d


def _build_detectors_in_process(algorithm_specs, infer_req_q=None, infer_resp_q=None):
    """在子进程中构造检测器；若提供 infer_req_q/infer_resp_q 则走主进程共享推理池"""
    detectors = []
    if infer_req_q is not None and infer_resp_q is not None:
        from app.analysis.remote_detector import RemoteDetector
        for spec in algorithm_specs:
            detectors.append({
                "algorithm_id": spec.get("id", 0),
                "algorithm_name": spec.get("name", ""),
                "engine": RemoteDetector(spec, infer_req_q, infer_resp_q),
            })
    else:
        from app.analysis.worker_pool import DetectorWorkerPool
        pool = DetectorWorkerPool()

        class _AlgoObj(object):
            pass

        for spec in algorithm_specs:
            o = _AlgoObj()
            for k, v in spec.items():
                setattr(o, k, v)
            eng = pool.get_detector(o)
            if eng:
                detectors.append({
                    "algorithm_id": spec.get("id", 0),
                    "algorithm_name": spec.get("name", ""),
                    "engine": eng,
                })
    return detectors


def pipeline_process_main(config, event_queue, cmd_queue, status_dict,
                          infer_req_q=None, infer_resp_q=None):
    """子进程主函数（spawn 入口，config 必须为纯 dict）"""
    from app.utils.Logger import LOG_FORMAT
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    log = logging.getLogger("analysis.process_worker")

    from app.analysis.pipeline import CameraPipeline
    from app.analysis.motion import MotionDetector

    stream_id = config["stream_id"]
    stream_code = config.get("stream_code", str(stream_id))
    rtsp_url = config["rtsp_url"]
    target_fps = config.get("target_fps", 5)
    analyze_fps = config.get("analyze_fps", target_fps)
    zones = config.get("zones") or []
    algorithm_specs = config.get("algorithms") or []
    use_shared_inference = bool(config.get("use_shared_inference", True))
    storage_alarm_dir = config.get("storage_alarm_dir") or ""
    static_dir = config.get("static_dir") or ""

    def on_event(ev):
        try:
            event_queue.put(("event", ev), timeout=2.0)
        except Exception as e:
            log.warning("事件入队失败: %s", e)

    def on_track_snapshot(sid, frame_index, active, has_motion):
        try:
            event_queue.put(("touch", {
                "stream_id": sid,
                "active": active,
                "has_motion": has_motion,
            }), timeout=1.0)
        except Exception:
            pass

    detectors = _build_detectors_in_process(
        algorithm_specs,
        infer_req_q if use_shared_inference else None,
        infer_resp_q if use_shared_inference else None,
    )
    if not detectors and not algorithm_specs:
        log.info("pipeline[%s] 无算法，仅运动检测", stream_code)

    motion = MotionDetector()
    pipeline = CameraPipeline(
        stream_id=stream_id,
        stream_code=stream_code,
        rtsp_url=rtsp_url,
        detectors=detectors,
        motion=motion,
        target_fps=target_fps,
        analyze_fps=analyze_fps,
        on_event=on_event,
        on_track_snapshot=on_track_snapshot,
        zone_polygons=zones,
        storage_alarm_dir=storage_alarm_dir,
        static_dir=static_dir,
    )
    pipeline._algorithm_name = ", ".join(d.get("name", "") for d in algorithm_specs) or "motion-only"

    import threading

    def status_reporter():
        # 等待 pipeline.run() 启动（_running 在 run() 里才置 True，
        # 否则 while pipeline._running 条件不满足会立即退出，导致 status_dict 永远为空）
        _wait = 0
        while not pipeline._running and _wait < 100:
            time.sleep(0.1)
            _wait += 1
        while pipeline._running:
            try:
                st = pipeline.status()
                status_dict[str(stream_id)] = st
            except Exception:
                pass
            time.sleep(1.0)

    reporter = threading.Thread(target=status_reporter, name="status-%s" % stream_id, daemon=True)
    reporter.start()

    def cmd_listener():
        while pipeline._running:
            try:
                cmd = cmd_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if not cmd:
                continue
            if cmd.get("cmd") == "stop":
                pipeline.stop()
                break
            if cmd.get("cmd") == "reload_zones":
                pipeline.zone_polygons = cmd.get("zones") or []
                if cmd.get("analyze_fps") is not None:
                    pipeline.set_analyze_fps(cmd.get("analyze_fps"))
                pipeline.reset_zone_runtime_state()

    cmd_thread = threading.Thread(target=cmd_listener, name="cmd-%s" % stream_id, daemon=True)
    cmd_thread.start()

    log.info("pipeline 子进程启动 stream=%s url=%s", stream_code, rtsp_url)
    try:
        pipeline.run()
    finally:
        try:
            status_dict.pop(str(stream_id), None)
        except Exception:
            pass
        log.info("pipeline 子进程退出 stream=%s", stream_code)


class PipelineProcessHandle(object):
    """主进程侧对子进程的封装"""

    def __init__(self, stream_id, process, event_queue, cmd_queue, status_dict):
        self.stream_id = stream_id
        self.process = process
        self.event_queue = event_queue
        self.cmd_queue = cmd_queue
        self.status_dict = status_dict
        self.running = True

    def stop(self, timeout=5):
        self.running = False
        try:
            self.cmd_queue.put({"cmd": "stop"}, timeout=1.0)
        except Exception:
            pass
        try:
            self.process.join(timeout=timeout)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=2)
        except Exception:
            pass

    def reload_zones(self, zones, analyze_fps=None):
        try:
            payload = {"cmd": "reload_zones", "zones": zones}
            if analyze_fps is not None:
                payload["analyze_fps"] = analyze_fps
            self.cmd_queue.put(payload, timeout=1.0)
        except Exception as e:
            logger.warning("reload_zones 发送失败: %s", e)

    def status(self):
        try:
            return self.status_dict.get(str(self.stream_id))
        except Exception:
            return None
