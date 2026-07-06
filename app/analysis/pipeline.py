# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""单摄像头分析流水线（实时解码 + 实时分析）

架构：
- 解码线程 _decode_loop：持续从 FrameSource 抓帧，写入有界 deque(maxlen=2)。
  队列满时自动丢弃最旧帧（deque 特性），绝不阻塞解码、也不阻塞分析。
- 分析循环 run()：从 deque 取最新帧，按 analyze_fps 节流跳帧，运行
  motion 门控 → 多检测器 → IoUTracker → 布控检测；仅业务算法规则命中时截图并报警。
- FPS 计数：每秒滚动刷新 self._analysis_fps，供 openStatus 实时展示。

事件通过 callback 上报给上层服务层（review/timeline/tracking），本模块不直接访问 ORM。
"""
import collections
import logging
import os
import threading
import time

from app.analysis.frames import FrameSource
from app.analysis.motion import MotionDetector
from app.analysis.tracker import IoUTracker

logger = logging.getLogger("analysis.pipeline")

try:
    import cv2
    _CV2_AVAILABLE = True
except Exception:
    cv2 = None
    _CV2_AVAILABLE = False

# 快照保存目录（相对项目根/static/storage/snapshots/）
_SNAPSHOT_DIRNAME = "snapshots"
_SNAPSHOT_MAX_PER_MIN = 60  # 每路每分钟最多快照数，避免磁盘暴涨


class CameraPipeline(object):
    """单摄像头分析流水线（解码线程 + 分析线程分离）"""

    def __init__(self, stream_id, stream_code, rtsp_url,
                 detector=None,
                 detectors=None,
                 motion=None,
                 target_fps=5,
                 analyze_fps=None,
                 on_event=None,
                 on_track_snapshot=None,
                 zone_polygons=None,
                 storage_alarm_dir=None,
                 static_dir=None,
                 queue_size=2):
        self.stream_id = stream_id
        self.stream_code = stream_code
        self.rtsp_url = rtsp_url
        # 子进程内不可 import GlobalUtils/Django，路径由 AnalysisManager 注入
        self._storage_alarm_dir = storage_alarm_dir or ""
        self._static_dir = static_dir or ""
        self.target_fps = target_fps
        # analyze_fps：算法分析频率（帧/秒），支持小于 1（如 2 秒 1 帧 = 0.5）
        fps = float(analyze_fps if analyze_fps is not None else target_fps)
        self.analyze_fps = fps if fps > 0 else 1.0
        self._analyze_interval = 1.0 / self.analyze_fps

        # 多检测器：list[dict(algorithm_id, algorithm_name, engine)]
        self._detectors = list(detectors or [])
        # 兼容旧调用：单 detector 入参也并入 _detectors
        if detector is not None and not self._detectors:
            self._detectors = [{"algorithm_id": 0, "algorithm_name": "legacy", "engine": detector}]
        # _detector 指向首个引擎，便于 info() / 兼容外部访问
        self._detector = self._detectors[0]["engine"] if self._detectors else None
        self._algorithm_name = (", ".join(d["algorithm_name"] for d in self._detectors)
                                if self._detectors else "motion-only")

        self._motion = motion or MotionDetector()
        self._tracker = IoUTracker()
        self._frame_source = FrameSource(rtsp_url, target_fps=target_fps)
        self._on_event = on_event or (lambda *a, **kw: None)
        self._on_track_snapshot = on_track_snapshot or (lambda *a, **kw: None)
        self.zone_polygons = zone_polygons or []

        # 解码/分析分离
        self._frame_queue = collections.deque(maxlen=max(1, int(queue_size)))
        self._queue_lock = threading.Lock()
        self._decode_thread = None
        self._decode_running = False

        # 帧计数与 FPS
        self._frame_index = 0
        self._decoded_count = 0
        self._analyzed_count = 0
        self._dropped_count = 0
        self._analysis_fps = 0.0
        self._decode_fps = 0.0
        self._fps_window_ts = time.time()
        self._fps_window_analyzed = 0
        self._fps_window_decoded = 0
        self._last_analyze_ts = 0.0

        self._running = False
        self._last_zone_state = {}  # track_id -> set(zone_ids)
        self._track_enter_ts = {}   # (track_id, zone_id) -> ts（滞留计时）
        self._last_w = 0
        self._last_h = 0
        self._last_frame = None     # 最近一帧（供事件触发时绘制快照）
        # 快照节流：每路每分钟上限
        self._snapshot_times = collections.deque(maxlen=_SNAPSHOT_MAX_PER_MIN)
        self._llm_zone_last_ts = {}     # (zone_id, biz_id) -> ts
        self._llm_track_last_ts = {}    # (track_id, biz_id) -> ts
        self._loiter_fired = set()      # (track_id, zone_id, biz_id) 本次停留已报滞留（按算法独立）
        # 扩展后处理运行时状态
        self._track_centers = {}        # track_id -> (cx, cy) 上一帧中心，用于越线/方向判断
        self._line_cross_fired = set()  # (track_id, zone_id, biz_id) 本次已报越线（避免重复）
        self._density_fired = set()     # (zone_id, biz_id) 本次密度已报警（按算法独立，目标数降回前不重复）
        self._direction_fired = set()   # (track_id, zone_id, biz_id) 方向报警去重

    def reset_zone_runtime_state(self):
        """热更新布控后清空区域/LLM/滞留运行时状态"""
        self._last_zone_state = {}
        self._track_enter_ts = {}
        self._llm_zone_last_ts = {}
        self._llm_track_last_ts = {}
        self._loiter_fired = set()
        self._track_centers = {}
        self._line_cross_fired = set()
        self._density_fired = set()
        self._direction_fired = set()

    def set_analyze_fps(self, analyze_fps):
        fps = float(analyze_fps)
        if fps <= 0:
            fps = 1.0
        self.analyze_fps = fps
        self._analyze_interval = 1.0 / fps
        logger.info("pipeline[%s] 分析频率调整为 %.3f fps (间隔 %.2fs)",
                    self.stream_code, fps, self._analyze_interval)

    def _frame_size(self, frame_index):
        return self._last_h, self._last_w

    @staticmethod
    def _scale_zone(coords, w, h):
        if not coords or w <= 0 or h <= 0:
            return coords
        out = []
        for p in coords:
            try:
                nx, ny = float(p[0]), float(p[1])
            except Exception:
                continue
            if nx > 1.0 or ny > 1.0:
                return coords
            out.append((nx * w, ny * h))
        return out

    # ============ 解码线程 ============
    def _decode_loop(self):
        try:
            self._frame_source.open()
        except Exception as e:
            logger.error("pipeline[%s] 打开流失败: %s" % (self.stream_code, str(e)))
            self._running = False
            return
        logger.info("pipeline[%s] 解码线程启动 url=%s" % (self.stream_code, self.rtsp_url))
        while self._decode_running and self._running:
            try:
                ok, frame = self._frame_source.read()
                if not ok or frame is None:
                    time.sleep(0.05)
                    continue
                with self._queue_lock:
                    if len(self._frame_queue) >= self._frame_queue.maxlen:
                        # deque 满会自动丢最旧，这里手动统计丢弃数
                        self._dropped_count += 1
                    self._frame_queue.append(frame)
                self._decoded_count += 1
                self._fps_window_decoded += 1
            except Exception as e:
                logger.warning("pipeline[%s] 解码异常: %s" % (self.stream_code, str(e)))
                time.sleep(0.1)
        try:
            self._frame_source.close()
        except Exception:
            pass
        logger.info("pipeline[%s] 解码线程退出 (decoded=%d dropped=%d)"
                    % (self.stream_code, self._decoded_count, self._dropped_count))

    def _pop_latest_frame(self):
        """取队列里最新一帧，丢弃中间帧（保证分析总是处理最近画面）"""
        with self._queue_lock:
            if not self._frame_queue:
                return None
            # 取最右（最新），清空其余
            frame = self._frame_queue[-1]
            self._frame_queue.clear()
            return frame

    # ============ 分析循环 ============
    def run(self):
        self._running = True
        self._decode_running = True
        self._decode_thread = threading.Thread(
            target=self._decode_loop, name="decode-%s" % self.stream_id, daemon=True)
        self._decode_thread.start()
        logger.info("pipeline[%s] 分析循环启动 analyze_fps=%.3f interval=%.2fs detectors=%d"
                    % (self.stream_code, self.analyze_fps, self._analyze_interval, len(self._detectors)))
        try:
            while self._running:
                frame = self._pop_latest_frame()
                if frame is None:
                    time.sleep(0.02)
                    continue
                # 跳帧节流：未到分析间隔则丢弃此帧
                now = time.time()
                if now - self._last_analyze_ts < self._analyze_interval:
                    continue
                self._last_analyze_ts = now
                self._frame_index += 1
                self._analyzed_count += 1
                self._fps_window_analyzed += 1
                try:
                    self._last_h, self._last_w = frame.shape[:2]
                except Exception:
                    pass
                self._last_frame = frame
                try:
                    self._process_frame(frame)
                except Exception as e:
                    logger.warning("pipeline[%s] 处理帧异常: %s" % (self.stream_code, str(e)))
                self._refresh_fps()
        except Exception as e:
            logger.exception("pipeline[%s] 异常: %s" % (self.stream_code, str(e)))
        finally:
            self._running = False
            self._decode_running = False
            try:
                if self._decode_thread and self._decode_thread.is_alive():
                    self._decode_thread.join(timeout=2)
            except Exception:
                pass
            logger.info("pipeline[%s] 已停止 (analyzed=%d)" % (self.stream_code, self._analyzed_count))

    def _refresh_fps(self):
        """每 1 秒滚动刷新一次解码/分析 FPS"""
        now = time.time()
        elapsed = now - self._fps_window_ts
        if elapsed >= 1.0:
            self._analysis_fps = self._fps_window_analyzed / elapsed
            self._decode_fps = self._fps_window_decoded / elapsed
            self._fps_window_analyzed = 0
            self._fps_window_decoded = 0
            self._fps_window_ts = now

    def _process_frame(self, frame):
        motion_boxes = self._motion.detect(frame)
        has_motion = len(motion_boxes) > 0

        detections = []
        if has_motion:
            if self._detectors:
                # 多检测器：依次推理，合并结果，每条标注来源算法
                for d in self._detectors:
                    eng = d.get("engine")
                    if not eng or not eng.ready():
                        continue
                    try:
                        res = eng.detect(frame)
                    except Exception as e:
                        logger.warning("pipeline[%s] 检测器 %s 异常: %s"
                                       % (self.stream_code, d.get("algorithm_name"), str(e)))
                        continue
                    algo_id = d.get("algorithm_id")
                    algo_name = d.get("algorithm_name")
                    for r in res:
                        r["algorithm_id"] = algo_id
                        r["algorithm_name"] = algo_name
                    detections.extend(res)
            # 无小模型检测器时不伪造 motion 目标；流程2 仍由 _check_llm_zones 按业务规则报警

        active, ended, new_tracks, frame_index = self._tracker.update(detections, self._frame_index)

        for tid in new_tracks:
            tr = next((t for t in active if t["track_id"] == tid), None)
            if tr:
                self._on_event({
                    "stream_id": self.stream_id,
                    "stream_code": self.stream_code,
                    "type": "object_start",
                    "track_id": tid,
                    "label": tr.get("label", "unknown"),
                    "box": tr.get("box"),
                    "score": tr.get("score", 0),
                    "timestamp": time.time(),
                })

        # 已停用每帧 on_track_snapshot 回调：
        # 原实现会每帧调 touch_tracks 写 DB（last_seen/duration/confidence），
        # 非报警却高频写库，是布控期间 SQLite 写锁与页面卡顿的主要来源。
        # 现仅保留 object_start/object_end 事件 + 业务报警事件写库，
        # 满足"仅业务算法报警才写入"的要求。
        # self._on_track_snapshot(self.stream_id, frame_index, active, has_motion)

        for tid in ended:
            self._on_event({
                "stream_id": self.stream_id,
                "stream_code": self.stream_code,
                "type": "object_end",
                "track_id": tid,
                "timestamp": time.time(),
            })

        self._check_zones(active, frame_index, frame)

        if has_motion:
            self._check_llm_zones(frame, motion_boxes)

    def _emit_biz_alarm(self, event_type, frame, tr, zone_cfg, biz_rule, track_id, zone_id, box, now, **extra):
        """仅业务算法规则命中时：截图、生成描述、上报报警事件。"""
        if not biz_rule:
            return False
        snap_path = self._save_alarm_snapshot(frame, tr, zone_cfg, event_type)
        evt = {
            "stream_id": self.stream_id,
            "stream_code": self.stream_code,
            "type": event_type,
            "track_id": track_id,
            "zone_id": zone_id,
            "label": (tr or {}).get("label", ""),
            "timestamp": now,
            "box": box,
            "snapshot_path": snap_path,
        }
        evt.update(extra)
        self._attach_alarm_context(evt, event_type, tr or {}, zone_cfg, biz_rule)
        self._on_event(evt)
        return True

    def _matched_area_rules(self, tr, zone_cfg):
        """旧名兼容：仅返回 AREA 后处理的匹配规则"""
        from app.analysis.biz_rules import matched_area_rules
        rules = (zone_cfg or {}).get("biz_algorithms") or []
        if not rules:
            return []
        return matched_area_rules(tr, zone_cfg)

    def _matched_rules(self, tr, zone_cfg):
        """统一调度：返回与当前目标匹配的所有后处理规则（AREA/LINE_CROSS/DIRECTION/DENSITY/DWELL）"""
        from app.analysis.biz_rules import matched_rules_for_track
        rules = (zone_cfg or {}).get("biz_algorithms") or []
        if not rules:
            return []
        return matched_rules_for_track(tr, zone_cfg)

    def _should_alarm_track_in_zone(self, tr, zone_cfg):
        """该目标在区域内是否需要被关注（命中任意后处理规则）"""
        rules = (zone_cfg or {}).get("biz_algorithms") or []
        if not rules:
            return False
        return len(self._matched_rules(tr, zone_cfg)) > 0

    def _attach_alarm_context(self, event, event_type, tr, zone_cfg, biz_rule=None):
        from app.analysis.biz_rules import build_alarm_context
        ctx = build_alarm_context(event_type, tr, zone_cfg, biz_rule)
        event.update(ctx)
        if ctx.get("alarm_reason"):
            event["description"] = ctx["alarm_reason"]
        return event

    def _llm_verify_track(self, frame, tr, biz_rule):
        """流程3：对大模型做二次校验"""
        llm = biz_rule.get("llm") or {}
        flow = int(biz_rule.get("flow_type") or 0)
        if flow == 3 and (not llm or not biz_rule.get("llm_prompt")):
            logger.warning("pipeline[%s] 流程3 缺少 LLM 配置，跳过报警" % self.stream_code)
            return False
        if not llm or not biz_rule.get("llm_prompt"):
            return True
        tid = tr.get("track_id")
        key = (tid, biz_rule.get("id"))
        now = time.time()
        if now - self._llm_track_last_ts.get(key, 0) < 6.0:
            return False
        if not _CV2_AVAILABLE or frame is None:
            return False
        box = tr.get("box") or []
        if len(box) < 4:
            return False
        try:
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = [int(v) for v in box]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 <= x1 or y2 <= y1:
                return False
            crop = frame[y1:y2, x1:x2]
            ok, buf = cv2.imencode('.jpg', crop)
            if not ok:
                return False
            from app.utils.LLMUtils import LLMUtils
            utils = LLMUtils(
                llm.get("api_url"), llm.get("api_key"), llm.get("timeout", 30),
                llm.get("inference_tool", "OpenAI"), llm.get("model_name"),
            )
            result = utils.infer(biz_rule.get("llm_prompt", ""), buf.tobytes())
            passed = LLMUtils.check_happen(result, biz_rule.get("llm_validate", ""))
            # 无论 LLM 判定是否通过，都更新冷却时间，避免每帧反复调用 LLM API
            self._llm_track_last_ts[key] = now
            return passed
        except Exception as e:
            logger.warning("pipeline[%s] LLM 校验失败: %s" % (self.stream_code, str(e)))
            return False

    def _flow3_needs_llm(self, zone_cfg, tr, post_process=None):
        """查找匹配当前目标的 flow3 业务算法（小模型+大模型）。
        post_process 指定时只匹配该后处理类型，否则匹配所有类型。
        """
        for r in (zone_cfg or {}).get("biz_algorithms") or []:
            if int(r.get("flow_type") or 0) != 3:
                continue
            if post_process and r.get("post_process") != post_process:
                continue
            from app.analysis.biz_rules import matched_rules_for_track
            # 复用统一匹配逻辑判断该规则是否命中当前目标
            matched = matched_rules_for_track(tr, {"biz_algorithms": [r]})
            if matched:
                return r
        return None

    def _check_llm_zones(self, frame, motion_boxes):
        """流程2：纯大模型 + 区域运动触发"""
        if not _CV2_AVAILABLE or frame is None or not motion_boxes:
            return
        from app.analysis.biz_rules import llm_rules_for_zone
        from app.utils.LLMUtils import LLMUtils
        h, w = frame.shape[:2]
        now = time.time()
        for z in self.zone_polygons:
            for rule in llm_rules_for_zone(z):
                if int(rule.get("flow_type") or 0) != 2:
                    continue
                key = (z.get("id"), rule.get("id"))
                if now - self._llm_zone_last_ts.get(key, 0) < 8.0:
                    continue
                coords = self._scale_zone(z.get("coords", []), w, h)
                motion_in = False
                hit_box = None
                for mb in motion_boxes:
                    box = mb.get("box") or []
                    if len(box) >= 4:
                        cx = (box[0] + box[2]) / 2
                        cy = (box[1] + box[3]) / 2
                        if self._point_in_polygon((cx, cy), coords):
                            motion_in = True
                            hit_box = box
                            break
                if not motion_in:
                    continue
                llm = rule.get("llm") or {}
                try:
                    ok, buf = cv2.imencode('.jpg', frame)
                    if not ok:
                        continue
                    utils = LLMUtils(
                        llm.get("api_url"), llm.get("api_key"), llm.get("timeout", 30),
                        llm.get("inference_tool", "OpenAI"), llm.get("model_name"),
                    )
                    result = utils.infer(rule.get("llm_prompt", ""), buf.tobytes())
                    if not LLMUtils.check_happen(result, rule.get("llm_validate", "")):
                        # LLM 判定无事件，仍更新冷却时间避免每帧反复调用 API
                        self._llm_zone_last_ts[key] = now
                        continue
                    self._llm_zone_last_ts[key] = now
                    tr_stub = {"box": hit_box, "label": "llm", "track_id": 0}
                    self._emit_biz_alarm(
                        "entered_zone", frame, tr_stub, z, rule,
                        track_id=0, zone_id=z.get("id"), box=hit_box, now=now,
                    )
                except Exception as e:
                    logger.warning("pipeline[%s] LLM 区域分析失败: %s" % (self.stream_code, str(e)))

    def _check_zones(self, active, frame_index, frame):
        now = time.time()
        h, w = self._frame_size(frame_index)
        cur_state = {}
        # 统计每个区域内的目标数（用于 DENSITY 后处理）
        zone_density_count = {}  # zone_id -> count

        for tr in active:
            tid = tr["track_id"]
            box = tr["box"]
            cx = (box[0] + box[2]) / 2
            cy = (box[1] + box[3]) / 2
            physical_in = set()
            for z in self.zone_polygons:
                coords = self._scale_zone(z.get("coords", []), w, h)
                if self._point_in_polygon((cx, cy), coords):
                    physical_in.add(z.get("id"))
                    zone_density_count[z.get("id")] = zone_density_count.get(z.get("id"), 0) + 1
            prev = self._last_zone_state.get(tid, set())
            confirmed = set(prev & physical_in)

            for zid in physical_in - prev:
                zone_cfg = next((z for z in self.zone_polygons if z.get("id") == zid), None)
                if not self._should_alarm_track_in_zone(tr, zone_cfg):
                    confirmed.add(zid)
                    continue
                flow3_rule = self._flow3_needs_llm(zone_cfg, tr)
                if flow3_rule and not self._llm_verify_track(frame, tr, flow3_rule):
                    continue
                matched_rules = self._matched_rules(tr, zone_cfg)
                # AREA/DWELL：每个匹配的算法都独立触发 entered_zone 事件
                area_like = [r for r in matched_rules if r.get("post_process") in ("AREA", "DWELL")]
                fired_any = False
                if flow3_rule:
                    # flow3 走 LLM 校验通过后报 entered_zone
                    if self._emit_biz_alarm(
                        "entered_zone", frame, tr, zone_cfg, flow3_rule,
                        track_id=tid, zone_id=zid, box=box, now=now,
                    ):
                        fired_any = True
                else:
                    for r in area_like:
                        if self._emit_biz_alarm(
                            "entered_zone", frame, tr, zone_cfg, r,
                            track_id=tid, zone_id=zid, box=box, now=now,
                        ):
                            fired_any = True
                if fired_any or matched_rules:
                    # 命中任意后处理即记录进入时间，供后续 loiter/line_cross/direction/density 判断
                    self._track_enter_ts[(tid, zid)] = now
                    confirmed.add(zid)

            for zid in prev - physical_in:
                self._on_event({
                    "stream_id": self.stream_id, "stream_code": self.stream_code,
                    "type": "left_zone", "track_id": tid, "zone_id": zid,
                    "label": tr["label"], "timestamp": now,
                })
                self._track_enter_ts.pop((tid, zid), None)
                # 清理该目标在该区域所有算法的滞留标记
                for lk in list(self._loiter_fired):
                    if lk[0] == tid and lk[1] == zid:
                        self._loiter_fired.discard(lk)
                # 清理该目标在该区域的所有越线标记
                for key in list(self._line_cross_fired):
                    if key[0] == tid and key[1] == zid:
                        self._line_cross_fired.discard(key)
                # 清理该目标在该区域的所有方向报警标记
                for key in list(self._direction_fired):
                    if key[0] == tid and key[1] == zid:
                        self._direction_fired.discard(key)

            for zid in confirmed:
                ts = self._track_enter_ts.get((tid, zid))
                if not ts:
                    continue
                zone_cfg = next((z for z in self.zone_polygons if z.get("id") == zid), None)
                matched_rules = self._matched_rules(tr, zone_cfg)
                if not matched_rules:
                    continue

                # —— DWELL / AREA 滞留报警：每个匹配的 AREA/DWELL 算法独立触发 ——
                threshold = (zone_cfg or {}).get("loiter_threshold", 0)
                if threshold and (now - ts) >= threshold:
                    dwell_rules = [r for r in matched_rules if r.get("post_process") in ("AREA", "DWELL")]
                    flow3_rule = self._flow3_needs_llm(zone_cfg, tr)
                    if flow3_rule and not self._llm_verify_track(frame, tr, flow3_rule):
                        rules_to_fire = []  # flow3 校验失败，跳过滞留
                    else:
                        rules_to_fire = [flow3_rule] if flow3_rule else dwell_rules
                    for matched in rules_to_fire:
                        biz_id = matched.get("id")
                        if (tid, zid, biz_id) in self._loiter_fired:
                            continue  # 该算法本次停留已报过，不重复
                        tr_loiter = dict(tr)
                        tr_loiter["duration"] = now - ts
                        evt_type = "dwell" if matched.get("post_process") == "DWELL" else "loiter"
                        if self._emit_biz_alarm(
                            evt_type, frame, tr_loiter, zone_cfg, matched,
                            track_id=tid, zone_id=zid, box=box, now=now,
                            duration=now - ts,
                        ):
                            self._loiter_fired.add((tid, zid, biz_id))

                # —— LINE_CROSS 越线检测 ——
                prev_center = self._track_centers.get(tid)
                cur_center = (cx, cy)
                line_rules = [r for r in matched_rules if r.get("post_process") == "LINE_CROSS"]
                for lr in line_rules:
                    key = (tid, zid, lr.get("id"))
                    if key in self._line_cross_fired:
                        continue
                    # 警戒线：zone 的 line_a/line_b 字段（坐标归一化 0~1）
                    line_a = (zone_cfg or {}).get("line_a")
                    line_b = (zone_cfg or {}).get("line_b")
                    if not line_a or not line_b:
                        continue
                    # 缩放到像素坐标
                    ax = float(line_a[0]) * w
                    ay = float(line_a[1]) * h
                    bx = float(line_b[0]) * w
                    by = float(line_b[1]) * h
                    if prev_center and self._cross_line(prev_center, cur_center, (ax, ay), (bx, by)):
                        flow3_rule = self._flow3_needs_llm(zone_cfg, tr, post_process="LINE_CROSS") if lr.get("flow_type") == 3 else None
                        if flow3_rule and not self._llm_verify_track(frame, tr, flow3_rule):
                            continue
                        if self._emit_biz_alarm(
                            "line_cross", frame, tr, zone_cfg, lr,
                            track_id=tid, zone_id=zid, box=box, now=now,
                        ):
                            self._line_cross_fired.add(key)

                # —— DIRECTION 方向入侵 ——
                dir_rules = [r for r in matched_rules if r.get("post_process") == "DIRECTION"]
                for dr in dir_rules:
                    if prev_center:
                        dx = cur_center[0] - prev_center[0]
                        dy = cur_center[1] - prev_center[1]
                        ref_angle = float(dr.get("ref_angle", 90.0))
                        tol = float(dr.get("angle_tolerance", 45.0))
                        if self._direction_match(dx, dy, ref_angle, tol):
                            flow3_rule = self._flow3_needs_llm(zone_cfg, tr, post_process="DIRECTION") if dr.get("flow_type") == 3 else None
                            if flow3_rule and not self._llm_verify_track(frame, tr, flow3_rule):
                                continue
                            # 方向匹配：去重节流（同目标同区域同算法 60 秒内只报一次）
                            dir_key = (tid, zid, dr.get("id"))
                            if dir_key in self._direction_fired:
                                continue
                            if self._emit_biz_alarm(
                                "direction", frame, tr, zone_cfg, dr,
                                track_id=tid, zone_id=zid, box=box, now=now,
                            ):
                                self._direction_fired.add(dir_key)

                # 记录中心点供下一帧使用（移到循环外，避免多区域时覆盖 prev_center）
                # 见下方统一更新

            cur_state[tid] = confirmed
            # 统一更新 track_centers：每帧每目标只更新一次，避免多区域循环内覆盖
            self._track_centers[tid] = (cx, cy)

        # —— DENSITY 密度报警（区域级，每帧检查）：每个匹配的密度算法独立触发 ——
        for z in self.zone_polygons:
            zid = z.get("id")
            density_rules = [r for r in (z.get("biz_algorithms") or [])
                             if r.get("post_process") == "DENSITY" and int(r.get("flow_type") or 0) in (1, 3)]
            if not density_rules:
                continue
            count = zone_density_count.get(zid, 0)
            threshold = int(z.get("density_threshold", 0))
            if not threshold or count < threshold:
                # 密度降回，清理该区域所有算法的已报警标记
                for dk in list(self._density_fired):
                    if dk[0] == zid:
                        self._density_fired.discard(dk)
                continue
            # 每个匹配的密度算法独立触发报警
            for dr in density_rules:
                biz_id = dr.get("id")
                if (zid, biz_id) in self._density_fired:
                    continue  # 该算法本次密度已报过，不重复
                tr_stub = {"density_count": count, "label": "—", "track_id": 0}
                if self._emit_biz_alarm(
                    "density", frame, tr_stub, z, dr,
                    track_id=0, zone_id=zid, box=None, now=now,
                    density_count=count,
                ):
                    self._density_fired.add((zid, biz_id))

        for tid in list(self._last_zone_state.keys()):
            if tid not in cur_state:
                self._last_zone_state.pop(tid, None)
                self._track_centers.pop(tid, None)
                for key in list(self._track_enter_ts.keys()):
                    if key[0] == tid:
                        self._track_enter_ts.pop(key, None)
                # 清理已结束目标的报警去重标记，避免内存泄漏
                for fk in list(self._loiter_fired):
                    if fk[0] == tid:
                        self._loiter_fired.discard(fk)
                for fk in list(self._line_cross_fired):
                    if fk[0] == tid:
                        self._line_cross_fired.discard(fk)
                for fk in list(self._direction_fired):
                    if fk[0] == tid:
                        self._direction_fired.discard(fk)
        self._last_zone_state = cur_state

    def _cross_line(self, prev_pt, cur_pt, line_a, line_b):
        from app.analysis.biz_rules import cross_line_segment
        return cross_line_segment(prev_pt, cur_pt, line_a, line_b)

    def _direction_match(self, dx, dy, ref_angle_deg, tolerance_deg):
        from app.analysis.biz_rules import direction_match
        return direction_match(dx, dy, ref_angle_deg, tolerance_deg)

    def _alarm_snapshot_dir(self):
        """返回当日报警快照目录绝对路径：{storageAlarmDir}/{stream_code}/{YYYYMMDD}/"""
        from datetime import datetime as _dt
        base = self._storage_alarm_dir or os.path.join(os.getcwd(), "static", "storage", "alarm")
        day = _dt.now().strftime("%Y%m%d")
        code = "".join(c for c in str(self.stream_code or "unknown") if c.isalnum() or c in "_-") or "unknown"
        d = os.path.join(base, code, day)
        try:
            os.makedirs(d, exist_ok=True)
        except Exception as e:
            logger.warning("pipeline[%s] 创建快照目录失败 %s: %s" % (self.stream_code, d, e))
        return d

    def _alarm_rel_path(self, fname):
        """根据绝对路径计算浏览器可访问的相对路径（相对 static/ 根目录）"""
        import datetime as _dt2
        code = "".join(c for c in str(self.stream_code or "unknown") if c.isalnum() or c in "_-") or "unknown"
        day = _dt2.datetime.now().strftime("%Y%m%d")
        static_root = self._static_dir or os.path.join(os.getcwd(), "static")
        abs_path = os.path.join(self._alarm_snapshot_dir(), fname)
        try:
            rel = os.path.relpath(abs_path, static_root).replace("\\", "/")
            if rel.startswith(".."):
                raise ValueError("snapshot outside static root")
            return rel
        except Exception:
            return "storage/alarm/%s/%s/%s" % (code, day, fname)

    def _save_alarm_snapshot(self, frame, track, zone_cfg, event_type):
        """绘制检测框 + 区域多边形 + 标签后保存 JPEG，返回相对 static/ 的路径；失败返回 ''"""
        if not _CV2_AVAILABLE or frame is None:
            if not _CV2_AVAILABLE:
                logger.warning("pipeline[%s] OpenCV 不可用，无法保存报警快照" % self.stream_code)
            return ""
        now = time.time()
        # 节流：60 秒窗口内超过上限则跳过
        while self._snapshot_times and now - self._snapshot_times[0] > 60.0:
            self._snapshot_times.popleft()
        if len(self._snapshot_times) >= _SNAPSHOT_MAX_PER_MIN:
            return ""
        try:
            import numpy as np
            img = frame.copy()
            h, w = img.shape[:2]
            # 画区域多边形（半透明填充 + 描边）
            if zone_cfg:
                coords = self._scale_zone(zone_cfg.get("coords", []), w, h)
                if coords and len(coords) >= 3:
                    pts = np.array([(int(p[0]), int(p[1])) for p in coords], dtype=np.int32)
                    overlay = img.copy()
                    cv2.fillPoly(overlay, [pts], (22, 159, 133))
                    cv2.addWeighted(overlay, 0.18, img, 0.82, 0, img)
                    cv2.polylines(img, [pts], True, (22, 159, 133), 2)
            # 画检测框 + 标签
            box = track.get("box") or [0, 0, 0, 0]
            x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
            cv2.rectangle(img, (x1, y1), (x2, y2), (220, 38, 38), 2)
            label = str(track.get("label") or "")
            score = track.get("score")
            txt = label + (" %.2f" % score if isinstance(score, (int, float)) else "")
            (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            ty = max(0, y1 - 6)
            cv2.rectangle(img, (x1, max(0, ty - th - 4)), (x1 + tw + 6, ty + 2), (220, 38, 38), -1)
            cv2.putText(img, txt, (x1 + 3, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            # 事件类型角标
            tag = event_type == "loiter" and "LOITER" or "ALARM"
            cv2.rectangle(img, (w - 90, 6), (w - 6, 26), (220, 38, 38), -1)
            cv2.putText(img, tag, (w - 84, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            fname = "%s_%s_%d_%s.jpg" % (self.stream_id, event_type, int(now * 1000), track.get("track_id", "x"))
            fpath = os.path.join(self._alarm_snapshot_dir(), fname)
            cv2.imwrite(fpath, img)
            self._snapshot_times.append(now)
            return self._alarm_rel_path(fname)
        except Exception as e:
            logger.warning("pipeline[%s] 保存快照失败: %s" % (self.stream_code, str(e)))
            return ""

    @staticmethod
    def _point_in_polygon(pt, poly):
        if not poly or len(poly) < 3:
            return False
        x, y = pt
        inside = False
        n = len(poly)
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi):
                inside = not inside
            j = i
        return inside

    # ============ 运行状态 ============
    def status(self):
        return {
            "stream_id": self.stream_id,
            "running": self._running,
            "algorithm_name": self._algorithm_name,
            "engine": self._detector.ENGINE_NAME if self._detector else "",
            "detectors": [{"algorithm_id": d.get("algorithm_id"),
                           "algorithm_name": d.get("algorithm_name"),
                           "engine": d["engine"].ENGINE_NAME if d.get("engine") else ""}
                          for d in self._detectors],
            "frame_index": self._frame_index,
            "decoded_count": self._decoded_count,
            "analyzed_count": self._analyzed_count,
            "dropped_count": self._dropped_count,
            "analysis_fps": round(self._analysis_fps, 1),
            "decode_fps": round(self._decode_fps, 1),
            "analyze_fps_target": self.analyze_fps,
        }

    def stop(self):
        self._running = False
        self._decode_running = False
