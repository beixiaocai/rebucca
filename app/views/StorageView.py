# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""
StorageView 文件下载模块
提供文件下载功能（导出日志、导出配置等场景使用）。
"""
from app.views.ViewsBase import *
from app.utils.LanguageUtils import LANG_VIEWS_T
from django.utils.encoding import escape_uri_path
import os


def api_openInfo(request):
    """查询存储空间信息（原 Storage 模块，已移除）"""
    if request.method != 'GET':
        return f_responseJson({"code": 0, "msg": LANG_VIEWS_T(request, "msg_method_not_supported")})

    __check_ret, __check_msg = f_checkRequestSafe(request)
    if not __check_ret:
        return f_responseJson({"code": 0, "msg": __check_msg})

    g_logger.info("StorageView.api_openInfo() ip:%s" % f_parseRequestIp(request))
    return f_responseJson({
        "code": 1000,
        "msg": "ok",
        "info": {
            "alarmFolderSize": 0,
            "recordFolderSize": 0
        }
    })


def api_openDownload(request):
    """文件下载（导出日志/导出配置等场景使用，下载完成后自动删除临时文件）"""
    params = f_parseGetParams(request)
    g_logger.info("StorageView.openDownload() params:%s" % str(params))

    filename = params.get("filename", "").strip()
    try:
        # 仅允许指定后缀的文件下载，避免任意文件读取
        if filename.endswith(".mp4") \
                or filename.endswith(".wav") \
                or filename.endswith(".jpg") \
                or filename.endswith(".png") \
                or filename.endswith(".tar") \
                or filename.endswith(".xclogs") \
                or filename.endswith(".xcsettings") \
                or filename.endswith(".xcupdate") \
                or filename.endswith(".xcflow"):

            filepath = os.path.join(g_config.storageTempDir, filename)

            if os.path.exists(filepath):
                # 使用 FileResponse 流式传输，避免一次性读入大文件占内存
                from django.http import FileResponse
                f = open(filepath, mode="rb")
                response = FileResponse(f, content_type="application/octet-stream")
                response['Access-Control-Allow-Origin'] = "*"
                response['Access-Control-Allow-Headers'] = "*"
                response['Access-Control-Allow-Methods'] = "POST, GET, OPTIONS, DELETE"
                response['Content-Disposition'] = "attachment;filename={};".format(escape_uri_path(filename))

                # 延迟删除：通过 after_response 钩子在响应发送完成后删除
                # Django 的 FileResponse 会在响应完成后自动关闭文件句柄
                # 使用 threading.Timer 延迟删除，确保文件已读取完毕
                import threading
                def __delayed_delete(path):
                    try:
                        time.sleep(5)  # 等待响应发送完成
                        if os.path.exists(path):
                            os.remove(path)
                    except Exception as e:
                        g_logger.error("StorageView.openDownload() delayed delete error,filepath=%s,e=%s" % (path, str(e)))

                t = threading.Thread(target=__delayed_delete, args=(filepath,))
                t.start()

                return response
            else:
                raise Exception("filepath not exists,filepath=%s" % filepath)
        else:
            raise Exception("unsupported filename format,filename=%s" % filename)
    except Exception as e:
        g_logger.debug("StorageView.openDownload() error,e=%s" % str(e))
        return f_responseJson({"code": 0, "msg": str(e)})
