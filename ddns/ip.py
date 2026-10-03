"""公网 IP 探测，支持 IPv4(A) 与 IPv6(AAAA)，以及绑定指定出口。

策略：先本地 socket 探测出口地址（快、无外部依赖），再用外部 API 从公网侧
回看校验；两者不一致时以公网结果为准，公网不可用时降级本地。

多出口：可通过 ``source`` 指定源地址或网卡名，强制从该出口发包，用于一台
机器有多个上行（多网卡/多拨）时把不同出口的 IP 写到不同域名。
"""
import ipaddress
import logging
import socket

import requests
from requests.adapters import HTTPAdapter

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

# 绑定源地址的 session 缓存，按 (record_type, 源地址) 复用
_sourced_sessions = {}


class SourceAddressAdapter(HTTPAdapter):
    """让 requests 从指定源地址发包。

    requests 的 HTTPAdapter 不接受 source_address 关键字，需子类化并在
    init_poolmanager 里透传给底层连接池。
    """

    def __init__(self, source_address, *args, **kwargs):
        self._source_address = source_address
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["source_address"] = self._source_address
        super().init_poolmanager(connections, maxsize, block, **pool_kwargs)


def resolve_source(source, record_type):
    """把配置里的 source 解析为源 IP。

    source 可以是：
      - 空 / None：返回 None，走默认路由；
      - 合法 IP：直接返回（family 需与 record_type 匹配）；
      - 其它：当作网卡名，取该网卡上同 family 的非链路本地地址。
    解析失败抛 ValueError。
    """
    if not source:
        return None
    if record_type not in _FAMILY:
        raise ValueError(f"不支持的记录类型: {record_type!r}")

    # 先按 IP 处理
    try:
        addr = _ADDR_CLASS[record_type](source)
    except (ipaddress.AddressValueError, ValueError):
        pass
    else:
        if addr.is_link_local or addr.is_unspecified:
            raise ValueError(f"source 不能是链路本地或未指定地址: {source!r}")
        return str(addr)

    # 当作网卡名解析
    return _resolve_interface_address(source, record_type)


def _resolve_interface_address(name, record_type):
    try:
        import psutil
    except ImportError as e:  # pragma: no cover
        raise ValueError(
            f"按网卡名指定出口需要 psutil，请 pip install psutil，"
            f"或直接把 source 写成源 IP。"
        ) from e

    family = _FAMILY[record_type]
    addrs = psutil.net_if_addrs()
    if name not in addrs:
        raise ValueError(
            f"未找到网卡 {name!r}，可用网卡: {', '.join(addrs) or '(无)'}"
        )

    for snic in addrs[name]:
        if snic.family != family:
            continue
        addr = snic.address.split("%")[0]  # 去掉 IPv6 的 zone id
        try:
            parsed = _ADDR_CLASS[record_type](addr)
        except (ipaddress.AddressValueError, ValueError):
            continue
        if parsed.is_link_local or parsed.is_unspecified:
            continue
        return str(parsed)

    raise ValueError(f"网卡 {name!r} 上没有可用的 {record_type} 地址")


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


def get_local_ip(record_type, source=None):
    """本地探测：让内核选出到公网的实际出口源地址。

    source 非空时先 bind 到该源地址，强制从指定出口发包。
    """
    if record_type not in _FAMILY:
        raise ValueError(f"不支持的记录类型: {record_type!r}")
    src = resolve_source(source, record_type)
    s = None
    try:
        s = socket.socket(_FAMILY[record_type], socket.SOCK_DGRAM)
        if src:
            s.bind((src, 0))
        s.connect(PROBE_TARGETS[record_type])
        ip = s.getsockname()[0]
        if is_valid_public_ip(ip, record_type):
            return ip
    except Exception as e:  # noqa: BLE001 - 探测失败应静默降级
        log.debug("本地探测 %s（source=%s）失败: %s", record_type, src, e)
    finally:
        if s is not None:
            s.close()
    return None


def _session_for_source(source):
    """取（或建）绑定到指定源地址的 session。"""
    if source not in _sourced_sessions:
        sess = requests.Session()
        sess.trust_env = False
        adapter = SourceAddressAdapter((source, 0))
        sess.mount("http://", adapter)
        sess.mount("https://", adapter)
        _sourced_sessions[source] = sess
    return _sourced_sessions[source]


def get_public_ip(record_type, source=None, apis=None, http=None):
    """外部 API 探测：从公网侧回看真实可路由的 IP。

    source 非空且未显式注入 http 时，使用绑定该源地址的 session。
    """
    apis = apis if apis is not None else IP_APIS[record_type]
    if http is None:
        src = resolve_source(source, record_type)
        http = _session_for_source(src) if src else session
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


def get_current_ip(record_type, source=None):
    """混合策略：本地优先，公网校验，不一致以公网为准，公网挂则降级本地。"""
    src = resolve_source(source, record_type)
    local_ip = get_local_ip(record_type, source)
    public_ip = get_public_ip(record_type, source)

    if local_ip and public_ip:
        if local_ip == public_ip:
            return local_ip
        log.info("本地(%s)与公网(%s)不一致（source=%s），采用公网地址",
                 local_ip, public_ip, src)
        return public_ip
    if public_ip:
        return public_ip
    if local_ip:
        log.warning("外部API不可用，降级使用本地地址: %s", local_ip)
        return local_ip
    return None
