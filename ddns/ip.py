"""公网 IP 探测，支持 IPv4(A) 与 IPv6(AAAA)。

策略与原脚本一致：先本地 socket 探测出口地址（快、无外部依赖），再用外部
API 从公网侧回看校验；两者不一致时以公网结果为准，公网不可用时降级本地。
"""
import ipaddress
import logging
import socket

import requests

log = logging.getLogger("ddns.ip")

# 各记录类型依次尝试的公网 IP 查询接口
IP_APIS = {
    "A": [
        "https://api.ipify.org",
        "https://ipv4.icanhazip.com",
        "https://v4.ident.me",
        "https://api-ipv4.ip.sb/ip",
    ],
    "AAAA": [
        "https://api-ipv6.ip.sb/ip",
        "https://v6.ident.me",
        "https://ipv6.icanhazip.com",
    ],
}

# 本地探测目标，仅用于让内核选择出口，不实际发包
PROBE_TARGETS = {
    "A": ("223.5.5.5", 80),  # 阿里公共 DNS IPv4
    "AAAA": ("2400:3200::1", 80),  # 阿里公共 DNS IPv6
}

_ADDR_CLASS = {"A": ipaddress.IPv4Address, "AAAA": ipaddress.IPv6Address}
_FAMILY = {"A": socket.AF_INET, "AAAA": socket.AF_INET6}

# 忽略系统代理：本机 HTTP 代理通常不支持 IPv6，会导致 TLS 中断
session = requests.Session()
session.trust_env = False


def is_valid_public_ip(ip, record_type):
    """校验是否为合法的、可路由的公网 IP。

    用 ``is_global`` 判定全局可达：它会排除私有段、回环、链路本地、
    保留/文档段（如 203.0.113.0/24）、CGNAT(100.64/10) 与 ULA(fc00::/7) 等。
    """
    try:
        addr = _ADDR_CLASS[record_type](ip.strip())
    except (ipaddress.AddressValueError, ValueError):
        return False
    if not getattr(addr, "is_global", False):
        return False
    if addr.is_multicast:
        return False
    return True


def get_local_ip(record_type):
    """本地探测：让内核选出到公网的实际出口源地址。"""
    if record_type not in _FAMILY:
        raise ValueError(f"不支持的记录类型: {record_type!r}")
    s = None
    try:
        s = socket.socket(_FAMILY[record_type], socket.SOCK_DGRAM)
        s.connect(PROBE_TARGETS[record_type])
        ip = s.getsockname()[0]
        if is_valid_public_ip(ip, record_type):
            return ip
    except Exception as e:  # noqa: BLE001 - 探测失败应静默降级
        log.debug("本地探测 %s 失败: %s", record_type, e)
    finally:
        if s is not None:
            s.close()
    return None


def get_public_ip(record_type, apis=None, http=None):
    """外部 API 探测：从公网侧回看真实可路由的 IP。"""
    apis = apis if apis is not None else IP_APIS[record_type]
    http = http if http is not None else session
    for url in apis:
        try:
            resp = http.get(url, timeout=10)
            resp.raise_for_status()
            text = resp.text.strip()
            ip = text.splitlines()[0].strip() if text else ""
            if is_valid_public_ip(ip, record_type):
                return ip
            log.warning("外部API返回非法 %s (%s): %r", record_type, url, ip)
        except Exception as e:  # noqa: BLE001 - 逐个接口容错
            log.warning("外部API获取 %s 失败 (%s): %s", record_type, url, e)
    return None


def get_current_ip(record_type):
    """混合策略：本地优先，公网校验，不一致以公网为准，公网挂则降级本地。"""
    local_ip = get_local_ip(record_type)
    public_ip = get_public_ip(record_type)

    if local_ip and public_ip:
        if local_ip == public_ip:
            return local_ip
        log.info("本地(%s)与公网(%s)不一致，采用公网地址", local_ip, public_ip)
        return public_ip
    if public_ip:
        return public_ip
    if local_ip:
        log.warning("外部API不可用，降级使用本地地址: %s", local_ip)
        return local_ip
    return None
