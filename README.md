# Rebucca

多路视频接入与智能布控分析平台。支持 GB28181 / RTSP、YOLO 小模型检测、OpenAI 兼容大模型复核、多边形布控与结构化报警。

| 链接 | |
|------|--|
| 官网 | https://www.yuturuishi.com |
| Gitee | https://gitee.com/Vanishi/rebucca |
| GitHub | https://github.com/beixiaocai/rebucca |
| 作者 | 北小菜 · [哔哩哔哩](https://space.bilibili.com/487906612) |

**开源协议：** MIT License，可自由商用。详见 `LICENSE`。

* 体验地址：http://47.110.138.209:10001 账号：admin 密码： admin888

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
pip install -r requirements-windows.txt

# Linux
pip install -r requirements-linux.txt
```

---

## 快速开始

```bash
python manage.py runserver 0.0.0.0:10001
```

浏览器访问 `http://<host>:10001/`，默认账号 `admin`。

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
