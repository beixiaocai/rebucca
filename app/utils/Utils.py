# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
import random
import time
from app.utils.LanguageUtils import LANG_UI_DICT
import collections



def buildPageLabels(page, page_num, lang='zh'):
    """
    :param page: 当前页面
    :param page_num: 总页数
    :param lang: 语言代码，默认 'zh'
    :return:
    返回式例：
        [{'page': 1, 'name': 1, 'cur': True}, {'page': 2, 'name': 2, 'cur': False}, {'page': 2, 'name': '下一页'}]

    """
    T = LANG_UI_DICT.get(lang, LANG_UI_DICT['zh'])
    label_first = T.get('perm_first_page', '首页')
    label_prev = T.get('perm_prev_page', '上一页')
    label_next = T.get('perm_next_page', '下一页')
    label_last = T.get('perm_last_page', '尾页')

    pageLabels = []
    if page > 1:
        pageLabels.append({
            "page": 1,
            "name": label_first
        })
        pageLabels.append({
            "page": page - 1,  # 当前页点击时候触发的页数
            "name": label_prev
        })
    if page == 1:
        pageArray = [1, 2, 3, 4]
    else:
        pageArray = list(range(page - 1, page + 3))  # page-1,page,page+1,page+2

    for p in pageArray:
        if p <= page_num:
            if page == p:
                cur = 1
            else:
                cur = 0
            pageLabels.append({
                "page": p,
                "name": p,
                "cur": cur
            })

    if page + 1 <= page_num:
        pageLabels.append({
            "page": page + 1,
            "name": label_next
        })
    if page_num > 0:
        pageLabels.append({
            "page": page_num,
            "name": label_last
        })
    return pageLabels

def group_by_field(data, field):

    """
    根据数据项中的field参数将一维列表分组为二维列表

    Args:
        data: list of dicts, 一维数据结构，每个数据项为字典，包含field键

    Returns:
        list of lists: 二维数据结构，每个子列表包含相同field的数据项
    """
    grouped_dict = collections.defaultdict(list)
    for item in data:
        # 获取stream_name作为分组键
        value = item.get(field)
        grouped_dict[value].append(item)

    # 将字典中的值转换为二维列表
    return list(grouped_dict.values())

class GB28181CodeUtils:
    def __init__(self, default_area_code="34020000", default_industry="13"):
        """
        初始化生成器
        :param default_area_code: 默认行政区划码 (8位)
        :param default_industry: 默认行业编码 (2位)
        """
        self.default_area_code = default_area_code
        self.default_industry = default_industry

    def generate_by_time(self, area_code=None):
        """
        基于当前时间生成编号（常用于流水号场景）
        格式：行政区(8) + 行业(2) + 年月日时分秒(10) + 随机(0-9)
        注意：这种格式总长度也是20位，但逻辑不同
        """
        area = area_code if area_code else self.default_area_code
        # 截取时间的后10位数字作为序列号的一部分
        time_str = time.strftime("%y%m%d%H%M%S")  # 12位，取后10位或者做处理
        # 使用毫秒时间戳的后4位 + 3位随机数作为序列号，确保快速连续调用也不重复
        ms_part = f"{int(time.time() * 1000) % 10000:04d}"
        rand_part = f"{random.randint(0, 999):03d}"
        serial = ms_part + rand_part

        return f"{area}{self.default_industry}200{serial}"
