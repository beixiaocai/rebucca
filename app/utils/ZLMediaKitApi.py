# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
import requests
from framework.settings import PROJECT_UA
from app.utils import Utils
from app.utils.LanguageUtils import LANG_VIEWS_USE_LANG_T

class ZLMediaKitApi():
    def __init__(self, logger, config):
        self.__logger = logger
        self.__config = config
        self.default_stream_app = "live"
        self.default_push_stream_app = "analyzer"
        self.timeout = 30
        self.__logger.info("ZLMediaKitApi.__init__()")

    def __byteFormat(self, bytes, suffix="bps"):

        factor = 1024
        for unit in ["", "K", "M", "G"]:
            if bytes < factor:
                return f"{bytes:.2f}{unit}{suffix}"
            bytes /= factor

    def get_wsHost(self, request_ip=None):
        __ip = self.__config.externalHost
        if __ip == "0.0.0.0" and request_ip:
            # （v4.725新增） 使用实时请求ip代替逻辑
            __ip = request_ip

        __address = "ws://" + __ip + ":" + str(self.__config.mediaHttpPort)

        return __address

    def get_hlsUrl(self, app, name, request_ip=None):
        __ip = self.__config.externalHost
        if __ip == "0.0.0.0" and request_ip:
            # （v4.725新增） 使用实时请求ip代替逻辑
            __ip = request_ip

        __address = "http://" + __ip + ":" + str(self.__config.mediaHttpPort)
        return "%s/%s/%s.hls.m3u8" % (__address , app, name)

    def get_httpFlvUrl(self, app, name, request_ip=None):
        __ip = self.__config.externalHost
        if __ip == "0.0.0.0" and request_ip:
            # （v4.725新增） 使用实时请求ip代替逻辑
            __ip = request_ip

        __address = "http://" + __ip + ":" + str(self.__config.mediaHttpPort)
        return "%s/%s/%s.live.flv" % (__address, app, name)

    def get_rtspUrl(self, app, name, request_ip=None):
        __ip = self.__config.externalHost
        if __ip == "0.0.0.0" and request_ip:
            # （v4.725新增） 使用实时请求ip代替逻辑
            __ip = request_ip
        __address = "rtsp://" + __ip + ":" + str(self.__config.mediaRtspPort)
        return "%s/%s/%s" % (__address, app, name)
    def get_rtmpUrl(self, app, name, request_ip=None):
        __ip = self.__config.externalHost
        if __ip == "0.0.0.0" and request_ip:
            # （v5.017新增） 使用实时请求ip代替逻辑
            __ip = request_ip
        __address = "rtmp://" + __ip + ":" + str(self.__config.mediaRtmpPort)
        return "%s/%s/%s" % (__address, app, name)
    def get_wsMp4Url(self, app, name, request_ip=None):
        __ip = self.__config.externalHost
        if __ip == "0.0.0.0" and request_ip:
            # （v4.725新增） 使用实时请求ip代替逻辑
            __ip = request_ip
        __address = "ws://" + __ip + ":" + str(self.__config.mediaHttpPort)
        return "%s/%s/%s.live.mp4" % (__address, app, name)

    def get_wsFlvUrl(self, app, name, request_ip=None):
        __ip = self.__config.externalHost
        if __ip == "0.0.0.0" and request_ip:
            # （v4.725新增） 使用实时请求ip代替逻辑
            __ip = request_ip
        __address = "ws://" + __ip + ":" + str(self.__config.mediaHttpPort)
        return "%s/%s/%s.live.flv" % (__address, app, name)

    def get_httpMp4Url(self, app, name, request_ip=None):
        __ip = self.__config.externalHost
        if __ip == "0.0.0.0" and request_ip:
            # （v4.725新增） 使用实时请求ip代替逻辑
            __ip = request_ip
        __address = "http://" + __ip + ":" + str(self.__config.mediaHttpPort)
        return "%s/%s/%s.live.mp4" % (__address, app, name)

    def getThreadsLoad(self):
        __ret = False
        __msg = "zlm.getThreadsLoad()"
        __data = []
        try:
            url = "{host}/index/api/getThreadsLoad".format(host=self.__config.mediaHttpHost)
            params = {
                "secret": self.__config.mediaSecret
            }

            res = requests.post(url, headers={
                "User-Agent": PROJECT_UA
            }, json=params, timeout=self.timeout)

            if res.status_code == 200:
                res_json = res.json()
                # print(res_json)
                if 0 == res_json["code"]:
                    __ret = True
                    __msg = "success"
                    __data = res_json["data"]
                else:
                    raise Exception(str(res_json))
            else:
                raise Exception("status=%d" % res.status_code)

        except Exception as e:
            __msg += " e:%s"%str(e)
            self.__logger.warning(__msg)

        return __ret, __msg, __data

    def addStreamProxy(self, app, name, origin_url, is_audio=0, vhost="__defaultVhost__",enable_rtmp=0):

        __key = None  # 添加成功返回的 "key" : "__defaultVhost__/proxy/0"  流的唯一标识
        __msg = "zlm.addStreamProxy(app=%s,name=%s,origin_url=%s,is_audio=%s)" % (app, name, str(origin_url),str(is_audio))

        try:
            url = "{host}/index/api/addStreamProxy".format(host=self.__config.mediaHttpHost)
            params = {
                "secret": self.__config.mediaSecret,
                'vhost': vhost,
                'app': app,
                'stream': name,
                'url': origin_url
            }
            params["rtp_type"] = 0  # rtsp拉流时，拉流方式，0：tcp，1：udp，2：组播
            # params["timeout_sec"] = 1; #  拉流超时时间，单位秒，float类型
            params["enable_hls"] = 0  # 是否转换成hls协议
            params["enable_mp4"] = 0  # 是否允许mp4录制
            # params["enable_rtsp"] = 1  # 是否转rtsp协议

            if enable_rtmp == 0:
                # 等于0，表示不开启rtmp转发
                params["enable_rtmp"] = 0  # 是否转rtmp / flv协议

            params["enable_ts"] = 0  # 是否转http - ts / ws - ts协议
            # params["enable_fmp4"] = 1  # 是否转http - fmp4 / ws - fmp4协议
            params["enable_audio"] = is_audio  # 转协议时是否开启音频
            params["add_mute_audio"] = 0  # 转协议时，无音频是否添加静音aac音频
            #  params["mp4_save_path"] = "" # mp4录制文件保存根目录，置空使用默认
            #  params["mp4_max_second"] = 1 #  mp4录制切片大小，单位秒
            #  params["hls_save_path"] = "" # hls文件保存保存根目录，置空使用默认

            res = requests.post(url, headers={
                "User-Agent": PROJECT_UA
            }, json=params, timeout=self.timeout)

            if res.status_code == 200:
                res_json = res.json()
                if 0 == res_json["code"]:
                    __key = res_json["data"]["key"]
                    __msg = "success"
                else:
                    raise Exception(str(res_json))

        except Exception as e:
            __msg += " e:%s" % str(e)
            self.__logger.warning(__msg)

        return __key, __msg

    def delStreamProxy(self, app, name, vhost="__defaultVhost__"):

        __flag = False  # "flag" : true  成功与否
        __msg = "zlm.delStreamProxy(app=%s,name=%s)" % (app, name)


        key = "{vhost}/{app}/{name}".format(vhost=vhost, app=app, name=name)

        try:
            url = "{host}/index/api/delStreamProxy?secret={secret}&key={key}".format(
                host=self.__config.mediaHttpHost,
                secret=self.__config.mediaSecret,
                key=key
            )
            res = requests.get(url, headers={
                "User-Agent": PROJECT_UA
            }, timeout=self.timeout)
            if res.status_code == 200:
                res_json = res.json()
                if 0 == res_json["code"]:
                    if res_json["data"]["flag"]:
                        __flag = True
                        __msg = "success"
                    else:
                        raise Exception(str(res_json))
                else:
                    raise Exception(str(res_json))
            else:
                raise Exception("status=%d" % res.status_code)

        except Exception as e:

            __msg += " e:%s" % str(e)
            self.__logger.warning(__msg)

        return __flag, __msg

    def close_streams(self, schema, app, name, vhost="__defaultVhost__"):

        __ret = False
        __msg = "zlm.close_streams(app=%s,name=%s)" % (app, name)

        try:
            url = "{host}/index/api/close_streams?secret={secret}&schema={schema}&vhost={vhost}&app={app}&stream={stream}&force=1".format(
                host=self.__config.mediaHttpHost,
                secret=self.__config.mediaSecret,
                vhost=vhost,
                schema=schema,
                app=app,
                stream=name,
            )
            res = requests.get(url, headers={
                "User-Agent": PROJECT_UA
            }, timeout=self.timeout)
            if res.status_code == 200:
                res_json = res.json()
                if 0 == res_json["code"]:
                    count_hit = res_json.get("count_hit",0)
                    count_closed = res_json.get("count_closed",0)

                    if count_hit > 0:
                        __ret = True
                        __msg = "success"
                    else:
                        raise Exception(str(res_json))
                else:
                    raise Exception(str(res_json))
            else:
                raise Exception("status=%d" % res.status_code)

        except Exception as e:

            __msg += " e:%s" % str(e)
            self.__logger.warning(__msg)

        return __ret, __msg

    def openRtpServer(self, port, stream_id, tcp_mode=0):
        """
        开启RTP服务器（用于GB28181）

        Args:
            port: RTP端口
            stream_id: 流ID（通常是channel_id）
            tcp_mode: TCP模式（0=UDP, 1=TCP主动, 2=TCP被动）

        Returns:
            tuple: (success, msg, actual_port)
                success: 是否成功
                msg: 消息
                actual_port: 实际分配的端口（可能与请求的不同）
        """
        __msg = f"zlm.openRtpServer(port={port}, stream_id={stream_id}, tcp_mode={tcp_mode})"
        __actual_port = 0

        try:
            url = f"{self.__config.mediaHttpHost}/index/api/openRtpServer"
            params = {
                "port": port,
                "tcp_mode": tcp_mode,
                "stream_id": stream_id,
                "secret": self.__config.mediaSecret
            }

            res = requests.post(url, json=params, timeout=self.timeout)

            if res.status_code == 200:
                res_json = res.json()
                if 0 == res_json["code"]:
                    __actual_port = res_json.get("port", port)
                    __msg = f"success (actual_port={__actual_port})"
                    return True, __msg, __actual_port
                else:
                    __msg = f"failed: {res_json.get('msg', 'unknown error')}"
                    return False, __msg, 0
            else:
                __msg = f"HTTP {res.status_code}"
                return False, __msg, 0

        except Exception as e:
            __msg += f" e:{str(e)}"
            self.__logger.warning(__msg)
            return False, __msg, 0

    def closeRtpServer(self, name):

        __hit = 0
        __msg = "zlm.closeRtpServer(name=%s)" % name

        try:
            url = "{host}/index/api/closeRtpServer?secret={secret}&stream_id={stream_id}".format(
                host=self.__config.mediaHttpHost,
                secret=self.__config.mediaSecret,
                stream_id=name
            )
            res = requests.get(url, headers={
                "User-Agent": PROJECT_UA
            }, timeout=self.timeout)

            if res.status_code == 200:
                res_json = res.json()
                if 0 == res_json["code"]:
                    __hit = res_json["hit"]
                    __msg = "success"
                else:
                    raise Exception(str(res_json))
            else:
                raise Exception("status=%d" % res.status_code)

        except Exception as e:
            __msg += " e:%s" % str(e)
            self.__logger.warning(__msg)

        return __hit, __msg

    def getMediaList(self,request_ip=None):
        mediaList = []
        try:
            url = "{host}/index/api/getMediaList?secret={secret}".format(
                host=self.__config.mediaHttpHost,
                secret=self.__config.mediaSecret
            )
            res = requests.get(url, headers={
                "User-Agent": PROJECT_UA
            }, timeout=self.timeout)

            if 200 == res.status_code:
                res_json = res.json()
                if 0 == res_json.get("code"):
                    data = res_json.get("data")
                    if data:
                        __data_group = {}  # 视频流按照流名称进行分组
                        for d in data:
                            app = d.get("app")  # 应用名
                            name = d.get("stream")  # 流id
                            schema = d.get("schema")  # 协议
                            app_name = "%s_%s" % (app, name)
                            v = __data_group.get(app_name)
                            if not v:
                                v = {}
                            v[schema] = d
                            __data_group[app_name] = v
                        for app_name, v in __data_group.items():
                            schema_clients = []
                            index = 0
                            d = None
                            for __schema, __d in v.items():
                                schema_clients.append({
                                    "schema": __schema,
                                    "readerCount": __d.get("readerCount")
                                })
                                if 0 == index:
                                    d = __d
                                index += 1
                            if d:
                                video_str = "无"
                                video_codec_name = None
                                video_width = 0
                                video_height = 0
                                audio_str = "无"
                                tracks = d.get("tracks", None)
                                if tracks:
                                    for track in tracks:
                                        # codec_id = track.get("codec_id","")
                                        codec_id_name = track.get("codec_id_name", "").lower()
                                        codec_type = track.get("codec_type", -1)  # Video = 0, Audio = 1
                                        # ready = track.get("ready","")

                                        if 0 == codec_type:  # 视频类型
                                            fps = track.get("fps")
                                            video_height = int(track.get("height", 0))
                                            video_width = int(track.get("width", 0))
                                            video_codec_name = codec_id_name

                                            video_str = "%s/%d/%dx%d" % (codec_id_name, fps, video_width, video_height)

                                        elif 1 == codec_type:  # 音频类型
                                            channels = track.get("channels")

                                            sample_bit = track.get("sample_bit")
                                            sample_rate = track.get("sample_rate")

                                            audio_str = "%s/%d/%d/%d" % (
                                                codec_id_name, channels, sample_rate, sample_bit)

                                produce_speed = self.__byteFormat(d.get("bytesSpeed"))  # 数据产生速度，单位byte/s

                                app = d.get("app")  # 应用名
                                name = d.get("stream")  # 流id
                                mediaList.append({
                                    "is_online": 1,
                                    "code": app_name,
                                    "an": app_name,
                                    "app_name": app_name,
                                    "app": app,
                                    "name": name,
                                    "produce_speed": produce_speed,
                                    "video": video_str,
                                    "video_codec_name": video_codec_name,
                                    "video_width": video_width,
                                    "video_height": video_height,
                                    "audio": audio_str,
                                    "originUrl": d.get("originUrl"),  # 推流地址
                                    "originType": d.get("originType"),  # 推流地址采用的推流协议类型
                                    "originTypeStr": d.get("originTypeStr"),  # 推流地址采用的推流协议类型（字符串）
                                    "clients": d.get("totalReaderCount"),  # 客户端总数量
                                    "schema_clients": schema_clients,
                                    "videoUrl": self.get_wsMp4Url(app=app,name=name,request_ip=request_ip),  # 默认播放地址(ws-fmp4)
                                    "wsHost": self.get_wsHost(request_ip=request_ip),
                                    "wsMp4Url": self.get_wsMp4Url(app=app,name=name,request_ip=request_ip)
                                })
                else:
                    raise Exception(str(res_json))
            else:
                raise Exception("status=%d" % res.status_code)

        except Exception as e:

            self.__logger.warning("zlm.getMediaList(request_ip=%s) e:%s" % (request_ip,str(e)))

        return mediaList

    def getMediaInfo(self, app, name, schema="rtsp", vhost="__defaultVhost__",media_http_host=None,media_secret=None):
        mediaInfo = {}
        try:
            if media_http_host is None:
                media_http_host = self.__config.mediaHttpHost
            if media_secret is None:
                media_secret = self.__config.mediaSecret

            url = "{host}/index/api/getMediaInfo?secret={secret}&schema={schema}&vhost={vhost}&app={app}&stream={name}".format(
                host=media_http_host,
                secret=media_secret,
                schema=schema,
                vhost=vhost,
                app=app,
                name=name
            )
            res = requests.get(url, headers={
                "User-Agent": PROJECT_UA
            }, timeout=self.timeout)

            if 200 == res.status_code:
                res_json = res.json()
                if 0 == res_json["code"]:
                    """res_json示例
                    {
                        'aliveSecond': 851,
                        'app': 'live',
                        'bytesSpeed': 116449,
                        'code': 0,
                        'createStamp': 1757481125,
                        'isRecordingHLS': False,
                        'isRecordingMP4': False,
                        'originSock': {
                            'identifier': 'class mediakit::RtspPlayerImp-23',
                            'local_ip': '192.168.1.106',
                            'local_port': 32527,
                            'peer_ip': '192.168.1.15',
                            'peer_port': 9554
                        },
                        'originType': 4,
                        'originTypeStr': 'pull',
                        'originUrl': 'rtsp://192.168.1.15:9554/live/cam77506144ae',
                        'params': '',
                        'readerCount': 2,
                        'schema': 'rtsp',
                        'stream': 'cam17306fb84c',
                        'totalBytes': 101651752,
                        'totalReaderCount': 3,
                        'tracks': [{
                            'codec_id': 0,
                            'codec_id_name': 'H264',
                            'codec_type': 0,
                            'duration': 852751,
                            'fps': 25.0,
                            'frames': 21302,
                            'gop_interval_ms': 970,
                            'gop_size': 25,
                            'height': 1080,
                            'key_frames': 853,
                            'loss': 0.0,
                            'ready': True,
                            'width': 1920
                        }],
                        'vhost': '__defaultVhost__'
                    }
                    """

                    mediaInfo["aliveSecond"] = res_json.get("aliveSecond",0) # 存活时长
                    mediaInfo["totalReaderCount"] = res_json.get("totalReaderCount",0)

                    tracks = res_json.get("tracks", None)
                    if tracks:
                        if len(tracks) > 0:
                            for track in tracks:
                                codec_type = int(track.get("codec_type", -1))  # Video = 0, Audio = 1
                                if 0 == codec_type:  # 视频类型


                                    mediaInfo["codec_id"] = track.get("codec_id")
                                    mediaInfo["video_codec_name"] = track.get("codec_id_name", "").lower()
                                    mediaInfo["video_width"] = int(track.get("width", 0))
                                    mediaInfo["video_height"] = int(track.get("height", 0))
                                    mediaInfo["gop_size"] = int(track.get("gop_size", 0))

                                    mediaInfo["success"] = True

                                    break

                    if not mediaInfo.get("success"):
                        raise Exception(str(res_json))
                else:
                    raise Exception(str(res_json))
            else:
                raise Exception("status=%d" % res.status_code)

        except Exception as e:
            self.__logger.warning("zlm.getMediaInfo(app=%s,name=%s,schema=%s) e:%s" % (app,name,schema,str(e)))

        if mediaInfo.get("success"):
            return mediaInfo
        else:
            return {}
