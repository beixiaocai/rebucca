#!/usr/bin/env python3
# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca

# -*- coding: utf-8 -*-
"""
GB28181 服务器 - Python版本
支持多个摄像头设备注册和被动接收推流
"""

import socket
import uuid
import time
import hashlib
import random
import threading
import os
import re
import requests
from datetime import datetime
from typing import Dict, Optional
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET
import traceback


def _safe_xml_parse(body):
    """安全解析XML，兼容带encoding声明的Unicode字符串（GB28181设备可能用GB2312编码声明）。

    ET.fromstring() 对含 encoding 声明的 Unicode 字符串会报错：
        ValueError: Unicode strings with encoding declaration are not supported.
    此函数先移除 encoding 声明再解析。
    """
    # 移除XML声明中的encoding属性（如 encoding="GB2312"、encoding="UTF-8" 等）
    cleaned = re.sub(r'encoding\s*=\s*["\'][^"\']*["\']', '', body, count=1, flags=re.IGNORECASE)
    return ET.fromstring(cleaned)


class Device:
    """GB28181设备类"""
    def __init__(self, device_id, ip=None, port=None):
        self.device_id = device_id
        self.ip = ip
        self.port = port
        self.registered = False
        self.register_time = None
        self.channels = []
        self.call_id = None
        self.from_tag = None
        self.to_tag = None
        self.last_register_time = 0  # 毫秒时间戳
        self.last_keepalive_time = 0  # 毫秒时间戳（设备级心跳时间，即使无通道也能保活）
        self.name = ""  # 设备名称（通过DeviceInfo查询获取）
        self.manufacturer = ""  # 厂商
        self.model = ""  # 型号
        self.firmware_version = ""  # 固件版本

class Channel:
    """GB28181通道类（支持多级目录结构）"""
    def __init__(self, channel_id, name="", device=None,logger=None):
        self.channel_id = channel_id
        self.name = name
        self.device = device  # 关联的Device对象
        self.device_id = device.device_id if device else None
        self.logger = logger
        self.status = "OFF"  # ON/OFF
        self.stream_url = ""
        # 多级目录支持
        self.parental = 0  # 0:叶子通道, 1:目录节点
        self.parent_id = ""  # 父节点ID
        self.device_type = ""  # 设备类型（IPC/DVR/NVR等）
        self.safety_way = 0  # 安全方式
        self.register_way = 0  # 注册方式
        self.secrecy = 0  # 保密属性
        self.children = []  # 子通道列表
        # Catalog信息
        self.sum_num = 0  # 通道总数
        self.manufacturer = ""  # 厂商
        self.model = ""  # 型号
        self.owner = ""  # 所有者
        self.civil_code = ""  # 行政区划
        # INVITE会话状态
        self.rtp_port = 0  # ZLM实际分配的RTP端口（用于SDP和BYE）
        self.allocated_rtp_port = 0  # 从端口管理器分配的原始端口（用于释放）
        self.call_id = ""  # INVITE会话的Call-ID
        self.from_tag = ""  # INVITE会话的From tag（服务器端生成）
        self.to_tag = ""    # INVITE 200 OK响应中的To tag（设备端返回）
        self.dialog_id = ""  # dialog标识
        self.streaming = False  # 是否正在推流
        self.inviting = False  # 是否正在INVITE中（防止重复INVITE）
        self.sn = 0  # 序列号（用于PTZ等请求）
        # 同步状态
        self.forward_state = 0  # 0:未转发 1:转发中
        self.last_keepalive_time = 0  # 毫秒时间戳
        self.last_register_time = 0  # 毫秒时间戳

    def update_admin(self, server):
        """同步通道信息到rebekah_admin数据库（与C++版本逻辑一致）"""
        admin_host = server.admin_host
        if not admin_host:
            return False, "admin_host not configured"

        url = f"{admin_host}/inner/on_media_update_stream"

        # Bug 9修复：从server获取最新设备信息
        with server.lock:
            device = server.devices.get(self.device_id)
            if device:
                device_ip = device.ip
                device_port = device.port
                client_id = device.device_id
            else:
                device_ip = ""
                device_port = 0
                client_id = ""

        # 构建请求参数（与C++版本完全一致）
        params = {
            "forwardState": self.forward_state,
            "app": "rtp",  # GB28181固定使用rtp
            "name": self.channel_id,  # 流name=channelId
            "ip": device_ip,
            "port": device_port,
            "clientId": client_id or "",
            "parentID": self.parent_id or "",
            "rtpServerPort": self.rtp_port,
            "rtpPort": 0,
            "pullStreamType": 21,  # 21=GB28181
            "pullStreamUrl": "rtp://__",  # GB28181占位字段
            "cameraSumNum": self.sum_num,
            "cameraName": self.name or "",
            "cameraManufacturer": self.manufacturer or "unknown",
            "cameraModel": self.model or "",
            "cameraOwner": self.owner or "",
            "cameraCivilCode": self.civil_code or "",
            "lastKeepaliveTime": self.last_keepalive_time,
            "lastRegisterTime": self.last_register_time,
            "rtpTransferMode": server.rtp_transfer_mode,  # 使用服务器配置
            "rtpTransferAudioType": server.rtp_transfer_audio_type  # 使用服务器配置
        }

        # 发送POST请求
        headers = {
            "Content-Type": "application/json;"
        }

        # 重试机制：admin服务启动可能晚于SIP服务，连接拒绝时重试
        max_retries = 3
        retry_interval = 1.0
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(url, json=params, headers=headers, timeout=5)

                if response.status_code == 200:
                    result = response.json()
                    if result.get('code') == 1000:
                        return True, "success"
                    else:
                        self.logger.debug(f"[GSS] [通道同步失败] {self.channel_id}: {result.get('msg')}")
                        return False, result.get('msg', 'unknown error')
                else:
                    self.logger.debug(f"[GSS] [通道同步HTTP错误] {self.channel_id}: HTTP {response.status_code}")
                    return False, f"HTTP {response.status_code}"
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                # 连接错误/超时：admin服务可能未就绪，重试
                if attempt < max_retries:
                    self.logger.debug(f"[GSS] [通道同步重试 {attempt}/{max_retries}] {self.channel_id}: {str(e)[:100]}")
                    time.sleep(retry_interval)
                else:
                    self.logger.debug(f"[GSS] [通道同步异常] {self.channel_id}: 重试{max_retries}次后仍失败: {str(e)[:100]}")
                    return False, str(e)
            except Exception as e:
                self.logger.debug(f"[GSS] [通道同步异常] {self.channel_id}: {str(e)}")
                return False, str(e)

        return False, "max retries exceeded"


class RTPPortManager:
    """RTP端口管理器（与C++版本逻辑一致）"""
    def __init__(self, min_port=20002, max_port=30000):
        self.min_port = min_port
        self.max_port = max_port
        self.current_port = min_port
        self.lock = threading.Lock()
        self.allocated_ports = {}  # {port: channel_id}

    def allocate(self, channel_id):
        """
        分配RTP端口

        Args:
            channel_id: 通道ID

        Returns:
            int: 分配的端口号，0表示失败
        """
        with self.lock:
            # 循环查找可用端口
            for _ in range((self.max_port - self.min_port) // 2):
                if self.current_port >= self.max_port:
                    self.current_port = self.min_port

                port = self.current_port
                self.current_port += 2  # RTP使用偶数端口

                # 检查端口是否可用
                if port not in self.allocated_ports:
                    if self._is_port_available(port):
                        self.allocated_ports[port] = channel_id
                        return port

            return 0  # 无可用端口

    def release(self, port):
        """释放RTP端口"""
        with self.lock:
            if port in self.allocated_ports:
                del self.allocated_ports[port]

    def _is_port_available(self, port):
        """检查端口是否可用"""

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('0.0.0.0', port))
            sock.close()
            return True
        except OSError:
            return False

class GB28181SipServer:
    """GB28181 SIP服务器"""
    def __init__(self, server_ip, server_port, server_id, realm, password,
                 sip_server_timeout=120, sip_server_expiry=60,
                 sip_transfer_mode=0, rtp_transfer_mode=0, rtp_transfer_audio_type=0,
                 auto_invite_after_rec_cate_log=True,
                 admin_host=None, zlm=None, logger=None
                 ):
        """
        初始化GB28181服务器

        Args:
            server_ip: SIP服务器IP（公网IP，用于SIP消息对外暴露）
            server_port: SIP服务器端口
            server_id: 服务器ID
            realm: SIP域
            password: 注册密码
            sip_server_timeout: SIP服务器超时时间（秒）
            sip_server_expiry: SIP注册过期时间（秒）
            sip_transfer_mode: SIP信令传输模式（0=UDP, 1=TCP）
            rtp_transfer_mode: RTP媒体流传输模式（0=UDP被动, 1=TCP被动）
            rtp_transfer_audio_type: RTP音频传输类型（0=静音, 1=原始音频）

            auto_invite_after_rec_cate_log: 收到CateLog响应后，是否主动发起Invite
            admin_host: rebucca_admin服务地址（如 http://127.0.0.1:10001）
            zlm: ZLMediaKitApi 实例
            logger: 日志记录器
        """
        self.server_ip = server_ip  # 公网IP，用于SIP消息对外暴露
        self.server_port = server_port
        self.server_id = server_id
        self.realm = realm
        self.password = password
        # SIP服务器配置参数
        self.sip_server_timeout = sip_server_timeout  # 超时时间（秒）
        self.sip_server_expiry = sip_server_expiry  # 注册过期时间（秒）
        self.sip_transfer_mode = sip_transfer_mode  # SIP信令传输模式：0=UDP, 1=TCP
        self.rtp_transfer_mode = rtp_transfer_mode  # RTP传输模式：0=UDP被动, 1=TCP被动
        self.rtp_transfer_audio_type = rtp_transfer_audio_type  # RTP音频传输类型
        
        # 本地监听地址：公网IP不能bind，必须用0.0.0.0
        self._listen_ip = "0.0.0.0"

        # 自动查询设备目录
        self.auto_query_catalog = True
        # 收到CateLog回复后，是否自动对所有叶子节点发起Invite请求
        self.auto_invite_after_rec_cate_log = auto_invite_after_rec_cate_log

        self.admin_host = admin_host       # rebekah_admin服务地址
        self.zlm = zlm                     # ZLMediaKitApi 实例
        self.logger = logger

        self.logger.debug("GB28181SipServer.__init__()")

        self.sock = None
        self.running = False
        self.devices: Dict[str, Device] = {}
        self.lock = threading.Lock()
        
        # TCP连接池（SIP信令TCP模式使用）
        self.tcp_connections: Dict[tuple, socket.socket] = {}  # {(ip, port): client_socket}
        self.tcp_lock = threading.Lock()  # 保护tcp_connections
        
        # 消息队列（异步处理）
        self.message_queue = Queue(maxsize=10000)  # 最多缓存10000条消息
        
        # Catalog查询防抖：防止短时间内重复查询
        self.last_catalog_query_time: Dict[str, float] = {}  # {device_id: timestamp}
        self.catalog_query_debounce_seconds = 10  # 10秒内不重复查询
        
        # 跟踪进行中的INVITE：防止catalog刷新丢失状态
        self.pending_invites: Dict[str, dict] = {}  # {channel_id: {rtp_port, call_id, device_id}}
        self.pending_invites_lock = threading.Lock()

        # Catalog响应处理锁：per-device串行化，防止并发Catalog响应导致重复update_admin
        self.catalog_locks: Dict[str, threading.Lock] = {}
        self.catalog_locks_guard = threading.Lock()
        
        # 线程池（控制并发数）
        self.worker_pool = ThreadPoolExecutor(
            max_workers=50,  # 最大50个工作线程
            thread_name_prefix='GB28181-Worker'
        )
        
        # Catalog查询限流
        self.catalog_query_semaphore = threading.Semaphore(10)  # 最多10个并发查询

        # RTP端口管理器
        self.rtp_port_mgr = RTPPortManager()

        # 统计信息
        self.stats = {
            'total_registers': 0,
            'total_invites': 0,
            'total_byes': 0,
            'total_messages': 0,
            'message_types': {
                'Keepalive': 0,  # 心跳消息
                'Catalog': 0,    # 设备目录
                'DeviceInfo': 0, # 设备信息
                'Other': 0       # 其他消息
            }
        }


    def _send_sip_response(self, response_msg, addr):
        """智能发送SIP响应（自动选择UDP或TCP）"""
        success = self._send_data(response_msg, addr)
        if success:
            self.log_sip_packet('TX', response_msg, addr)
        return success

    def _send_data(self, data, addr):
        """
        发送SIP数据（根据传输模式自动选择UDP或TCP）
        
        Args:
            data: 要发送的字符串数据
            addr: 目标地址 (ip, port)
        """
        encoded_data = data.encode('utf-8')
        
        if self.sip_transfer_mode == 1:
            # TCP模式：从连接池查找对应的socket
            with self.tcp_lock:
                client_sock = self.tcp_connections.get(addr)
            
            if client_sock:
                try:
                    client_sock.sendall(encoded_data)
                    return True
                except Exception as e:
                    self.logger.error(f"[GSS] TCP发送失败 {addr}: {e}")
                    # 移除失效连接
                    with self.tcp_lock:
                        self.tcp_connections.pop(addr, None)
                    return False
            else:
                self.logger.error(f"[GSS] TCP连接不存在 {addr}，无法发送数据")
                return False
        else:
            # UDP模式：直接sendto
            try:
                self.sock.sendto(encoded_data, addr)
                return True
            except Exception as e:
                self.logger.error(f"[GSS] UDP发送失败 {addr}: {e}")
                return False

    def _get_sip_transport(self):
        """获取SIP传输协议（UDP或TCP）"""
        return "TCP" if self.sip_transfer_mode == 1 else "UDP"

    def log_sip_packet(self, direction, data, addr=None):
        """
        记录SIP数据报（完整内容，用于诊断设备接入问题）

        Args:
            direction: 'RX' (接收) 或 'TX' (发送)
            data: SIP消息原始数据
            addr: 地址元组 (ip, port)
        """
        addr_str = f"{addr[0]}:{addr[1]}" if addr else "?"
        lines = data.split('\r\n')
        first_line = lines[0] if lines else ''
        # 记录完整SIP消息（DEBUG级别）
        self.logger.debug(f"[GSS] [{direction}] {addr_str} | {first_line}")
        # 记录完整消息体（含SDP/XML）
        self.logger.debug(f"[GSS] [{direction}] 完整消息:\n{data}")

    def start(self):
        """启动服务器"""

        self.logger.debug("[GSS] start...")

        # 根据配置创建socket（支持UDP或TCP）
        if self.sip_transfer_mode == 1:
            # TCP模式
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self._listen_ip, self.server_port))
            self.sock.listen(5)  # 开始监听，等待连接
            self.logger.debug("[GSS] SIP服务器已启动: TCP {listen}:{external}".format(
                listen="{ip}:{port}".format(ip=self._listen_ip, port=self.server_port),
                external="{ip}:{port}".format(ip=self.server_ip, port=self.server_port)))
        else:
            # UDP模式（默认）
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self._listen_ip, self.server_port))
            self.sock.settimeout(1.0)
            self.logger.debug("[GSS] SIP服务器已启动: UDP {listen}:{external}".format(
                listen="{ip}:{port}".format(ip=self._listen_ip, port=self.server_port),
                external="{ip}:{port}".format(ip=self.server_ip, port=self.server_port)))

        self.running = True

        # 启动接收线程（TCP和UDP使用不同的处理方式）
        if self.sip_transfer_mode == 1:
            # TCP模式：需要accept连接
            receive_thread = threading.Thread(target=self._tcp_receive_loop, daemon=True)
        else:
            # UDP模式：直接接收数据报
            receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
        receive_thread.start()

        # 启动消息处理工作线程池
        for i in range(3):  # 3个工作线程处理队列
            worker = threading.Thread(target=self._process_message_queue, daemon=True, name=f'MsgWorker-{i}')
            worker.start()

        # 启动设备状态检查线程
        check_thread = threading.Thread(target=self._check_devices_loop, daemon=True)
        check_thread.start()

        return receive_thread, check_thread

    def stop(self):
        """停止服务器"""
        self.logger.debug("[GSS] stop...")
        self.running = False
        
        # 【关键修复】停止所有通道的推流并清理资源
        active_stream_count = 0
        with self.lock:
            for device in self.devices.values():
                for channel in device.channels:
                    if channel.streaming or channel.forward_state == 1:
                        channel_id = channel.channel_id
                        rtp_port = channel.allocated_rtp_port
                        
                        # 关闭ZLM RTP服务器
                        try:
                            self._close_rtp_server(channel_id)
                        except Exception as e:
                            self.logger.error(f"[GSS] ✗ Failed to close RTP server for {channel_id}: {e}")
                        
                        # 释放RTP端口
                        if rtp_port > 0:
                            try:
                                self.rtp_port_mgr.release(rtp_port)
                            except Exception as e:
                                self.logger.error(f"[GSS] ✗ Failed to release port {rtp_port}: {e}")
                        
                        active_stream_count += 1
        
        if active_stream_count > 0:
            self.logger.debug(f"[GSS] 🛑 Stopped {active_stream_count} active streams")
        
        # 清理pending invites
        with self.pending_invites_lock:
            pending_count = len(self.pending_invites)
            for channel_id, pending in list(self.pending_invites.items()):
                try:
                    # 释放RTP端口
                    self.rtp_port_mgr.release(pending['rtp_port'])
                    # 关闭ZLM RTP服务器
                    self._close_rtp_server(channel_id)
                except Exception as e:
                    self.logger.error(f"[GSS] ✗ Failed to clean pending invite {channel_id}: {e}")
            self.pending_invites.clear()
        
        if pending_count > 0:
            self.logger.debug(f"[GSS] 🧹 Cleaned {pending_count} pending invites")
        
        # 清空消息队列
        if hasattr(self, 'message_queue'):
            while not self.message_queue.empty():
                try:
                    self.message_queue.get_nowait()
                except:
                    break
            self.logger.debug("[GSS] ✓ 消息队列已清空")
        
        # 关闭线程池（等待正在执行的任务完成）
        if hasattr(self, 'worker_pool'):
            self.worker_pool.shutdown(wait=True)
            self.logger.debug("[GSS] ✓ 线程池已关闭")
        
        if self.sock:
            self.sock.close()
        self.logger.debug("[GSS] stop finish")

    def _receive_loop(self):
        """UDP接收消息循环（异步入队）"""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
                # 修复：优先UTF-8解码，失败则使用GBK（兼容GB2312编码的小众GB28181设备，避免中文乱码）
                try:
                    message = data.decode('utf-8')
                except UnicodeDecodeError:
                    message = data.decode('gbk', errors='replace')
                self.log_sip_packet('RX', message, addr)
                # 快速入队，不阻塞
                try:
                    self.message_queue.put_nowait((message, addr))
                except:
                    self.logger.debug("[GSS] 消息队列已满，丢弃消息")
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"[GSS] 接收消息异常: {e}")

    def _process_message_queue(self):
        """消息处理工作线程（从队列取消息处理）"""
        while self.running:
            try:
                message, addr = self.message_queue.get(timeout=1)
                # 提交到线程池处理
                self.worker_pool.submit(self._handle_message, message, addr)
            except Empty:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"[GSS] 处理消息队列异常: {e}")

    def _tcp_receive_loop(self):
        """TCP接收消息循环（支持多连接）"""
        while self.running:
            try:
                # 接受新连接
                client_sock, addr = self.sock.accept()
                self.logger.debug(f"[GSS] TCP新连接: {addr[0]}:{addr[1]}")
                # 为每个连接创建处理线程
                client_thread = threading.Thread(target=self._handle_tcp_client, args=(client_sock, addr), daemon=True)
                client_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"[GSS] TCP接受连接异常: {e}")

    def _handle_tcp_client(self, client_sock, addr):
        """处理单个TCP客户端连接"""
        buffer = b''
        
        # 注册TCP连接到连接池
        with self.tcp_lock:
            self.tcp_connections[addr] = client_sock
        
        try:
            while self.running:
                data = client_sock.recv(65535)
                if not data:
                    break  # 连接关闭
                
                buffer += data
                # 查找完整的SIP消息（以\r\n\r\n分隔头部和体部）
                while b'\r\n\r\n' in buffer:
                    # 提取头部找到Content-Length（头部为ASCII，UTF-8解码安全）
                    header_bytes = buffer.split(b'\r\n\r\n', 1)[0]
                    header_part = header_bytes.decode('utf-8', errors='ignore')

                    # 解析Content-Length
                    content_length = 0
                    for line in header_part.split('\r\n'):
                        if line.lower().startswith('content-length:'):
                            try:
                                content_length = int(line.split(':', 1)[1].strip())
                            except:
                                pass

                    # 计算完整消息长度（使用原始字节长度，避免编码转换误差）
                    complete_msg_len = len(header_bytes) + 4 + content_length
                    if len(buffer) >= complete_msg_len:
                        # 提取完整消息
                        # 修复：优先UTF-8解码，失败则使用GBK（兼容GB2312编码的小众GB28181设备，避免中文乱码）
                        try:
                            message = buffer[:complete_msg_len].decode('utf-8')
                        except UnicodeDecodeError:
                            message = buffer[:complete_msg_len].decode('gbk', errors='replace')
                        buffer = buffer[complete_msg_len:]
                        
                        self.log_sip_packet('RX', message, addr)
                        self._handle_message(message, addr)
                    else:
                        break  # 等待更多数据
        except Exception as e:
            if self.running:
                self.logger.error(f"[GSS] TCP客户端处理异常: {e}")
        finally:
            # 从连接池移除
            with self.tcp_lock:
                self.tcp_connections.pop(addr, None)
            self.logger.debug(f"[GSS] TCP连接断开: {addr[0]}:{addr[1]}")
            client_sock.close()

    def _check_devices_loop(self):
        """检查设备状态循环"""
        catalog_check_counter = 0
        catalog_check_interval_cycles = 5  # 5分钟检查一次Catalog（每次循环60秒，5*60=300秒）
        while self.running:
            time.sleep(60)  # 每分钟检查一次
            self._check_expired_devices()
            # 每5分钟自动查询所有设备的Catalog，获取最新通道列表
            catalog_check_counter += 1
            if catalog_check_counter >= catalog_check_interval_cycles:
                catalog_check_counter = 0
                try:
                    with self.lock:
                        device_ids = list(self.devices.keys())
                    for device_id in device_ids:
                        self.query_catalog(device_id)
                except Exception as e:
                    self.logger.error(f"[GSS] 定时Catalog查询失败: {e}")

    def _handle_message(self, message, addr):
        """
        处理接收到的SIP消息

        Args:
            message: SIP消息字符串
            addr: (ip, port) 元组
        """
        try:
            lines = message.split('\r\n')
            if not lines:
                return

            first_line = lines[0]
            # 记录SIP接收日志（DEBUG级别，便于诊断设备接入问题）
            self.logger.debug(f"[GSS] [RX] {addr[0]}:{addr[1]} | {first_line}")

            # 计数统计
            with self.lock:
                if first_line.startswith('REGISTER'):
                    self.stats['total_registers'] += 1
                elif first_line.startswith('INVITE'):
                    self.stats['total_invites'] += 1
                elif first_line.startswith('MESSAGE'):
                    self.stats['total_messages'] += 1

            # 解析消息类型
            if first_line.startswith('REGISTER'):
                self._handle_register(message, addr)
            elif first_line.startswith('INVITE'):
                self._handle_invite(message, addr)
            elif first_line.startswith('MESSAGE'):
                self._handle_message_request(message, addr)
            elif first_line.startswith('NOTIFY'):
                self._handle_notify(message, addr)
            elif first_line.startswith('BYE'):
                self._handle_bye(message, addr)
            elif first_line.startswith('ACK'):
                self._handle_ack(message, addr)
            else:
                # 可能是响应消息
                self._handle_response(message, addr)
        except Exception as e:
            self.logger.error(f"[GSS] _handle_message 异常: {e}", exc_info=True)
            self.logger.error(f"[GSS] 消息第一行: {lines[0] if lines else '空消息'}")

    def _parse_sip_headers(self, message):
        """解析SIP消息头"""
        headers = {}
        lines = message.split('\r\n')

        # 跳过第一行（请求行或状态行）
        for line in lines[1:]:
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip()] = value.strip()
            elif line == '':
                break

        return headers

    def _parse_request_line(self, first_line):
        """解析SIP请求行"""
        parts = first_line.split(' ')
        if len(parts) >= 3:
            return {
                'method': parts[0],
                'uri': parts[1],
                'version': parts[2]
            }
        return {}

    def _generate_nonce(self):
        """生成nonce"""
        return hashlib.md5(f"{time.time()}:{random.random()}".encode()).hexdigest()

    def _calculate_response(self, username, realm, password, nonce, method, uri, qop='', cnonce='', nc=''):
        """
        计算Digest认证response（支持qop）

        Args:
            username: 用户名
            realm: 域
            password: 密码
            nonce: 服务器生成的随机数
            method: SIP方法
            uri: 请求URI
            qop: 保护质量 (auth 或 auth-int)
            cnonce: 客户端生成的随机数
            nc: 请求计数器

        Returns:
            str: 计算出的response
        """
        # HA1 = MD5(username:realm:password)
        ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()

        # HA2 = MD5(method:uri)
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()

        if qop:
            # 带qop的计算方式: response = MD5(HA1:nonce:nc:cnonce:qop:HA2)
            response = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
        else:
            # 不带qop的计算方式: response = MD5(HA1:nonce:HA2)
            response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()

        return response

    def _send_debug_raw_message(self, raw_message, addr):
        """发送原始SIP消息用于调试"""
        return self._send_sip_response(raw_message, addr)

    def _handle_register(self, message, addr):
        """
        处理REGISTER请求

        Args:
            message: SIP消息
            addr: 发送方地址
        """
        try:
            headers = self._parse_sip_headers(message)
            # REGISTER处理（仅保留关键日志）
            request_info = self._parse_request_line(message.split('\r\n')[0])

            # 提取设备ID (从From头)
            from_header = headers.get('From', '')
            device_id = ''
            if '<sip:' in from_header:
                start = from_header.find('<sip:') + 5
                end = from_header.find('>', start)
                if end > start:
                    device_id = from_header[start:end].split('@')[0]

            if not device_id:
                self.logger.error("[GSS] [REGISTER] 无法提取设备ID")
                return



            # 检查是否有Authorization头
            auth_header = headers.get('Authorization', '')

            if not auth_header:
                self._send_401_unauthorized(message, addr)
            else:
                if self._verify_auth(auth_header, request_info.get('uri', ''), 'REGISTER', device_id):
                    # 更新设备信息（支持NAT穿透）
                    received_ip = self._extract_received_ip(message)
                    rport = self._extract_rport(message)
                    if received_ip and rport > 0:
                        addr = (received_ip, rport)

                    # 初始化，防止首次注册（新设备）时未定义
                    channels_to_bye = []

                    with self.lock:
                        if device_id not in self.devices:
                            self.devices[device_id] = Device(device_id, addr[0], addr[1])
                        else:
                            # 设备重新注册：只更新IP/端口，不清理推流资源
                            # 某些小厂设备会频繁重注册（每3-10秒），如果每次都清理推流会导致
                            # INVITE推流刚建立就被BYE终止，视频流永远无法上线
                            # 推流资源只在设备真正离线（心跳超时）时才清理
                            device = self.devices[device_id]
                            # 更新设备联系地址（NAT穿透后地址可能变化）
                            device.ip = addr[0]
                            device.port = addr[1]
                        device = self.devices[device_id]
                        device.registered = True
                        device.register_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        device.last_register_time = int(time.time() * 1000)  # 记录注册时间戳
                        device.from_tag = headers.get('From', '').split('tag=')[-1] if 'tag=' in headers.get('From', '') else None
                        device.call_id = headers.get('Call-ID', '')
                        devices_count = len(self.devices)

                    # 在锁外发送BYE（避免持锁阻塞网络IO）
                    for bye_info in channels_to_bye:
                        self._send_bye_for_channel(
                            addr[0], addr[1],
                            bye_info['channel_id'],
                            bye_info['call_id'],
                            bye_info['from_tag'],
                            bye_info['to_tag']
                        )

                    self._send_200_ok(message, addr, device)
                    self.logger.info(f"[GSS] [REGISTER] 设备 {device_id} 注册成功 (共{devices_count}台)")

                    # 注册成功后自动查询设备通道列表（防抖：10秒内不重复查询）
                    if self.auto_query_catalog:
                        now = time.time()
                        last_query = self.last_catalog_query_time.get(device_id, 0)
                        if now - last_query >= self.catalog_query_debounce_seconds:
                            self.last_catalog_query_time[device_id] = now
                            self.logger.debug(f"[GSS] [CATALOG] 准备查询设备 {device_id} 的通道列表")
                            threading.Thread(target=self.query_catalog, args=(device_id,), daemon=True).start()
                            # 同时发送DeviceInfo查询获取设备名称
                            threading.Thread(target=self.query_device_info, args=(device_id,), daemon=True).start()
                        else:
                            self.logger.debug(f"[GSS] [REGISTER] 跳过Catalog查询（距上次查询{int(now - last_query)}秒，防抖{self.catalog_query_debounce_seconds}秒）")
                else:
                    self.logger.info(f"[GSS] [REGISTER] 设备 {device_id} 认证失败")
                    self._send_401_unauthorized(message, addr)
        except Exception as e:
            self.logger.error(f"[GSS] _handle_register 异常: {e}", exc_info=True)
            # 即使出错也要回复401，否则客户端会一直等待
            try:
                self._send_401_unauthorized(message, addr)
            except:
                pass

    def _handle_invite(self, message, addr):
        """处理INVITE请求（推流请求）"""
        try:
            headers = self._parse_sip_headers(message)
            # NAT穿透

            # 提取设备ID和通道ID
            from_header = headers.get('From', '')
            to_header = headers.get('To', '')
            
            # NAT穿透：优先使用 received+rport
            received_ip = self._extract_received_ip(message)
            rport = self._extract_rport(message)
            if received_ip and rport > 0:
                addr = (received_ip, rport)

            # 发送100 Trying
            self._send_100_trying(message, addr)

            # 发送200 OK (被动接收模式)
            self._send_200_ok_invite(message, addr, headers)
        except Exception as e:
            self.logger.error(f"[GSS] _handle_invite 异常: {e}", exc_info=True)
            # Bug 8修复：发送错误响应
            try:
                self._send_response(message, addr, 500, "Internal Server Error")
            except:
                pass

    def _handle_message_request(self, message, addr):
        """处理MESSAGE请求（通常是心跳或目录查询）"""
        try:
            headers = self._parse_sip_headers(message)

            # 提取消息体
            body = ''
            if '\r\n\r\n' in message:
                body = message.split('\r\n\r\n')[1]

            # 提取DeviceID
            device_id = ''
            match = re.search(r'<DeviceID>(.*?)</DeviceID>', body)
            if match:
                device_id = match.group(1)

            # 检查设备是否已注册
            with self.lock:
                device = self.devices.get(device_id)
                is_registered = device and device.registered

            # NAT穿透：优先使用 received+rport
            received_ip = self._extract_received_ip(message)
            rport = self._extract_rport(message)
            if received_ip and rport > 0:
                addr = (received_ip, rport)

            # 解析消息类型
            if 'Keepalive' in body:
                with self.lock:
                    self.stats['message_types']['Keepalive'] += 1

                if not is_registered:
                    self.logger.debug(f"[GSS] [MESSAGE] 未注册设备 {device_id} 发送心跳，忽略")
                    return

                # 更新设备联系地址（NAT穿透）
                # 优先使用 received+rport，否则使用原始 addr
                if received_ip and rport > 0:
                    self._update_device_contact(device_id, received_ip, rport, message)
                else:
                    self._update_device_contact(device_id, addr[0], addr[1], message)
                
                # 更新设备通道的心跳时间
                with self.lock:
                    device = self.devices.get(device_id)
                    if device:
                        now_ms = int(time.time() * 1000)
                        # 更新设备级心跳时间（即使无通道也能保活，防止误判超时）
                        device.last_keepalive_time = now_ms
                        # 更新所有通道的心跳时间
                        for channel in device.channels:
                            channel.last_keepalive_time = now_ms
                self._send_response(message, addr, 200, "OK")

            elif 'Catalog' in body:
                with self.lock:
                    self.stats['message_types']['Catalog'] += 1

                # 先解析XML获取通道数量和编号信息
                channel_count = 0
                channel_ids = []
                channel_types = []
                try:
                    root = _safe_xml_parse(body)
                    item_list = root.findall('.//Item')
                    if item_list:
                        channel_count = len(item_list)
                        for item in item_list:
                            ch_id_elem = item.find('DeviceID')
                            parental_elem = item.find('Parental')
                            if ch_id_elem is not None:
                                ch_id = ch_id_elem.text or ''
                                parental = int(parental_elem.text) if parental_elem is not None and parental_elem.text else 0
                                channel_ids.append(ch_id)
                                channel_types.append('目录' if parental == 1 else '叶子')
                except Exception as e:
                    self.logger.debug(f"[GSS] [MESSAGE] 解析Catalog XML失败: {e}")
                
                # 打印详细日志
                if channel_count > 0:
                    channels_info = ', '.join([f"{ch_id}({ch_type})" for ch_id, ch_type in zip(channel_ids[:5], channel_types[:5])])
                    if channel_count > 5:
                        channels_info += f" ... 等{channel_count}个"
                    self.logger.debug(f"[GSS] [MESSAGE] 收到Catalog消息: 设备={device_id}, 通道数={channel_count}, 通道=[{channels_info}]")
                else:
                    self.logger.debug(f"[GSS] [MESSAGE] 收到Catalog消息: 设备={device_id}, 长度={len(body)}")
                
                # 放宽注册检查：允许刚注册的设备立即发送Catalog响应（某些摄像头行为）
                if not is_registered:
                    # 检查设备是否存在（可能正在注册过程中）
                    with self.lock:
                        device_exists = device_id in self.devices
                    
                    if not device_exists:
                        self.logger.debug(f"[GSS] [MESSAGE] 未知设备 {device_id} 发送目录请求，拒绝")
                        self._send_response(message, addr, 403, "Forbidden")
                        return
                    else:
                        self.logger.debug(f"[GSS] [MESSAGE] 设备 {device_id} 正在注册中，接受Catalog响应")

                # NAT穿透：更新设备联系地址（与Keepalive一致）
                if received_ip and rport > 0:
                    self._update_device_contact(device_id, received_ip, rport, message)
                else:
                    self._update_device_contact(device_id, addr[0], addr[1], message)

                # 设备主动发送的Catalog响应（包含通道列表）
                if '<Response>' in body or '<Item>' in body:
                    # 提取响应中的DeviceID（可能是子目录ID）
                    resp_device_id_match = re.search(r'<DeviceID>(.*?)</DeviceID>', body)
                    resp_device_id = resp_device_id_match.group(1) if resp_device_id_match else device_id

                    self.logger.debug(f"[GSS] [MESSAGE] 收到目录响应: 设备={device_id}, 父ID={resp_device_id if resp_device_id != device_id else '无'}")
                    self.parse_catalog_response(body, device_id, parent_id=resp_device_id if resp_device_id != device_id else "")
                else:
                    self.logger.debug(f"[GSS] [MESSAGE] Catalog消息格式不正确，缺少<Response>或<Item>标签")
                    self.logger.debug(f"[GSS] [MESSAGE] Catalog消息内容: {body[:500]}")
                self._send_response(message, addr, 200, "OK")

            elif 'DeviceInfo' in body:
                with self.lock:
                    self.stats['message_types']['DeviceInfo'] += 1

                if not is_registered:
                    self.logger.debug(f"[GSS] [MESSAGE] 未注册设备 {device_id} 发送信息查询，拒绝")
                    self._send_response(message, addr, 403, "Forbidden")
                    return

                # 解析DeviceInfo响应，获取设备名称等信息
                try:
                    root = _safe_xml_parse(body)
                    device_name_elem = root.find('DeviceName')
                    manufacturer_elem = root.find('Manufacturer')
                    model_elem = root.find('Model')
                    firmware_elem = root.find('FirmwareVersion')

                    device_name = device_name_elem.text if device_name_elem is not None and device_name_elem.text else ''
                    manufacturer = manufacturer_elem.text if manufacturer_elem is not None and manufacturer_elem.text else ''
                    model = model_elem.text if model_elem is not None and model_elem.text else ''
                    firmware = firmware_elem.text if firmware_elem is not None and firmware_elem.text else ''

                    self.logger.debug(f"[GSS] [DEVICEINFO] 设备 {device_id} 信息: 名称={device_name}, 厂商={manufacturer}, 型号={model}, 固件={firmware}")

                    # 更新Device对象的名称等信息
                    channels_to_update = []
                    with self.lock:
                        device = self.devices.get(device_id)
                        if device:
                            if device_name:
                                device.name = device_name
                            if manufacturer:
                                device.manufacturer = manufacturer
                            if model:
                                device.model = model
                            if firmware:
                                device.firmware_version = firmware

                            # 如果设备已有通道（自动创建的），更新通道名称并标记需要重新同步
                            for ch in device.channels:
                                if device_name and not ch.name:
                                    old_name = ch.name
                                    ch.name = device_name
                                    if manufacturer:
                                        ch.manufacturer = manufacturer
                                    if model:
                                        ch.model = model
                                    self.logger.debug(f"[GSS] [DEVICEINFO] 通道 {ch.channel_id} 名称更新: '{old_name}' → '{ch.name}'")
                                    channels_to_update.append(ch)

                    # 在锁外重新同步通道到admin数据库（更新名称）
                    if channels_to_update and self.admin_host:
                        for ch in channels_to_update:
                            threading.Thread(
                                target=ch.update_admin,
                                args=(self,),
                                daemon=True
                            ).start()
                            self.logger.debug(f"[GSS] [DEVICEINFO] 通道 {ch.channel_id} 已重新同步到admin数据库（名称更新为'{ch.name}'）")

                except ET.ParseError as e:
                    self.logger.debug(f"[GSS] [DEVICEINFO] 解析DeviceInfo响应XML失败: {e}")
                    self.logger.debug(f"[GSS] [DEVICEINFO] 消息内容: {body[:500]}")
                except Exception as e:
                    self.logger.error(f"[GSS] [DEVICEINFO] 处理DeviceInfo响应异常: {e}", exc_info=True)

                self._send_response(message, addr, 200, "OK")

            else:
                with self.lock:
                    self.stats['message_types']['Other'] += 1

                self._send_response(message, addr, 200, "OK")
        except Exception as e:
            self.logger.error(f"[GSS] _handle_message_request 异常: {e}", exc_info=True)

    def _handle_bye(self, message, addr):
        """处理BYE请求（结束推流）"""
        try:
            
            # 提取Call-ID用于查找通道
            call_id = self._get_header(message, 'Call-ID')
            
            # 释放通道资源（RTP端口、更新状态、关闭ZLM RTP服务器）
            if call_id:
                self._release_channel_by_callid(call_id)
            else:
                self.logger.debug(f"[GSS] ⚠️ BYE请求中未找到Call-ID，无法释放通道资源")
            
            self._send_200_ok(message, addr, None)
        except Exception as e:
            self.logger.error(f"[GSS] _handle_bye 异常: {e}", exc_info=True)
            # Bug 7修复：即使出错也要回复响应
            try:
                self._send_response(message, addr, 500, "Internal Server Error")
            except:
                pass

    def _handle_ack(self, message, addr):
        """处理ACK请求"""
        # ACK日志已精简，避免刷屏

    def _handle_notify(self, message, addr):
        """
        处理NOTIFY请求（某些设备通过NOTIFY推送Catalog目录变更）

        Args:
            message: SIP消息
            addr: 发送方地址
        """
        try:
            headers = self._parse_sip_headers(message)

            # NAT穿透：优先使用 received+rport
            received_ip = self._extract_received_ip(message)
            rport = self._extract_rport(message)
            if received_ip and rport > 0:
                addr = (received_ip, rport)

            # 提取消息体
            body = ''
            if '\r\n\r\n' in message:
                body = message.split('\r\n\r\n')[1]

            # 提取DeviceID
            device_id = ''
            match = re.search(r'<DeviceID>(.*?)</DeviceID>', body)
            if match:
                device_id = match.group(1)

            # 先回复200 OK（防止设备重发）
            self._send_response(message, addr, 200, "OK")

            if not body:
                self.logger.debug(f"[GSS] [NOTIFY] 设备 {device_id} 空消息体")
                return

            self.logger.debug(f"[GSS] [NOTIFY] 收到设备 {device_id} 的NOTIFY通知")

            # 处理Catalog通知（某些设备通过NOTIFY推送目录变更）
            if 'Catalog' in body:
                if '<Response>' in body or '<Item>' in body:
                    self.logger.debug(f"[GSS] [NOTIFY] 设备 {device_id} 通过NOTIFY推送Catalog目录")
                    self.parse_catalog_response(body, device_id, parent_id="")
                else:
                    self.logger.debug(f"[GSS] [NOTIFY] Catalog消息格式不正确，缺少<Response>或<Item>标签")
            elif 'Keepalive' in body:
                # NOTIFY心跳：更新设备级心跳时间
                with self.lock:
                    device = self.devices.get(device_id)
                    if device and device.registered:
                        now_ms = int(time.time() * 1000)
                        device.last_keepalive_time = now_ms
                        for channel in device.channels:
                            channel.last_keepalive_time = now_ms
            else:
                # 其他NOTIFY类型（如媒体存在通知）
                self.logger.debug(f"[GSS] [NOTIFY] 设备 {device_id} 未识别的通知类型: {body[:200]}")

        except Exception as e:
            self.logger.error(f"[GSS] _handle_notify 异常: {e}", exc_info=True)
            try:
                self._send_response(message, addr, 500, "Internal Server Error")
            except:
                pass

    def _handle_response(self, message, addr):
        """处理响应消息（设备对我们的INVITE/BYE的回复）"""
        lines = message.split('\r\n')
        if not lines:
            return
        first_line = lines[0]
        
        # 解析状态码
        parts = first_line.split(' ', 2)
        if len(parts) < 2:
            return

        try:
            status_code = int(parts[1])
        except ValueError:
            return

        headers = self._parse_sip_headers(message)
        call_id = headers.get('Call-ID', '')
        cseq = headers.get('CSeq', '')

        # 处理INVITE响应
        if 'INVITE' in cseq:
            self._handle_invite_response(status_code, message, headers, call_id, addr)
        # 处理BYE响应
        elif 'BYE' in cseq:
            self._handle_bye_response(status_code, message, headers, call_id, addr)
        # 处理MESSAGE响应（如Catalog查询的200 OK）
        elif 'MESSAGE' in cseq:
            if status_code != 200:
                self.logger.debug(f"[GSS] MESSAGE响应状态码非200: {status_code}, addr={addr}")
            else:
                self.logger.debug(f"[GSS] [RX] MESSAGE 200 OK (Catalog查询确认) addr={addr}")

    def _handle_invite_response(self, status_code, message, headers, call_id, addr):
        """
        处理设备对INVITE的响应

        Args:
            status_code: SIP状态码（200=成功）
            message: 完整SIP消息
            headers: 解析后的头字段
            call_id: Call-ID
            addr: 设备地址
        """
        if status_code == 200:
            # 提取SDP（如果有）
            if '\r\n\r\n' in message:
                sdp = message.split('\r\n\r\n', 1)[1]
                if sdp:
                    self.logger.debug(f"[GSS] 设备SDP:\n{sdp[:200]}")

            # 提取To tag并存储到通道（用于后续BYE构造）
            to_header = headers.get('To', '')
            to_tag = ''
            if 'tag=' in to_header:
                to_tag = to_header.split('tag=')[-1].strip()

            # 更新通道状态为推流中
            self._update_channel_streaming_by_callid(call_id, streaming=True, forward_state=1, inviting=False, to_tag=to_tag)

            # 发送ACK
            self._send_ack(message, addr)

        elif status_code == 100:
            pass  # 正常流程，不需要日志

        elif status_code == 180:
            pass  # 正常流程，不需要日志

        elif status_code == 486:
            self.logger.debug(f"[GSS] ❌ INVITE 486 Busy Here - 设备忙，尝试发送BYE终止旧会话")
            # 尝试发送BYE终止设备上的旧会话，以便下次INVITE能成功
            self._try_send_bye_on_486(call_id, headers, addr)
            # 释放端口和资源
            self._release_channel_by_callid(call_id)
        
        elif status_code == 488:
            self.logger.debug(f"[GSS] ❌ INVITE 488 Not Acceptable Here - 媒体格式不被接受（SDP协商失败）")
            # 释放端口并重置通道状态
            self._release_channel_by_callid(call_id)

        elif 100 <= status_code < 200:
            pass  # 1xx临时响应（101/181/182/183等），等待最终响应，不释放资源
        else:
            self.logger.debug(f"[GSS] ⚠️ INVITE {status_code} - 未知响应")
            # 释放端口
            self._release_channel_by_callid(call_id)

    def _handle_bye_response(self, status_code, message, headers, call_id, addr):
        """
        处理设备对BYE的响应

        Args:
            status_code: SIP状态码
            message: 完整SIP消息
            headers: 解析后的头字段
            call_id: Call-ID
            addr: 设备地址
        """
        if status_code == 200:
            pass  # 正常流程，不需要日志
        else:
            self.logger.debug(f"[GSS] ⚠️ BYE {status_code} - 未知响应")

    def _send_ack(self, invite_response, addr):
        """
        发送ACK确认（对INVITE 200 OK的回复）

        Args:
            invite_response: 收到的INVITE 200 OK响应
            addr: 设备地址
        """
        headers = self._parse_sip_headers(invite_response)

        call_id = headers.get('Call-ID', '')
        from_header = headers.get('From', '')
        to_header = headers.get('To', '')
        via = headers.get('Via', '')

        # 提取To tag
        to_tag = ''
        if 'tag=' in to_header:
            to_tag = to_header.split('tag=')[-1].strip()

        # 构建ACK
        branch = f"z9hG4bK{random.randint(100000000, 999999999)}"

        ack_msg = (
            f"ACK sip:{addr[0]}:{addr[1]} SIP/2.0\r\n"
            f"Via: SIP/2.0/{self._get_sip_transport()} {self.server_ip}:{self.server_port};rport;branch={branch}\r\n"
            f"From: {from_header}\r\n"
            f"To: {to_header}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: 1 ACK\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n"
            f"\r\n"
        )

        try:
            self._send_sip_response(ack_msg, addr)
        except Exception as e:
            self.logger.error(f"[GSS] 发送ACK失败: {e}")

    def _send_bye_for_channel(self, device_ip, device_port, channel_id, call_id, from_tag, to_tag=""):
        """
        发送BYE请求终止指定通道的INVITE会话

        Args:
            device_ip: 设备IP
            device_port: 设备SIP端口
            channel_id: 通道ID
            call_id: INVITE会话的Call-ID
            from_tag: INVITE中的From tag（服务器端）
            to_tag: INVITE 200 OK中的To tag（设备端，可选）
        """
        if not call_id:
            return False

        branch = f"z9hG4bK{random.randint(100000000, 999999999)}"

        to_header = f"<sip:{channel_id}@{self.realm}>"
        if to_tag:
            to_header = f"<sip:{channel_id}@{self.realm}>;tag={to_tag}"

        bye_msg = (
            f"BYE sip:{channel_id}@{device_ip}:{device_port} SIP/2.0\r\n"
            f"Via: SIP/2.0/{self._get_sip_transport()} {self.server_ip}:{self.server_port};rport;branch={branch}\r\n"
            f"From: <sip:{self.server_id}@{self.realm}>;tag={from_tag}\r\n"
            f"To: {to_header}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: 2 BYE\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n"
            f"\r\n"
        )

        try:
            addr = (device_ip, device_port)
            success = self._send_sip_response(bye_msg, addr)
            if success:
                self.logger.debug(f"[GSS] 📤 已发送BYE终止旧会话: {channel_id}, call_id={call_id[:16]}...")
            return success
        except Exception as e:
            self.logger.error(f"[GSS] ❌ 发送BYE失败: {channel_id}, error={e}")
            return False

    def _try_send_bye_on_486(self, call_id, headers, addr):
        """
        收到486 Busy Here时，尝试发送BYE终止设备上的旧会话

        486表示设备认为自己仍在旧会话中，需要发送BYE释放旧会话后才能重新INVITE。
        此方法会从pending_invites和通道中查找旧会话信息来构造BYE。

        Args:
            call_id: 当前INVITE的Call-ID（被拒绝的新INVITE）
            headers: 486响应的SIP头
            addr: 设备地址 (ip, port)
        """
        # 从pending_invites中查找旧会话信息
        old_call_id = ""
        old_from_tag = ""
        old_to_tag = ""
        found_channel_id = ""
        device_ip = addr[0]
        device_port = addr[1]

        with self.pending_invites_lock:
            for ch_id, pending in list(self.pending_invites.items()):
                if pending['call_id'] == call_id:
                    old_call_id = pending.get('old_call_id', '')
                    old_from_tag = pending.get('old_from_tag', '')
                    old_to_tag = pending.get('old_to_tag', '')
                    found_channel_id = ch_id
                    break

        # 如果pending_invites中没有旧会话信息，尝试从通道中查找
        if not old_call_id and found_channel_id:
            with self.lock:
                for device in self.devices.values():
                    channel = self._find_channel(device.channels, found_channel_id)
                    if channel:
                        # 通道的call_id可能已被新INVITE覆盖，但from_tag/to_tag可能还在
                        if channel.from_tag:
                            old_from_tag = channel.from_tag
                        if channel.to_tag:
                            old_to_tag = channel.to_tag
                        device_ip = device.ip
                        device_port = device.port
                        break

        if old_call_id:
            self.logger.debug(f"[GSS] 📤 486恢复：发送BYE终止旧会话: channel={found_channel_id}, old_call_id={old_call_id[:16]}...")
            self._send_bye_for_channel(device_ip, device_port, found_channel_id, old_call_id, old_from_tag, old_to_tag)
        else:
            # 没有旧会话信息，尝试发送一个无dialog匹配的BYE（部分设备会接受）
            if found_channel_id:
                self.logger.debug(f"[GSS] ⚠️ 486恢复：无旧会话dialog信息，尝试发送通用BYE: channel={found_channel_id}")
                # 使用From头中的tag作为from_tag（这是新INVITE的tag，但某些设备可能接受）
                from_header = headers.get('From', '')
                fallback_from_tag = ''
                if 'tag=' in from_header:
                    fallback_from_tag = from_header.split('tag=')[-1].strip()
                self._send_bye_for_channel(device_ip, device_port, found_channel_id, call_id, fallback_from_tag, "")

    def _release_channel_by_callid(self, call_id):
        """
        根据Call-ID释放通道资源

        Args:
            call_id: INVITE会话的Call-ID
        """
        # 清理pending invite
        channel_id_to_clean = None
        with self.pending_invites_lock:
            for ch_id, pending in list(self.pending_invites.items()):
                if pending['call_id'] == call_id:
                    channel_id_to_clean = ch_id
                    break
        
        if channel_id_to_clean:
            with self.pending_invites_lock:
                pending = self.pending_invites.pop(channel_id_to_clean, None)
                if pending:
                    # 释放RTP端口
                    self.rtp_port_mgr.release(pending['rtp_port'])
                    # 关闭ZLM RTP服务器
                    self._close_rtp_server(channel_id_to_clean)
                    self.logger.debug(f"[GSS] 🧹 清理pending INVITE: {channel_id_to_clean}")
                    
                    # 同时重置通道状态（防止catalog刷新后丢失call_id导致状态不清理）
                    with self.lock:
                        device = self.devices.get(pending['device_id'])
                        if device:
                            channel = self._find_channel(device.channels, channel_id_to_clean)
                            if channel:
                                channel.rtp_port = 0
                                channel.allocated_rtp_port = 0
                                channel.call_id = ""
                                channel.from_tag = ""
                                channel.to_tag = ""
                                channel.streaming = False
                                channel.forward_state = 0
                                channel.inviting = False
                                self.logger.debug(f"[GSS] ✓ 已重置通道状态: {channel_id_to_clean}")
        
        with self.lock:
            for device in self.devices.values():
                for channel in device.channels:
                    if channel.call_id == call_id:
                        channel_id = channel.channel_id
                        rtp_port = channel.allocated_rtp_port  # 使用分配的端口
                        
                        # 释放RTP端口
                        if rtp_port > 0:
                            self.rtp_port_mgr.release(rtp_port)
                        
                        # 关闭ZLM RTP服务器
                        if channel_id:
                            self._close_rtp_server(channel_id)
                        
                        # 重置通道状态
                        channel.rtp_port = 0
                        channel.allocated_rtp_port = 0
                        channel.call_id = ""
                        channel.from_tag = ""
                        channel.to_tag = ""
                        channel.streaming = False
                        channel.forward_state = 0
                        channel.inviting = False  # 清除inviting标志
                        return

    def _update_channel_streaming_by_callid(self, call_id, streaming=False, forward_state=0, inviting=None, to_tag=None):
        """
        根据Call-ID更新通道推流状态

        Args:
            call_id: INVITE会话的Call-ID
            streaming: 是否正在推流
            forward_state: 转发状态 0:未转发 1:转发中
            inviting: 是否正在INVITE中（None表示不修改此状态）
            to_tag: INVITE 200 OK中的To tag（None表示不修改）
        """
        with self.lock:
            for device in self.devices.values():
                for channel in device.channels:
                    if channel.call_id == call_id:
                        channel.streaming = streaming
                        channel.forward_state = forward_state
                        if inviting is not None:
                            channel.inviting = inviting
                        if to_tag is not None:
                            channel.to_tag = to_tag
                        return

    def _send_401_unauthorized(self, request, addr):
        """发送401 Unauthorized响应"""
        nonce = self._generate_nonce()

        response = (
            "SIP/2.0 401 Unauthorized\r\n"
            f"Via: {self._get_header(request, 'Via')}\r\n"
            f"From: {self._get_header(request, 'From')}\r\n"
            f"To: {self._get_header(request, 'To')}\r\n"
            f"CSeq: {self._get_header(request, 'CSeq')}\r\n"
            f"Call-ID: {self._get_header(request, 'Call-ID')}\r\n"
            f'WWW-Authenticate: Digest realm="{self.realm}", '
            f'nonce="{nonce}", '
            f'algorithm=MD5, '
            f'qop="auth"\r\n'
            "Content-Length: 0\r\n"
            "\r\n"
        )

        self._send_sip_response(response, addr)

    def _send_200_ok(self, request, addr, device):
        """发送200 OK响应"""
        to_header = self._get_header(request, 'To')

        # 添加tag
        if ';tag=' not in to_header:
            tag = str(random.randint(10000000, 99999999))
            to_header = to_header.replace('>', f';tag={tag}>')

        response = (
            "SIP/2.0 200 OK\r\n"
            f"Via: {self._get_header(request, 'Via')}\r\n"
            f"From: {self._get_header(request, 'From')}\r\n"
            f"To: {to_header}\r\n"
            f"CSeq: {self._get_header(request, 'CSeq')}\r\n"
            f"Call-ID: {self._get_header(request, 'Call-ID')}\r\n"
            f"Contact: <sip:{self.server_id}@{self.server_ip}:{self.server_port}>\r\n"
            f"Expires: {self.sip_server_expiry}\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )

        self._send_sip_response(response, addr)

    def _send_100_trying(self, request, addr):
        """发送100 Trying响应"""
        response = (
            "SIP/2.0 100 Trying\r\n"
            f"Via: {self._get_header(request, 'Via')}\r\n"
            f"From: {self._get_header(request, 'From')}\r\n"
            f"To: {self._get_header(request, 'To')}\r\n"
            f"CSeq: {self._get_header(request, 'CSeq')}\r\n"
            f"Call-ID: {self._get_header(request, 'Call-ID')}\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )

        self._send_sip_response(response, addr)

    def _build_sdp_media_line(self, media_type, port, payload_types, is_rtp=True):
        """
        构建SDP媒体行（根据rtp_transfer_mode自动选择UDP或TCP被动）
        
        Args:
            media_type: 媒体类型（video/audio）
            port: 端口号
            payload_types: 负载类型列表，如 [96, 98, 97]
            is_rtp: 是否为RTP（True=RTP/AVP或TCP/RTP/AVP，False=其他）
        
        Returns:
            tuple: (media_line, attributes_list)
        """
        attrs = []
        
        if self.rtp_transfer_mode == 0:
            # UDP模式：不包含setup和connection属性
            media_line = f"m={media_type} {port} RTP/AVP {' '.join(map(str, payload_types))}"
        elif self.rtp_transfer_mode == 1:
            # TCP被动模式
            media_line = f"m={media_type} {port} TCP/RTP/AVP {' '.join(map(str, payload_types))}"
            attrs.append("a=setup:passive")
            attrs.append("a=connection:new")
        else:
            # 未知模式，默认UDP
            media_line = f"m={media_type} {port} RTP/AVP {' '.join(map(str, payload_types))}"
        
        return media_line, attrs

    def _build_sdp(self, media_type, port, payload_types, attrs_map, include_audio=False):
        """
        构建完整的SDP（根据rtp_transfer_mode自动选择UDP或TCP）
        
        Args:
            media_type: 主媒体类型（video）
            port: 端口号
            payload_types: 主媒体负载类型列表
            attrs_map: 属性映射 {payload_type: rtpmap_string}
            include_audio: 是否包含音频（Python版本：UDP和TCP模式均支持）
        
        Returns:
            str: SDP字符串
        """
        # 构建主媒体行
        media_line, tcp_attrs = self._build_sdp_media_line(media_type, port, payload_types)
        
        sdp = (
            f"v=0\r\n"
            f"o={self.server_id} 0 0 IN IP4 {self.server_ip}\r\n"
            f"s=Play\r\n"
            f"c=IN IP4 {self.server_ip}\r\n"
            f"t=0 0\r\n"
            f"{media_line}\r\n"
        )
        
        # 与C++版本一致：先添加setup和connection属性，再添加rtpmap
        for attr in tcp_attrs:
            sdp += f"{attr}\r\n"
        
        # 添加rtpmap
        for pt, rtpmap in attrs_map.items():
            sdp += f"a=rtpmap:{pt} {rtpmap}\r\n"
        
        # 与C++版本一致：INVITE场景使用a=recvonly（服务器接收RTP流）
        sdp += f"a=recvonly\r\n"
        
        # Python版本特殊扩展：UDP模式下rtpTransferAudioType=1也支持音频（C++版本仅TCP支持）
        if include_audio:
            audio_payloads = [8, 0, 9, 18, 97, 98]  # PCMA/PCMU/G722/G729/G726/AAC
            audio_media_line, audio_tcp_attrs = self._build_sdp_media_line("audio", port, audio_payloads)
            sdp += f"{audio_media_line}\r\n"
            for attr in audio_tcp_attrs:
                sdp += f"{attr}\r\n"
            sdp += f"a=recvonly\r\n"
            sdp += f"a=rtpmap:8 PCMA/8000\r\n"
            sdp += f"a=rtpmap:0 PCMU/8000\r\n"
            sdp += f"a=rtpmap:9 G722/16000\r\n"
            sdp += f"a=rtpmap:18 G729/8000\r\n"
            sdp += f"a=rtpmap:97 G726-32/8000\r\n"
            sdp += f"a=rtpmap:98 mpeg4-generic/8000/1\r\n"
            sdp += f"a=fmtp:98 profile-level-id=1;mode=AAC-hbr;config=1210;sizeLength=13;indexLength=3;indexDeltaLength=3\r\n"
            sdp += f"a=ssrc:87654321\r\n"
            sdp += f"a=y:0100000002\r\n"
        
        # 添加ssrc（某些设备需要此字段）
        sdp += f"a=ssrc:12345678\r\n"
        sdp += f"a=y:0100000001\r\n"
        
        return sdp

    def _send_200_ok_invite(self, request, addr, headers):
        """发送200 OK响应（INVITE）"""
        # 根据rtp_transfer_audio_type决定是否包含音频
        include_audio = (self.rtp_transfer_audio_type == 1)
        
        # 使用_build_sdp构建标准SDP（与C++版本保持一致）
        sdp = self._build_sdp(
            media_type="video",
            port=0,  # 端口在设备SDP中指定
            payload_types=[96, 98, 97],  # PS/H264/MPEG4，与C++版本一致
            attrs_map={96: "PS/90000", 98: "H264/90000", 97: "MPEG4/90000"},
            include_audio=include_audio
        )

        to_header = self._get_header(request, 'To')
        if ';tag=' not in to_header:
            tag = str(random.randint(10000000, 99999999))
            to_header = to_header.replace('>', f';tag={tag}>')

        response = (
            "SIP/2.0 200 OK\r\n"
            f"Via: {self._get_header(request, 'Via')}\r\n"
            f"From: {self._get_header(request, 'From')}\r\n"
            f"To: {to_header}\r\n"
            f"CSeq: {self._get_header(request, 'CSeq')}\r\n"
            f"Call-ID: {self._get_header(request, 'Call-ID')}\r\n"
            f"Contact: <sip:{self.server_id}@{self.server_ip}:{self.server_port}>\r\n"
            f"Content-Type: application/sdp\r\n"
            f"Content-Length: {len(sdp)}\r\n"
            "\r\n"
            f"{sdp}"
        )

        self._send_sip_response(response, addr)

    def _send_response(self, request, addr, code, reason):
        """发送通用SIP响应"""
        response = (
            f"SIP/2.0 {code} {reason}\r\n"
            f"Via: {self._get_header(request, 'Via')}\r\n"
            f"From: {self._get_header(request, 'From')}\r\n"
            f"To: {self._get_header(request, 'To')}\r\n"
            f"CSeq: {self._get_header(request, 'CSeq')}\r\n"
            f"Call-ID: {self._get_header(request, 'Call-ID')}\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )
        self._send_sip_response(response, addr)

    def _send_200_ok_message(self, request, addr):
        """发送200 OK响应（MESSAGE）"""
        response = (
            "SIP/2.0 200 OK\r\n"
            f"Via: {self._get_header(request, 'Via')}\r\n"
            f"From: {self._get_header(request, 'From')}\r\n"
            f"To: {self._get_header(request, 'To')}\r\n"
            f"CSeq: {self._get_header(request, 'CSeq')}\r\n"
            f"Call-ID: {self._get_header(request, 'Call-ID')}\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        )

        self._send_sip_response(response, addr)

    def _get_header(self, message, header_name):
        """获取SIP消息头"""
        lines = message.split('\r\n')
        for line in lines[1:]:
            if line.lower().startswith(header_name.lower() + ':'):
                return line.split(':', 1)[1].strip()
        return ''

    def _verify_auth(self, auth_header, uri, method, device_id=''):
        """验证Digest认证（严格密码校验）"""
        # 去除"Digest "前缀
        if auth_header.startswith('Digest '):
            auth_header = auth_header[7:]

        # 解析Authorization参数（兼容带引号和不带引号的值）
        auth_params = {}
        for match in re.finditer(r'(\w+)="([^"]*)"|(\w+)=(\w+)', auth_header):
            key = (match.group(1) or match.group(3)).lower()
            value = match.group(2) if match.group(2) is not None else match.group(4)
            auth_params[key] = value

        username = auth_params.get('username', '')
        realm = auth_params.get('realm', '')
        nonce = auth_params.get('nonce', '')
        response = auth_params.get('response', '')
        uri_val = auth_params.get('uri', '')
        qop = auth_params.get('qop', '').strip('"')  # 去除可能的引号
        cnonce = auth_params.get('cnonce', '')
        nc = auth_params.get('nc', '')

        if not all([username, realm, nonce, response, uri_val]):
            self.logger.error("[GSS] 认证参数不完整")
            self.logger.debug(f"[GSS] 解析结果: {auth_params}")
            return False

        # 计算期望的response
        expected_response = self._calculate_response(
            username, realm, self.password, nonce, method, uri_val,
            qop=qop, cnonce=cnonce, nc=nc
        )

        # Bug 16修复：加锁访问self.devices，防止竞态条件
        with self.lock:
            device = self.devices.get(device_id)
            is_first_register = (device_id not in self.devices) or (device and not device.registered)
        
        # 详细调试日志（设备首次注册时打印，方便排查密码问题）
        if is_first_register:
            self.logger.debug(f"[GSS] 🔐 认证参数详情:")
            self.logger.debug(f"[GSS]   设备用户名: {username}")
            self.logger.debug(f"[GSS]   Realm: {realm}")
            self.logger.debug(f"[GSS]   服务器密码: {self.password}")
            self.logger.debug(f"[GSS]   qop: {qop}, nc: {nc}, cnonce: {cnonce}")
            self.logger.debug(f"[GSS]   设备返回: {response}")
            self.logger.debug(f"[GSS]   服务器计算: {expected_response}")

        # 严格比对
        if response == expected_response:
            return True
        else:
            self.logger.error(f"[GSS] ❌ 认证失败: 密码错误或计算方式不匹配")
            return False

    def _extract_received_ip(self, message):
        """
        从SIP消息的Via头中提取received参数（NAT穿透关键）
        
        Args:
            message: SIP消息字符串
            
        Returns:
            str: 公网IP地址，如果不存在则返回空字符串
        """
        # 匹配: Via: SIP/2.0/UDP 192.168.1.100:5060;received=公网IP;rport=端口
        match = re.search(r'Via:\s+SIP/2\.0/\w+\s+[^;]+;received=([\d\.]+)', message)
        if match:
            return match.group(1)
        return ""

    def _extract_rport(self, message):
        """
        从SIP消息的Via头中提取rport参数（NAT穿透关键）
        
        Args:
            message: SIP消息字符串
            
        Returns:
            int: 公网端口号，如果不存在则返回-1
        """
        # Bug 6修复：只匹配第一个Via头中的rport
        lines = message.split('\r\n')
        for line in lines:
            if line.startswith('Via:'):
                match = re.search(r'rport=(\d+)', line)
                if match:
                    return int(match.group(1))
                break
        return -1

    def _update_device_contact(self, device_id, new_ip, new_port, message=''):
        """
        更新设备的联系地址（支持NAT穿透）
        
        Args:
            device_id: 设备ID
            new_ip: 新IP地址
            new_port: 新端口
            message: SIP消息（用于提取received和rport）
            
        Returns:
            bool: 是否更新了地址
        """
        with self.lock:
            device = self.devices.get(device_id)
            if not device:
                return False
            
            # 优先使用Via头的received和rport（NAT环境下的公网地址）
            if message:
                received_ip = self._extract_received_ip(message)
                rport = self._extract_rport(message)
                
                if received_ip and rport > 0:
                    new_ip = received_ip
                    new_port = rport
            
            # 检查地址是否有变化
            if device.ip == new_ip and device.port == new_port:
                return False
            
            old_ip = device.ip
            old_port = device.port
            device.ip = new_ip
            device.port = new_port
            
            self.logger.debug(f"[GSS]   地址更新: {old_ip}:{old_port} -> {new_ip}:{new_port}")
            
            return True

    def _check_expired_devices(self):
        """检查过期设备（基于心跳时间和注册过期时间）"""
        now_ms = int(time.time() * 1000)
        # 心跳超时：使用配置的sip_server_timeout（秒→毫秒），最小180秒防止配置过小
        expired_timeout = max(self.sip_server_timeout, 180) * 1000
        # 注册过期超时：使用配置的sip_server_expiry（秒→毫秒），无心跳时按注册过期判断
        register_expiry_ms = max(self.sip_server_expiry, 600) * 1000
        cleanup_timeout = 1800000  # 30分钟无活动则清理设备
        
        # 第一阶段：在锁内收集需要处理的设备和通道信息
        expired_devices_info = []  # [(device_id, channels_to_stop)]
        devices_to_cleanup = []  # 需要清理的设备ID列表
        
        with self.lock:
            expired_devices = []
            for device_id, device in list(self.devices.items()):  # 使用list()避免遍历时修改字典
                if device.registered:
                    # 优先检查设备级心跳时间（即使无通道也能保活）
                    has_recent_keepalive = False
                    if device.last_keepalive_time > 0:
                        dev_diff = now_ms - device.last_keepalive_time
                        if dev_diff < expired_timeout:
                            has_recent_keepalive = True

                    # 再检查通道级心跳时间
                    if not has_recent_keepalive:
                        for channel in device.channels:
                            if channel.last_keepalive_time > 0:
                                time_diff = now_ms - channel.last_keepalive_time
                                if time_diff < expired_timeout:
                                    has_recent_keepalive = True
                                    break
                    
                    # 如果所有通道都超时，且没有新的注册
                    if not has_recent_keepalive:
                        # 检查注册时间：无心跳时，按注册过期时间判断（而非心跳超时）
                        if device.last_register_time > 0:
                            reg_diff = now_ms - device.last_register_time
                            if reg_diff > register_expiry_ms:
                                expired_devices.append(device_id)
                        else:
                            # 没有注册时间记录，保守处理
                            pass
                else:
                    # 设备已离线，检查是否需要清理
                    if device.last_register_time > 0:
                        offline_duration = now_ms - device.last_register_time
                        if offline_duration > cleanup_timeout:
                            devices_to_cleanup.append(device_id)
                            self.logger.debug(f"[GSS] 🧹 清理长时间离线设备: {device_id} (离线{offline_duration//60000}分钟)")

            # 收集需要停止推流的通道信息
            for device_id in expired_devices:
                device = self.devices[device_id]
                channels_to_stop = []
                for channel in device.channels:
                    if channel.streaming:
                        channels_to_stop.append({
                            'channel_id': channel.channel_id,
                            'rtp_port': channel.allocated_rtp_port  # 使用分配的端口
                        })
                expired_devices_info.append((device_id, channels_to_stop))
                # 立即更新状态（在锁内）
                device.registered = False
                for channel in device.channels:
                    channel.streaming = False
                    channel.rtp_port = 0
                    channel.allocated_rtp_port = 0
                    channel.call_id = ""
                    channel.forward_state = 0
                    # Bug 3修复：清理inviting状态
                    channel.inviting = False
            
            # 清理长时间离线的设备
            for device_id in devices_to_cleanup:
                device = self.devices.pop(device_id, None)
                if device:
                    # 确保清理所有资源
                    for channel in device.channels:
                        if channel.streaming or channel.allocated_rtp_port > 0:
                            self._close_rtp_server(channel.channel_id)
                            if channel.allocated_rtp_port > 0:
                                self.rtp_port_mgr.release(channel.allocated_rtp_port)

        # 第二阶段：在锁外执行HTTP请求和端口释放（避免持锁阻塞）
        for device_id, channels_to_stop in expired_devices_info:
            self.logger.debug(f"[GSS] ⚠️ 设备 {device_id} 心跳超时，标记为离线")
            for ch_info in channels_to_stop:
                self.logger.debug(f"[GSS] ⏹️ 停止过期设备的推流: {ch_info['channel_id']}")
                # 关闭ZLM RTP服务器（HTTP请求，可能阻塞）
                self._close_rtp_server(ch_info['channel_id'])
                # 释放RTP端口
                self.rtp_port_mgr.release(ch_info['rtp_port'])

        if expired_devices_info:
            self.logger.debug(f"[GSS] 发现 {len(expired_devices_info)} 个过期设备")

    def log_status(self):
        """打印服务器状态"""
        self.logger.debug("[GSS] -----------GB28181SipServer.log_status start----------")

        # 在锁内获取设备快照，避免遍历时字典被修改
        with self.lock:
            devices_snapshot = list(self.devices.values())
            devices_count = len(self.devices)

        self.logger.debug(f"[GSS] 服务器: {self.server_ip}:{self.server_port}")
        self.logger.debug(f"[GSS] 已注册设备: {devices_count}")
        self.logger.debug(f"[GSS] 统计信息:")
        self.logger.debug(f"[GSS]   - 总注册数: {self.stats['total_registers']}")
        self.logger.debug(f"[GSS]   - 总邀请数: {self.stats['total_invites']}")
        self.logger.debug(f"[GSS]   - 总消息数: {self.stats['total_messages']}")

        if devices_snapshot:
            self.logger.debug(f"[GSS] \n设备列表:")
            for device in devices_snapshot:
                self.logger.debug(f"[GSS]   - {device.device_id}: {device.ip}:{device.port} "
                        f"({'在线' if device.registered else '离线'}) "
                        f"注册于 {device.register_time}")

        self.logger.debug("[GSS] -----------GB28181SipServer.log_status end----------")

    def send_invite(self, device_id, channel_id):
        """
        发送INVITE请求到设备（主动推流）

        Args:
            device_id: 设备ID
            channel_id: 通道ID

        Returns:
            bool: 是否成功发送
        """
        # 在锁内获取设备信息和通道状态
        with self.lock:
            if device_id not in self.devices:
                self.logger.error(f"[GSS] 设备 {device_id} 不存在")
                return False

            device = self.devices[device_id]
            if not device.registered:
                self.logger.error(f"[GSS] 设备 {device_id} 未注册")
                return False

            device_ip = device.ip
            device_port = device.port
            
            # 检查通道是否已在推流或正在INVITE中（防止重复INVITE）
            channel = self._find_channel(device.channels, channel_id)
            if channel and (channel.streaming or channel.forward_state == 1 or channel.inviting):
                self.logger.debug(f"[GSS] 通道 {channel_id} 已在推流中或正在INVITE，跳过重复请求")
                return False
            
            # 设置inviting标志（在锁内，防止竞态条件）
            if channel:
                channel.inviting = True

        # 从RTPPortManager统一分配端口
        rtp_port = self.rtp_port_mgr.allocate(channel_id)
        self.logger.debug(f"[GSS] 🔧 send_invite分配RTP端口: {rtp_port}, channel_id={channel_id}")
        if rtp_port == 0:
            self.logger.error(f"[GSS] RTP端口分配失败: {channel_id}")
            # 清除inviting标志
            with self.lock:
                device = self.devices.get(device_id)
                if device:
                    channel = self._find_channel(device.channels, channel_id)
                    if channel:
                        channel.inviting = False
            return False
        
        # 调用ZLMediaKit openRtpServer创建RTP服务器
        zlm_port = 0
        try:
            success, msg, zlm_port = self.zlm.openRtpServer(
                port=rtp_port,
                tcp_mode=2 if self.rtp_transfer_mode == 1 else 0,
                stream_id=channel_id
            )
            if not success:
                # 如果stream已存在，先关闭再重试
                if "already exists" in msg:
                    self.logger.debug(f"[GSS] ⚠️ RTP服务器已存在，先关闭再重试: {channel_id}")
                    self._close_rtp_server(channel_id)
                    time.sleep(0.5)  # 等待关闭完成
                    
                    # 重试创建
                    success, msg, zlm_port = self.zlm.openRtpServer(
                        port=rtp_port,
                        tcp_mode=2 if self.rtp_transfer_mode == 1 else 0,
                        stream_id=channel_id
                    )
                    
                    if not success:
                        self.logger.error(f"[GSS] ZLM openRtpServer重试失败: {msg}")
                        # 释放已分配的端口
                        self.rtp_port_mgr.release(rtp_port)
                        # 清除inviting标志
                        with self.lock:
                            device = self.devices.get(device_id)
                            if device:
                                channel = self._find_channel(device.channels, channel_id)
                                if channel:
                                    channel.inviting = False
                        return False
                else:
                    self.logger.error(f"[GSS] ZLM openRtpServer失败: {msg}")
                    # 释放已分配的端口
                    self.rtp_port_mgr.release(rtp_port)
                    # 清除inviting标志
                    with self.lock:
                        device = self.devices.get(device_id)
                        if device:
                            channel = self._find_channel(device.channels, channel_id)
                            if channel:
                                channel.inviting = False
                    return False
            # 获取ZLM实际分配的端口（可能与请求的不同）
            self.logger.debug(f"[GSS] ✓ RTP端口分配: {rtp_port}, ZLM实际端口: {zlm_port}, stream_id={channel_id}")
        except Exception as e:
            self.logger.error(f"[GSS] ZLM openRtpServer异常: {e}")
            # 异常时释放已分配的端口
            self.rtp_port_mgr.release(rtp_port)
            # 清除inviting标志
            with self.lock:
                device = self.devices.get(device_id)
                if device:
                    channel = self._find_channel(device.channels, channel_id)
                    if channel:
                        channel.inviting = False
            return False

        # 构建INVITE请求（与C++版本一致）
        call_id = str(uuid.uuid4()).replace('-', '')
        from_tag = str(random.randint(100000000, 999999999))
        branch = f"z9hG4bK{random.randint(100000000, 999999999)}"
        
        # Subject: {channel_id}:0,{server_id}:0（GB28181必须字段）
        subject = f"{channel_id}:0,{self.server_id}:0"

        # SDP内容（与C++版本SipServer.cpp保持一致）
        include_audio = (self.rtp_transfer_audio_type == 1)
        # 使用ZLM实际分配的端口（可能与请求的不同）
        final_port = zlm_port if zlm_port > 0 else rtp_port
        sdp = self._build_sdp(
            media_type="video",
            port=final_port,
            payload_types=[96, 98, 97],  # PS/H264/MPEG4，与C++版本一致
            attrs_map={96: "PS/90000", 98: "H264/90000", 97: "MPEG4/90000"},
            include_audio=include_audio
        )

        invite = (
            f"INVITE sip:{channel_id}@{device_ip}:{device_port} SIP/2.0\r\n"
            f"Via: SIP/2.0/{self._get_sip_transport()} {self.server_ip}:{self.server_port};rport;branch={branch}\r\n"
            f"From: <sip:{self.server_id}@{self.realm}>;tag={from_tag}\r\n"
            f"To: <sip:{channel_id}@{self.realm}>\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: 1 INVITE\r\n"
            f"Max-Forwards: 70\r\n"
            f"Contact: <sip:{self.server_id}@{self.server_ip}:{self.server_port}>\r\n"
            f"User-Agent: rebucca\r\n"
            f"Subject: {subject}\r\n"
            f"Session-Expires: {self.sip_server_timeout};refresher=uas\r\n"
            f"Supported: timer\r\n"
            f"Content-Type: application/sdp\r\n"
            f"Content-Length: {len(sdp)}\r\n"
            f"\r\n"
            f"{sdp}"
        )

        # Debug: 打印INVITE完整内容用于诊断488错误（已禁用）
        # if self.log_debug:
        #     self.logger.debug(f"[GSS] ===== INVITE Message =====")
        #     for i, line in enumerate(invite.split('\r\n')):
        #         self.logger.debug(f"[GSS]   [{i}] {line}")
        #     self.logger.debug(f"[GSS] ===== End INVITE =====")

        # 注册pending invite（在发送前，防止catalog刷新丢失状态）
        with self.pending_invites_lock:
            self.pending_invites[channel_id] = {
                'rtp_port': rtp_port,  # 使用分配的端口，不是ZLM返回的端口
                'call_id': call_id,
                'device_id': device_id
            }

        try:
            addr = (device_ip, device_port)
            self._send_sip_response(invite, addr)
            
            # 记录call_id和rtp_port用于后续状态更新（不立即设置forward_state）
            # 真正的状态更新在收到200 OK响应时进行
            with self.lock:
                device = self.devices.get(device_id)
                if device:
                    channel = self._find_channel(device.channels, channel_id)
                    if channel:
                        channel.rtp_port = final_port  # ZLM实际返回的端口
                        channel.allocated_rtp_port = rtp_port  # 保存分配的端口
                        channel.call_id = call_id
                        channel.from_tag = from_tag  # 保存from_tag用于后续BYE构造
                        # 不清除inviting标志，等待200 OK或错误响应
                        self.logger.debug(f"[GSS] ✓ INVITE已发送，等待200 OK响应: {channel_id}")
                    else:
                        # 通道已不存在（可能被catalog刷新或设备重新注册移除），但保留pending状态
                        self.logger.debug(f"[GSS] ⚠️ 通道 {channel_id} 在INVITE发送后不在内存中，pending状态已保留")
                        # 不清理资源！pending状态会在catalog刷新后恢复
                        return True  # 返回True，等待200 OK响应
                else:
                    # Bug 14修复：设备已不存在（极端情况），保留pending状态
                    self.logger.debug(f"[GSS] ⚠️ 设备 {device_id} 在INVITE发送后已不存在，等待catalog刷新恢复")
                    return True  # 返回True，等待200 OK响应
            
            self.logger.debug(f"[GSS] 📡 INVITE已发送: {channel_id} -> {device_ip}:{device_port}, RTP port={rtp_port}")
            return True
        except Exception as e:
            self.logger.error(f"[GSS] ✗ 发送INVITE失败: {e}")
            # 发送失败时释放已分配的端口
            self.rtp_port_mgr.release(rtp_port)
            # 关闭ZLM服务器
            self._close_rtp_server(channel_id)
            # 清除inviting标志并重置通道状态
            with self.lock:
                device = self.devices.get(device_id)
                if device:
                    channel = self._find_channel(device.channels, channel_id)
                    if channel:
                        channel.inviting = False
                        channel.rtp_port = 0
                        channel.allocated_rtp_port = 0
                        channel.call_id = ""
                        channel.streaming = False
                        channel.forward_state = 0
            return False

    def query_device_info(self, device_id):
        """
        查询设备信息（DeviceInfo），获取设备名称、厂商、型号等
        注册后自动调用，与Catalog查询并行

        Args:
            device_id: 设备ID
        """
        with self.lock:
            if device_id not in self.devices:
                return False
            device = self.devices[device_id]
            device_ip = device.ip
            device_port = device.port

        call_id = str(uuid.uuid4()).replace('-', '')
        from_tag = str(random.randint(100000000, 999999999))
        branch = f"z9hG4bK{random.randint(100000000, 999999999)}"
        sn = random.randint(1, 9999)

        body = (
            f"<?xml version=\"1.0\"?>\r\n"
            f"<Query>\r\n"
            f"<CmdType>DeviceInfo</CmdType>\r\n"
            f"<SN>{sn}</SN>\r\n"
            f"<DeviceID>{device_id}</DeviceID>\r\n"
            f"</Query>\r\n"
        )

        msg = (
            f"MESSAGE sip:{device_id}@{device_ip}:{device_port} SIP/2.0\r\n"
            f"Via: SIP/2.0/{self._get_sip_transport()} {self.server_ip}:{self.server_port};rport;branch={branch}\r\n"
            f"From: <sip:{self.server_id}@{self.realm}>;tag={from_tag}\r\n"
            f"To: <sip:{device_id}@{self.realm}>\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: 1 MESSAGE\r\n"
            f"Max-Forwards: 70\r\n"
            f"Contact: <sip:{self.server_id}@{self.server_ip}:{self.server_port}>\r\n"
            f"Content-Type: Application/MANSCDP+xml\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"\r\n"
            f"{body}"
        )

        try:
            addr = (device_ip, device_port)
            self._send_sip_response(msg, addr)
            self.logger.debug(f"[GSS] [DEVICEINFO] 已发送DeviceInfo查询到设备 {device_id} @ {device_ip}:{device_port}")
            return True
        except Exception as e:
            self.logger.error(f"[GSS] [DEVICEINFO] 发送DeviceInfo查询失败: {e}")
            return False

    def query_catalog(self, device_id):
        """
        查询设备通道目录（注册后自动调用）

        Args:
            device_id: 设备ID
        """
        # 在锁内获取设备信息
        with self.lock:
            if device_id not in self.devices:
                return False
            device = self.devices[device_id]
            device_ip = device.ip
            device_port = device.port

        call_id = str(uuid.uuid4()).replace('-', '')
        from_tag = str(random.randint(100000000, 999999999))
        branch = f"z9hG4bK{random.randint(100000000, 999999999)}"
        sn = random.randint(1, 9999)

        body = (
            f"<?xml version=\"1.0\"?>\r\n"
            f"<Query>\r\n"
            f"<CmdType>Catalog</CmdType>\r\n"
            f"<SN>{sn}</SN>\r\n"
            f"<DeviceID>{device_id}</DeviceID>\r\n"
            f"</Query>\r\n"
        )

        msg = (
            f"MESSAGE sip:{device_id}@{device_ip}:{device_port} SIP/2.0\r\n"
            f"Via: SIP/2.0/{self._get_sip_transport()} {self.server_ip}:{self.server_port};rport;branch={branch}\r\n"
            f"From: <sip:{self.server_id}@{self.realm}>;tag={from_tag}\r\n"
            f"To: <sip:{device_id}@{self.realm}>\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: 1 MESSAGE\r\n"
            f"Max-Forwards: 70\r\n"
            f"Contact: <sip:{self.server_id}@{self.server_ip}:{self.server_port}>\r\n"
            f"Content-Type: Application/MANSCDP+xml\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"\r\n"
            f"{body}"
        )

        try:
            addr = (device_ip, device_port)
            self._send_sip_response(msg, addr)
            self.logger.debug(f"[GSS] [CATALOG] 已发送Catalog查询到设备 {device_id} @ {device_ip}:{device_port}")
            return True
        except Exception as e:
            self.logger.error(f"[GSS] [CATALOG] 发送Catalog查询失败: {e}")
            return False

    def _get_catalog_lock(self, device_id):
        """获取per-device的Catalog处理锁，串行化同一设备的Catalog响应处理，防止并发导致重复update_admin"""
        with self.catalog_locks_guard:
            if device_id not in self.catalog_locks:
                self.catalog_locks[device_id] = threading.Lock()
            return self.catalog_locks[device_id]

    def remove_channel(self, channel_id):
        """
        从内存中删除指定通道（当用户在UI删除流时调用）。
        防止parse_catalog_response的old_channel_map缓存抑制update_admin，
        导致下级重新注册后上级看不到通道数据。
        幂等操作，通道不存在时不报错。
        """
        if not channel_id:
            return
        removed_count = 0
        with self.lock:
            for device in self.devices.values():
                # 递归清理通道（含子目录）
                def _remove_from_list(channels):
                    nonlocal removed_count
                    kept = []
                    for ch in channels:
                        if ch.channel_id == channel_id:
                            removed_count += 1
                            continue
                        if ch.children:
                            ch.children = _remove_from_list(ch.children)
                        kept.append(ch)
                    return kept
                device.channels = _remove_from_list(device.channels)
        if removed_count > 0:
            self.logger.debug(f"[GSS] 已从内存清理通道: {channel_id} (共{removed_count}处)")

    def parse_catalog_response(self, body, device_id, parent_id=""):
        """
        解析设备返回的Catalog响应（支持多级目录结构）

        Args:
            body: XML响应体
            device_id: 设备ID
            parent_id: 父节点ID（用于递归查询子目录）
        """

        try:
            root = _safe_xml_parse(body)
            item_list = root.findall('.//Item')

            if not item_list:
                self.logger.debug(f"[GSS] ⚠️ Catalog响应中没有通道项")
                return []

            # per-device锁：串行化同一设备的Catalog处理，防止并发Catalog响应导致重复update_admin
            catalog_lock = self._get_catalog_lock(device_id)
            with catalog_lock:
                channels = []
                seen_channel_ids = set()  # 去重集合，防止Catalog响应含重复DeviceID导致通道重复
                with self.lock:
                    device = self.devices.get(device_id)

                # 【关键修复】在循环前构建旧通道映射，用于判断通道是否已存在
                # 防止多次Catalog响应并发触发update_admin导致重复插入av_stream
                old_channel_map = {}
                if device:
                    def _build_ch_map(chs):
                        m = {}
                        for ch in chs:
                            m[ch.channel_id] = ch
                            if ch.children:
                                m.update(_build_ch_map(ch.children))
                        return m
                    with self.lock:
                        old_channel_map = _build_ch_map(device.channels)

                for item in item_list:
                    ch_id_elem = item.find('DeviceID')
                    name_elem = item.find('Name')
                    status_elem = item.find('Status')
                    parental_elem = item.find('Parental')
                    parent_id_elem = item.find('ParentID')
                    device_type_elem = item.find('DeviceType')
                    manufacturer_elem = item.find('Manufacturer')
                    model_elem = item.find('Model')
                    owner_elem = item.find('Owner')
                    civil_code_elem = item.find('CivilCode')
                    sum_num_elem = item.find('SumNum')

                    if ch_id_elem is not None:
                        ch_id = ch_id_elem.text or ''

                        # 去重：跳过已处理的channel_id，防止重复通道
                        if ch_id in seen_channel_ids:
                            self.logger.debug(f"[GSS] ⚠️ Catalog响应含重复通道ID {ch_id}，已跳过")
                            continue
                        seen_channel_ids.add(ch_id)
                        name = name_elem.text if name_elem is not None else ''
                        status = status_elem.text if status_elem is not None else 'OFF'
                        parental = int(parental_elem.text) if parental_elem is not None and parental_elem.text else 0
                        pid = parent_id_elem.text if parent_id_elem is not None else (parent_id if parent_id else device_id)
                        dev_type = device_type_elem.text if device_type_elem is not None else ''
                        manufacturer = manufacturer_elem.text if manufacturer_elem is not None else ''
                        model = model_elem.text if model_elem is not None else ''
                        owner = owner_elem.text if owner_elem is not None else ''
                        civil_code = civil_code_elem.text if civil_code_elem is not None else ''
                        sum_num = int(sum_num_elem.text) if sum_num_elem is not None and sum_num_elem.text else 0

                        # 创建Channel并关联device（与C++版本一致）
                        channel = Channel(ch_id, name, device=device if device else None,logger=self.logger)
                        channel.status = status
                        channel.parental = parental
                        channel.parent_id = pid
                        channel.device_type = dev_type
                        channel.manufacturer = manufacturer
                        channel.model = model
                        channel.owner = owner
                        channel.civil_code = civil_code
                        channel.sum_num = sum_num

                        # 设置时间戳
                        channel.last_register_time = int(time.time() * 1000) if device else 0

                        if parental == 1:
                            # 目录节点
                            self.logger.debug(f"[GSS]   📁 目录: {ch_id} ({name})")
                            # 递归查询子目录
                            threading.Thread(
                                target=self.query_sub_catalog,
                                args=(device_id, ch_id),
                                daemon=True
                            ).start()
                        else:
                            # 叶子通道
                            type_icon = {'IPC': '📷', 'DVR': '📼', 'NVR': '🖥️'}.get(dev_type, '📹')
                            self.logger.debug(f"[GSS]   {type_icon} 通道: {ch_id} ({name}) [{status}]")

                            # 自动同步到rebekah_admin（与C++版本逻辑一致）
                            # 【关键修复】只在通道首次出现时调update_admin，防止多次Catalog响应并发导致重复插入
                            if self.admin_host and ch_id not in old_channel_map:
                                threading.Thread(
                                    target=channel.update_admin,
                                    args=(self,),
                                    daemon=True
                                ).start()

                        channels.append(channel)

                # 如果是子目录查询，将通道添加到父目录的children中
                if parent_id:
                    with self.lock:
                        device = self.devices.get(device_id)
                        if device:
                            parent_ch = self._find_channel(device.channels, parent_id)
                            if parent_ch:
                                # 保留子目录通道的状态
                                old_children = parent_ch.children if parent_ch.children else []

                                # 递归构建旧子通道映射
                                def build_child_map(old_channels):
                                    ch_map = {}
                                    for ch in old_channels:
                                        ch_map[ch.channel_id] = ch
                                        if ch.children:
                                            ch_map.update(build_child_map(ch.children))
                                    return ch_map

                                old_child_map = build_child_map(old_children)

                                # 递归保留状态
                                def preserve_child_states(new_channels):
                                    for new_ch in new_channels:
                                        if new_ch.channel_id in old_child_map:
                                            old_ch = old_child_map[new_ch.channel_id]
                                            new_ch.streaming = old_ch.streaming
                                            new_ch.rtp_port = old_ch.rtp_port
                                            new_ch.allocated_rtp_port = old_ch.allocated_rtp_port  # 同步复制分配的端口
                                            new_ch.call_id = old_ch.call_id
                                            new_ch.from_tag = old_ch.from_tag  # 保留dialog信息
                                            new_ch.to_tag = old_ch.to_tag  # 保留dialog信息
                                            # ⚠️ 不保留inviting状态！inviting是临时状态
                                            new_ch.inviting = False
                                            new_ch.forward_state = old_ch.forward_state
                                        if new_ch.children:
                                            preserve_child_states(new_ch.children)

                                preserve_child_states(channels)

                                parent_ch.children = channels
                                self.logger.debug(f"[GSS]   ↳ 子目录 {parent_id} 包含 {len(channels)}个通道/目录")

                                # 子目录也需要自动发起INVITE推流
                                if self.auto_invite_after_rec_cate_log:
                                    for new_ch in channels:
                                        if new_ch.parental == 0 and new_ch.forward_state == 0:  # 只处理叶子通道
                                            if not new_ch.streaming and not new_ch.inviting:
                                                self.logger.debug(f"[GSS]   🚀 子目录自动发起INVITE推流: {new_ch.channel_id}")
                                                threading.Thread(
                                                    target=self.send_invite,
                                                    args=(device_id, new_ch.channel_id),
                                                    daemon=True
                                                ).start()
                            else:
                                self.logger.debug(f"[GSS]   ⚠️ 未找到父目录 {parent_id}")
                else:
                    # 更新设备的通道列表（如果是根目录查询）
                    # 注意：不主动清理 channel_id == device_id 的回退通道，避免推流会话被中断
                    with self.lock:
                        if device_id in self.devices:
                            # old_channel_map已在循环前构建，此处直接复用

                            # 递归为新通道保留状态
                            def preserve_states(new_channels):
                                for new_ch in new_channels:
                                    if new_ch.channel_id in old_channel_map:
                                        old_ch = old_channel_map[new_ch.channel_id]
                                        # 保留持久状态（streaming、rtp_port等）
                                        new_ch.streaming = old_ch.streaming
                                        new_ch.rtp_port = old_ch.rtp_port
                                        new_ch.allocated_rtp_port = old_ch.allocated_rtp_port  # 同步复制分配的端口
                                        new_ch.call_id = old_ch.call_id
                                        new_ch.from_tag = old_ch.from_tag  # 保留dialog信息
                                        new_ch.to_tag = old_ch.to_tag  # 保留dialog信息
                                        # ⚠️ 不保留inviting状态！inviting是临时状态，设备重新注册后应重置
                                        new_ch.inviting = False
                                        new_ch.forward_state = old_ch.forward_state
                                        new_ch.last_keepalive_time = old_ch.last_keepalive_time
                                        new_ch.last_register_time = old_ch.last_register_time
                                        new_ch.sn = old_ch.sn
                                    # 递归处理子目录
                                    if new_ch.children:
                                        preserve_states(new_ch.children)

                            preserve_states(channels)
                            self.devices[device_id].channels = channels
                            self.logger.debug(f"[GSS] ✓ 设备 {device_id} 通道列表已更新: {len(channels)}个通道/目录")

                            # 自动发起INVITE推流（在通道列表更新后执行）
                            if self.auto_invite_after_rec_cate_log:
                                for new_ch in channels:
                                    if new_ch.parental == 0 and new_ch.forward_state == 0:  # 只处理叶子通道
                                        if not new_ch.streaming and not new_ch.inviting:
                                            self.logger.debug(f"[GSS]   🚀 自动发起INVITE推流: {new_ch.channel_id}")
                                            threading.Thread(
                                                target=self.send_invite,
                                                args=(device_id, new_ch.channel_id),
                                                daemon=True
                                            ).start()

                return channels

        except ET.ParseError as e:
            self.logger.error(f"[GSS] 解析Catalog XML失败: {e}")
        except Exception as e:
            self.logger.error(f"[GSS] 处理Catalog响应异常: {e}")
        return []

    def _find_channel(self, channels, channel_id):
        """递归查找通道"""
        for ch in channels:
            if ch.channel_id == channel_id:
                return ch
            if ch.children:
                found = self._find_channel(ch.children, channel_id)
                if found:
                    return found
        return None

    def query_sub_catalog(self, device_id, catalog_id):
        """
        查询子目录（递归）

        Args:
            device_id: 设备ID
            catalog_id: 目录ID
        """
        time.sleep(1)  # 稍作延迟，等待父目录添加到列表

        # 在锁内保存设备信息，避免后续访问时设备已被注销
        with self.lock:
            if device_id not in self.devices:
                self.logger.debug(f"[GSS] ⚠️ 设备 {device_id} 已不存在，取消子目录查询")
                return
            device = self.devices[device_id]
            device_ip = device.ip
            device_port = device.port

        call_id = str(uuid.uuid4()).replace('-', '')
        from_tag = str(random.randint(100000000, 999999999))
        branch = f"z9hG4bK{random.randint(100000000, 999999999)}"
        sn = random.randint(1, 9999)

        body = (
            f"<?xml version=\"1.0\"?>\r\n"
            f"<Query>\r\n"
            f"<CmdType>Catalog</CmdType>\r\n"
            f"<SN>{sn}</SN>\r\n"
            f"<DeviceID>{catalog_id}</DeviceID>\r\n"
            f"</Query>\r\n"
        )

        msg = (
            f"MESSAGE sip:{catalog_id}@{device_ip}:{device_port} SIP/2.0\r\n"
            f"Via: SIP/2.0/{self._get_sip_transport()} {self.server_ip}:{self.server_port};rport;branch={branch}\r\n"
            f"From: <sip:{self.server_id}@{self.realm}>;tag={from_tag}\r\n"
            f"To: <sip:{catalog_id}@{self.realm}>\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: 1 MESSAGE\r\n"
            f"Max-Forwards: 70\r\n"
            f"Contact: <sip:{self.server_id}@{self.server_ip}:{self.server_port}>\r\n"
            f"Content-Type: Application/MANSCDP+xml\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"\r\n"
            f"{body}"
        )

        try:
            addr = (device_ip, device_port)
            self._send_sip_response(msg, addr)
            self.logger.debug(f"[GSS] 📂 已发送子目录查询: {catalog_id}")
        except Exception as e:
            self.logger.error(f"[GSS] 发送子目录查询失败: {e}")

    def _find_channel_by_id(self, channel_id):
        """
        根据channel_id查找通道（遍历所有设备）

        Args:
            channel_id: 通道ID

        Returns:
            tuple: (device, channel) 或 (None, None)
        """
        with self.lock:
            for device in self.devices.values():
                channel = self._find_channel(device.channels, channel_id)
                if channel:
                    return device, channel
        return None, None

    def _open_rtp_server(self, port, channel_id):
        """
        调用ZLMediaKit API开启RTP服务器

        Args:
            port: 期望的RTP端口
            channel_id: 通道ID（作为stream_id）

        Returns:
            int: 实际开启的RTP端口，失败返回0
        """
        try:
            # Bug 4修复：使用与send_invite一致的tcp_mode参数
            tcp_mode = 2 if self.rtp_transfer_mode == 1 else 0
            self.logger.debug(f"[GSS] 🔧 创建RTP服务器: 请求端口={port}, tcp_mode={tcp_mode}, stream_id={channel_id}")
            success, msg, actual_port = self.zlm.openRtpServer(
                port=port,
                tcp_mode=tcp_mode,
                stream_id=channel_id
            )
            if success:
                self.logger.debug(f"[GSS] ✅ RTP服务器创建成功: 实际端口={actual_port}, stream_id={channel_id}")
                return actual_port
            else:
                self.logger.error(f"[GSS] ❌ ZLM openRtpServer失败: {msg}")
                return 0
        except Exception as e:
            self.logger.error(f"[GSS] ❌ ZLM openRtpServer异常: {e}")
            return 0

    def _close_rtp_server(self, channel_id):
        """
        调用ZLMediaKit API关闭RTP服务器

        Args:
            channel_id: 通道ID（stream_id）

        Returns:
            bool: 是否成功
        """
        try:
            hit, msg = self.zlm.closeRtpServer(channel_id)
            
            if hit == 1:
                pass
            else:
                self.logger.debug(f"[GSS] ⚠️ ZLM closeRtpServer: {msg}")
            return hit == 1
        except Exception as e:
            self.logger.error(f"[GSS] ❌ ZLM closeRtpServer异常: {e}")
            return False

    def request_invite(self, client_id, channel_id, force=False):
        """
        发起INVITE推流请求（与C++版本逻辑一致）

        Args:
            client_id: 设备ID
            channel_id: 通道ID
            force: 是否强制重新INVITE（为True时，即使通道标记为推流中也会先发BYE再重新INVITE）

        Returns:
            tuple: (success: bool, msg: str)
        """
        self.logger.debug(f"[GSS] 🔍 开始INVITE请求: client_id={client_id}, channel_id={channel_id}, force={force}")
        try:
            # 查找设备和通道，并在锁内检查状态（避免竞态条件）
            with self.lock:
                device = self.devices.get(client_id)
                if not device:
                    self.logger.debug(f"[GSS] ❌ 设备未注册: {client_id}")
                    return False, "client not registered"

                channel = self._find_channel(device.channels, channel_id)
                if not channel:
                    # 通道不存在，创建临时通道对象（兼容不响应Catalog的摄像头）
                    self.logger.debug(f"[GSS] ⚠️ 通道 {channel_id} 不在内存中，创建临时通道")
                    channel = Channel(channel_id, channel_id, device=device, logger=self.logger)
                    channel.parental = 0  # 叶子通道
                    channel.forward_state = 0
                    device.channels.append(channel)
                    # 异步查询Catalog以更新通道信息
                    threading.Thread(target=self.query_catalog, args=(client_id,), daemon=True).start()

                # 保存旧会话信息（用于发送BYE终止旧会话）
                old_call_id = channel.call_id
                old_from_tag = channel.from_tag
                old_to_tag = channel.to_tag
                old_allocated_rtp_port = channel.allocated_rtp_port
                old_device_ip = device.ip
                old_device_port = device.port

                # 检查是否已经在推流或正在INVITE中（必须在锁内检查）
                if channel.streaming or channel.forward_state == 1:
                    if not force:
                        self.logger.debug(f"[GSS] ⚠️ 通道已在推流中: {channel_id}，直接返回成功")
                        return True, "already streaming"
                    else:
                        # force=True：流可能已断开但状态未更新，需要先BYE再重新INVITE
                        self.logger.debug(f"[GSS] 🔄 通道 {channel_id} 标记为推流中但force=True，先发BYE终止旧会话")

                # 如果存在旧会话，先发送BYE终止（防止486 Busy Here）
                need_send_bye = False
                if old_call_id:
                    need_send_bye = True
                    # 立即重置通道状态，防止重复INVITE
                    channel.streaming = False
                    channel.forward_state = 0
                    channel.call_id = ""
                    channel.from_tag = ""
                    channel.to_tag = ""
                    channel.rtp_port = 0
                    channel.allocated_rtp_port = 0

                # 如果inviting为True，可能是之前会话的残留状态，强制清除
                if channel.inviting:
                    self.logger.debug(f"[GSS] ⚠️ 通道 {channel_id} inviting标志为True，可能是残留状态，强制清除")
                    channel.inviting = False

                # 设置inviting标志
                channel.inviting = True

                # 保存设备信息
                device_ip = device.ip
                device_port = device.port

            # 在锁外发送BYE（避免持锁阻塞）
            if need_send_bye:
                self._send_bye_for_channel(old_device_ip, old_device_port, channel_id, old_call_id, old_from_tag, old_to_tag)
                # 关闭旧的ZLM RTP服务器
                self._close_rtp_server(channel_id)
                # 释放旧的RTP端口
                if old_allocated_rtp_port > 0:
                    self.rtp_port_mgr.release(old_allocated_rtp_port)
                time.sleep(0.5)  # 等待BYE被设备处理

            self.logger.debug(f"[GSS] 找到设备和通道: {device.device_id}, {channel.channel_id}")

            # 分配RTP端口
            rtp_port = self.rtp_port_mgr.allocate(channel_id)
            if rtp_port == 0:
                self.logger.error(f"[GSS] ❌ 无法分配RTP端口")
                # 清除inviting标志
                with self.lock:
                    device = self.devices.get(client_id)
                    if device:
                        channel = self._find_channel(device.channels, channel_id)
                        if channel:
                            channel.inviting = False
                return False, "no available RTP port"
            
            self.logger.debug(f"[GSS] 🔧 request_invite分配RTP端口: {rtp_port}, channel_id={channel_id}")

            # 调用ZLMediaKit openRtpServer创建RTP服务器（与send_invite保持一致）
            zlm_rtp_port = 0
            try:
                tcp_mode = 2 if self.rtp_transfer_mode == 1 else 0
                self.logger.debug(f"[GSS] 🔧 创建RTP服务器: 请求端口={rtp_port}, tcp_mode={tcp_mode}, stream_id={channel_id}")
                success, msg, zlm_rtp_port = self.zlm.openRtpServer(
                    port=rtp_port,
                    tcp_mode=tcp_mode,
                    stream_id=channel_id
                )
                if not success:
                    # 如果stream已存在，直接使用现有RTP服务器
                    if "already exists" in msg:
                        self.logger.debug(f"[GSS] ⚠️ RTP服务器已存在，使用现有服务器: {channel_id}")
                        # stream已存在，说明之前已经开启过，使用分配的端口
                        # 注意：这里使用rtp_port是因为openRtpServer失败时zlm_rtp_port可能为0
                        zlm_rtp_port = rtp_port
                    else:
                        self.logger.error(f"[GSS] ❌ ZLM openRtpServer失败: {msg}")
                        self.rtp_port_mgr.release(rtp_port)
                        with self.lock:
                            device = self.devices.get(client_id)
                            if device:
                                channel = self._find_channel(device.channels, channel_id)
                                if channel:
                                    channel.inviting = False
                        return False, f"failed to open RTP server on ZLM: {msg}"
            except Exception as e:
                self.logger.error(f"[GSS] ❌ ZLM openRtpServer异常: {e}")
                self.rtp_port_mgr.release(rtp_port)
                with self.lock:
                    device = self.devices.get(client_id)
                    if device:
                        channel = self._find_channel(device.channels, channel_id)
                        if channel:
                            channel.inviting = False
                return False, f"failed to open RTP server on ZLM: {str(e)}"
            
            self.logger.debug(f"[GSS] ✅ RTP服务器创建成功: 请求端口={rtp_port}, ZLM实际端口={zlm_rtp_port}, stream_id={channel_id}")

            # 构建SDP消息体（与C++版本SipServer.cpp保持一致）
            include_audio = (self.rtp_transfer_audio_type == 1)
            sdp_body = self._build_sdp(
                media_type="video",
                port=zlm_rtp_port,
                payload_types=[96, 98, 97],  # PS/H264/MPEG4，与C++版本一致
                attrs_map={96: "PS/90000", 98: "H264/90000", 97: "MPEG4/90000"},
                include_audio=include_audio
            )

            # 构建INVITE请求
            call_id = str(uuid.uuid4()).replace('-', '')
            from_tag = str(random.randint(100000000, 999999999))
            branch = f"z9hG4bK{random.randint(100000000, 999999999)}"

            invite_msg = (
                f"INVITE sip:{channel_id}@{device_ip}:{device_port} SIP/2.0\r\n"
                f"Via: SIP/2.0/{self._get_sip_transport()} {self.server_ip}:{self.server_port};rport;branch={branch}\r\n"
                f"From: <sip:{self.server_id}@{self.realm}>;tag={from_tag}\r\n"
                f"To: <sip:{channel_id}@{self.realm}>\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: 1 INVITE\r\n"
                f"Max-Forwards: 70\r\n"
                f"Contact: <sip:{self.server_id}@{self.server_ip}:{self.server_port}>\r\n"
                f"Content-Type: application/sdp\r\n"
                f"Content-Length: {len(sdp_body)}\r\n"
                f"\r\n"
                f"{sdp_body}"
            )

            # 发送INVITE
            addr = (device_ip, device_port)
            self._send_sip_response(invite_msg, addr)

            # 注册pending invite（保存旧会话信息用于486恢复）
            with self.pending_invites_lock:
                self.pending_invites[channel_id] = {
                    'rtp_port': rtp_port,
                    'call_id': call_id,
                    'device_id': client_id,
                    'old_call_id': old_call_id if old_call_id else '',
                    'old_from_tag': old_from_tag if old_from_tag else '',
                    'old_to_tag': old_to_tag if old_to_tag else '',
                }

            with self.lock:
                device = self.devices.get(client_id)
                if device:
                    channel = self._find_channel(device.channels, channel_id)
                    if channel:
                        channel.rtp_port = zlm_rtp_port  # ZLM实际返回的端口
                        channel.allocated_rtp_port = rtp_port  # 保存最初分配的端口（用于释放）
                        channel.call_id = call_id
                        channel.from_tag = from_tag  # 保存from_tag用于后续BYE构造
                        # Bug 17修复：不立即设置forward_state和streaming，等待设备200 OK响应
                        # forward_state和streaming状态在收到200 OK响应时由_handle_invite_response更新
                        channel.inviting = False  # 清除inviting标志
                        # 清理pending_invites（INVITE已成功发送）
                        with self.pending_invites_lock:
                            self.pending_invites.pop(channel_id, None)
                        self.stats['total_invites'] += 1
                    else:
                        # 通道已不存在，清理已分配的资源！
                        self.logger.debug(f"[GSS] ⚠️ 通道 {channel_id} 在INVITE成功后已不存在，清理资源")
                        self.rtp_port_mgr.release(rtp_port)
                        self._close_rtp_server(channel_id)
                        return False, "channel not found after INVITE sent"
                else:
                    # Bug 15修复：设备已不存在（极端情况），清理资源
                    self.logger.debug(f"[GSS] ⚠️ 设备 {client_id} 在INVITE成功后已不存在，清理资源")
                    self.rtp_port_mgr.release(rtp_port)
                    self._close_rtp_server(channel_id)
                    return False, "device not found after INVITE sent"

            return True, "success"

        except Exception as e:
            self.logger.error(f"[GSS] ❌ INVITE请求异常: {e}")
            self.logger.error(f"[GSS] 异常堆栈: {traceback.format_exc()}")
            # 异常时释放资源（必须清理所有可能已分配的资源）
            try:
                # 释放已分配的RTP端口（使用局部变量rtp_port，而不是channel.rtp_port）
                if 'rtp_port' in locals() and rtp_port > 0:
                    self.rtp_port_mgr.release(rtp_port)
                # 关闭ZLM RTP服务器（无论端口多少，通过channel_id关闭）
                self._close_rtp_server(channel_id)
                # 重置通道状态
                with self.lock:
                    device = self.devices.get(client_id)
                    if device:
                        channel = self._find_channel(device.channels, channel_id)
                        if channel:
                            channel.inviting = False
                            channel.rtp_port = 0
                            channel.allocated_rtp_port = 0
                            channel.call_id = ""
                            channel.streaming = False
                            channel.forward_state = 0
            except Exception as cleanup_e:
                self.logger.error(f"[GSS] ❌ 清理INVITE资源异常: {cleanup_e}")
            return False, f"invite error: {str(e)}"

    def request_bye(self, client_id, channel_id):
        """
        发送BYE停止推流

        Args:
            client_id: 设备ID
            channel_id: 通道ID

        Returns:
            tuple: (success: bool, msg: str)
        """
        try:
            # 查找设备和通道，并在锁内检查状态（避免竞态条件）
            with self.lock:
                device = self.devices.get(client_id)
                if not device:
                    return False, "client not registered"

                channel = self._find_channel(device.channels, channel_id)
                if not channel:
                    # 通道不存在，但仍需清理ZLM资源和端口（兼容临时通道或已清除的通道）
                    self.logger.debug(f"[GSS] ⚠️ 通道 {channel_id} 不在内存中，尝试清理资源")
                    self._close_rtp_server(channel_id)
                    # 从 pending_invites 中清理
                    with self.pending_invites_lock:
                        pending = self.pending_invites.pop(channel_id, None)
                        if pending:
                            self.rtp_port_mgr.release(pending['rtp_port'])
                    return True, "resource cleaned"

                # 检查是否在推流（必须在锁内检查）
                if not channel.streaming:
                    self.logger.debug(f"[GSS] ⚠️ 通道 {channel_id} 未在推流，但仍需清理资源")
                    # 即使未推流，也要清理可能的残留资源
                    self._close_rtp_server(channel_id)
                    with self.pending_invites_lock:
                        pending = self.pending_invites.pop(channel_id, None)
                        if pending:
                            self.rtp_port_mgr.release(pending['rtp_port'])
                    # 重置状态
                    channel.rtp_port = 0
                    channel.allocated_rtp_port = 0
                    channel.call_id = ""
                    channel.forward_state = 0
                    channel.inviting = False
                    return True, "resource cleaned"

                # 保存需要的信息
                call_id = channel.call_id
                from_tag = channel.from_tag  # 使用存储的from_tag（INVITE时保存）
                to_tag = channel.to_tag  # 使用存储的to_tag（200 OK时保存）
                device_ip = device.ip
                device_port = device.port
                allocated_rtp_port = channel.allocated_rtp_port  # 使用最初分配的端口

                # 立即更新状态，防止重复BYE
                channel.rtp_port = 0
                channel.allocated_rtp_port = 0
                channel.call_id = ""
                channel.from_tag = ""  # 清除dialog信息
                channel.to_tag = ""
                channel.streaming = False
                channel.forward_state = 0
                channel.inviting = False  # Bug 10修复：重置inviting状态

            # 使用_send_bye_for_channel发送BYE（使用正确的dialog信息）
            self._send_bye_for_channel(device_ip, device_port, channel_id, call_id, from_tag, to_tag)

            # 关闭ZLM RTP服务器（与C++版本一致）
            self._close_rtp_server(channel_id)

            # 释放RTP端口（使用最初分配的端口，而不是ZLM返回的端口）
            if allocated_rtp_port > 0:
                self.rtp_port_mgr.release(allocated_rtp_port)

            with self.lock:
                self.stats['total_byes'] += 1

            return True, "success"

        except Exception as e:
            self.logger.error(f"[GSS] BYE请求异常: {e}")
            # 异常时仍需确保资源释放（状态已在锁内更新，只需清理ZLM和端口）
            try:
                # 关闭ZLM RTP服务器
                self._close_rtp_server(channel_id)
                # 释放RTP端口（使用保存的allocated_rtp_port变量）
                if 'allocated_rtp_port' in locals() and allocated_rtp_port > 0:
                    self.rtp_port_mgr.release(allocated_rtp_port)
            except Exception as cleanup_e:
                self.logger.error(f"[GSS] ❌ 清理BYE资源异常: {cleanup_e}")
            return False, f"bye error: {str(e)}"

    def request_ptz(self, client_id, channel_id, ptz_type, val):
        """
        发送PTZ云台控制指令

        Args:
            client_id: 设备ID
            channel_id: 通道ID
            ptz_type: PTZ类型（0-停止, 1-右转, 3-上转, 5-左转, 7-下转, 9-变焦, 10-光圈, 11-聚焦）
            val: 速度/值

        Returns:
            tuple: (success: bool, msg: str)
        """
        try:
            # 查找设备和通道，并在锁内更新SN（避免竞态条件）
            with self.lock:
                device = self.devices.get(client_id)
                if not device:
                    return False, "client not registered"

                channel = self._find_channel(device.channels, channel_id)
                if not channel:
                    return False, "channel not found"

                # 在锁内更新SN
                channel.sn += 1
                sn = channel.sn
                
                # 保存设备信息
                device_ip = device.ip
                device_port = device.port

            # 构建PTZ指令（GB28181标准Hex编码）
            ptz_cmd = self._build_ptz_command(ptz_type, val)

            # 构建XML消息体
            body = (
                f"<?xml version=\"1.0\"?>\r\n"
                f"<ControlInfo>\r\n"
                f"<CmdType>DeviceControl</CmdType>\r\n"
                f"<SN>{sn}</SN>\r\n"
                f"<DeviceID>{channel_id}</DeviceID>\r\n"
                f"<PTZCmd>{ptz_cmd}</PTZCmd>\r\n"
                f"</ControlInfo>\r\n"
            )

            # 构建MESSAGE请求
            call_id = str(uuid.uuid4()).replace('-', '')
            from_tag = str(random.randint(100000000, 999999999))
            branch = f"z9hG4bK{random.randint(100000000, 999999999)}"

            msg = (
                f"MESSAGE sip:{channel_id}@{device_ip}:{device_port} SIP/2.0\r\n"
                f"Via: SIP/2.0/{self._get_sip_transport()} {self.server_ip}:{self.server_port};rport;branch={branch}\r\n"
                f"From: <sip:{self.server_id}@{self.realm}>;tag={from_tag}\r\n"
                f"To: <sip:{channel_id}@{self.realm}>\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: 1 MESSAGE\r\n"
                f"Max-Forwards: 70\r\n"
                f"Contact: <sip:{self.server_id}@{self.server_ip}:{self.server_port}>\r\n"
                f"Content-Type: Application/MANSCDP+xml\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n"
                f"{body}"
            )

            # 发送PTZ指令
            addr = (device_ip, device_port)
            self._send_sip_response(msg, addr)

            ptz_names = {0: '停止', 1: '右转', 3: '上转', 5: '左转', 7: '下转', 9: '变焦', 10: '光圈', 11: '聚焦'}
            ptz_name = ptz_names.get(ptz_type, f'类型{ptz_type}')
            self.logger.debug(f"[GSS] 🎮 已发送PTZ指令: {channel_id} - {ptz_name} (val={val})")

            return True, "success"

        except Exception as e:
            self.logger.error(f"[GSS] PTZ请求异常: {e}")
            return False, f"ptz error: {str(e)}"

    def _build_ptz_command(self, ptz_type, val):
        """
        构建PTZ控制指令（GB28181标准Hex格式）

        Args:
            ptz_type: PTZ类型
            val: 速度/值 (0-255)

        Returns:
            str: Hex编码的PTZ指令
        """
        # GB28181 PTZ指令格式：A5 0F [命令字节] [参数] [校验]
        # 简化版：使用标准位置控制

        speed = min(max(val, 0), 255)  # 限制0-255

        # 命令字节映射
        cmd_map = {
            0: 0x00,   # 停止
            1: 0x02,   # 右转
            2: 0x0A,   # 右上
            3: 0x08,   # 上转
            4: 0x09,   # 左上
            5: 0x04,   # 左转
            6: 0x0C,   # 左下
            7: 0x10,   # 下转
            8: 0x06,   # 右下
            9: 0x20,   # 变焦
            10: 0x40,  # 光圈
            11: 0x10   # 聚焦
        }

        cmd_byte = cmd_map.get(ptz_type, 0x00)

        # 构建指令：A5 0F 01 [cmd] [speed1] [speed2] [00] [校验]
        ptz_bytes = bytes([0xA5, 0x0F, 0x01, cmd_byte, speed, speed, 0x00])

        # 计算校验和
        checksum = sum(ptz_bytes) & 0xFF
        ptz_bytes += bytes([checksum])

        # 转换为Hex字符串
        return ptz_bytes.hex().upper()

