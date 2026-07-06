# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
from app.views.ViewsBase import *
from django.shortcuts import render


def index(request):
    """报警管理页面：集中展示与处理进入区域/滞留/运动等报警事件及快照"""
    return render(request, 'app/alarm/index.html', {})
