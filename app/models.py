# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
from django.db import models
from app.utils.Database import g_dbLock
import json


class ThreadSafetyManager(models.Manager):
    def get_queryset(self):
        with g_dbLock:
            ret = super(ThreadSafetyManager, self).get_queryset()
        return ret


class StreamModel(models.Model):
    """视频流模型（摄像头管理）"""
    objects = ThreadSafetyManager()

    user_id = models.IntegerField(verbose_name='用户')
    sort = models.IntegerField(verbose_name='排序')
    code = models.CharField(max_length=50, verbose_name='编号')
    app = models.CharField(max_length=50, verbose_name='流分组')
    name = models.CharField(max_length=50, verbose_name='流名称')
    pull_stream_url = models.CharField(max_length=300, verbose_name='视频流源地址')
    pull_stream_type = models.IntegerField(verbose_name='视频流来源类型')  # 0:未知,1:RTSP,2:RTMP,3:FLV,4:HLS,21:GB28181,31:被动RTSP,32:被动RTMP
    pull_stream_transfer_mode = models.IntegerField(verbose_name='视频流传输模式')  # 0:UDP,1:TCP被动,2:TCP主动
    pull_stream_ip = models.CharField(max_length=50, verbose_name='拉流IP')
    pull_stream_port = models.IntegerField(verbose_name='拉流端口')
    pull_stream_username = models.CharField(max_length=50, verbose_name='拉流用户名')
    pull_stream_password = models.CharField(max_length=50, verbose_name='拉流密码')
    nickname = models.CharField(max_length=200, verbose_name='视频流昵称')
    remark = models.CharField(max_length=200, verbose_name='备注')
    forward_state = models.IntegerField(verbose_name='转发状态')  # 0:未转发 1:转发中
    is_audio = models.IntegerField(default=0, verbose_name='音频传输类型')  # 0:静音 1:原始声音
    snap_filepath = models.CharField(max_length=200, verbose_name='快照文件路径')
    snap_time = models.DateTimeField(auto_now_add=True, verbose_name='快照时间')
    camera_sum_num = models.IntegerField(default=0, verbose_name='通道总数')
    camera_name = models.CharField(max_length=100, verbose_name='摄像头名称')
    camera_manufacturer = models.CharField(max_length=100, verbose_name='摄像头厂商')
    camera_owner = models.CharField(max_length=50, verbose_name='摄像头所属者')
    camera_model = models.CharField(max_length=50, verbose_name='摄像头型号')
    camera_device_id = models.CharField(max_length=50, verbose_name='GB28181设备ID')  # gb28181注册的client_id
    camera_parent_id = models.CharField(max_length=50, verbose_name='GB28181父设备ID')
    camera_civilcode = models.CharField(max_length=50, verbose_name='行政区划码')
    camera_last_keepalive_time = models.DateTimeField(auto_now_add=True, verbose_name='最近一次心跳时间')
    camera_last_register_time = models.DateTimeField(auto_now_add=True, verbose_name='最近一次注册时间')

    # 向上级联国标编号字段（v1.0新增）start
    cascade_device_id = models.CharField(max_length=50, default='', verbose_name='向上级联国标编号')  # 自定义向上级联的国标编号，为空则使用camera_device_id
    cascade_enable = models.IntegerField(default=0, verbose_name='是否启用向上级联')  # 0:不启用 1:启用
    # 向上级联国标编号字段 end

    # 视频分析字段（v1.0新增）start
    algorithm = models.ForeignKey('AlgorithmModel', on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='streams', verbose_name='分析算法')  # null=走默认算法
    record_enable = models.IntegerField(default=0, verbose_name='启用24/7录像')  # 0:否 1:是
    # 视频分析字段 end

    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    last_update_time = models.DateTimeField(auto_now_add=True, verbose_name='更新时间')
    add_type = models.IntegerField(default=0, verbose_name='添加类型')  # 0:手动添加 1:批量导入 10:接口添加 21:GB28181自动添加
    state = models.IntegerField(default=0, verbose_name='状态')

    def __repr__(self):
        return self.nickname

    def __str__(self):
        return self.nickname

    def delete(self, using=None, keep_parents=False):
        with g_dbLock:
            ret = super(StreamModel, self).delete(using, keep_parents)
        return ret

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        with g_dbLock:
            ret = super(StreamModel, self).save(force_insert, force_update, using, update_fields)
        return ret

    class Meta:
        db_table = 'av_stream'
        verbose_name = '视频流'
        verbose_name_plural = '视频流'


class AlgorithmModel(models.Model):
    """算法模型 — 检测算法的元数据与运行时参数（每路摄像头可独立选择）"""
    objects = ThreadSafetyManager()

    ENGINE_YOLO_PYTORCH = 'yolo_pytorch'
    ENGINE_ONNXRUNTIME = 'onnxruntime'
    ENGINE_OPENVINO = 'openvino'
    ENGINE_CHOICES = (
        (ENGINE_YOLO_PYTORCH, 'Yolo-PyTorch'),
        (ENGINE_ONNXRUNTIME, 'OnnxRuntime'),
        (ENGINE_OPENVINO, 'OpenVINO'),
    )

    # 算法类型：YOLO 检测系列 + ReID 特征系列
    ALGO_TYPE_YOLO5 = 'yolo5'
    ALGO_TYPE_YOLO8 = 'yolo8'
    ALGO_TYPE_YOLO11 = 'yolo11'
    ALGO_TYPE_YOLO26 = 'yolo26'
    ALGO_TYPE_OSNET = 'osnet'
    ALGO_TYPE_CHOICES = (
        (ALGO_TYPE_YOLO5, 'YOLOv5'),
        (ALGO_TYPE_YOLO8, 'YOLOv8'),
        (ALGO_TYPE_YOLO11, 'YOLOv11'),
        (ALGO_TYPE_YOLO26, 'YOLO26'),
        (ALGO_TYPE_OSNET, 'OSNet ReID'),
    )

    # 任务类型
    TASK_DETECT = 'detect'
    TASK_SEGMENT = 'segment'
    TASK_CLASSIFY = 'classify'
    TASK_POSE = 'pose'
    TASK_OBB = 'obb'
    TASK_REID = 'reid'
    TASK_CHOICES = (
        (TASK_DETECT, 'Detect'),
        (TASK_SEGMENT, 'Segment'),
        (TASK_CLASSIFY, 'Classify'),
        (TASK_POSE, 'Pose'),
        (TASK_OBB, 'OBB'),
        (TASK_REID, 'ReID'),
    )

    # 推理设备
    DEVICE_CPU = 'cpu'
    DEVICE_CUDA = 'cuda'
    DEVICE_GPU = 'gpu'
    DEVICE_CHOICES = (
        (DEVICE_CPU, 'CPU'),
        (DEVICE_CUDA, 'CUDA'),
        (DEVICE_GPU, 'GPU'),
    )

    name = models.CharField(max_length=100, verbose_name='算法名称')
    algorithm_type = models.CharField(max_length=30, default='yolo8', choices=ALGO_TYPE_CHOICES, verbose_name='算法类型')
    task_type = models.CharField(max_length=20, default=TASK_DETECT, choices=TASK_CHOICES, verbose_name='任务类型')
    inference_engine = models.CharField(max_length=20, default=ENGINE_YOLO_PYTORCH, choices=ENGINE_CHOICES, verbose_name='推理引擎')
    device = models.CharField(max_length=20, default=DEVICE_CPU, choices=DEVICE_CHOICES, verbose_name='推理设备')
    model_file = models.CharField(max_length=300, default='', verbose_name='模型文件相对路径')  # 相对 uploadDir/weight/
    model_file_size = models.IntegerField(default=0, verbose_name='模型文件大小(字节)')
    input_width = models.IntegerField(default=640, verbose_name='输入宽度')
    input_height = models.IntegerField(default=640, verbose_name='输入高度')
    conf_threshold = models.FloatField(default=0.4, verbose_name='置信度阈值')
    iou_threshold = models.FloatField(default=0.5, verbose_name='NMS IoU 阈值')
    labels = models.TextField(default='[]', verbose_name='支持类别JSON数组')  # ["person","car",...]
    is_default = models.IntegerField(default=0, verbose_name='是否默认算法')  # 1=全局兜底
    state = models.IntegerField(default=1, verbose_name='状态')  # 0=禁用 1=启用
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    last_update_time = models.DateTimeField(auto_now_add=True, verbose_name='更新时间')

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name

    def delete(self, using=None, keep_parents=False):
        with g_dbLock:
            ret = super(AlgorithmModel, self).delete(using, keep_parents)
        return ret

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        with g_dbLock:
            ret = super(AlgorithmModel, self).save(force_insert, force_update, using, update_fields)
        return ret

    class Meta:
        db_table = 'av_algorithm'
        verbose_name = '小模型'
        verbose_name_plural = '小模型'


class BizAlgorithmModel(models.Model):
    """业务算法 — 小模型/大模型推理 + 后处理业务逻辑（布控绑定此表）"""
    objects = ThreadSafetyManager()

    FLOW_SMALL = 1
    FLOW_LLM = 2
    FLOW_BOTH = 3
    FLOW_DETECT_REID = 4
    FLOW_CHOICES = (
        (FLOW_SMALL, '小模型+后处理'),
        (FLOW_LLM, '大模型+后处理'),
        (FLOW_BOTH, '小模型+大模型+后处理'),
        (FLOW_DETECT_REID, '检测+ReID+后处理'),
    )

    POST_AREA = 'AREA'           # 区域入侵：目标中心在多边形内
    POST_LINE_CROSS = 'LINE_CROSS'  # 越线检测：轨迹跨过有向线段
    POST_LINE_COUNT = 'LINE_COUNT'  # 越线计数：正向/逆向分别累计，超阈值报警
    POST_DIRECTION = 'DIRECTION'  # 方向入侵：移动方向匹配设定方向
    POST_DENSITY = 'DENSITY'     # 密度报警：区域内目标数 >= 阈值
    POST_DWELL = 'DWELL'         # 滞留报警：在区域内停留 >= 阈值秒
    POST_CHOICES = (
        (POST_AREA, '区域入侵'),
        (POST_LINE_CROSS, '越线检测'),
        (POST_LINE_COUNT, '越线计数'),
        (POST_DIRECTION, '方向入侵'),
        (POST_DENSITY, '密度报警'),
        (POST_DWELL, '滞留报警'),
    )

    name = models.CharField(max_length=100, verbose_name='算法名称')
    flow_type = models.IntegerField(default=FLOW_SMALL, choices=FLOW_CHOICES, verbose_name='流程类型')
    small_model = models.ForeignKey(
        'AlgorithmModel', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='biz_algorithms', verbose_name='小模型',
    )
    detector_model = models.ForeignKey(
        'AlgorithmModel', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='biz_algorithms_as_detector', verbose_name='检测小模型(YOLO)',
    )
    target_labels = models.TextField(default='[]', verbose_name='目标类别JSON')  # ["person","car"]
    llm = models.ForeignKey(
        'LLMModel', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='biz_algorithms', verbose_name='大模型',
    )
    llm_prompt = models.TextField(default='', verbose_name='大模型提示词')
    llm_validate = models.TextField(default='', verbose_name='提示词校验值')  # 逗号分隔关键词
    post_process = models.CharField(max_length=30, default=POST_AREA, choices=POST_CHOICES, verbose_name='后处理逻辑')
    # DIRECTION 后处理参数：参考角度(0°=右,90°=下,180°=左,270°=上) 与容差
    ref_angle = models.FloatField(default=90.0, verbose_name='方向参考角度')
    angle_tolerance = models.FloatField(default=45.0, verbose_name='方向容差(度)')
    forward_count_threshold = models.IntegerField(default=0, verbose_name='正向计数报警阈值')  # 0=不报警
    reverse_count_threshold = models.IntegerField(default=0, verbose_name='逆向计数报警阈值')  # 0=不报警
    state = models.IntegerField(default=1, verbose_name='状态')  # 0=禁用 1=启用
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    last_update_time = models.DateTimeField(auto_now_add=True, verbose_name='更新时间')

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name

    def delete(self, using=None, keep_parents=False):
        with g_dbLock:
            ret = super(BizAlgorithmModel, self).delete(using, keep_parents)
        return ret

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        with g_dbLock:
            ret = super(BizAlgorithmModel, self).save(force_insert, force_update, using, update_fields)
        return ret

    class Meta:
        db_table = 'av_biz_algorithm'
        verbose_name = '业务算法'
        verbose_name_plural = '业务算法'


class ZoneModel(models.Model):
    """摄像头区域（多边形）— 跨摄像头追踪/告警规则的区域定义"""
    objects = ThreadSafetyManager()

    stream = models.ForeignKey(StreamModel, on_delete=models.CASCADE, verbose_name='所属摄像头')
    name = models.CharField(max_length=100, verbose_name='区域名称')
    coordinates = models.TextField(verbose_name='多边形坐标')  # JSON: [[x1,y1],[x2,y2],...]
    is_required = models.IntegerField(default=1, verbose_name='是否必需区域')  # 1:目标必须在区域内才触发区域类后处理
    loiter_threshold = models.IntegerField(default=0, verbose_name='滞留阈值(秒)')  # 0=不检测滞留
    detect_interval_sec = models.FloatField(default=1.0, verbose_name='检测间隔(秒)')  # 每 N 秒
    detect_frames = models.IntegerField(default=1, verbose_name='检测帧数')  # 分析 M 帧，频率=M/N fps
    color = models.CharField(max_length=20, default='#169F85', verbose_name='显示颜色')
    # LINE_CROSS 后处理：警戒线段两端点(归一化坐标0~1)，JSON: [x,y]
    line_a = models.TextField(default='', verbose_name='警戒线端点A')  # JSON: [x,y] 归一化
    line_b = models.TextField(default='', verbose_name='警戒线端点B')  # JSON: [x,y] 归一化
    # DENSITY 后处理：密度报警阈值(区域内目标数)
    density_threshold = models.IntegerField(default=0, verbose_name='密度阈值')  # 0=不检测密度
    algorithms = models.ManyToManyField('BizAlgorithmModel', blank=True, related_name='zones', verbose_name='分析算法')
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    last_update_time = models.DateTimeField(auto_now_add=True, verbose_name='更新时间')
    state = models.IntegerField(default=1, verbose_name='状态')  # 1:启用 0:禁用

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name

    def delete(self, using=None, keep_parents=False):
        with g_dbLock:
            ret = super(ZoneModel, self).delete(using, keep_parents)
        return ret

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        with g_dbLock:
            ret = super(ZoneModel, self).save(force_insert, force_update, using, update_fields)
        return ret

    class Meta:
        db_table = 'av_zone'
        verbose_name = '区域'
        verbose_name_plural = '区域'


class AlarmModel(models.Model):
    """报警记录 — 布控分析触发的报警事件"""
    objects = ThreadSafetyManager()

    EVENT_TYPES = (
        ('entered_zone', '进入区域'),
        ('loiter', '滞留告警'),
    )

    stream = models.ForeignKey(StreamModel, null=True, on_delete=models.CASCADE, verbose_name='摄像头')
    event_type = models.CharField(max_length=32, default='entered_zone', verbose_name='报警类型')
    description = models.CharField(max_length=300, default='', verbose_name='描述')
    timestamp = models.DateTimeField(verbose_name='发生时间')
    metadata = models.TextField(default='{}', verbose_name='元数据JSON')
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='入库时间')

    def __repr__(self):
        return self.event_type

    def __str__(self):
        return self.event_type

    def delete(self, using=None, keep_parents=False):
        with g_dbLock:
            ret = super(AlarmModel, self).delete(using, keep_parents)
        return ret

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        with g_dbLock:
            ret = super(AlarmModel, self).save(force_insert, force_update, using, update_fields)
        return ret

    class Meta:
        db_table = 'av_alarm'
        verbose_name = '报警'
        verbose_name_plural = '报警'
        indexes = [
            models.Index(fields=['-timestamp'], name='av_alarm_ts_idx'),
            models.Index(fields=['stream', 'timestamp'], name='av_alarm_st_idx'),
        ]


class RecordingModel(models.Model):
    """24/7 录像分段索引"""
    objects = ThreadSafetyManager()

    stream = models.ForeignKey(StreamModel, on_delete=models.CASCADE, verbose_name='摄像头')
    file_path = models.CharField(max_length=500, verbose_name='文件路径')
    start_time = models.DateTimeField(verbose_name='开始时间')
    end_time = models.DateTimeField(verbose_name='结束时间')
    duration = models.FloatField(default=0, verbose_name='时长(秒)')
    file_size = models.BigIntegerField(default=0, verbose_name='文件大小(字节)')
    has_motion = models.IntegerField(default=0, verbose_name='含运动')
    has_object = models.IntegerField(default=0, verbose_name='含目标')
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='入库时间')

    class Meta:
        db_table = 'av_recording'
        verbose_name = '录像分段'
        verbose_name_plural = '录像分段'
        indexes = [
            models.Index(fields=['stream', 'start_time'], name='av_recording_st_idx'),
        ]


class LLMModel(models.Model):
    """大模型配置（OpenAI 兼容 API）"""
    objects = ThreadSafetyManager()

    user_id = models.IntegerField(verbose_name='用户')
    sort = models.IntegerField(default=0, verbose_name='排序')
    code = models.CharField(max_length=50, verbose_name='编号')
    name = models.CharField(max_length=50, default='', verbose_name='名称')
    model_name = models.CharField(max_length=200, verbose_name='模型名称')
    api_url = models.CharField(max_length=500, verbose_name='API地址')
    api_key = models.CharField(max_length=200, default='', verbose_name='API密钥')
    timeout = models.IntegerField(default=30, verbose_name='超时时间(秒)')
    inference_tool = models.CharField(max_length=100, default='OpenAI', verbose_name='推理工具')
    remark = models.TextField(default='', verbose_name='备注')
    state = models.IntegerField(default=1, verbose_name='状态')  # 0=禁用 1=启用
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    last_update_time = models.DateTimeField(auto_now_add=True, verbose_name='更新时间')

    def delete(self, using=None, keep_parents=False):
        with g_dbLock:
            ret = super(LLMModel, self).delete(using, keep_parents)
        return ret

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        with g_dbLock:
            ret = super(LLMModel, self).save(force_insert, force_update, using, update_fields)
        return ret

    class Meta:
        db_table = 'av_llm'
        verbose_name = '大模型'
        verbose_name_plural = '大模型'


class LogModel(models.Model):
    """管理员操作日志"""
    objects = ThreadSafetyManager()

    user_id = models.IntegerField(verbose_name='用户ID')
    log_type = models.IntegerField(verbose_name='日志类型')  # 1:添加 2:编辑 3:删除 10:系统操作 100:系统重置
    content = models.CharField(max_length=200, verbose_name='日志内容')
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    state = models.IntegerField(verbose_name='状态')  # 1:成功 0:失败

    def __repr__(self):
        return self.content

    def __str__(self):
        return self.content

    def delete(self, using=None, keep_parents=False):
        with g_dbLock:
            ret = super(LogModel, self).delete(using, keep_parents)
        return ret

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        with g_dbLock:
            ret = super(LogModel, self).save(force_insert, force_update, using, update_fields)
        return ret

    class Meta:
        db_table = 'av_log'
        verbose_name = '管理员日志'
        verbose_name_plural = '管理员日志'
