# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""本机显卡信息采集（支持 NVIDIA / Intel / AMD，Windows & Linux）"""
import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

_GPU_CACHE = {"ts": 0.0, "data": []}
_GPU_STATIC_CACHE = {"ts": 0.0, "adapters": []}
_GPU_CACHE_LOCK = threading.Lock()
_GPU_CACHE_TTL = 8.0
_GPU_STATIC_TTL = 120.0


def _byte_to_mb(val):
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return round(v / (1024 * 1024), 1)


def _run_cmd(cmd, timeout=8, shell=False):
    try:
        flags = 0
        if os.name == 'nt' and hasattr(subprocess, 'CREATE_NO_WINDOW'):
            flags = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
            encoding='utf-8',
            errors='ignore',
            creationflags=flags,
        )
        if proc.returncode != 0:
            return ''
        return (proc.stdout or '').strip()
    except Exception:
        return ''


def _vendor_from_name(name):
    n = (name or '').lower()
    if 'nvidia' in n or 'geforce' in n or 'quadro' in n or 'tesla' in n or 'rtx' in n or 'gtx' in n:
        return 'nvidia'
    if 'intel' in n or 'iris' in n or 'uhd' in n:
        return 'intel'
    if 'amd' in n or 'radeon' in n:
        return 'amd'
    return 'other'


def _is_virtual_gpu(name):
    n = (name or '').lower()
    skip = (
        'microsoft basic', 'remote desktop', 'virtual display', 'virtual adapter',
        'meta virtual', 'spacedesk', 'parsec', 'vmware', 'virtualbox',
        'oray', 'idd driver', 'sunlogin', 'toDesk',
    )
    return any(k in n for k in skip)


def _merge_gpu(existing, new):
    """按 index / 规范化名称合并，保留利用率更高的记录。"""
    key = new.get('key') or str(new.get('index', new.get('name', '')))
    old = existing.get(key)
    if not old:
        existing[key] = new
        return
    for field in ('util_percent', 'mem_used_mb', 'mem_total_mb', 'temperature_c'):
        nv = new.get(field)
        ov = old.get(field)
        if nv is not None and (ov is None or (field == 'util_percent' and nv > ov)):
            old[field] = nv
    if len(new.get('name') or '') > len(old.get('name') or ''):
        old['name'] = new['name']
    if new.get('vendor') and new.get('vendor') != 'other':
        old['vendor'] = new['vendor']


def _finalize_gpu(item):
    util = item.get('util_percent')
    mem_used = item.get('mem_used_mb')
    mem_total = item.get('mem_total_mb')
    mem_rate = None
    if mem_used is not None and mem_total and mem_total > 0:
        mem_rate = round(mem_used / mem_total, 3)
    elif item.get('mem_util_percent') is not None:
        mem_rate = round(float(item['mem_util_percent']) / 100, 3)

    parts = []
    if util is not None:
        parts.append('%s%%' % round(float(util), 1))
    if mem_used is not None and mem_total:
        parts.append('%s / %s' % (_fmt_mb(mem_used), _fmt_mb(mem_total)))
    elif mem_total:
        parts.append(_fmt_mb(mem_total))

    return {
        'index': item.get('index', 0),
        'name': item.get('name') or 'GPU',
        'vendor': item.get('vendor') or 'other',
        'util_percent': round(float(util), 1) if util is not None else None,
        'mem_used_mb': mem_used,
        'mem_total_mb': mem_total,
        'mem_used_rate': mem_rate,
        'temperature_c': item.get('temperature_c'),
        'detail_str': ' / '.join(parts) if parts else '--',
    }


def _fmt_mb(v):
    if v is None:
        return '--'
    if v >= 1024:
        return '%.2fGB' % (v / 1024)
    if float(v).is_integer():
        return '%dMB' % int(v)
    return '%.1fMB' % float(v)


def _collect_nvidia_gpus():
    if not shutil.which('nvidia-smi'):
        return []
    out = _run_cmd([
        'nvidia-smi',
        '--query-gpu=index,name,utilization.gpu,utilization.memory,memory.total,memory.used,temperature.gpu',
        '--format=csv,noheader,nounits',
    ])
    if not out:
        return []
    gpus = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 6:
            continue
        try:
            idx = int(parts[0])
        except ValueError:
            idx = len(gpus)
        name = parts[1]
        util_gpu = _safe_float(parts[2])
        mem_util = _safe_float(parts[3])
        mem_total = _safe_float(parts[4])
        mem_used = _safe_float(parts[5])
        temp = _safe_float(parts[6]) if len(parts) > 6 else None
        gpus.append({
            'key': 'nvidia:%s' % idx,
            'index': idx,
            'name': name,
            'vendor': 'nvidia',
            'util_percent': util_gpu,
            'mem_util_percent': mem_util,
            'mem_total_mb': mem_total,
            'mem_used_mb': mem_used,
            'temperature_c': temp,
        })
    return gpus


def _safe_float(s):
    if s is None:
        return None
    s = str(s).strip().replace('[N/A]', '').replace('N/A', '')
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _collect_windows_adapters():
    """WMI 读取显卡列表（较快，不含利用率）。"""
    now = time.time()
    with _GPU_CACHE_LOCK:
        if _GPU_STATIC_CACHE['adapters'] and now - _GPU_STATIC_CACHE['ts'] < _GPU_STATIC_TTL:
            return list(_GPU_STATIC_CACHE['adapters'])

    ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$controllers = Get-CimInstance Win32_VideoController | Where-Object {
    $_.Name -and ($_.Name -notmatch 'Microsoft Basic|Remote Desktop|Virtual Display|Virtual Adapter|Meta Virtual|Spacedesk|Parsec|VMware|VirtualBox|Oray|Idd Driver|Sunlogin|ToDesk')
}
$list = @()
$i = 0
foreach ($c in $controllers) {
    $name = [string]$c.Name
    $vendor = 'other'
    if ($name -match 'NVIDIA|GeForce|Quadro|RTX|GTX|Tesla') { $vendor = 'nvidia' }
    elseif ($name -match 'Intel|Iris|UHD|Arc') { $vendor = 'intel' }
    elseif ($name -match 'AMD|Radeon') { $vendor = 'amd' }
    $ramMb = $null
    if ($c.AdapterRAM -and [double]$c.AdapterRAM -gt 0) {
        $ramMb = [math]::Round([double]$c.AdapterRAM / 1MB, 0)
    }
    $list += [pscustomobject]@{
        index = $i
        name = $name
        vendor = $vendor
        mem_total_mb = $ramMb
    }
    $i++
}
$list | ConvertTo-Json -Compress
"""
    out = _run_cmd(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script], timeout=5)
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]

    adapters = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get('name') or ''
        if _is_virtual_gpu(name):
            continue
        adapters.append({
            'index': item.get('index', len(adapters)),
            'name': name,
            'vendor': item.get('vendor') or _vendor_from_name(name),
            'mem_total_mb': item.get('mem_total_mb'),
        })

    with _GPU_CACHE_LOCK:
        _GPU_STATIC_CACHE['adapters'] = list(adapters)
        _GPU_STATIC_CACHE['ts'] = time.time()
    return adapters


def _collect_windows_util():
    """读取 Windows GPU 利用率（Get-Counter 较慢，单独调用并限制超时）。"""
    ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$utilByPhys = @{}
try {
    $samples = (Get-Counter '\GPU Engine(*)\Utilization Percentage' -SampleInterval 1 -MaxSamples 1).CounterSamples
    foreach ($s in $samples) {
        if ($s.InstanceName -match 'phys_(\d+)') {
            $p = $matches[1]
            $v = [double]$s.CookedValue
            if (-not $utilByPhys.ContainsKey($p) -or $v -gt $utilByPhys[$p]) {
                $utilByPhys[$p] = [math]::Round($v, 1)
            }
        }
    }
} catch {}
$utilByPhys | ConvertTo-Json -Compress
"""
    out = _run_cmd(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script], timeout=4)
    if not out:
        return {}
    try:
        util_map = json.loads(out or '{}')
    except json.JSONDecodeError:
        return {}
    return util_map if isinstance(util_map, dict) else {}


def _merge_windows_adapters_util(adapters, util_map):
    gpus = []
    for item in adapters:
        idx = item.get('index', len(gpus))
        name = item.get('name') or ''
        util = _safe_float(util_map.get(str(idx)))
        if util is None:
            util = _safe_float(util_map.get(idx))
        gpus.append({
            'key': 'win:%s:%s' % (idx, _norm_name(name)),
            'index': idx,
            'name': name,
            'vendor': item.get('vendor') or _vendor_from_name(name),
            'util_percent': util,
            'mem_total_mb': item.get('mem_total_mb'),
            'mem_used_mb': None,
        })

    used_utils = {g.get('util_percent') for g in gpus if g.get('util_percent') is not None}
    spare_utils = []
    for v in (util_map or {}).values():
        fv = _safe_float(v)
        if fv is not None and fv not in used_utils:
            spare_utils.append(fv)
    spare_utils.sort(reverse=True)
    for g in gpus:
        if g.get('util_percent') is None and spare_utils:
            g['util_percent'] = spare_utils.pop(0)
    return gpus


def _collect_windows_gpus():
    adapters = _collect_windows_adapters()
    if not adapters:
        return []
    util_map = _collect_windows_util()
    return _merge_windows_adapters_util(adapters, util_map)


def _norm_name(name):
    return re.sub(r'\s+', ' ', (name or '').strip().lower())


def _collect_linux_gpus():
    merged = {}
    # NVIDIA
    for g in _collect_nvidia_gpus():
        _merge_gpu(merged, g)

    # DRM 卡名称
    drm_cards = []
    drm_root = '/sys/class/drm'
    if os.path.isdir(drm_root):
        for entry in sorted(os.listdir(drm_root)):
            if not re.match(r'^card\d+$', entry):
                continue
            card_path = os.path.join(drm_root, entry)
            name = _read_first_line(os.path.join(card_path, 'device/vendor'))
            prod = _read_first_line(os.path.join(card_path, 'device/device'))
            label = entry
            try:
                for dev in os.listdir(card_path):
                    if dev.startswith('renderD') or re.match(r'^card\d+-', dev):
                        pass
            except OSError:
                pass
            vendor_file = _read_first_line(os.path.join(card_path, 'device/vendor'))
            device_file = _read_first_line(os.path.join(card_path, 'device/device'))
            human = _linux_pci_name(vendor_file, device_file) or entry
            idx_match = re.search(r'card(\d+)', entry)
            idx = int(idx_match.group(1)) if idx_match else len(drm_cards)
            drm_cards.append({'index': idx, 'name': human, 'vendor': _vendor_from_name(human), 'key': 'drm:%s' % entry})

    # Intel GPU load (RK/Intel platforms)
    intel_load = _read_first_line('/sys/kernel/debug/dri/0/i915_gem_objects')  # not util
    intel_util = _linux_intel_util()

    for card in drm_cards:
        util = intel_util if card['vendor'] == 'intel' and intel_util is not None else None
        _merge_gpu(merged, {
            'key': card['key'],
            'index': card['index'],
            'name': card['name'],
            'vendor': card['vendor'],
            'util_percent': util,
        })

    return list(merged.values())


def _read_first_line(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read().strip()
    except OSError:
        return ''


def _linux_pci_name(vendor, device):
    vendor_map = {'0x8086': 'Intel', '0x10de': 'NVIDIA', '0x1002': 'AMD'}
    v = vendor_map.get(vendor.lower() if vendor else '', '')
    if v:
        return '%s GPU (%s)' % (v, device or '')
    return ''


def _linux_intel_util():
    """尝试读取 Intel iGPU 占用（部分内核提供 dri 调试节点）。"""
    for path in (
        '/sys/class/drm/card0/device/gt_busy_percent',
        '/sys/class/drm/card1/device/gt_busy_percent',
    ):
        val = _read_first_line(path)
        if val:
            f = _safe_float(val.replace('%', ''))
            if f is not None:
                return f
    return None


def _merge_nvidia_into_windows(merged, nvidia_gpus):
    for g in nvidia_gpus:
        matched = False
        norm = _norm_name(g.get('name'))
        for item in merged.values():
            if item.get('vendor') == 'nvidia' and (
                _norm_name(item.get('name')) in norm or norm in _norm_name(item.get('name'))
            ):
                item.update({
                    'util_percent': g.get('util_percent', item.get('util_percent')),
                    'mem_used_mb': g.get('mem_used_mb', item.get('mem_used_mb')),
                    'mem_total_mb': g.get('mem_total_mb', item.get('mem_total_mb')),
                    'mem_util_percent': g.get('mem_util_percent'),
                    'temperature_c': g.get('temperature_c'),
                    'name': g.get('name') or item.get('name'),
                })
                matched = True
                break
        if not matched:
            _merge_gpu(merged, g)


def _collect_gpu_info_uncached():
    merged = {}
    system = platform.system()
    if system == 'Windows':
        adapters = _collect_windows_adapters()
        nvidia_gpus = []
        util_map = {}

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_util = pool.submit(_collect_windows_util)
            f_nv = pool.submit(_collect_nvidia_gpus)
            try:
                util_map = f_util.result(timeout=4.5) or {}
            except Exception:
                util_map = {}
            try:
                nvidia_gpus = f_nv.result(timeout=3) or []
            except Exception:
                nvidia_gpus = []

        for g in _merge_windows_adapters_util(adapters, util_map):
            _merge_gpu(merged, g)
        _merge_nvidia_into_windows(merged, nvidia_gpus)
    else:
        for g in _collect_linux_gpus():
            _merge_gpu(merged, g)

    result = [_finalize_gpu(v) for v in merged.values()]
    result.sort(key=lambda x: (x.get('index', 0), x.get('name', '')))
    for i, g in enumerate(result):
        g['index'] = i
    return result


def get_gpu_info(force_refresh=False):
    """返回本机所有可用显卡列表（带短时缓存，避免频繁调用 PowerShell）。"""
    now = time.time()
    with _GPU_CACHE_LOCK:
        if not force_refresh and _GPU_CACHE['data'] and now - _GPU_CACHE['ts'] < _GPU_CACHE_TTL:
            return list(_GPU_CACHE['data'])

    result = _collect_gpu_info_uncached()
    with _GPU_CACHE_LOCK:
        _GPU_CACHE['data'] = list(result)
        _GPU_CACHE['ts'] = time.time()
    return result
