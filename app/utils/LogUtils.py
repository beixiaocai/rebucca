# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
# -*- coding: utf-8 -*-
"""管理员操作日志工具类"""
from datetime import datetime

from app.models import LogModel
from app.utils.LanguageUtils import LANG_VIEWS_USE_LANG_T


class LogUtils:
    LOG_TYPE_ADD = 1
    LOG_TYPE_EDIT = 2
    LOG_TYPE_LOGIN = 20
    LOG_TYPE_LOGOUT = 21
    STATE_SUCCESS = 1

    @staticmethod
    def add_log(user_id, log_type, content, state=STATE_SUCCESS):
        try:
            log = LogModel()
            log.user_id = user_id
            log.log_type = log_type
            log.content = content
            log.state = state
            log.create_time = datetime.now()
            log.save()
            return True
        except Exception as e:
            print(f"LogUtils.add_log() error: {str(e)}")
            return False

    @staticmethod
    def _action_text(log_type, lang):
        if log_type == LogUtils.LOG_TYPE_ADD:
            return LANG_VIEWS_USE_LANG_T(lang, "log_type_add")
        return LANG_VIEWS_USE_LANG_T(lang, "log_type_edit")

    @staticmethod
    def add_stream_log(user_id, stream_code, log_type, lang=None):
        action = LogUtils._action_text(log_type, lang)
        content = LANG_VIEWS_USE_LANG_T(lang, "log_content_stream").format(
            action=action, stream_code=stream_code)
        return LogUtils.add_log(user_id, log_type, content)

    @staticmethod
    def add_user_log(user_id, username, log_type, lang=None):
        action = LogUtils._action_text(log_type, lang)
        content = LANG_VIEWS_USE_LANG_T(lang, "log_content_user").format(
            action=action, username=username)
        return LogUtils.add_log(user_id, log_type, content)
