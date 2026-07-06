# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
from app.views.ViewsBase import *
from django.shortcuts import render
from framework.settings import PROJECT_VERSION, PROJECT_FLAG
from app.utils.LanguageUtils import GSettingsLanguages


def index(request):
    context = {
        "project_version": PROJECT_VERSION,
        "project_flag": PROJECT_FLAG,
    }
    return render(request, 'app/version/index.html', context)


def api_openCheckVersion(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")

    lang = f_parseRequestLang(request)
    info = {
        "historyVersionUrl": GSettingsLanguages.get(lang, {}).get("oem", {}).get('check_version_download_url', '')
    }

    if request.method == 'GET':
        request_ip = f_parseRequestIp(request)
        peer_ip = f_parsePeerIp(request)
        peer_port = f_parsePeerPort(request)
        __online, __state, __msg, __info = CheckServerUtils.checkVersion(
            request_ip=request_ip, peer_ip=peer_ip, peer_port=peer_port, lang=lang
        )
        if __online:
            if __state:
                info["version"] = __info.get("version")
                info["pubdate"] = __info.get("pubdate")
                info["updateContent"] = __info.get("updateContent", "").split("\\n")
                info["historyVersionUrl"] = __info.get("historyVersionUrl", "")
                info["url"] = __info.get("url", "")

                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            else:
                msg = LANG_VIEWS_T(request, "version_no_new_version")
        else:
            msg = LANG_VIEWS_T(request, "version_check_failed")
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")

    res = {
        "code": 1000 if ret else 0,
        "msg": msg,
        "info": info
    }
    return f_responseJson(res)
