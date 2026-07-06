# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
import json
import os
from framework.settings import BASE_DIR

LANG_UI_DICT = {}
LANG_UI_JSON_CACHE = {}
_LANG_FILES_MTIME = 0.0


def _load_json_file(filepath):
    for encoding in ["utf-8", "gbk"]:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                data = json.load(f)
            return data
        except Exception as e:
            print("LanguageUtils: failed to load %s (encoding=%s): %s" % (filepath, encoding, str(e)))
    raise RuntimeError("LanguageUtils: cannot load from %s" % filepath)


def _flatten_lang_dict(data):
    merged = dict(data.get("LANG_UI_DICT") or {})
    for k, v in data.items():
        if k == "LANG_UI_DICT":
            continue
        if isinstance(v, str):
            merged[k] = v
    return merged


def _lang_files_mtime():
    mtimes = []
    for language_config in GSettingsLanguages.values():
        filename = language_config.get("filename", "")
        if not filename:
            continue
        filepath = os.path.join(BASE_DIR, filename)
        if os.path.exists(filepath):
            mtimes.append(os.path.getmtime(filepath))
    settings_path = os.path.join(BASE_DIR, "settings.json")
    if os.path.exists(settings_path):
        mtimes.append(os.path.getmtime(settings_path))
    return max(mtimes) if mtimes else 0.0


def reload_lang_dict(force=False):
    """Reload language files when changed on disk (dev-friendly, no restart needed)."""
    global LANG_UI_DICT, LANG_UI_JSON_CACHE, _LANG_FILES_MTIME, GSettingsLanguages, GSettingsLangDefault

    current_mtime = _lang_files_mtime()
    if not force and current_mtime <= _LANG_FILES_MTIME and LANG_UI_DICT:
        return

    settings_path = os.path.join(BASE_DIR, "settings.json")
    settings_data = _load_json_file(settings_path)
    GSettingsLangDefault = settings_data.get("lang_default", "zh")
    GSettingsLanguages = settings_data.get("languages", {})

    new_dict = {}
    for lang_code, language_config in GSettingsLanguages.items():
        filename = language_config.get("filename", "")
        if not filename:
            continue
        filepath_language = os.path.join(BASE_DIR, filename)
        try:
            language_data = _load_json_file(filepath_language)
            lang_ui_dict = _flatten_lang_dict(language_data)
            if lang_ui_dict:
                new_dict[lang_code] = lang_ui_dict
        except Exception as e:
            print("LanguageUtils: failed to load %s: %s" % (filename, str(e)))

    LANG_UI_DICT.clear()
    LANG_UI_DICT.update(new_dict)
    LANG_UI_JSON_CACHE.clear()
    LANG_UI_JSON_CACHE.update({
        lang: json.dumps(d, ensure_ascii=False)
        for lang, d in LANG_UI_DICT.items()
    })
    _LANG_FILES_MTIME = current_mtime


__settings_json_filepath = os.path.join(BASE_DIR, "settings.json")
__settings_data = _load_json_file(__settings_json_filepath)

GSettingsLangDefault = __settings_data.get("lang_default", "zh")
GSettingsLanguages = __settings_data.get("languages", {})

reload_lang_dict(force=True)


def __parse_get_params(request):
    params = {}
    try:
        for k in request.GET:
            params.__setitem__(k, request.GET.get(k))
    except Exception as e:
        params = {}
    return params


def __parse_post_params(request):
    params = {}
    for k in request.POST:
        params.__setitem__(k, request.POST.get(k))

    if not params:
        try:
            params = request.body.decode('utf-8')
            params = json.loads(params)
        except Exception:
            params = {}

    return params


def f_parse_request_lang(request):
    reload_lang_dict()
    request_lang = None

    if request.method == 'GET':
        params = __parse_get_params(request)
        lang = params.get('lang', '').strip()
        if lang:
            request_lang = lang
    elif request.method == 'POST':
        params = __parse_post_params(request)
        lang = params.get('lang', '').strip()
        if lang:
            request_lang = lang

    if not request_lang:
        if hasattr(request, 'session'):
            request_lang = request.session.get('lang', GSettingsLangDefault)

    if not request_lang:
        request_lang = GSettingsLangDefault

    return request_lang


def LANG_VIEWS_T(request, key):
    """翻译函数：根据当前请求的语言环境，从 LANG_UI_DICT 中获取翻译文本"""
    reload_lang_dict()
    lang = f_parse_request_lang(request)
    return LANG_UI_DICT.get(lang, {}).get(key, key)


def LANG_VIEWS_USE_LANG_T(lang, key):
    """翻译函数：根据指定语言，从 LANG_UI_DICT 中获取翻译文本"""
    reload_lang_dict()
    if not lang:
        lang = GSettingsLangDefault
    return LANG_UI_DICT.get(lang, {}).get(key, key)
