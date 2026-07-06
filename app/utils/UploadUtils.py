# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
from datetime import datetime
import os
import shutil
import xlrd
from app.utils.LanguageUtils import LANG_VIEWS_USE_LANG_T


class UploadUtils():
    """文件上传工具类"""

    # 上传摄像头Excel文件
    def upload_camera_xlsx(self, file, upload_dir, lang=None):
        __ret = False
        __msg = LANG_VIEWS_USE_LANG_T(lang, "msg_unknown_error")
        __data = []

        file_name = file.name
        file_content_type = file.content_type
        if 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' == file_content_type and file_name.endswith(".xlsx"):
            filename_dir = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + file_name
            abs_filedir = os.path.join(upload_dir, filename_dir)
            if not os.path.exists(abs_filedir):
                os.makedirs(abs_filedir)

            abs_filepath = os.path.join(abs_filedir, file_name)
            f = open(abs_filepath, 'wb')
            f.write(file.read())
            f.close()

            # 读取excel
            wb = xlrd.open_workbook(abs_filepath)
            sheet = wb.sheet_by_index(0)

            if sheet.ncols in (8, 9, 10):  # 兼容8/9/10列
                for row in range(sheet.nrows):
                    if row > 0:
                        try:
                            row_cols = sheet.row_values(row)

                            code = str(row_cols[0]).strip()
                            nickname = str(row_cols[1]).strip()
                            pull_stream_url = str(row_cols[2]).strip()
                            pull_stream_ip = str(row_cols[3]).strip()

                            try:
                                pull_stream_port = int(row_cols[4])
                            except:
                                pull_stream_port = 554

                            username = str(row_cols[5]).strip()
                            password = str(row_cols[6]).strip()
                            remark = str(row_cols[7]).strip()

                            try:
                                is_audio = int(row_cols[8])
                            except:
                                is_audio = 0
                            try:
                                camera_device_id = str(row_cols[9]).strip()
                            except:
                                camera_device_id = code

                            d = {
                                'code': code,
                                'nickname': nickname,
                                'pull_stream_url': pull_stream_url,
                                'pull_stream_ip': pull_stream_ip,
                                'pull_stream_port': pull_stream_port,
                                'username': username,
                                'password': password,
                                'remark': remark,
                                'is_audio': is_audio,
                                'camera_device_id': camera_device_id,
                            }
                            __data.append(d)
                        except:
                            pass

                __ret = True
                __msg = LANG_VIEWS_USE_LANG_T(lang, "msg_success")
            else:
                __msg = LANG_VIEWS_USE_LANG_T(lang, "upload_xlsx_cols_incorrect")

            if os.path.exists(abs_filedir):
                shutil.rmtree(abs_filedir)
        else:
            __msg = LANG_VIEWS_USE_LANG_T(lang, "upload_xlsx_format_incorrect")

        return __ret, __msg, __data
