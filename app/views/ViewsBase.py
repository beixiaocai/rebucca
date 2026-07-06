# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
from app.utils.GlobalUtils import *
from app.utils.LanguageUtils import LANG_VIEWS_T, GSettingsLangDefault
import json
from django.http import HttpResponse

def f_parseGetParams(request):
    params = {}
    try:
        for k in request.GET:
            params.__setitem__(k, request.GET.get(k))
    except Exception as e:
        params = {}

    return params

def f_parsePostParams(request):
    params = {}
    for k in request.POST:
        params.__setitem__(k, request.POST.get(k))

    # 接收json方式上传的参数
    if not params:
        try:
            params = request.body.decode('utf-8')
            params = json.loads(params)
        except:
            params = {}

    return params
def f_parseRequestLang(request):
    # v5.006 新增
    request_lang = None

    # 1. 最高优先级：获取GET或POST的lang参数
    if request.method == 'GET':
        params = f_parseGetParams(request)
        lang = params.get('lang', '').strip()
        if lang:
            request_lang = lang
    elif request.method == 'POST':
        params = f_parsePostParams(request)
        lang = params.get('lang', '').strip()
        if lang:
            request_lang = lang

    if not request_lang:
        # 2. 次优先级：session中的语言设置
        if hasattr(request, 'session'):
            request_lang = request.session.get('lang', GSettingsLangDefault)

    if not request_lang:
        # 3. 最低优先级：系统默认语言
        request_lang = GSettingsLangDefault

    return request_lang
def f_parseRequestIp(request):
    try:
        if request.method == 'GET':
            params = f_parseGetParams(request)
            ip = params.get('request_ip', '').strip()
            if ip:
                return ip
        elif request.method == 'POST':
            params = f_parsePostParams(request)
            ip = params.get('request_ip', '').strip()
            if ip:
                return ip
        host = request.get_host()
        ip = host.split(':')[0]
    except Exception as e:
        g_logger.error("f_parseRequestIp() error: %s"%str(e))
        ip = "0.0.0.0"
    return ip
def f_parsePeerIp(request):
    try:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR') # 备用方案
    except Exception as e:
        g_logger.error("f_parsePeerIp() error: %s"%str(e))
        ip = "0.0.0.0"
    return ip
def f_parsePeerPort(request):
    try:
        port = int(request.get_port())
    except Exception as e:
        g_logger.error("f_parsePeerPort() error: %s"%str(e))
        port = 0
    return port

def f_sessionReadUser(request):
    user = request.session.get(g_session_key_user)
    return user

def f_sessionReadUserId(request):
    try:
        user_id = f_sessionReadUser(request).get("id")
    except:
        user_id = 0
    return user_id

def f_checkRequestSafe(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    # 检查请求是否安全
    user_id = f_sessionReadUserId(request)
    if user_id:
        ret = True
        msg = LANG_VIEWS_T(request, "msg_success")
    else:
        headers = request.headers
        Safe = headers.get("Safe")
        if Safe and Safe == g_config.safe:
            ret = True
            msg = LANG_VIEWS_T(request, "msg_success")
        else:
            msg = LANG_VIEWS_T(request, "msg_safe_verify_error")
    return ret,msg

def f_responseJson(res):
    def json_dumps_default(obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        else:
            raise TypeError

    return HttpResponse(json.dumps(res, default=json_dumps_default), content_type="application/json")

def f_dbReadStreamData():
    data = g_database.select("select * from av_stream order by id desc")
    return data