# Rebucca

**Language / 语言：** [简体中文](README.md) | [English](README_en.md)

**License:** MIT License, free for commercial use. See `LICENSE` for details.

- Website: https://www.yuturuishi.com
- WeChat: yuturuishi
- Gitee: https://gitee.com/Vanishi/rebucca
- GitHub: https://github.com/beixiaocai/rebucca

- A multi-channel video access and intelligent surveillance/deployment analysis platform. Supports GB28181 / RTSP, YOLO small-model detection, OpenAI-compatible LLM review, polygon-based deployment zones, and structured alarms.

---

## Features

- Video access: RTSP / GB28181 streaming, ZLMediaKit forwarding, ONVIF discovery
- Intelligent analysis: YOLO-PyTorch / ONNX / OpenVINO small models + optional LLM review
- Deployment & alarms: polygon zones, 5 post-processing rules (intrusion / line-crossing / direction / density / dwell)
- Operations: dashboard monitoring, streaming server start/stop, recording, multi-language (7 languages)

---

## Requirements

- Python 3.10+
- FFmpeg (in PATH or configured in `config.json`)
- ZLMediaKit (streaming server, ports must match `config.json`)
- GPU optional


```bash
On Linux, you need to manually enter zlm/bin.x86.gcc9.4 or zlm/bin.arm.gcc9.4 and make sure ./rebucca_zlm can be executed correctly.

If ./rebucca_zlm fails to run, refer to the following two ways to resolve the dependency issues.

(1) Solution 1
sudo chmod -R a+x *
echo "export LD_LIBRARY_PATH=\"$(pwd):\$LD_LIBRARY_PATH\"" >> ~/.bashrc && source ~/.bashrc

(2) Solution 2

sudo apt update
sudo apt install -y libsrtp2-1

// Download the Ubuntu 20 libssl1.1 package
wget http://security.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2.24_amd64.deb
sudo dpkg -i libssl1.1_1.1.1f-1ubuntu2.24_amd64.deb

// Fix dependencies
sudo apt -f install

```

**Install dependencies:**

```bash
# Windows
pip install -r requirements-windows.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
or
pip install -r requirements-windows.txt

# Linux
pip install -r requirements-linux.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
or
pip install -r requirements-linux.txt
```

---

## Quick Start

```bash
python manage.py runserver 0.0.0.0:10001
```

Open `http://<host>:10001/` in your browser. Default account: `admin`, default password: `admin888`.

For the first deployment, edit `config.json` (ports, ZLM, FFmpeg, etc.) and `settings.json` (UI branding). Most items take effect via hot reload after saving on the startup configuration page; changing the admin port or debug logging requires a service restart.

---

## Recommended Workflow

```
Video Management → Small Models → LLMs → Business Algorithms → Deployment Management → Start Analysis → Alarm Management
```

1. Add cameras and confirm streaming works
2. Upload/configure small models (flow 1/3) and LLMs (flow 2/3)
3. Create business algorithms, draw zones on the deployment page and bind algorithms
4. Click "Start Analysis" (**must be clicked again manually after a service restart**)
5. View results in Alarm Management

> Only hits on business algorithm rules produce alarms; merely detecting targets or detecting motion in the frame does not create alarm records.

---

## FAQ

| Issue | Solution |
|------|------|
| No alarms | Confirm streaming works, the zone has a bound algorithm, analysis is started, and detection classes match |
| Config changes not applied | Deployment/algorithm settings support hot reload; changing small models requires restarting analysis; changing ports requires a service restart |
| Port occupied | Kill leftover `python.exe` processes and restart |

Log directory: `log/`. For the version number, see `framework/settings.py`.

---

## Changelog

### v1.004
- 2026/09/02
- **Fixed incorrect detection box positions in deployment alarm snapshots (important)**
  - The shared inference pool pipeline (enabled by default) downscales frames to a long side of ≤1280 before sending to save transfer cost. The detection boxes / keypoints / segmentation polygons returned by inference are in the downscaled image coordinate system, but were previously drawn directly onto the original full-resolution snapshot without rescaling. As a result, detection boxes in alarm management images were shifted toward the top-left and too small — the higher the resolution, the worse the misalignment.
  - Detection result coordinates are now rescaled back to the original image coordinates (`remote_detector.py`), with zero-overhead passthrough when no downscaling occurs. This also fixes potential false/missed alarms caused by incorrect coordinates in zone-hit detection (point-in-polygon).
- **Fixed error when submitting the user edit form (`int() argument ... not 'NoneType'`)**
  - The database returns `is_active` as a boolean. The frontend assigned it directly to the status dropdown, causing the value match to fail; on submit it was serialized as `null`, and the backend's `int(None)` threw a raw exception.
  - Fixed on both ends: the frontend normalizes the status to `'1' / '0'` (`user/index.html`); the backend normalizes `is_active` with boolean/string compatibility and returns a business error message when `id` is missing (`UserView.py`).
- **Fixed the business algorithm edit dialog not showing previously selected detection targets**
  - When opening the edit dialog, previously selected detection targets were first populated correctly, but the subsequent `onSmallModelChange()` call re-rendered the select with an empty selection set, wiping out all restored selections — appearing as "no matter how many targets were selected, none show up when editing".
  - Now the select is re-rendered while preserving the current selection (consistent with `onDetectorModelChange` in the detect+ReID flow). When actually switching small models, old selections that are not in the new model's label list are still filtered out naturally (`algorithm/index.html`).

### v1.003
- 2026/08/06
- **Fixes related to LLM selection in business algorithms (important)**
  - LLM configuration now has a new "Name" field which can be left empty; on add/edit, if the name is empty, it falls back to the model name (`name = model_name`), preventing empty names in LLM configurations.
  - In business algorithm list/edit views, the display name of a bound LLM now falls back to the model name (`llm_name` falls back to `name or model_name`) instead of showing blank.
  - **Fixed an issue where, when editing a business algorithm bound to an LLM that has been disabled, the dropdown could not display the selection, looking like "configuration lost / not selectable"**: an echo item tagged with "[disabled]" is now added automatically, and each time the edit dialog opens, the previous echo item is cleaned up.
  - The label of the business algorithm "LLM" dropdown options is now `name || model_name || #id`, ensuring correct display when only the model name is filled in.
- **Added "Statistics Dashboard" (alarm situation overview)**
  - Alarm management now has a "Statistics Dashboard" page (`/alarm/dashboard`) for an at-a-glance view of the alarm situation.
  - 4 core stat cards: today's alarms, last-7-day alarms, total alarms, and number of involved cameras (all clickable to drill down to the corresponding list).
  - Alarm trend chart: supports switching between last 7 days / last 30 days.
  - Alarm type distribution and top cameras by alarm count.
  - Added the `alarm/openStats` API and a "Statistics Dashboard" entry in the left navigation.
- **i18n completion**
  - Completed the 16 translation keys related to the statistics dashboard in all 7 languages (es / ko / ru / vi / zh-hk / zh / en), fixing the issue where only zh / en had translations and other languages displayed raw keys.

> For the version number, see `PROJECT_VERSION` in `framework/settings.py`.
