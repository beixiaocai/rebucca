# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
from app.utils.LanguageUtils import LANG_UI_DICT, LANG_UI_JSON_CACHE, f_parse_request_lang, GSettingsLanguages
from app.utils.GlobalUtils import g_session_key_user

def lang_processor(request):
    from app.utils.LanguageUtils import reload_lang_dict
    reload_lang_dict()
    lang = f_parse_request_lang(request)

    # 从 GSettingsLanguages 将字典转换为列表供模板遍历
    languages_list = list(GSettingsLanguages.values())

    # 从 GSettingsLanguages 字典中直接获取当前语言的 OEM 配置
    oem_settings = GSettingsLanguages.get(lang,{}).get('oem', {})

    # 获取当前登录用户信息
    current_user = request.session.get(g_session_key_user, {})

    return {
        'T': LANG_UI_DICT.get(lang),
        'T_JSON': LANG_UI_JSON_CACHE.get(lang, '{}'),
        'T_SELECTED_LANG': lang,
        'T_SETTINGS_LANGUAGES': languages_list,
        'settings': oem_settings,
        'current_user': current_user
    }