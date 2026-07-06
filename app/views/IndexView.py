# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
from app.views.ViewsBase import *
from app.models import *
from django.shortcuts import render
from app.utils.OSSystem import OSSystem



def index(request):
    context = {}

    return render(request, 'app/index.html', context)


def api_openIndex(request):
    # highcharts 例子 https://www.highcharts.com.cn/demo/highcharts/dynamic-update
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")

    appInfo = {}
    osInfo = {}

    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            # params = f_parseGetParams(request)
            appInfo = {
                "project_ua": PROJECT_UA,
                "project_version": PROJECT_VERSION,
                "project_flag": PROJECT_FLAG,
                "project_built": PROJECT_BUILT,
                "start_timestamp": PROJECT_ADMIN_START_TIMESTAMP
            }
            osSystem = OSSystem()
            osInfo = osSystem.getOSInfo(
                spend_date_fmt=LANG_VIEWS_T(request, "syscfg_spend_date_fmt"),
                include_gpu=False,
            )

            ret = True
            msg = LANG_VIEWS_T(request, "msg_success")
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")

    res = {
        "code": 1000 if ret else 0,
        "msg": msg,
        "osInfo": osInfo,
        "appInfo": appInfo
    }
    return f_responseJson(res)


def api_openGpuInfo(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    os_gpus = []

    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                from app.utils.GpuInfo import get_gpu_info
                os_gpus = get_gpu_info()
            except Exception:
                os_gpus = []
            ret = True
            msg = LANG_VIEWS_T(request, "msg_success")
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")

    return f_responseJson({
        "code": 1000 if ret else 0,
        "msg": msg,
        "os_gpus": os_gpus,
    })


def api_openMediaStatus(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = {}
    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                from app.utils.MediaServerManager import get_media_server_manager
                data = get_media_server_manager().status()
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def api_openMediaControl(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            action = str(params.get("action", "")).strip().lower()
            try:
                from app.utils.MediaServerManager import get_media_server_manager
                mgr = get_media_server_manager()
                if action == "start":
                    ret, msg = mgr.start()
                elif action == "stop":
                    ret, msg = mgr.stop()
                elif action == "restart":
                    ret, msg = mgr.restart()
                else:
                    msg = LANG_VIEWS_T(request, "msg_invalid_parameter")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def forbidden(request):
    context = {}
    return render(request, 'app/forbidden.html', context)

def api_openSwitchLang(request):
    from app.utils.LanguageUtils import LANG_UI_DICT

    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")

    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parseGetParams(request)
            lang = params.get('lang')
            
            if not lang:
                msg = LANG_VIEWS_T(request, "index_lang_param_required")
            elif lang not in LANG_UI_DICT:
                available = list(LANG_UI_DICT.keys())
                msg = LANG_VIEWS_T(request, "index_lang_not_supported") % (lang, str(available))
            else:
                request.session['lang'] = lang
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")

    res = {
        "code": 1000 if ret else 0,
        "msg": msg
    }
    return f_responseJson(res)
