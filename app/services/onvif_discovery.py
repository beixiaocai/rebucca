# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
"""ONVIF WS-Discovery 设备发现"""
import logging
import socket
import struct
import uuid
from xml.etree import ElementTree as ET

logger = logging.getLogger("services.onvif")

WS_DISCOVERY_ADDR = "239.255.255.250"
WS_DISCOVERY_PORT = 3702

PROBE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{msg_id}</w:MessageID>
    <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action a:mustUnderstand="true" xmlns:a="http://www.w3.org/2003/05/soap-envelope">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </e:Body>
</e:Envelope>"""


def _parse_probe_match(data):
    try:
        root = ET.fromstring(data)
    except Exception:
        return None
    ns = {
        "s": "http://www.w3.org/2003/05/soap-envelope",
        "wsa": "http://schemas.xmlsoap.org/ws/2004/08/addressing",
        "d": "http://schemas.xmlsoap.org/ws/2005/04/discovery",
    }
    scopes = ""
    xaddrs = ""
    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "Scopes" and el.text:
            scopes = el.text.strip()
        if tag == "XAddrs" and el.text:
            xaddrs = el.text.strip()
    if not xaddrs:
        return None
    url = xaddrs.split()[0]
    name = scopes.split("/")[-1] if scopes else url
    return {"name": name, "xaddr": url, "scopes": scopes}


def discover_onvif(timeout=3.0):
    """UDP 组播 WS-Discovery，返回 [{name, xaddr, scopes, ip}]"""
    results = []
    seen = set()
    msg = PROBE_TEMPLATE.format(msg_id=uuid.uuid4()).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)
        ttl = struct.pack("b", 2)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        sock.sendto(msg, (WS_DISCOVERY_ADDR, WS_DISCOVERY_PORT))
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            ip = addr[0]
            if ip in seen:
                continue
            item = _parse_probe_match(data)
            if item:
                item["ip"] = ip
                seen.add(ip)
                results.append(item)
    except Exception as e:
        logger.warning("ONVIF discovery 失败: %s", e)
    finally:
        sock.close()
    return results


def get_rtsp_url_from_onvif(xaddr, username="", password=""):
    """尝试通过 ONVIF 获取 RTSP 主码流地址"""
    try:
        from onvif import ONVIFCamera
        from urllib.parse import urlparse
        p = urlparse(xaddr if "://" in xaddr else "http://" + xaddr)
        host = p.hostname
        port = p.port or 80
        cam = ONVIFCamera(host, port, username or "admin", password or "admin")
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            return ""
        token = profiles[0].token
        uri = media.GetStreamUri({
            "StreamSetup": {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}},
            "ProfileToken": token,
        })
        return uri.Uri if uri else ""
    except Exception as e:
        logger.debug("ONVIF get stream uri: %s", e)
        return ""
