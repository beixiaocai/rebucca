# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
from datetime import datetime

from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from app.views.ViewsBase import *
from app.models import LLMModel
from app.utils.Utils import buildPageLabels
from app.utils.LLMUtils import LLMUtils


def index(request):
    params = f_parseGetParams(request)
    page = params.get('p', 1)
    page_size = params.get('ps', 10)
    try:
        page = int(page)
        if page < 1:
            page = 1
    except Exception:
        page = 1
    try:
        page_size = int(page_size)
        if page_size < 1:
            page_size = 10
        elif page_size > 100:
            page_size = 100
    except Exception:
        page_size = 10

    skip = (page - 1) * page_size
    count_row = g_database.select("select count(id) as count from av_llm")
    count = int(count_row[0]["count"]) if count_row else 0
    data = []
    if count > 0:
        data = g_database.select(
            "select * from av_llm order by id desc limit %d,%d" % (skip, page_size))
        for d in data:
            if d.get("last_update_time"):
                d["last_update_time"] = d["last_update_time"].strftime("%Y/%m/%d %H:%M")

    page_num = count // page_size
    if count % page_size > 0:
        page_num += 1
    page_labels = buildPageLabels(page=page, page_num=page_num, lang=f_parseRequestLang(request))
    page_data = {
        "page": page,
        "page_size": page_size,
        "page_num": page_num,
        "count": count,
        "pageLabels": page_labels,
    }
    return render(request, 'app/llm/index.html', {"data": data, "pageData": page_data})


def test(request):
    return render(request, 'app/llm/test.html', {})


def api_openIndex(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = []
    if request.method == "GET":
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            try:
                for d in LLMModel.objects.all().order_by('-id'):
                    data.append({
                        'id': d.id,
                        'code': d.code,
                        'name': d.name,
                        'model_name': d.model_name,
                        'api_url': d.api_url,
                        'api_key': d.api_key,
                        'timeout': d.timeout,
                        'inference_tool': d.inference_tool,
                        'state': d.state,
                        'remark': d.remark,
                        'last_update_time': d.last_update_time.strftime("%Y/%m/%d %H:%M") if d.last_update_time else '',
                    })
                ret = True
                msg = LANG_VIEWS_T(request, "msg_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "data": data})


def api_openAdd(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == "POST":
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            g_logger.info("LLMView.openAdd() params:%s" % str(params))
            code = params.get("code", "").strip()
            name = params.get("name", "").strip()
            model_name = params.get("model_name", "").strip()
            api_url = params.get("api_url", "").strip()
            api_key = params.get("api_key", "").strip()
            timeout = int(params.get("timeout", 30))
            inference_tool = params.get("inference_tool", "OpenAI").strip() or "OpenAI"
            if inference_tool != "OpenAI":
                raise Exception(LANG_VIEWS_T(request, "llm_inference_tool_unsupported"))
            state = int(params.get("state", 1))
            remark = params.get("remark", "").strip()
            try:
                if LLMModel.objects.filter(code=code).first():
                    raise Exception(LANG_VIEWS_T(request, "msg_code_already_exists"))
                if api_url and not (api_url.startswith("http://") or api_url.startswith("https://")):
                    raise Exception(LANG_VIEWS_T(request, "llm_api_url_format_error"))
                if not model_name:
                    raise Exception(LANG_VIEWS_T(request, "llm_input_model_name"))
                if not api_url:
                    raise Exception(LANG_VIEWS_T(request, "llm_input_api_url"))
                if not api_key:
                    raise Exception(LANG_VIEWS_T(request, "llm_input_api_key"))

                llm = LLMModel()
                llm.user_id = f_sessionReadUserId(request)
                llm.code = code
                llm.name = name
                llm.model_name = model_name
                llm.api_url = api_url
                llm.api_key = api_key
                llm.timeout = timeout
                llm.inference_tool = inference_tool
                llm.remark = remark
                llm.sort = 0
                llm.create_time = datetime.now()
                llm.last_update_time = datetime.now()
                llm.state = state
                llm.save()
                ret = True
                msg = LANG_VIEWS_T(request, "msg_add_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def api_openEdit(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == "POST":
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            g_logger.info("LLMView.openEdit() params:%s" % str(params))
            code = params.get("code", "").strip()
            name = params.get("name", "").strip()
            model_name = params.get("model_name", "").strip()
            api_url = params.get("api_url", "").strip()
            api_key = params.get("api_key", "").strip()
            timeout = int(params.get("timeout", 30))
            inference_tool = params.get("inference_tool", "OpenAI").strip() or "OpenAI"
            if inference_tool != "OpenAI":
                raise Exception(LANG_VIEWS_T(request, "llm_inference_tool_unsupported"))
            state = int(params.get("state", 1))
            remark = params.get("remark", "").strip()
            try:
                if api_url and not (api_url.startswith("http://") or api_url.startswith("https://")):
                    raise Exception(LANG_VIEWS_T(request, "llm_api_url_format_error"))
                llm = LLMModel.objects.filter(code=code).first()
                if not llm:
                    raise Exception(LANG_VIEWS_T(request, "msg_data_not_exist"))
                llm.name = name
                llm.model_name = model_name
                llm.api_url = api_url
                llm.api_key = api_key
                llm.timeout = timeout
                llm.inference_tool = inference_tool
                llm.remark = remark
                llm.last_update_time = datetime.now()
                llm.state = state
                llm.save()
                ret = True
                msg = LANG_VIEWS_T(request, "msg_edit_success")
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


def api_openInfo(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    info = {}
    if request.method == "GET":
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            code = f_parseGetParams(request).get("code", "").strip()
            if not code:
                msg = LANG_VIEWS_T(request, "msg_invalid_parameter")
            else:
                try:
                    llm = LLMModel.objects.filter(code=code).first()
                    if llm:
                        info = {
                            "id": llm.id,
                            "code": llm.code,
                            "name": llm.name,
                            "model_name": llm.model_name,
                            "api_url": llm.api_url or "",
                            "api_key": llm.api_key or "",
                            "timeout": llm.timeout,
                            "inference_tool": llm.inference_tool,
                            "state": llm.state,
                            "remark": llm.remark or "",
                            "create_time": llm.create_time.strftime("%Y-%m-%d %H:%M:%S") if llm.create_time else "",
                            "last_update_time": llm.last_update_time.strftime("%Y-%m-%d %H:%M:%S") if llm.last_update_time else "",
                        }
                        ret = True
                        msg = LANG_VIEWS_T(request, "msg_success")
                    else:
                        msg = LANG_VIEWS_T(request, "llm_config_not_exist")
                except Exception as e:
                    msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg, "info": info})


def api_openDel(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == "POST":
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            code = f_parsePostParams(request).get("code")
            llm = LLMModel.objects.filter(code=code).first()
            if llm:
                if llm.delete():
                    ret = True
                    msg = LANG_VIEWS_T(request, "msg_success")
                else:
                    msg = LANG_VIEWS_T(request, "msg_failed_to_delete")
            else:
                msg = LANG_VIEWS_T(request, "msg_data_not_exist")
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")
    return f_responseJson({"code": 1000 if ret else 0, "msg": msg})


@csrf_exempt
def api_openTest(request):
    try:
        if request.method != "POST":
            raise Exception(LANG_VIEWS_T(request, "msg_method_not_supported"))
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if not __check_ret:
            raise Exception(__check_msg)

        code = request.POST.get('code', '').strip()
        prompt = request.POST.get('prompt', '请详细描述图片中的内容？').strip()

        if code:
            llm = LLMModel.objects.filter(code=code).first()
            if not llm:
                raise Exception(LANG_VIEWS_T(request, "llm_not_found"))
            if llm.state != 1:
                raise Exception(LANG_VIEWS_T(request, "llm_is_disabled"))
            api_url = llm.api_url
            api_key = llm.api_key
            timeout = llm.timeout
            inference_tool = "OpenAI"
            model = llm.model_name
        else:
            api_url = request.POST.get('api_url', 'https://api.openai.com/v1').strip()
            api_key = request.POST.get('api_key', '').strip()
            timeout = int(request.POST.get('timeout', 30))
            inference_tool = request.POST.get('inferenceTool', 'OpenAI').strip() or 'OpenAI'
            if inference_tool != 'OpenAI':
                raise Exception(LANG_VIEWS_T(request, "llm_inference_tool_unsupported"))
            model = request.POST.get('model', 'gpt-4o').strip()

        file_content_base64 = request.POST.get('file_content', '').strip()
        if file_content_base64:
            image_bytes = base64.b64decode(file_content_base64)
        elif 'image' in request.FILES:
            image_bytes = request.FILES['image'].read()
        else:
            raise Exception(LANG_VIEWS_T(request, "llm_no_image_provided"))

        result = LLMUtils(api_url, api_key, timeout, inference_tool, model).infer(prompt, image_bytes)
        return f_responseJson({"code": 1000, "result": result})
    except Exception as e:
        return f_responseJson({"code": 0, "msg": str(e)})
