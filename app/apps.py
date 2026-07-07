# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
import os

from django.apps import AppConfig


class AppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app'

    def ready(self):
        # Django runserver 默认带 StatReloader 会启动两个进程：
        #   - 主进程（reloader，RUN_MAIN 未设置）：只负责监听文件变化重启子进程
        #   - 子进程（RUN_MAIN=true）：真正处理 HTTP 请求、运行 AnalysisManager
        # AnalysisManager、推理池等单例资源只能在子进程初始化一次，
        # 否则两个进程会重复启动 pipeline / 推理 worker，互相冲突（端口占用、队列不共享、状态错乱）。
        is_main_worker = os.environ.get("RUN_MAIN") == "true"
        # SQLite 优化：每个新连接执行 PRAGMA
        # - journal_mode=DELETE：传统 rollback journal 模式，只产生一个 rebucca.sqlite3 文件
        # - busy_timeout=5000：写冲突等 5s 而非立即报错
        # - cache_size=-65536：64MB 页缓存
        # - temp_store=MEMORY：临时表用内存
        from django.db.backends.signals import connection_created

        def _setup_sqlite_pragma(sender, connection, **kwargs):
            if connection.vendor != 'sqlite':
                return
            with connection.cursor() as cur:
                cur.execute('PRAGMA journal_mode=DELETE;')
                cur.execute('PRAGMA busy_timeout=5000;')
                cur.execute('PRAGMA cache_size=-65536;')
                cur.execute('PRAGMA temp_store=MEMORY;')

        connection_created.connect(_setup_sqlite_pragma)

        try:
            from app.utils.schema_upgrade import ensure_biz_algorithm_line_count_columns
            ensure_biz_algorithm_line_count_columns()
        except Exception as e:
            import logging
            logging.getLogger("app.bootstrap").warning("schema upgrade: %s", e)

        # 仅在 runserver 的子进程（RUN_MAIN=true）启动后台服务，
        # 避免 reloader 主进程重复初始化 AnalysisManager / 推理池。
        if not is_main_worker:
            return
        import threading
        threading.Thread(target=self._bootstrap_services, name="app-bootstrap", daemon=True).start()

    def _bootstrap_services(self):
        try:
            import time
            time.sleep(2)
            try:
                from app.utils.GlobalUtils import g_config
                if getattr(g_config, "recordingEnabled", False):
                    from app.recording.manager import get_recording_manager
                    get_recording_manager()
            except Exception:
                pass
            try:
                from app.utils.GlobalUtils import g_config
                if getattr(g_config, "autoStartMedia", False):
                    from app.utils.MediaServerManager import get_media_server_manager
                    ok, info = get_media_server_manager().start()
                    import logging
                    logging.getLogger("app.bootstrap").info("autoStartMedia: ok=%s %s", ok, info)
            except Exception as e:
                import logging
                logging.getLogger("app.bootstrap").warning("autoStartMedia: %s", e)
            # 不自动启动布控分析，统一由用户在布控管理页手动点击「启动分析」
        except Exception as e:
            import logging
            logging.getLogger("app.bootstrap").exception("bootstrap: %s", e)
