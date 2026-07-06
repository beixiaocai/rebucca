# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""Rebucca 启动配置 — 所有可配置项均来自 config.json，后台「启动配置」页可编辑。"""
import json
import os

from framework.settings import BASE_DIR


def _resolve_path(path, base=None):
    """相对路径基于项目根目录 BASE_DIR 解析为绝对路径。"""
    base = base or str(BASE_DIR)
    if not path:
        return ""
    p = str(path).strip()
    if not p:
        return ""
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(base, p.replace("\\", "/")))


def _bool(v, default=False):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class Config:
    def __init__(self, filepath):
        self.__filepath = filepath
        config_data = None
        for encoding in ["utf-8", "gbk"]:
            try:
                with open(filepath, "r", encoding=encoding) as f:
                    config_data = json.loads(f.read())
                break
            except Exception as e:
                print("Config.__init__() error:%s,encoding=%s|%s" % (str(e), encoding, str(filepath)))

        if not config_data:
            raise Exception("Config.__init__() read %s error" % str(filepath))

        self.__config_data = config_data
        self._apply(config_data)

    def _apply(self, config_data):
        self.__config_data_str = str(config_data)
        base = str(BASE_DIR)

        # —— 基础 ——
        self.safe = config_data.get("safe", "")
        self.internalHost = "127.0.0.1"
        self.externalHost = config_data.get("host", "127.0.0.1")
        self.adminPort = _int(config_data.get("adminPort"), 10001)

        self.logDebug = _bool(config_data.get("logDebug"), False)
        self.isEnableLoginCaptcha = _bool(config_data.get("isEnableLoginCaptcha"), True)
        self.isEnableUpdatePopup = _bool(config_data.get("isEnableUpdatePopup"), True)

        self.autoAddStreamProxy = _bool(config_data.get("autoAddStreamProxy"), True)
        self.autoAddStreamProxySleep = _int(config_data.get("autoAddStreamProxySleep"), 15)

        # —— 路径与工具 ——
        self.ffmpeg = str(config_data.get("ffmpeg", "ffmpeg") or "ffmpeg").strip()
        self.fontPath = _resolve_path(config_data.get("fontPath", ""), base)
        self.uploadDir = _resolve_path(config_data.get("uploadDir", "static/upload"), base)
        self.storageDir = _resolve_path(config_data.get("storageDir", "static/storage"), base)

        # —— 流媒体 ZLM ——
        self.mediaHttpPort = _int(config_data.get("mediaHttpPort"), 10002)
        self.mediaRtspPort = _int(config_data.get("mediaRtspPort"), 10554)
        self.mediaRtmpPort = _int(config_data.get("mediaRtmpPort"), 10935)
        self.isEnableMediaProxyRtmp = _bool(config_data.get("isEnableMediaProxyRtmp"), False)
        self.mediaSecret = config_data.get("mediaSecret", "")
        self.mediaStartPath = _resolve_path(config_data.get("mediaStartPath", ""), base)
        self.mediaStartConfigPath = _resolve_path(config_data.get("mediaStartConfigPath", ""), base)
        self.autoStartMedia = _bool(config_data.get("autoStartMedia"), False)

        self.adminHost = "http://" + self.internalHost + ":" + str(self.adminPort)
        self.mediaHttpHost = "http://" + self.internalHost + ":" + str(self.mediaHttpPort)

        # —— 视频分析 ——
        self.analysisTargetFps = _int(config_data.get("analysisTargetFps"), 5)
        self.analysisConfThreshold = _float(config_data.get("analysisConfThreshold"), 0.4)
        self.analysisProcessMode = _int(config_data.get("analysisProcessMode"), 1)
        self.analysisSharedInference = _bool(config_data.get("analysisSharedInference"), True)
        self.analysisInferenceWorkers = max(1, _int(config_data.get("analysisInferenceWorkers"), 2))

        # —— 录像 ——
        self.recordingEnabled = _bool(config_data.get("recordingEnabled"), False)
        self.recordingSegmentSeconds = max(60, _int(config_data.get("recordingSegmentSeconds"), 600))
        self.recordingRetainDays = max(0, _int(config_data.get("recordingRetainDays"), 7))
        self.recordingRetainGb = max(0.0, _float(config_data.get("recordingRetainGb"), 0.0))

        # —— GB28181 SIP ——
        __sip = config_data.get("sipServer") or {}
        self.sipServer = {
            "sipServerIp": str(__sip.get("sipServerIp", "127.0.0.1")).strip(),
            "sipServerPort": _int(__sip.get("sipServerPort"), 15060),
            "sipServerNonce": str(__sip.get("sipServerNonce", "")).strip(),
            "sipTransferMode": _int(__sip.get("sipTransferMode"), 0),
            "sipServerId": str(__sip.get("sipServerId", "34020000002000000001")).strip(),
            "sipServerRealm": str(__sip.get("sipServerRealm", "3402000000")).strip(),
            "sipServerPass": str(__sip.get("sipServerPass", "123456")).strip(),
            "sipServerTimeout": _int(__sip.get("sipServerTimeout"), 1800),
            "sipServerExpiry": _int(__sip.get("sipServerExpiry"), 3600),
            "rtpTransferMode": _int(__sip.get("rtpTransferMode"), 0),
            "rtpTransferAudioType": _int(__sip.get("rtpTransferAudioType"), 0),
            "autoInviteAfterRecCateLog": _bool(__sip.get("autoInviteAfterRecCateLog"), True),
        }

        self._ensure_storage_dirs()

    def _ensure_storage_dirs(self):
        for d in (self.uploadDir, self.storageDir):
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
        self.uploadAlgorithmWeightDir = os.path.join(self.uploadDir, "weight")
        self.uploadAudioDir = os.path.join(self.uploadDir, "audio")
        self.uploadAudioDir_www = "/upload/audio/"

        self.storageTempDir = os.path.join(self.storageDir, "temp")
        self.storageAlarmDir = os.path.join(self.storageDir, "alarm")
        self.storageSnapshotsDir = os.path.join(self.storageDir, "snapshots")
        self.storageRecordDir = os.path.join(self.storageDir, "record")
        for d in (self.storageTempDir, self.storageAlarmDir, self.storageSnapshotsDir, self.storageRecordDir):
            if not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
        self.storageDir_www = "/storage/openAccess?filename="

    def getStr(self):
        return self.__config_data_str

    def to_dict(self):
        """供启动配置页 / API 使用的完整配置快照。"""
        d = dict(self.__config_data)
        d.setdefault("sipServer", {})
        # 布尔/int 与内存态保持一致
        d["host"] = self.externalHost
        d["autoAddStreamProxy"] = self.autoAddStreamProxy
        d["autoAddStreamProxySleep"] = self.autoAddStreamProxySleep
        d["isEnableLoginCaptcha"] = self.isEnableLoginCaptcha
        d["logDebug"] = self.logDebug
        d["isEnableUpdatePopup"] = self.isEnableUpdatePopup
        d["isEnableMediaProxyRtmp"] = self.isEnableMediaProxyRtmp
        d["autoStartMedia"] = self.autoStartMedia
        d["analysisSharedInference"] = self.analysisSharedInference
        d["recordingEnabled"] = self.recordingEnabled
        d["sipServer"] = dict(self.sipServer)
        return d

    def save_from_web(self, params):
        """合并 Web 表单并写回 config.json（保留未在表单中的键）。"""
        data = dict(self.__config_data)
        p = params or {}

        def _set(key, val):
            data[key] = val

        for key in ("safe", "ffmpeg", "mediaSecret"):
            if key in p:
                _set(key, str(p.get(key) or "").strip())

        if "host" in p:
            _set("host", str(p.get("host") or "").strip())
        if "uploadDir" in p:
            _set("uploadDir", str(p.get("uploadDir") or "").strip())
        if "storageDir" in p:
            _set("storageDir", str(p.get("storageDir") or "").strip())
        if "fontPath" in p:
            _set("fontPath", str(p.get("fontPath") or "").strip())
        if "mediaStartPath" in p:
            _set("mediaStartPath", str(p.get("mediaStartPath") or "").strip())
        if "mediaStartConfigPath" in p:
            _set("mediaStartConfigPath", str(p.get("mediaStartConfigPath") or "").strip())

        int_keys = (
            "adminPort", "mediaHttpPort", "mediaRtspPort", "mediaRtmpPort",
            "autoAddStreamProxySleep",
            "analysisTargetFps", "analysisProcessMode", "analysisInferenceWorkers",
            "recordingSegmentSeconds", "recordingRetainDays",
        )
        for key in int_keys:
            if key in p:
                _set(key, _int(p.get(key), data.get(key)))

        float_keys = ("analysisConfThreshold", "recordingRetainGb")
        for key in float_keys:
            if key in p:
                _set(key, _float(p.get(key), data.get(key)))

        bool_keys = (
            "autoAddStreamProxy", "isEnableLoginCaptcha", "logDebug", "isEnableUpdatePopup",
            "isEnableMediaProxyRtmp", "autoStartMedia",
            "analysisSharedInference", "recordingEnabled",
        )
        for key in bool_keys:
            if key in p:
                _set(key, _bool(p.get(key), _bool(data.get(key))))

        sip = dict(data.get("sipServer") or {})
        sip_map = {
            "sipServerIp": "sipServerIp",
            "sipServerPort": ("sipServerPort", _int),
            "sipServerNonce": "sipServerNonce",
            "sipTransferMode": ("sipTransferMode", _int),
            "sipServerId": "sipServerId",
            "sipServerRealm": "sipServerRealm",
            "sipServerPass": "sipServerPass",
            "sipServerTimeout": ("sipServerTimeout", _int),
            "sipServerExpiry": ("sipServerExpiry", _int),
            "rtpTransferMode": ("rtpTransferMode", _int),
            "rtpTransferAudioType": ("rtpTransferAudioType", _int),
            "autoInviteAfterRecCateLog": ("autoInviteAfterRecCateLog", _bool),
        }
        for param_key, spec in sip_map.items():
            if param_key not in p:
                continue
            if isinstance(spec, tuple):
                sip_key, conv = spec
                sip[sip_key] = conv(p.get(param_key), sip.get(sip_key))
            else:
                sip[spec] = str(p.get(param_key) or "").strip()
        data["sipServer"] = sip
        for _k in ("install", "code", "name", "describe"):
            data.pop(_k, None)

        with open(self.__filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        self.__config_data = data
        self._apply(data)
