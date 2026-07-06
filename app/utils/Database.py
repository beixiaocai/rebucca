# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
import threading
from django.db import connection
g_dbLock = threading.Lock()# 用于操作数据库的全局锁（20240930新增，由于sqlite不支持锁，因此在程序中做锁控制）

class Database(object):
    def __init__(self, logger):
        self.logger = logger

    def select(self, sql):
        data = []
        with g_dbLock:
            cursor = connection.cursor()
            cursor.execute(sql)
            try:
                rawData = cursor.fetchall()
                col_names = [desc[0] for desc in cursor.description]
                for row in rawData:
                    d = {}
                    for index, value in enumerate(row):
                        d[col_names[index]] = value
                    data.append(d)
            except Exception as e:
                self.logger.error("Database.select() error:%s,sql:%s" % (str(e),sql))

        return data

    def execute(self, sql):
        ret = False
        with g_dbLock:
            try:
                cursor = connection.cursor()
                cursor.execute(sql)
                ret = True
            except Exception as e:
                self.logger.error("Database.execute() error:%s,sql:%s" % (str(e), sql))
        return ret

