# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""分析事件桥 — 消费子进程 event_queue，在主进程写库"""
import logging
import queue
import threading

logger = logging.getLogger("analysis.event_bridge")

_BRIDGE = None
_BRIDGE_LOCK = threading.Lock()


class AnalysisEventBridge(object):
    def __init__(self):
        self._thread = None
        self._running = False
        self._queues = []
        self._lock = threading.Lock()

    def register_queue(self, q):
        with self._lock:
            if q not in self._queues:
                self._queues.append(q)

    def unregister_queue(self, q):
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="analysis-event-bridge", daemon=True)
        self._thread.start()
        logger.info("AnalysisEventBridge 已启动")

    def _loop(self):
        while self._running:
            handled = False
            with self._lock:
                queues = list(self._queues)
            for q in queues:
                try:
                    while True:
                        msg = q.get_nowait()
                        self._handle(msg)
                        handled = True
                except queue.Empty:
                    continue
            if not handled:
                threading.Event().wait(0.05)

    def _handle(self, msg):
        if not msg or len(msg) < 2:
            return
        kind, payload = msg[0], msg[1]
        try:
            if kind == "event":
                self._on_event(payload)
            elif kind == "touch":
                self._on_touch(payload)
        except Exception as e:
            logger.exception("事件桥处理失败: %s", e)

    def _on_event(self, event):
        from app.services.alarm_service import write_alarm, ALARM_EVENT_TYPES
        etype = event.get("type", "")
        if etype in ALARM_EVENT_TYPES:
            write_alarm(event)

    def _on_touch(self, payload):
        # 已停用：不再写追踪快照
        pass


def get_event_bridge():
    global _BRIDGE
    with _BRIDGE_LOCK:
        if _BRIDGE is None:
            _BRIDGE = AnalysisEventBridge()
            _BRIDGE.start()
        return _BRIDGE
