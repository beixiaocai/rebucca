# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
from django.http import HttpResponseRedirect

try:
    from django.utils.deprecation import MiddlewareMixin
except ImportError:
    MiddlewareMixin = object

# 无需登录即可访问的路径前缀（精确控制，禁止 blanket /open/ 放行）
AUTH_WHITELIST_PREFIXES = (
    '/login',
    '/logout',
    '/inner/',
    '/nvr/openSnap',
    '/user/openCaptcha',
    '/static/',
)

# 需 Safe 请求头鉴权的 open API（供 ZLM/内部服务调用，不暴露给浏览器）
OPEN_API_SAFE_HEADER_PREFIXES = (
    '/inner/',
)


class SimpleMiddleware(MiddlewareMixin):
    def process_request(self, request):
        path = request.path_info

        for prefix in AUTH_WHITELIST_PREFIXES:
            if path.startswith(prefix):
                return None

        if request.session.has_key("user"):
            if path.startswith("/login"):
                return HttpResponseRedirect("/")
            return None

        # 未登录：open API 须带 Safe 头（config.json safe 字段）
        if '/open' in path:
            headers = request.headers
            safe = headers.get("Safe") or request.META.get("HTTP_SAFE")
            try:
                from app.utils.GlobalUtils import g_config
                if safe and safe == g_config.safe:
                    return None
            except Exception:
                pass
            return HttpResponseRedirect("/login")

        return HttpResponseRedirect("/login")

    def process_response(self, request, response):
        return response
