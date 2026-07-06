# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
import time
from app.views.ViewsBase import *
from app.utils.Utils import buildPageLabels
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from app.utils.OSSystem import OSSystem
from io import BytesIO
from app.utils.LogUtils import LogUtils
from django.http import HttpResponse
import json
# 生成验证码start
import random
from PIL import Image, ImageDraw, ImageFont

def random_color(min_val=50, max_val=200):
    """生成随机RGB颜色"""
    return (
        random.randint(min_val, max_val),
        random.randint(min_val, max_val),
        random.randint(min_val, max_val)
    )
def load_captcha_font(height):
    """跨平台字体加载（优先Linux兼容字体）"""
    osSystem = OSSystem()
    if osSystem.getSystemName() == "Windows":
        font_paths = [
            g_config.fontPath,  # 项目内嵌字体
            "C:\\Windows\\Fonts\\arial.ttf"  # Windows
        ]
    else:
        font_paths = [
            g_config.fontPath,  # 项目内嵌字体
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"  # Linux
        ]
    for font_path in font_paths:
        try:
            if os.path.exists(font_path):
                font_size = int(height * 0.7)
                font = ImageFont.truetype(font_path, font_size)
                return font,font_size
            else:
                raise Exception("file not exist")
        except Exception as e:
            g_logger.error("load_captcha_font() error,font_path=%s,e=%s"%(font_path,str(e)))

    font_size = int(height * 2)
    return ImageFont.load_default(),font_size  # 保底方案
def generate_secure_captcha(length=4):
    """生成带干扰线的验证码图片"""

    width = 120
    height = 40
    font,font_size = load_captcha_font(height)

    image = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    # 生成随机文本（排除易混淆字符）
    chars = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    captcha_text = ''.join(random.choices(chars, k=length))

    # 绘制扭曲字符
    x_offset = 10
    for char in captcha_text:
        angle = random.randint(-10, 10)  # 随机旋转角度
        char_img = Image.new('RGBA', (font_size, font_size), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_img)
        char_draw.text((0, 0), char, font=font, fill=random_color(0, 100))
        rotated_char = char_img.rotate(angle, expand=True, resample=Image.BILINEAR)
        image.paste(rotated_char, (x_offset, 5), rotated_char)
        x_offset += rotated_char.width - random.randint(0, 8)  # 随机间距

    # 添加干扰线（核心防御）
    for _ in range(4):  # 干扰线数量
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        draw.line([x1, y1, x2, y2], fill=random_color(150, 220), width=random.choice([1, 2]))

    # 添加噪点（30个点）
    for _ in range(30):
        x, y = random.randint(0, width), random.randint(0, height)
        draw.point((x, y), fill=random_color(100, 200))

    return captcha_text, image
# 生成验证码end


def index(request):
    context = {}
    return render(request, 'app/user/index.html', context)


def api_openIndex(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    data = []
    pageData = {}

    if request.method == 'GET':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parseGetParams(request)

            page = params.get('p', 1)
            page_size = params.get('ps', 10)
            try:
                page = int(page)
            except:
                page = 1

            try:
                page_size = int(page_size)
                if page_size < 1:
                    page_size = 1
            except:
                page_size = 10

            skip = (page - 1) * page_size
            sql_data = "select * from auth_user order by id desc limit %d,%d " % (skip, page_size)
            sql_data_num = "select count(id) as count from auth_user "

            count = g_database.select(sql_data_num)

            if len(count) > 0:
                count = int(count[0]["count"])
                data = g_database.select(sql_data)
            else:
                count = 0

            # 格式化日期字段
            for d in data:
                if d.get("date_joined"):
                    try:
                        d["date_joined"] = d["date_joined"].strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        pass
                else:
                    d["date_joined"] = ""
                if d.get("last_login"):
                    try:
                        d["last_login"] = d["last_login"].strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        pass
                else:
                    d["last_login"] = ""

            page_num = int(count / page_size)
            if count % page_size > 0:
                page_num += 1
            pageLabels = buildPageLabels(page=page, page_num=page_num, lang=f_parseRequestLang(request))
            pageData = {
                "page": page,
                "page_size": page_size,
                "page_num": page_num,
                "count": count,
                "pageLabels": pageLabels
            }

            ret = True
            msg = LANG_VIEWS_T(request, "msg_success")
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")

    res = {
        "code": 1000 if ret else 0,
        "msg": msg,
        "data": data,
        "pageData": pageData
    }
    return f_responseJson(res)
def api_openAdd(request):
    __ret = False
    __msg = LANG_VIEWS_T(request, "msg_unknown_error")

    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            g_logger.info("UserView.openAdd() params:%s" % str(params))
            try:
                login_user = f_sessionReadUser(request)
                if not login_user:
                    raise Exception(LANG_VIEWS_T(request, "msg_not_logged_in"))

                username = params.get("username", "").strip()
                email = params.get("email", "").strip()
                password = params.get("password", "").strip()
                is_active = params.get("is_active")
                is_active = int(is_active)

                if username == "":
                    raise Exception(LANG_VIEWS_T(request, "user_username_required"))
                if email == "":
                    raise Exception(LANG_VIEWS_T(request, "user_email_required"))
                if len(password) < 6 or len(password) > 16:
                    raise Exception(LANG_VIEWS_T(request, "user_password_length"))

                if User.objects.filter(username=username).exists():
                    raise Exception(LANG_VIEWS_T(request, "user_username_exists"))
                else:
                    now = datetime.now()
                    user = User()
                    user.username = username
                    user.set_password(password)
                    user.email = email
                    user.date_joined = now
                    user.is_superuser = 0  # 表单创建均为非超级管理员
                    user.is_staff = 1
                    user.is_active = is_active
                    user.save()

                    if user.id > 0:
                        # 添加日志
                        lang = f_parseRequestLang(request)
                        LogUtils.add_user_log(login_user.get("id"), username, LogUtils.LOG_TYPE_ADD, lang=lang)
                        __ret = True
                        __msg = LANG_VIEWS_T(request, "msg_add_success")
                    else:
                        __msg = LANG_VIEWS_T(request, "msg_add_failed")
            except Exception as e:
                __msg = str(e)
        else:
            __msg = __check_msg
    else:
        __msg = LANG_VIEWS_T(request, "msg_method_not_supported")

    res = {
        "code": 1000 if __ret else 0,
        "msg": __msg
    }
    g_logger.info("UserView.openAdd() res=%s" % str(res))
    return f_responseJson(res)
def api_openEdit(request):
    __ret = False
    __msg = LANG_VIEWS_T(request, "msg_unknown_error")

    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            g_logger.info("UserView.openEdit() params:%s" % str(params))
            try:
                login_user = f_sessionReadUser(request)
                if not login_user:
                    raise Exception(LANG_VIEWS_T(request, "msg_not_logged_in"))

                user_id = params.get("id")  # 被操作用户id
                is_active = params.get("is_active")
                username = params.get("username", "").strip()
                email = params.get("email", "").strip()
                new_password = params.get("new_password", "")
                re_password = params.get("re_password", "")
                user_id = int(user_id)
                is_active = int(is_active)

                if username == "":
                    raise Exception(LANG_VIEWS_T(request, "user_username_required"))
                if email == "":
                    raise Exception(LANG_VIEWS_T(request, "user_email_required"))
                if re_password == "" and new_password == "":
                    pass
                    # 未修改密码
                else:
                    # 修改了密码

                    if new_password == "":
                        raise Exception(LANG_VIEWS_T(request, "user_new_password_required"))
                    if re_password == "":
                        raise Exception(LANG_VIEWS_T(request, "user_confirm_password_required"))
                    if new_password != re_password:
                        raise Exception(LANG_VIEWS_T(request, "user_password_mismatch"))
                    if len(new_password) < 6 or len(new_password) > 16:
                        raise Exception(LANG_VIEWS_T(request, "user_new_password_length"))

                user = User.objects.filter(id=user_id).first()
                if user:
                    # 验证要修改的用户名是否已经存在start
                    if user.username == username:
                        pass
                        # 用户名未做修改
                    else:
                        filter_username = g_database.select(
                            "select count(1) as count from auth_user where id!=%d and username='%s'" % (
                                user_id, username))
                        filter_username_count = int(filter_username[0]["count"])
                        if filter_username_count > 0:
                            raise Exception(LANG_VIEWS_T(request, "user_new_username_exists"))
                        user.username = username  # 修改了用户名
                    # 验证要修改的用户名是否已经存在end

                    if re_password == "" and new_password == "":
                        pass
                    else:
                        user.set_password(new_password)  # 修改了密码

                    user.email = email
                    user.is_active = is_active
                    user.save()
                    
                    # 添加日志
                    lang = f_parseRequestLang(request)
                    LogUtils.add_user_log(login_user.get("id"), username, LogUtils.LOG_TYPE_EDIT, lang=lang)
                    __ret = True
                    __msg = LANG_VIEWS_T(request, "msg_edit_success")
                else:
                    raise Exception(LANG_VIEWS_T(request, "msg_data_not_exist"))
            except Exception as e:
                __msg = str(e)
        else:
            __msg = __check_msg
    else:
        __msg = LANG_VIEWS_T(request, "msg_method_not_supported")

    res = {
        "code": 1000 if __ret else 0,
        "msg": __msg
    }
    g_logger.info("UserView.openEdit() res=%s" % str(res))
    return f_responseJson(res)
def api_openDel(request):
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    if request.method == 'POST':
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parsePostParams(request)
            try:
                login_user = f_sessionReadUser(request)
                if not login_user:
                    raise Exception(LANG_VIEWS_T(request, "msg_not_logged_in"))

                user_id = int(params.get("id"))
                if not user_id:
                    raise Exception(LANG_VIEWS_T(request, "user_request_params_invalid"))

                login_user_id = int(login_user.get("id"))
                if login_user_id == user_id:
                    raise Exception(LANG_VIEWS_T(request, "user_super_admin_no_delete_self"))

                user = User.objects.filter(id=user_id)
                if len(user) > 0:
                    user = user[0]
                    if user.is_superuser == 1:
                        raise Exception(LANG_VIEWS_T(request, "user_super_admin_no_delete"))
                    else:
                        if user.delete():
                            ret = True
                            msg = LANG_VIEWS_T(request, "msg_success")
                        else:
                            msg = LANG_VIEWS_T(request, "msg_failed_to_delete")
                else:
                    raise Exception(LANG_VIEWS_T(request, "msg_data_not_exist"))
            except Exception as e:
                msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")

    res = {
        "code": 1000 if ret else 0,
        "msg": msg
    }
    g_logger.info("UserView.openDel() res=%s" % str(res))
    return f_responseJson(res)

def api_openInfo(request):
    """获取单条用户详情"""
    ret = False
    msg = LANG_VIEWS_T(request, "msg_unknown_error")
    info = {}

    if request.method == "GET":
        __check_ret, __check_msg = f_checkRequestSafe(request)
        if __check_ret:
            params = f_parseGetParams(request)
            user_id = params.get("id", "")
            
            if not user_id:
                msg = LANG_VIEWS_T(request, "user_id_required")
            else:
                try:
                    user_id = int(user_id)
                    user = User.objects.filter(id=user_id).first()
                    if user:
                        info = {
                            "id": user.id,
                            "username": user.username,
                            "email": user.email,
                            "is_active": user.is_active,
                            "is_superuser": user.is_superuser,
                            "is_staff": user.is_staff,
                            "date_joined": user.date_joined.strftime("%Y-%m-%d %H:%M:%S") if user.date_joined else "",
                            "last_login": user.last_login.strftime("%Y-%m-%d %H:%M:%S") if user.last_login else ""
                        }
                        ret = True
                        msg = LANG_VIEWS_T(request, "msg_success")
                    else:
                        msg = LANG_VIEWS_T(request, "user_not_exist")
                except Exception as e:
                    msg = str(e)
        else:
            msg = __check_msg
    else:
        msg = LANG_VIEWS_T(request, "msg_method_not_supported")

    res = {
        "code": 1000 if ret else 0,
        "msg": msg,
        "info": info
    }
    g_logger.info("UserView.openInfo() res=%s" % str(res))
    return f_responseJson(res)

def api_openCaptcha(request):
    """生成验证码图片视图"""
    # 生成验证码
    text,image = generate_secure_captcha()

    # 存储到session
    cur_timestamp = int(time.time())
    request.session[g_session_key_captcha] = {
        "captcha_text": text,
        "captcha_create_timestamp": cur_timestamp,  # 创建秒级时间戳
    }

    # 创建内存流输出
    stream = BytesIO()
    image.save(stream, 'PNG')
    return HttpResponse(stream.getvalue(), content_type='image/png')

def login(request):

    context = {
        "projectVersion": PROJECT_VERSION,
        "projectFlag": PROJECT_FLAG
    }


    if request.method == 'POST':
        ret = False
        msg = LANG_VIEWS_T(request, "msg_unknown_error")

        params = f_parsePostParams(request)
        username = (params.get("username") or params.get("username_s") or "").strip()
        password = (params.get("password") or params.get("password_s") or "").strip()
        captcha = params.get("captcha", None)

        try:
            if g_config.isEnableLoginCaptcha:
                if not captcha:
                    raise Exception(LANG_VIEWS_T(request, "user_captcha_missing"))
                # 开启了登录验证码功能
                session_captcha = request.session.get(g_session_key_captcha, None)
                if not session_captcha:
                    raise Exception(LANG_VIEWS_T(request, "user_captcha_not_found"))

                if session_captcha:
                    captcha_text = session_captcha.get("captcha_text", "")
                    captcha_create_timestamp = session_captcha.get("captcha_create_timestamp", 0)
                    cur_timestamp = int(time.time())

                    # 验证码过期判断
                    if (cur_timestamp - captcha_create_timestamp) > 300:
                        raise Exception(LANG_VIEWS_T(request, "user_captcha_expired"))

                    # 验证码相同判断
                    if captcha_text != captcha:
                        raise Exception(LANG_VIEWS_T(request, "user_captcha_incorrect"))
            if username and password:
                user = User.objects.filter(username=username).first()
                if user:
                    if user.is_active:
                        if user.check_password(password):
                            user.first_name = "cec=0"
                            user.last_login = datetime.now()
                            user.save()

                            # 无权限区分，所有登录用户均可访问所有功能
                            request.session[g_session_key_user] = {
                                "id": user.id,
                                "username": username,
                                "email": user.email,
                                "is_superuser": user.is_superuser,
                                "is_active": user.is_active,
                                "is_staff":  user.is_staff,
                                "log_debug": 1 if g_config.logDebug else 0,
                            }

                            # 记录登录日志
                            LogUtils.add_log(
                                user_id=user.id,
                                log_type=LogUtils.LOG_TYPE_LOGIN,
                                content=f"用户登录[{username}]",
                                state=LogUtils.STATE_SUCCESS
                            )

                            ret = True
                            msg = LANG_VIEWS_T(request, "user_login_success")
                        else:
                            continuous_error_count = 0
                            try:
                                vals = user.first_name.split(",")
                                for val in vals:
                                    array = val.split("=")
                                    if len(array) == 2:
                                        if array[0] == "cec":
                                            continuous_error_count = int(array[1])
                            except:
                                pass

                            continuous_error_count += 1
                            if continuous_error_count > 6:
                                is_active = False
                                msg = LANG_VIEWS_T(request, "user_password_error_lock") % continuous_error_count
                            else:
                                is_active = True
                                msg = LANG_VIEWS_T(request, "user_password_error_count") % continuous_error_count
                            user.is_active = is_active
                            user.first_name = "cec=%d"%continuous_error_count
                            user.save()
                    else:
                        msg = LANG_VIEWS_T(request, "user_account_locked")
                else:
                    msg = LANG_VIEWS_T(request, "user_not_registered")
            else:
                msg = LANG_VIEWS_T(request, "msg_invalid_parameter")
        except Exception as e:
            msg = str(e)

        res = {
            "code": 1000 if ret else 0,
            "msg": msg
        }
        return f_responseJson(res)
    else:
        context["isEnableLoginCaptcha"] = 1 if g_config.isEnableLoginCaptcha else 0
        return render(request, 'app/user/login.html', context)

def logout(request):

    # 记录退出登录日志
    if request.session.has_key(g_session_key_user):
        user_info = request.session.get(g_session_key_user)
        user_id = user_info.get('id', 0)
        username = user_info.get('username', '未知用户')
        
        # 记录日志
        if user_id:
            LogUtils.add_log(
                user_id=user_id,
                log_type=LogUtils.LOG_TYPE_LOGOUT,
                content=f"用户退出[{username}]",
                state=LogUtils.STATE_SUCCESS
            )
        
        del request.session[g_session_key_user]
    
    if request.session.has_key(g_session_key_captcha):
        del request.session[g_session_key_captcha]

    return redirect("/")
