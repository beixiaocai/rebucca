# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""ZLMediaKit (rebucca_zlm) 进程管理 — 启动/停止/重启/状态查询。"""
import logging
import os
import subprocess
import sys
import threading
import time

logger = logging.getLogger("utils.media_server")

_MANAGER = None
_LOCK = threading.Lock()


class MediaServerManager(object):
    def __init__(self):
        self._proc = None
        self._lock = threading.RLock()

    def _paths(self):
        from app.utils.GlobalUtils import g_config
        exe = getattr(g_config, "mediaStartPath", "") or ""
        cfg = getattr(g_config, "mediaStartConfigPath", "") or ""
        return exe, cfg

    def api_alive(self):
        try:
            from app.utils.GlobalUtils import g_zlm
            ok, _msg, _data = g_zlm.getThreadsLoad()
            return bool(ok)
        except Exception as e:
            logger.debug("api_alive: %s", e)
            return False

    def managed_pid(self):
        with self._lock:
            if self._proc is None:
                return None
            if self._proc.poll() is None:
                return self._proc.pid
            self._proc = None
            return None

    def status(self):
        exe, cfg = self._paths()
        pid = self.managed_pid()
        api_ok = self.api_alive()
        return {
            "running": api_ok,
            "api_ok": api_ok,
            "managed": pid is not None,
            "pid": pid or 0,
            "exe": exe,
            "config": cfg,
            "exe_exists": bool(exe and os.path.isfile(exe)),
            "config_exists": bool(cfg and os.path.isfile(cfg)),
        }

    def start(self):
        exe, cfg = self._paths()
        if not exe or not os.path.isfile(exe):
            return False, "mediaStartPath 无效或文件不存在: %s" % (exe or "(空)")
        if not cfg or not os.path.isfile(cfg):
            return False, "mediaStartConfigPath 无效或文件不存在: %s" % (cfg or "(空)")
        if self.api_alive():
            return True, "流媒体服务已在运行"

        work_dir = os.path.dirname(exe) or str(os.getcwd())
        cmd = [exe, "-c", cfg]
        logger.info("启动 ZLM: %s", " ".join(cmd))
        try:
            kwargs = {"cwd": work_dir, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            else:
                kwargs["start_new_session"] = True
            with self._lock:
                self._proc = subprocess.Popen(cmd, **kwargs)
            for _ in range(30):
                time.sleep(0.2)
                if self.api_alive():
                    return True, "流媒体服务已启动 (pid=%s)" % self._proc.pid
            return False, "进程已拉起但 API 未响应，请检查端口与 config.ini"
        except Exception as e:
            logger.exception("启动 ZLM 失败")
            return False, str(e)

    def _kill_by_image(self, exe):
        if not exe:
            return
        name = os.path.basename(exe)
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/IM", name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                )
            else:
                subprocess.run(
                    ["pkill", "-f", exe],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                )
        except Exception as e:
            logger.warning("kill_by_image %s: %s", name, e)

    def stop(self):
        exe, _cfg = self._paths()
        with self._lock:
            proc = self._proc
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                self._proc = None

        if self.api_alive():
            self._kill_by_image(exe)
            time.sleep(0.5)

        if self.api_alive():
            return False, "流媒体服务仍在运行，请检查是否有其他进程占用"
        return True, "流媒体服务已停止"

    def restart(self):
        ok, msg = self.stop()
        if not ok and self.api_alive():
            return False, msg
        time.sleep(0.8)
        return self.start()


def get_media_server_manager():
    global _MANAGER
    with _LOCK:
        if _MANAGER is None:
            _MANAGER = MediaServerManager()
        return _MANAGER
