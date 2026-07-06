# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
import os
import time
import json
import platform
import requests
from datetime import datetime
import sys
from framework.settings import BASE_DIR, PROJECT_UA, PROJECT_BUILT, PROJECT_VERSION, PROJECT_FLAG, PROJECT_ADMIN_START_TIMESTAMP
from app.utils.ZLMediaKitApi import ZLMediaKitApi
from app.utils.Config import Config
from app.utils.Logger import CreateLogger
from app.utils.OSSystem import OSSystem
from app.utils.Database import Database
from app.utils.GB28181SipServer import GB28181SipServer

# ========== 应用名常量 ==========
APP_NAME_LIVE = "live"
APP_NAME_RTP = "rtp"
from app.utils.LanguageUtils import LANG_UI_DICT, LANG_VIEWS_USE_LANG_T
from app.models import *

# BASE_DIR 是项目根目录（扁平化后 settings.py 的父父目录即根目录）
# BASE_PARENT_DIR = str(BASE_DIR)  # 扁平化后 BASE_PARENT_DIR 与 BASE_DIR 相同，均在根目录
g_filepath_settings_json = os.path.join(BASE_DIR, "settings.json")
g_filepath_config_json = os.path.join(BASE_DIR, "config.json")

g_config = Config(filepath=g_filepath_config_json)

__log_dir = os.path.join(BASE_DIR, "log")
if not os.path.exists(__log_dir):
    os.makedirs(__log_dir)

__log_name = "%s%s.log" % ("rebucca", datetime.now().strftime("%Y%m%d-%H%M%S"))
g_logger = CreateLogger(filepath=os.path.join(__log_dir, __log_name),
                        is_show_console=False,
                        log_debug=g_config.logDebug)

g_logger.info("%s v%s,%s" % (PROJECT_UA, PROJECT_VERSION, PROJECT_FLAG))
g_logger.info(PROJECT_BUILT)
g_logger.info("g_filepath_config_json=%s" % g_filepath_config_json)
g_logger.info("config.json:%s" % g_config.getStr())
g_logger.info("logDebug=%d" % g_config.logDebug)

__argv_extend = sys.argv[1] if len(sys.argv) >= 2 else None
g_logger.info("argv_extend=%s" % str(__argv_extend))

g_zlm = ZLMediaKitApi(logger=g_logger, config=g_config)
g_database = Database(logger=g_logger)

__config_sip_server = g_config.sipServer
# 启动 SIP 服务器（GB28181接入）
g_gb28181SipServer = GB28181SipServer(
    server_ip=__config_sip_server.get("sipServerIp"),
    server_port=__config_sip_server.get("sipServerPort"),
    server_id=__config_sip_server.get("sipServerId"),
    realm=__config_sip_server.get("sipServerRealm"),
    password=__config_sip_server.get("sipServerPass"),
    sip_server_timeout=__config_sip_server.get("sipServerTimeout"),
    sip_server_expiry=__config_sip_server.get("sipServerExpiry"),
    sip_transfer_mode=__config_sip_server.get("sipTransferMode"),
    rtp_transfer_mode=__config_sip_server.get("rtpTransferMode"),
    rtp_transfer_audio_type=__config_sip_server.get("rtpTransferAudioType"),
    auto_invite_after_rec_cate_log=__config_sip_server.get("autoInviteAfterRecCateLog"),
    admin_host=g_config.adminHost,
    zlm=g_zlm,
    logger=g_logger
)

g_gb28181SipServer.start()

g_pull_stream_types = [
    {"id": 1, "name": "RTSP"},
    {"id": 2, "name": "RTMP"},
    {"id": 3, "name": "FLV"},
    {"id": 4, "name": "HLS"},
    {"id": 21, "name": "GB28181"},
    {"id": 31, "name": "cRTSP"},
    {"id": 32, "name": "cRTMP"}
]

def get_audio_types(lang='zh'):
    """返回音频类型"""
    T = LANG_UI_DICT.get(lang, {})
    result = []
    __audio_types = [
        {"type": 0, "name": "静音", "name_key": "audio_pull_mute"},
        {"type": 1, "name": "原始音频", "name_key": "audio_pull_original"}
    ]
    for audio_type in __audio_types:
        result.append({
            "type": audio_type["type"],
            "name": T.get(audio_type["name_key"], audio_type["name"])
        })
    return result

g_session_key_user = "user"
g_session_key_captcha = "captcha"


def _bool_cfg(v):
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in ("1", "true", "yes", "on")


class GlobalUtils(object):

    @staticmethod
    def addStreamProxy(stream, lang=None):
        """开启流代理（拉流到ZLM）"""
        __ret = False
        __msg = LANG_VIEWS_USE_LANG_T(lang, "msg_unknown_error")

        if stream.pull_stream_type in [1, 2, 3, 4]:
            enable_rtmp = 1 if g_config.isEnableMediaProxyRtmp else 0
            add_key, add_msg = g_zlm.addStreamProxy(app=stream.app,
                                                       name=stream.name,
                                                       origin_url=stream.pull_stream_url,
                                                       is_audio=stream.is_audio,
                                                       enable_rtmp=enable_rtmp)
            if add_key:
                __ret = True
                __msg = LANG_VIEWS_USE_LANG_T(lang, "stream_forward_enabled_success")
            else:
                __msg = add_msg
        elif stream.pull_stream_type == 21:
            __ret, __msg = g_gb28181SipServer.request_invite(client_id=stream.camera_device_id, channel_id=stream.name)
            if __ret:
                __msg = LANG_VIEWS_USE_LANG_T(lang, "stream_forward_enabled_success")
        elif stream.pull_stream_type in [31, 32]:
            __msg = LANG_VIEWS_USE_LANG_T(lang, "media_push_stream_hint")
        else:
            __msg = LANG_VIEWS_USE_LANG_T(lang, "media_protocol_not_supported")
        return __ret, __msg

    @staticmethod
    def addAllStreamProxy(lang=None):
        """开启所有流代理"""
        ret = False
        msg = LANG_VIEWS_USE_LANG_T(lang, "msg_unknown_error")

        online_streams = g_zlm.getMediaList()
        online_stream_dict = {}

        if len(online_streams) == 0:
            g_database.execute("update av_stream set forward_state=0")
        else:
            for d in online_streams:
                an = "{app}_{name}".format(app=d["app"], name=d["name"])
                online_stream_dict[an] = d

        success_count = 0
        error_count = 0
        streams = StreamModel.objects.all()
        for stream in streams:
            stream_an = "{app}_{name}".format(app=stream.app, name=stream.name)
            if online_stream_dict.get(stream_an):
                success_count += 1
            else:
                __add_ret, __add_msg = GlobalUtils.addStreamProxy(stream, lang=lang)
                if __add_ret:
                    stream.forward_state = 1
                    stream.save()
                    success_count += 1
                else:
                    error_count += 1
        ret = True
        msg = LANG_VIEWS_USE_LANG_T(lang, "msg_batch_result") % (success_count, error_count)
        return ret, msg

    @staticmethod
    def delStreamProxy(stream, lang=None):
        """关闭流代理"""
        __ret = False
        __msg = LANG_VIEWS_USE_LANG_T(lang, "msg_unknown_error")

        if stream.pull_stream_type in [1, 2, 3, 4]:
            del_flag, del_msg = g_zlm.delStreamProxy(app=stream.app, name=stream.name)
            if del_flag:
                __ret = True
                __msg = LANG_VIEWS_USE_LANG_T(lang, "media_forward_stop_success")
            else:
                __msg = del_msg
        elif stream.pull_stream_type == 21:
            __ret, __msg = g_gb28181SipServer.request_bye(client_id=stream.camera_device_id, channel_id=stream.name)
            if __ret:
                __msg = LANG_VIEWS_USE_LANG_T(lang, "media_forward_stop_success")
        elif stream.pull_stream_type == 31:
            __ret, __msg = g_zlm.close_streams(schema="rtsp", app=stream.app, name=stream.name)
            if __ret:
                __msg = LANG_VIEWS_USE_LANG_T(lang, "media_forward_stop_success")
        elif stream.pull_stream_type == 32:
            __ret, __msg = g_zlm.close_streams(schema="rtmp", app=stream.app, name=stream.name)
            if __ret:
                __msg = LANG_VIEWS_USE_LANG_T(lang, "media_forward_stop_success")
        else:
            __msg = LANG_VIEWS_USE_LANG_T(lang, "media_protocol_not_supported")
        return __ret, __msg

    @staticmethod
    def delAllStreamProxy(lang=None):
        """关闭所有流代理"""
        online_streams = g_zlm.getMediaList()
        for d in online_streams:
            stream = StreamModel.objects.filter(app=d["app"], name=d["name"]).first()
            if stream:
                __ret, __msg = GlobalUtils.delStreamProxy(stream, lang=lang)
        g_database.execute("update av_stream set forward_state=0")


    @staticmethod
    def apply_runtime_config(before_cfg):
        """保存 config.json 后热更新运行时组件（不重启 Django 进程）。"""
        before_cfg = before_cfg or {}
        after_cfg = g_config.to_dict()
        notes = []

        def _sip_snapshot(cfg):
            sip = dict((cfg or {}).get("sipServer") or {})
            return (
                sip.get("sipServerIp"), sip.get("sipServerPort"), sip.get("sipServerId"),
                sip.get("sipServerRealm"), sip.get("sipServerPass"), sip.get("sipServerTimeout"),
                sip.get("sipServerExpiry"), sip.get("sipTransferMode"), sip.get("rtpTransferMode"),
                sip.get("rtpTransferAudioType"), sip.get("autoInviteAfterRecCateLog"),
            )

        if _sip_snapshot(before_cfg) != _sip_snapshot(after_cfg):
            try:
                GlobalUtils._reload_gb28181_sip()
                g_logger.info("apply_runtime_config: GB28181 SIP reloaded")
            except Exception as e:
                g_logger.warning("apply_runtime_config: GB28181 reload failed: %s", e)
                notes.append("gb28181")

        before_rec = _bool_cfg(before_cfg.get("recordingEnabled"))
        after_rec = bool(g_config.recordingEnabled)
        if after_rec and not before_rec:
            try:
                from app.recording.manager import get_recording_manager
                get_recording_manager()
            except Exception as e:
                g_logger.warning("apply_runtime_config: recording manager: %s", e)

        if before_cfg.get("adminPort") != after_cfg.get("adminPort"):
            notes.append("adminPort")
        if _bool_cfg(before_cfg.get("logDebug")) != bool(g_config.logDebug):
            notes.append("logDebug")

        media_keys = (
            "mediaHttpPort", "mediaRtspPort", "mediaRtmpPort",
            "mediaStartPath", "mediaStartConfigPath", "mediaSecret",
        )
        if any(before_cfg.get(k) != after_cfg.get(k) for k in media_keys):
            notes.append("zlm")

        return notes

    @staticmethod
    def _reload_gb28181_sip():
        global g_gb28181SipServer
        try:
            g_gb28181SipServer.stop()
        except Exception:
            pass
        sip = dict(g_config.sipServer or {})
        g_gb28181SipServer = GB28181SipServer(
            server_ip=sip.get("sipServerIp"),
            server_port=sip.get("sipServerPort"),
            server_id=sip.get("sipServerId"),
            realm=sip.get("sipServerRealm"),
            password=sip.get("sipServerPass"),
            sip_server_timeout=sip.get("sipServerTimeout"),
            sip_server_expiry=sip.get("sipServerExpiry"),
            sip_transfer_mode=sip.get("sipTransferMode"),
            rtp_transfer_mode=sip.get("rtpTransferMode"),
            rtp_transfer_audio_type=sip.get("rtpTransferAudioType"),
            auto_invite_after_rec_cate_log=sip.get("autoInviteAfterRecCateLog"),
            admin_host=g_config.adminHost,
            zlm=g_zlm,
            logger=g_logger,
        )
        g_gb28181SipServer.start()


class CheckServerUtils():
    @staticmethod
    def checkVersion(request_ip, peer_ip, peer_port, lang=None):
        __online = False
        __state = False
        __msg = LANG_VIEWS_USE_LANG_T(lang, "msg_unknown_error")
        __info = {}
        headers = {
            "User-Agent": PROJECT_UA,
            "Content-Type": "application/json;"
        }
        try:
            servicesHost = "http://www.yuturuishi.com"  # 服务地址（不对外）

            url = "%s/api/rebucca/checkVersion" % servicesHost
            osSystem = OSSystem()
            machine_cpu = osSystem.getMachineCpu()

            machineMacs = []

            runInfo = {}
            runInfo["request_ip"] = request_ip
            runInfo["peer_ip"] = peer_ip
            runInfo["peer_port"] = peer_port

            data = {
                "lang": lang,
                "enableUpdatePopup": g_config.isEnableUpdatePopup,
                "flag": PROJECT_FLAG,
                "version": PROJECT_VERSION,
                "machineMacs": machineMacs,
                "finger": "rebucca",
                "msgs": [],
                "runInfo": runInfo,
                "machine_cpu": machine_cpu,
                "machine_version": str(platform.version()),
                "machine_machine": str(platform.machine()),
                "machine_release": str(platform.release()),
                "machine_node": str(platform.node()),
                "machine_architecture": str(platform.architecture()),
                "machine_uname": str(platform.uname()),
                "machine_win32_ver": "",
                "machine_system": str(osSystem.getSystemName()),
                "app_start_timestamp": PROJECT_ADMIN_START_TIMESTAMP,
                "current_timestamp": int(time.time())
            }
            data_json = json.dumps(data)
            res = requests.post(url=url, headers=headers, data=data_json, timeout=30)
            if res.status_code == 200:
                res_result = res.json()
                __msg = res_result["msg"]
                if res_result["code"] == 1000:
                    __info = res_result["data"]
                    __state = True
            else:
                __msg = LANG_VIEWS_USE_LANG_T(lang, "msg_status_code") % res.status_code

            __online = True
        except Exception as e:
            __online = False
            __msg = str(e)
            g_logger.error("CheckServerUtils.checkVersion() e:%s" % str(e))

        return __online, __state, __msg, __info

    @staticmethod
    def reportHeart(report_count, lang=None):
        __state = False
        __msg = LANG_VIEWS_USE_LANG_T(lang, "msg_unknown_error")
        headers = {
            "User-Agent": PROJECT_UA,
            "Content-Type": "application/json;"
        }
        try:
            servicesHost = "http://www.yuturuishi.com"  # 服务地址（不对外）
            url = "%s/api/rebucca/reportHeart" % servicesHost

            osSystem = OSSystem()

            osInfo = osSystem.getOSInfo()

            data = {
                "machineMacs": [],
                "finger": "rebucca",
                "runInfo": {},
                "osInfo": str(osInfo),
                "reportCount": report_count
            }
            data_json = json.dumps(data)

            res = requests.post(url=url, headers=headers, data=data_json, timeout=10)

            if res.status_code == 200:
                res_result = res.json()
                __msg = res_result["msg"]
                if res_result["code"] == 1000:
                    __state = True
            else:
                __msg = LANG_VIEWS_USE_LANG_T(lang, "msg_status_code") % res.status_code
        except Exception as e:
            __msg = str(e)
            g_logger.error("CheckServerUtils.reportHeart() e:%s" % str(e))
