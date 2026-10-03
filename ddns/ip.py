"""公网 IP 探测，支持 IPv4(A) 与 IPv6(AAAA)，以及绑定指定出口。

策略：先本地 socket 探测出口地址（快、无外部依赖），再用外部 API 从公网侧
回看校验；两者不一致时以公网结果为准，公网不可用时降级本地。

多出口：可通过 ``source`` 指定源地址或网卡名，强制从该出口发包，用于一台
机器有多个上行（多网卡/多拨）时把不同出口的 IP 写到不同域名。
"""
import ipaddress
import logging
import re
import socket
import subprocess
import sys

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


# 判断"同一网段"用的前缀长度：IPv6 用 /64，IPv4 用 /24
_PREFIX_LEN = {"A": 24, "AAAA": 64}


def is_same_prefix(a, b, record_type):
    """判断两个地址是否属于同一网段（A: /24，AAAA: /64）。非法地址返回 False。"""
    if record_type not in _PREFIX_LEN:
        return False
    try:
        addr_a = _ADDR_CLASS[record_type](str(a).strip())
        addr_b = _ADDR_CLASS[record_type](str(b).strip())
    except (ipaddress.AddressValueError, ValueError):
        return False
    net = ipaddress.ip_network(
        f"{addr_a}/{_PREFIX_LEN[record_type]}", strict=False
    )
    return addr_b in net


def has_local_address(ip, record_type):
    """判断该地址当前是否存在于本机的任一网卡上（含临时/弃用地址）。

    用于 stable 策略的安全判定：只有"已发布地址仍在本机"时才跳过更新，
    地址过期消失后会返回 False，从而触发更新，避免 DNS 长期指向失效地址。
    psutil 不可用时保守返回 False（宁可更新）。
    """
    if record_type not in _FAMILY:
        return False
    try:
        import psutil
    except ImportError:  # pragma: no cover
        return False
    family = _FAMILY[record_type]
    target = str(ip).strip().split("%")[0]
    try:
        addrs = psutil.net_if_addrs()
    except Exception:  # noqa: BLE001
        return False
    for snics in addrs.values():
        for snic in snics:
            if snic.family != family:
                continue
            if snic.address.split("%")[0] == target:
                return True
    return False


# ===== 稳定地址识别（隐私扩展下优先使用不轮换的地址）=====

def _stable_ipv6_macos():
    """macOS：解析 ifconfig，返回稳定全局 IPv6 列表（排除 temporary）。

    带回 {网卡名: [地址]} 便于旁路判断。解析失败返回 []。
    """
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("ifconfig 执行失败: %s", e)
        return []
    result, cur = {}, None
    for line in out.splitlines():
        if line and not line[0].isspace() and ":" in line:
            cur = line.split(":")[0]
        elif "inet6" in line:
            if "temporary" in line:
                continue
            m = re.search(r"inet6\s+([0-9a-fA-F:]+)", line)
            if not m:
                continue
            try:
                addr = ipaddress.IPv6Address(m.group(1).split("%")[0])
            except ValueError:
                continue
            if addr.is_global and not addr.is_multicast:
                result.setdefault(cur, []).append(str(addr))
    return result


def _stable_ipv6_linux():
    """Linux：读 /proc/net/if_inet6，排除 IFA_F_TEMPORARY(0x01)。

    返回 {网卡名: [地址]}。文件不存在或解析失败返回 {}。
    """
    result = {}
    try:
        with open("/proc/net/if_inet6", "r") as f:
            lines = f.readlines()
    except OSError as e:
        log.debug("读取 /proc/net/if_inet6 失败: %s", e)
        return result
    for line in lines:
        parts = line.split()
        if len(parts) < 6:
            continue
        hexaddr, _idx, plen, scope, flags, ifname = parts[:6]
        try:
            if int(flags, 16) & 0x01:  # IFA_F_TEMPORARY
                continue
        except ValueError:
            continue
        try:
            addr = ipaddress.IPv6Address(int(hexaddr, 16))
        except (ValueError, OverflowError):
            continue
        if addr.is_global and not addr.is_multicast:
            result.setdefault(ifname, []).append(str(addr))
    return result


def stable_ipv6_addresses():
    """返回 {网卡名: [稳定全局 IPv6 地址]}。

    仅支持 Linux 与 macOS（可从系统信息判断稳定/临时）；其他平台返回 {}。
    """
    if sys.platform == "darwin":
        return _stable_ipv6_macos()
    if sys.platform.startswith("linux"):
        return _stable_ipv6_linux()
    return {}


def prefer_stable_ipv6(ip):
    """给定一个全局 IPv6，若存在同 /64 的稳定地址则返回它，否则返回原值。

    DNS 记录变更存在传播延迟，优先使用不随隐私扩展轮换的稳定地址可减少更新。
    找不到稳定地址时返回原 ip（保持原行为）。
    """
    if not ip:
        return ip
    try:
        addr = ipaddress.IPv6Address(str(ip).split("%")[0])
    except ValueError:
        return ip
    if not addr.is_global:
        return ip
    net = ipaddress.ip_network(f"{addr}/64", strict=False)
    for addrs in stable_ipv6_addresses().values():
        for cand in addrs:
            try:
                if ipaddress.IPv6Address(cand) in net:
                    if cand != str(ip):
                        log.info("发现同网段稳定地址 %s，优先使用（原 %s）", cand, ip)
                    return cand
            except ValueError:
                continue
    return ip



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


def _is_explicit_ip(source, record_type):
    """判断 source 是否为显式 IP（而非网卡名或空）。"""
    if not source or record_type not in _FAMILY:
        return False
    try:
        _ADDR_CLASS[record_type](str(source))
    except (ipaddress.AddressValueError, ValueError):
        return False
    return True


def get_current_ip(record_type, source=None):
    """混合策略：本地优先，公网校验，不一致以公网为准，公网挂则降级本地。

    对 IPv6 会优先使用同网段的稳定地址（若系统可识别），以减少隐私扩展下
    临时地址轮换导致的 DNS 更新；显式指定了源 IP 时尊重用户选择，不替换。
    """
    src = resolve_source(source, record_type)
    local_ip = get_local_ip(record_type, source)
    public_ip = get_public_ip(record_type, source)

    if local_ip and public_ip:
        if local_ip == public_ip:
            result = local_ip
        else:
            log.info("本地(%s)与公网(%s)不一致（source=%s），采用公网地址",
                     local_ip, public_ip, src)
            result = public_ip
    elif public_ip:
        result = public_ip
    elif local_ip:
        log.warning("外部API不可用，降级使用本地地址: %s", local_ip)
        result = local_ip
    else:
        return None

    # IPv6：优先稳定地址；用户显式指定源 IP 时不替换
    if record_type == "AAAA" and not _is_explicit_ip(source, record_type):
        result = prefer_stable_ipv6(result)
    return result
