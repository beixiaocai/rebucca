# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
import os
import time
import threading
import platform

from django.db import transaction
from app.views.ViewsBase import *
from app.utils.LanguageUtils import GSettingsLangDefault
from app.utils.Utils import GB28181CodeUtils

"""
内部服务调用的接口
"""

# 按code的细粒度锁（不同code完全并发，同一code串行化，防止并发插入重复编号）
_code_locks = {}
_code_locks_guard = threading.Lock()

def _get_code_lock(code):
    """获取指定code的锁对象"""
    with _code_locks_guard:
        if code not in _code_locks:
            _code_locks[code] = threading.Lock()
        return _code_locks[code]

# （内部调用，无需国际化）被rebucca调用，用于修改流（主要是国标等协议）
def api_on_media_update_stream(request):
    ret = False
    msg = "unknown error"

    if request.method == 'POST':
        params = f_parsePostParams(request)
        lang = f_parseRequestLang(request)
        try:
            forward_state = int(params.get("forwardState", 0))
            app = params.get("app")  # 流app
            name = params.get("name")  # 流name（视频通道channelId）
            ip = params.get("ip")  # 设备IP
            port = int(params.get("port", 0))  # 设备SIP通信端口
            clientId = params.get("clientId")  # gb28181注册的client_id
            parentID = params.get("parentID", "")  # 设备连接的sipServer-sipId
            rtpServerPort = int(params.get("rtpServerPort", 0))
            rtpPort = int(params.get("rtpPort", 0))

            pullStreamType = int(params.get("pullStreamType", 0))
            pullStreamUrl = params.get("pullStreamUrl")

            cameraSumNum = int(params.get("cameraSumNum", 1))
            cameraName = params.get("cameraName", "")
            cameraManufacturer = params.get("cameraManufacturer", "")
            cameraModel = params.get("cameraModel", "")
            cameraOwner = params.get("cameraOwner", "")
            cameraCivilCode = params.get("cameraCivilCode", "")

            lastKeepaliveTime = int(params.get("lastKeepaliveTime", 0))
            lastRegisterTime = int(params.get("lastRegisterTime", 0))
            rtpTransferMode = int(params.get("rtpTransferMode", 0))
            rtpTransferAudioType = int(params.get("rtpTransferAudioType", 0))

            if app is None:
                raise Exception("The parameter app is invalid")
            else:
                app = str(app)
            if name is None:
                raise Exception("The parameter name is invalid")
            else:
                name = str(name)
            if ip is None:
                raise Exception("The parameter ip is invalid")
            else:
                ip = str(ip)

            if clientId is None:
                raise Exception("The parameter clientId is invalid")
            else:
                clientId = str(clientId)

            if pullStreamUrl is None:
                raise Exception("The parameter pullStreamUrl is invalid")
            if cameraName is None:
                raise Exception("The parameter cameraName is invalid")

            now_date = datetime.now()

            # 【关键修复】按code的细粒度锁，彻底防止并发插入重复编号
            # 不同code完全并发，同一code串行化
            # 注意：SQLite写锁是数据库级的，不能用transaction.atomic()，否则不同code会互相阻塞报"database is locked"
            code_lock = _get_code_lock(name)
            with code_lock:
                stream = StreamModel.objects.filter(code=name).first()
                if stream:
                    # 编辑（不修改nickname，nickname允许用户自定义）
                    pass
                else:
                    # 新增
                    stream = StreamModel()
                    stream.user_id = 0
                    stream.sort = 0
                    stream.code = name
                    stream.app = app
                    stream.name = name
                    stream.create_time = now_date
                    stream.add_type = 0
                    stream.state = 0
                    stream.nickname = cameraName
                    stream.remark = ""

                stream.forward_state = forward_state
                stream.last_update_time = now_date
                stream.pull_stream_type = pullStreamType
                stream.pull_stream_url = pullStreamUrl
                stream.pull_stream_ip = ip
                stream.pull_stream_port = port

                stream.camera_sum_num = cameraSumNum
                stream.camera_name = cameraName
                stream.camera_manufacturer = cameraManufacturer
                stream.camera_owner = cameraOwner
                stream.camera_model = cameraModel
                stream.camera_civilcode = cameraCivilCode
                stream.camera_device_id = clientId
                stream.camera_parent_id = parentID

                if lastKeepaliveTime > 0:
                    lastKeepaliveTime_date = datetime.fromtimestamp(int(lastKeepaliveTime / 1000))
                    stream.camera_last_keepalive_time = lastKeepaliveTime_date

                if lastRegisterTime > 0:
                    lastRegisterTime_date = datetime.fromtimestamp(int(lastRegisterTime / 1000))
                    stream.camera_last_register_time = lastRegisterTime_date

                stream.pull_stream_transfer_mode = rtpTransferMode
                stream.is_audio = rtpTransferAudioType

                stream.save()

            ret = True
            msg = LANG_VIEWS_T(request, "msg_success")
        except Exception as e:
            msg = str(e)
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")

    res = {
        "code": 1000 if ret else 0,
        "msg": msg
    }
    if not ret:
        g_logger.warning("InnerView.api_on_media_update_stream() res=%s" % str(res))
    return f_responseJson(res)

# （内部调用，无需国际化）被GB28181SipServer调用，用于删除回退通道的数据库记录
def api_on_media_delete_stream(request):
    ret = False
    msg = "unknown error"

    if request.method == 'POST':
        try:
            params = f_parsePostParams(request)
            code = params.get("code")
            if not code:
                raise Exception("The parameter code is invalid")

            stream = StreamModel.objects.filter(code=code).first()
            if stream:
                stream.delete()
                g_gb28181SipServer.remove_channel(code)
                ret = True
                msg = "success"
            else:
                msg = "stream not found"
        except Exception as e:
            msg = str(e)
    else:
        msg = "method not supported"

    res = {
        "code": 1000 if ret else 0,
        "msg": msg
    }
    if not ret:
        g_logger.warning("InnerView.api_on_media_delete_stream() res=%s" % str(res))
    return f_responseJson(res)

# （内部调用，无需国际化）被rebucca_zlm调用，用于实时获得推流信息
def api_on_publish(request):
    # ZLMediaKit Hook https://github.com/ZLMediaKit/ZLMediaKit/wiki/MediaServer%E6%94%AF%E6%8C%81%E7%9A%84HTTP-HOOK-API

    ret = False
    msg = "unknown error"

    if request.method == 'POST':
        try:
            params = f_parsePostParams(request)
            lang = f_parseRequestLang(request)

            _app = params.get("app", "").strip()
            _stream = params.get("stream", "").strip()
            _tcp_id = params.get("id", "").strip()
            _schema = params.get("schema", "").strip()
            _ip = params.get("ip", "").strip()
            _port = int(params.get("port", 0))

            if _app == APP_NAME_LIVE:
                # 被动推流（RTSP/RTMP推流到ZLM的live应用）
                stream_code = _stream
                stream = StreamModel.objects.filter(code=stream_code).first()
                now_date = datetime.now()
                if stream:
                    if stream.pull_stream_type == 31 or stream.pull_stream_type == 32:
                        pass
                    else:
                        raise Exception("This stream does not come from passive streaming")
                else:
                    stream = StreamModel()
                    stream.user_id = 0
                    stream.sort = 0
                    stream.code = stream_code
                    stream.app = _app
                    stream.name = _stream
                    stream.create_time = now_date
                    stream.add_type = 0
                    stream.state = 0
                    stream.is_audio = 0  # 默认静音（与手动添加一致）
                    stream.pull_stream_transfer_mode = 0
                    stream.nickname = _stream
                    stream.remark = ""

                    stream.camera_name = _stream
                    stream.camera_manufacturer = _stream
                    stream.camera_device_id = "default"  # 默认分组编号

                if _schema == "rtsp":
                    pullStreamType = 31
                elif _schema == "rtmp":
                    pullStreamType = 32
                else:
                    raise Exception("unsupported schema type, schema=%s" % _schema)

                pullStreamUrl = "%s://%s:%d/%s" % (_schema, _ip, _port, _tcp_id)

                stream.forward_state = 1
                stream.last_update_time = now_date
                stream.pull_stream_type = pullStreamType
                stream.pull_stream_url = pullStreamUrl
                stream.pull_stream_ip = _ip
                stream.pull_stream_port = _port

                stream.save()

                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            elif _app == APP_NAME_RTP:
                # gb28181接入被动接收的推流，默认通过
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            else:
                raise Exception("unsupported app, app=%s" % _app)
        except Exception as e:
            msg = "error %s" % str(e)
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")

    res = {
        "code": 0 if ret else -1,  # 返回-1的请求，推流将会被取消
        "msg": msg
    }
    if not ret:
        g_logger.warning("InnerView.api_on_publish() res=%s" % str(res))

    return f_responseJson(res)

# （内部调用，无需国际化）被rebucca_zlm调用，用于实时获得not found的流信息
def api_on_stream_not_found(request):
    # ZLMediaKit Hook https://github.com/ZLMediaKit/ZLMediaKit/wiki/MediaServer%E6%94%AF%E6%8C%81%E7%9A%84HTTP-HOOK-API
    ret = False
    msg = "unknown error"
    params = None

    if request.method == 'POST':
        params = f_parsePostParams(request)

        _app = params.get("app", "").strip()
        _stream = params.get("stream", "").strip()

        if _app == APP_NAME_RTP:
            # gb28181 流不存在，尝试重新 invite
            stream = StreamModel.objects.filter(code=_stream).first()
            if stream and stream.pull_stream_type == 21:
                __ret, __msg = g_gb28181SipServer.request_invite(
                    client_id=stream.camera_device_id, channel_id=stream.name)
                if __ret:
                    ret = True
                    msg = "success"
                else:
                    msg = __msg
            else:
                msg = "the stream does not exist"
        else:
            msg = "unsupported app"
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")

    if not ret:
        g_logger.warning("InnerView.api_on_stream_not_found() params=%s,msg=%s" % (str(params), msg))

    res = {
        "code": 0,
        "msg": "success"
    }
    return f_responseJson(res)


def t_init_thread():
    g_logger.info("InnerView.t_init_thread()")

    lang = GSettingsLangDefault

    if g_config.autoAddStreamProxy:
        if g_config.autoAddStreamProxySleep > 0:
            time.sleep(g_config.autoAddStreamProxySleep)

        ret, msg = GlobalUtils.addAllStreamProxy(lang=lang)
        g_logger.info("autoAddStreamProxy ret=%d,msg=%s" % (ret,msg))

    i = 0
    report_count = 0
    while True:
        if i > 0 and i % 480 == 0:
            report_count += 1
            CheckServerUtils.reportHeart(report_count=report_count, lang=lang)

        time.sleep(10)

        i += 1

t = threading.Thread(target=t_init_thread)
t.daemon = True
t.start()
