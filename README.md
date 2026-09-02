# Rebucca

**语言 / Language：** [简体中文](README.md) | [English](README_en.md)

**开源协议：** MIT License，可自由商用。详见 `LICENSE`。

- 官网：https://www.yuturuishi.com
- 微信：yuturuishi
- gitee开源地址：https://gitee.com/Vanishi/rebucca
- github开源地址：https://github.com/beixiaocai/rebucca

- Rebucca是多路视频接入与智能布控分析平台。支持 GB28181 / RTSP、YOLO 小模型检测、OpenAI 兼容大模型复核、多边形布控与结构化报警。

---

## 功能

- 视频接入：RTSP / GB28181 拉流，ZLMediaKit 转发，ONVIF 发现
- 智能分析：YOLO-PyTorch / ONNX / OpenVINO 小模型 + 可选大模型复核
- 布控报警：多边形区域、5 种后处理规则（入侵/越线/方向/密度/滞留）
- 运维：控制面板监控、流媒体启停、录像、多语言（7 种）

---

## 环境要求

- Python 3.10+
- FFmpeg（PATH 或 `config.json` 配置）
- ZLMediaKit（流媒体，端口与 `config.json` 一致）
- GPU 可选


```bash
如果是Linux系统，需要手动进入到zlm/bin.x86.gcc9.4 或 zlm/bin.arm.gcc9.4 ，确保可以正确执行 ./rebucca_zlm


如果执行./rebucca_zlm失败了，可以参考下面的两种方式解决安装环境问题

（1）解决方式一
sudo chmod -R a+x *
echo "export LD_LIBRARY_PATH=\"$(pwd):\$LD_LIBRARY_PATH\"" >> ~/.bashrc && source ~/.bashrc

（2）解决方式二

sudo apt update
sudo apt install -y libsrtp2-1

//下载ubuntu20的libssl1.1包
wget http://security.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2.24_amd64.deb
sudo dpkg -i libssl1.1_1.1.1f-1ubuntu2.24_amd64.deb

//修复依赖
sudo apt -f install

```

**安装依赖：**

```bash
# Windows
pip install -r requirements-windows.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
或
pip install -r requirements-windows.txt

# Linux
pip install -r requirements-linux.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
或
pip install -r requirements-linux.txt
```

---

## 快速开始

```bash
python manage.py runserver 0.0.0.0:10001
```

浏览器访问 `http://<host>:10001/`，默认账号 `admin`，默认密码 `admin888`。

首次部署请编辑 `config.json`（端口、ZLM、FFmpeg 等）和 `settings.json`（界面品牌）。启动配置页保存后多数项热更新生效；改管理端口或调试日志需重启服务。

---

## 使用顺序

```
视频管理 → 小模型 → 大模型 → 业务算法 → 布控管理 → 启动分析 → 报警管理
```

1. 添加摄像头并确认拉流正常
2. 上传/配置小模型（流程 1/3）和大模型（流程 2/3）
3. 创建业务算法，在布控页画区域并绑定算法
4. 点击「启动分析」（**重启服务后需手动再点**）
5. 在报警管理查看结果

> 只有业务算法规则命中才会报警；单纯检测到目标或画面运动不会产生报警记录。

---

## 常见问题

| 问题 | 处理 |
|------|------|
| 没有报警 | 确认拉流正常、布控已绑算法、已启动分析、检测类别匹配 |
| 改配置不生效 | 布控/算法可热更新；换小模型需重启分析；改端口需重启服务 |
| 端口占用 | 结束残留 `python.exe` 后重新启动 |

日志目录：`log/`。版本号见 `framework/settings.py`。

---

## 更新日志

### v1.004
- 2026/09/02
- **修复布控报警快照识别框位置异常（重要）**
  - 共享推理池链路（默认开启）发送帧前会将长边降采样至 ≤1280 以节省传输，推理返回的检测框 / 关键点 / 分割多边形坐标属于缩放后小图坐标系，此前未经还原直接画到原始分辨率快照上，导致报警管理图片中识别框整体偏左上、尺寸偏小，分辨率越高错位越明显。
  - 现已按缩放比例将检测结果坐标还原回原图坐标（`remote_detector.py`），未降采样时零开销直通；同时修正了区域命中判断（点在多边形内）使用错位坐标导致的潜在误报 / 漏报。
- **修复编辑用户提交报错（`int() argument ... not 'NoneType'`）**
  - 数据库返回的 `is_active` 为布尔值，前端直接赋给状态下拉框导致值匹配失败，提交时序列化为 `null`，后端 `int(None)` 抛出原始异常。
  - 前后端双重修复：前端将状态归一化为 `'1' / '0'`（`user/index.html`）；后端对 `is_active` 做布尔 / 字符串兼容归一化，`id` 缺失时返回业务错误提示（`UserView.py`）。
- **修复业务算法编辑弹框不回显已选检测目标**
  - 打开编辑弹框时，已选检测目标先被正确填充，但随后触发的 `onSmallModelChange()` 以空选中集重绘下拉框，把回显项全部清空，表现为「选了多少项，打开编辑却一个都没选中」。
  - 现改为保留当前已选项重绘（与检测+ReID 流程的 `onDetectorModelChange` 行为一致）；真实切换小模型时，不属于新模型标签列表的旧选中项仍会被自然过滤（`algorithm/index.html`）。

### v1.003
- 2026/08/06
- **业务算法选择大模型相关修复（重要）**
  - 大模型配置新增「名称」字段，可留空；新增 / 编辑时若名称为空，自动以「模型名称」兜底（`name = model_name`），避免大模型配置出现空名称。
  - 业务算法列表 / 编辑中，绑定大模型的显示名现在会回退到「模型名称」（`llm_name` 兜底 `name or model_name`），不再显示空白。
  - **修复业务算法编辑时，绑定的大模型若已被禁用，下拉框无法回显、看似「配置丢失 / 选不中」的问题**：现在自动补一个带「[禁用]」标记的回显项，且每次打开编辑会清理上一次的回显项。
  - 业务算法「大模型」下拉选项 label 改为 `name || model_name || #id`，确保只填了模型名称时也能正确显示。
- **新增「统计看板」（报警态势总览）**
  - 报警管理新增「统计看板」页面（`/alarm/dashboard`），一站式掌握报警态势。
  - 4 张核心统计卡：今日报警、近 7 天报警、累计报警、涉及摄像头数（均可点击下钻到对应列表）。
  - 报警趋势图：支持近 7 天 / 近 30 天切换。
  - 报警类型分布、报警 TOP 摄像头排行。
  - 新增接口 `alarm/openStats`，左侧导航新增「统计看板」入口。
- **国际化补全**
  - 补齐统计看板相关 16 个翻译键至全部 7 种语言（es / ko / ru / vi / zh-hk / zh / en），修复此前仅 zh / en 有译、其余语言界面显示原始 key 的问题。

> 版本号见 `framework/settings.py` 的 `PROJECT_VERSION`。
