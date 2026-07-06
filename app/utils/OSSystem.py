# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
import psutil
import shutil
from datetime import datetime
import platform
import subprocess
import os


class OSSystem():
    def __init__(self):
        self.__system_name = platform.system()  # 操作系统
        self.__machine_node = str(platform.node())  # 机器名称

    @staticmethod
    def getDateFmtStr(spend_date, spend_date_fmt="%d天%d小时%d分钟%d秒"):  # type <class 'datetime.timedelta'>
        spend_day = spend_date.days  # 已运行的天数 int
        spend_seconds = spend_date.seconds  # 已运行的秒数 int
        spend_hour = int(spend_seconds / 60 / 60)  # 已运行小时 int
        spend_seconds -= spend_hour * 60 * 60  # 已运行的秒数 int
        spend_minute = int(spend_seconds / 60)  # 已运行的分钟 int
        spend_seconds -= spend_minute * 60  # 已运行的秒数 int

        spend_date_str = spend_date_fmt % (spend_day, spend_hour, spend_minute, spend_seconds)

        return spend_date_str

    def __byteFormat(self, bytes, suffix="B"):
        """
        Scale bytes to its proper format
        e.g:
            1253656 => '1.20MB'
            1253656678 => '1.17GB'
        """
        factor = 1024
        for unit in ["", "K", "M", "G", "T", "P"]:
            if bytes < factor:
                return f"{bytes:.2f}{unit}{suffix}"
            bytes /= factor

    def getOSInfo(self, spend_date_fmt="%d天%d小时%d分钟%d秒", include_gpu=False):

        # 获取系统cpu比例 start
        os_cpu_used = psutil.cpu_percent()
        # os_cpu_physical_core = psutil.cpu_count(logical=False) # 物理核心数量
        os_cpu_total_core = psutil.cpu_count(logical=True)  # 逻辑核心数量
        os_cpu_used_rate = round(os_cpu_used / 100, 3)  # <class 'float'> 0.125
        # 获取系统cpu比例 end

        # 获取系统内存比例 start
        os_virtual_mem = psutil.virtual_memory()
        os_virtual_mem_total = os_virtual_mem.total
        if os_virtual_mem.total == 0:
            os_virtual_mem_used_rate = 0
        else:
            os_virtual_mem_used_rate = os_virtual_mem.used / os_virtual_mem.total
        os_virtual_mem_used_rate = round(os_virtual_mem_used_rate, 3)  # <class 'float'> 0.635
        # 获取系统内存比例 end

        # 获取系统磁盘比例 start
        os_disk_total = 0
        os_disk_used = 0
        os_disk_free = 0
        os_disk_partitions = psutil.disk_partitions()
        for partition in os_disk_partitions:
            try:
                partition_usage = psutil.disk_usage(partition.mountpoint)
                os_disk_total += partition_usage.total
                os_disk_free += partition_usage.free
                os_disk_used += partition_usage.used
            except Exception as e:
                pass
        if os_disk_total == 0:
            os_disk_used_rate = 0
        else:
            os_disk_used_rate = os_disk_used / os_disk_total
        os_disk_used_rate = round(os_disk_used_rate, 3)  # 当前系统磁盘占用比例
        # 获取系统磁盘比例 end

        # 获取系统开机时间 start
        os_boot_timestamp = int(psutil.boot_time())  # <class 'float'> 1651904713.9067075
        os_boot_date = datetime.fromtimestamp(os_boot_timestamp)  # <class 'datetime.datetime'>
        os_run_date = datetime.now() - os_boot_date  # <class 'datetime.timedelta'>
        os_run_date_str = self.getDateFmtStr(os_run_date, spend_date_fmt=spend_date_fmt)
        # 获取系统开机时间 end

        os_gpus = []
        if include_gpu:
            try:
                from app.utils.GpuInfo import get_gpu_info
                os_gpus = get_gpu_info()
            except Exception:
                os_gpus = []

        os_info = {
            "machine_node": str(platform.node()),
            "system_name": self.getSystemName(),
            "os_cpu_used_rate": os_cpu_used_rate,  # cpu总占比
            "os_virtual_mem_used_rate": os_virtual_mem_used_rate,  # 内存总占比
            "os_disk_used_rate": os_disk_used_rate,

            "os_cpu_used_rate_str": str(round(os_cpu_used_rate * 100, 1)) + "% / " + str(os_cpu_total_core),
            "os_virtual_mem_used_rate_str": str(round(os_virtual_mem_used_rate * 100, 1)) + "% / " + str(
                self.__byteFormat(os_virtual_mem_total)),
            "os_disk_used_rate_str": str(round(os_disk_used_rate * 100, 1)) + "% / " + str(
                self.__byteFormat(os_disk_total)),

            "os_run_date_str": os_run_date_str,
            "os_gpus": os_gpus,
        }

        return os_info

    def getSystemName(self):
        return self.__system_name

    def getMachineNode(self):
        return self.__machine_node

    def getMachineOsRelease(self):
        # cat /etc/os-release
        if self.getSystemName() == "Windows":
            __str = "Windows"
        else:
            try:
                result = os.popen("cat /etc/os-release")
                __str = str(result.read()).strip()
            except:
                __str = "run error"

        return __str

    def getMachineLsCpu(self):
        # lscpu
        if self.getSystemName() == "Windows":
            __str = "Windows"
        else:
            try:
                result = os.popen("lscpu")
                __str = str(result.read()).strip()
            except:
                __str = "run error"

        return __str

    def getMachineUnameA(self):
        # uname -a
        if self.getSystemName() == "Windows":
            __str = "Windows"
        else:
            try:
                result = os.popen("uname -a")
                __str = str(result.read()).strip()
            except:
                __str = "run error"

        return __str

    def getMachineCpu(self):
        """
        获取系统 CPU 信息
        兼容 Windows 11 (PowerShell) 和 Linux 系统
        采用多种方法确保可靠获取
        """
        system_name = self.getSystemName()

        if system_name == "Windows":
            machine_cpu = None

            # --- 方案一：PowerShell Get-CimInstance (推荐，Win8+ 兼容) ---
            try:
                ps_command = [
                    "powershell",
                    "-Command",
                    "Get-CimInstance -ClassName Win32_Processor | Select-Object -ExpandProperty Name"
                ]
                output = subprocess.check_output(
                    ps_command,
                    stderr=subprocess.STDOUT,
                    timeout=10,
                    encoding='utf-8',
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                machine_cpu = output.strip()

                # 验证结果是否有效
                if machine_cpu and len(machine_cpu) > 3 and not machine_cpu.startswith("Get-CimInstance"):
                    return machine_cpu
            except Exception as e:
                pass

            # --- 方案二：WMIC 命令 (旧版 Windows 回退方案) ---
            try:
                output = subprocess.check_output(
                    "wmic cpu get Name",
                    shell=True,
                    timeout=10,
                    encoding='utf-8',
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                lines = [line.strip() for line in output.splitlines() if line.strip()]

                # 解析输出，跳过标题行 "Name"
                if len(lines) >= 2:
                    # 第一行是 "Name"，第二行开始是 CPU 名称
                    machine_cpu = lines[1].strip()
                    if machine_cpu and len(machine_cpu) > 3:
                        return machine_cpu
            except Exception as e:
                pass

            # --- 方案三：PowerShell Get-WmiObject (备选，兼容旧系统) ---
            try:
                ps_command = [
                    "powershell",
                    "-Command",
                    "Get-WmiObject -Class Win32_Processor | Select-Object -ExpandProperty Name"
                ]
                output = subprocess.check_output(
                    ps_command,
                    stderr=subprocess.STDOUT,
                    timeout=10,
                    encoding='utf-8',
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                machine_cpu = output.strip()
                if machine_cpu and len(machine_cpu) > 3 and not machine_cpu.startswith("Get-WmiObject"):
                    return machine_cpu
            except Exception as e:
                pass

            # --- 方案四：使用 psutil (如果可用) ---
            try:
                cpu_info = platform.processor()
                if cpu_info and len(cpu_info) > 3:
                    return cpu_info
            except Exception:
                pass

            return "run error"

        else:  # Linux / macOS / 其他
            # --- 方案一：直接读取 /proc/cpuinfo (最可靠，不需要外部命令) ---
            try:
                with open('/proc/cpuinfo', 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith("model name"):
                            machine_cpu = line.split(":", 1)[1].strip()
                            if machine_cpu:
                                return machine_cpu
            except Exception as e:
                pass

            # --- 方案二：使用 lscpu 命令 ---
            try:
                result = subprocess.run(
                    ['lscpu'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                    universal_newlines=True
                )

                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if line.startswith("Model name"):
                            machine_cpu = line.split(":", 1)[1].strip()
                            if machine_cpu:
                                return machine_cpu
            except Exception as e:
                pass

            # --- 方案三：使用 uname -m 获取架构信息 ---
            try:
                result = subprocess.run(
                    ['uname', '-m'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                    universal_newlines=True
                )
                if result.returncode == 0:
                    arch = result.stdout.strip()
                    if arch:
                        # 对于 ARM 设备，返回架构信息
                        return f"ARM Processor ({arch})"
            except Exception as e:
                pass

            # --- 方案四：尝试读取设备树信息 (适用于嵌入式 ARM 设备) ---
            try:
                dt_paths = [
                    '/proc/device-tree/model',
                    '/proc/device-tree/compatible'
                ]
                for path in dt_paths:
                    if os.path.exists(path):
                        with open(path, 'rb') as f:
                            value = f.read().rstrip(b'\x00').decode('utf-8', errors='ignore')
                            if value and len(value) > 3:
                                return value.replace('\n', ' ').strip()
            except Exception as e:
                pass

            return "run error"

    def getMachineNvidia(self):
        # nvidia-smi
        try:
            if shutil.which("nvidia-smi"):
                result = os.popen("nvidia-smi")
                __str = str(result.read()).strip()
                if len(__str) > 0:
                    lines = __str.split("\n")
                    lines_filter = []
                    for line in lines:
                        if line.find("NVIDIA-SMI") > -1:
                            lines_filter.append(line.strip())
                        elif line.find("Default") > -1:
                            lines_filter.append(line.strip())
                        elif line.find("NVIDIA") > -1:
                            lines_filter.append(line.strip())
                    __str = ",".join(lines_filter)
                else:
                    __str = ""
            else:
                __str = "no"
        except:
            __str = "run error"

        return __str

    def getMachineAscend(self):
        # npu-smi info
        if self.getSystemName() == "Windows":
            return ""
        else:
            # 2. 定义可能的 npu-smi 路径 (防止 PATH 未配置)
            # 昇腾默认安装路径通常在 /usr/local/Ascend/driver/tools/
            possible_paths = [
                "npu-smi",
                "/usr/local/Ascend/driver/tools/npu-smi",
                "/usr/local/Ascend/bin/npu-smi"
            ]

            cmd_path = None
            # 优先查找环境变量中的命令，如果找不到则尝试硬编码路径
            for path in possible_paths:
                if shutil.which(path):
                    cmd_path = path
                    break

            if not cmd_path:
                return "no_cmd_found"  # 明确区分是找不到命令还是执行失败

            try:
                # 3. 使用 subprocess.run 替代 os.popen
                # capture_output=True: 同时捕获 stdout 和 stderr
                # text=True: 直接返回字符串而非 bytes
                # timeout=10: 防止命令卡死导致程序挂起
                result = subprocess.run(
                    [cmd_path, "info"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=os.environ  # 显式继承当前环境变量
                )

                # 4. 合并输出 (有些错误信息在 stderr，有些正常输出在 stdout)
                # 注意：npu-smi 正常时 stderr 通常为空，但为了调试建议都看看
                output = result.stdout.strip()
                error = result.stderr.strip()

                # 如果返回码不为 0，说明执行出错 (可能是权限问题)
                if result.returncode != 0:
                    # 如果是权限问题，npu-smi 通常会提示 "Permission denied" 或类似信息
                    return f"exec_error(code={result.returncode}): {error or output}"

                if not output:
                    return "empty_output"

                # 5. 优化过滤逻辑 (保留原逻辑但增加容错)
                lines = output.split("\n")
                lines_filter = []

                has_table = False
                for line in lines:
                    # 只要包含 | 就认为是表格行
                    if "|" in line:
                        lines_filter.append(line.strip())
                        has_table = True

                # 【改进】如果过滤后为空，但原始输出不为空，说明格式可能变了，不要直接丢弃，返回原始内容供调试
                if not has_table:
                    # 可以选择返回原始输出，或者标记为格式未知
                    # return output
                    pass

                final_str = ",".join(lines_filter)
                return final_str if final_str else output

            except subprocess.TimeoutExpired:
                return "timeout"
            except PermissionError:
                return "permission_denied_need_root"
            except Exception as e:
                return f"run_exception: {str(e)}"

    def getMachineRknpu(self):
        # cat /sys/kernel/debug/rknpu/load
        if self.getSystemName() == "Windows":
            __str = ""
        else:
            try:
                if os.path.exists("/sys/kernel/debug/rknpu/load"):
                    result = os.popen("cat /sys/kernel/debug/rknpu/load")
                    __str = str(result.read()).strip()
                    if len(__str) > 0:
                        lines = __str.split("\n")
                        __str = ",".join(lines)
                    else:
                        __str = ""
                else:
                    __str = "no"
            except:
                __str = "run error"

        return __str
