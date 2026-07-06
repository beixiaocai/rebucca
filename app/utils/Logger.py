# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
import logging
from logging.handlers import TimedRotatingFileHandler

# 统一日志格式：含模块名(name)与源码行号，便于 grep 定位
LOG_FORMAT = '%(asctime)s %(name)s:%(lineno)d [%(levelname)s] %(message)s'


def CreateLogger(filepath, is_show_console=False,log_debug=False):
    LOGGER_WHEN = 'd'
    LOGFILE_BACKUPCOUNT = 3
    if log_debug:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logger = logging.getLogger()
    logger.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)

    # 最基础
    # fileHandler = logging.FileHandler(filepath, encoding='utf-8')  # 指定utf-8格式编码，避免输出的日志文本乱码
    # fileHandler.setLevel(level)
    # fileHandler.setFormatter(formatter)
    # logger.addHandler(fileHandler)

    # 时间滚动切分
    # when:备份的时间单位，backupCount:备份保存的时间长度
    timedRotatingFileHandler = TimedRotatingFileHandler(filepath,
                                                        when=LOGGER_WHEN,
                                                        backupCount=LOGFILE_BACKUPCOUNT,
                                                        encoding='utf-8')

    timedRotatingFileHandler.setLevel(level)
    timedRotatingFileHandler.setFormatter(formatter)
    logger.addHandler(timedRotatingFileHandler)

    # 控制台打印
    if is_show_console:
        streamHandler = logging.StreamHandler()
        streamHandler.setLevel(level)
        streamHandler.setFormatter(formatter)
        logger.addHandler(streamHandler)

    return logger

