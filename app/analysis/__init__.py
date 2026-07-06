# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""
Rebucca · 视频分析层（阶段1）

模块构成：
- frames        从 ZLMediaKit 输出的 RTSP 流取帧（OpenCV VideoCapture）
- motion        运动检测（OpenCV 背景减除）
- detector      目标检测（ONNX Runtime，缺模型时优雅降级）
- tracker       单摄像头目标跟踪（轻量 IoU 关联）
- pipeline      单摄像头流水线：取帧 → 运动 → 检测 → 跟踪 → 事件
- worker_pool   多路共享的检测器进程池
- manager       全局分析管理器（启动/停止每路 pipeline，单例）

设计原则：
- 全部用 Python 实现，不引入 C++ 服务。
- 运动门控：仅在有运动的区域跑检测，显著降低 CPU/GPU 占用。
- 与 ZLMediaKit 解耦：通过 ZLM 输出的 RTSP URL 取帧，ZLM 仅负责协议接入。
- 优雅降级：未安装 opencv/numpy/onnxruntime 或未配置模型时，Web 层（Zone/Review/
  Timeline/TrackedObject）仍可正常使用，仅"启动分析"会提示依赖不可用。

为避免在 Django 启动期就拉起 OpenCV/ONNX 等较重依赖，本包不在此处 eager 导入
AnalysisManager；请通过 get_manager() 按需获取。
"""

def get_manager():
    """懒加载并返回全局 AnalysisManager 单例"""
    from app.analysis.manager import AnalysisManager
    return AnalysisManager()


__all__ = ["get_manager"]
