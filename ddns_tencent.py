import requests
import time
import os
import ipaddress
import socket
from pathlib import Path
from dotenv import load_dotenv
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.dnspod.v20210323 import dnspod_client, models

# ===== 配置区 =====
# 读取与本脚本同目录下的 .env
load_dotenv(Path(__file__).resolve().parent / ".env")

SECRET_ID = os.getenv("TENCENT_SECRET_ID")
SECRET_KEY = os.getenv("TENCENT_SECRET_KEY")
DOMAIN = os.getenv("DDNS_DOMAIN", "example.com")  # 你的主域名
SUB_DOMAIN = os.getenv("DDNS_SUB_DOMAIN", "home")  # 子域名前缀，如 home.example.com 就填 home
CHECK_INTERVAL = int(os.getenv("DDNS_CHECK_INTERVAL", "60"))  # 检测间隔（秒）
# 状态文件固定放在脚本同目录，避免受启动时 cwd 影响
STATE_FILE = Path(__file__).resolve().parent / "last_ipv6.txt"

if not SECRET_ID or not SECRET_KEY:
    raise RuntimeError(
        "未配置 TENCENT_SECRET_ID / TENCENT_SECRET_KEY，"
        "请复制 .env.example 为 .env 并填写。"
    )


# 依次尝试的 IPv6 查询接口（api6.ipify.org 在国内不可达）
IPV6_APIS = [
    "https://api-ipv6.ip.sb/ip",
    "https://v6.ident.me",
    "https://ipv6.icanhazip.com",
]

# 忽略系统代理：本机系统代理(如 127.0.0.1:7890)不支持 IPv6，会导致 TLS 中断
session = requests.Session()
session.trust_env = False

# 本地探测时用于让内核选出口的探测目标（只用于选路，不实际发包）
PROBE_TARGET = ("2400:3200::1", 80)  # 阿里公共DNS IPv6


def is_valid_public_ipv6(ip):
    """校验是否为合法的、可路由的公网 IPv6 地址"""
    try:
        addr = ipaddress.IPv6Address(ip.strip())
    except (ipaddress.AddressValueError, ValueError):
        return False
    if addr.is_loopback or addr.is_link_local or addr.is_unspecified:
        return False
    # 排除 ULA 内网地址 (fc00::/7)
    if addr.is_private:
        return False
    return True


def get_local_ipv6():
    """本地探测：让内核选出到公网的实际出口源地址（快、无外部依赖）

    注意：若处于 IPv6 NAT 环境，这里可能拿到内网地址，
    因此结果还需经 get_public_ipv6() 用外部 API 校验。
    """
    s = None
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        s.connect(PROBE_TARGET)
        ip = s.getsockname()[0]
        if is_valid_public_ipv6(ip):
            return ip
    except Exception as e:
        print(f"本地探测IPv6失败: {e}")
    finally:
        if s is not None:
            s.close()
    return None


def get_public_ipv6():
    """外部API探测：从公网侧回看，返回真实可路由的IPv6"""
    for url in IPV6_APIS:
        try:
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            # 只取首个非空行，避免多行/带附加文本的响应
            ip = resp.text.strip().splitlines()[0].strip() if resp.text.strip() else ""
            if is_valid_public_ipv6(ip):
                return ip
            print(f"外部API返回非法IPv6 ({url}): {ip!r}")
        except Exception as e:
            print(f"外部API获取IPv6失败 ({url}): {e}")
    return None


def get_current_ipv6():
    """混合策略：优先本地探测（快），再用外部API校验；本地失败则回退外部API"""
    local_ip = get_local_ipv6()
    public_ip = get_public_ipv6()

    if local_ip and public_ip:
        if local_ip == public_ip:
            return local_ip
        # 本地是内网地址或与公网不一致，以外网结果为准
        print(f"⚠️ 本地({local_ip})与公网({public_ip})不一致，采用公网地址")
        return public_ip
    if public_ip:
        return public_ip
    if local_ip:
        # 外网API不可用但本地有公网地址，降级使用
        print(f"⚠️ 外部API不可用，降级使用本地地址: {local_ip}")
        return local_ip
    return None


def read_last_ip():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    return None


def save_last_ip(ip):
    with open(STATE_FILE, "w") as f:
        f.write(ip)


def get_record_id(client):
    """查询指定子域名的AAAA记录ID"""
    req = models.DescribeRecordListRequest()
    req.Domain = DOMAIN
    req.Subdomain = SUB_DOMAIN
    req.RecordType = "AAAA"
    try:
        resp = client.DescribeRecordList(req)
        if resp.RecordList and len(resp.RecordList) > 0:
            return resp.RecordList[0].RecordId
        else:
            print(f"❌ 未找到 {SUB_DOMAIN}.{DOMAIN} 的AAAA记录，请先在控制台手动创建")
            return None
    except TencentCloudSDKException as e:
        print(f"查询记录ID失败: {e}")
        return None


def update_dnspod_record(client, record_id, ipv6):
    """更新DNSPod的AAAA记录"""
    req = models.ModifyRecordRequest()
    req.Domain = DOMAIN
    req.RecordId = record_id
    req.SubDomain = SUB_DOMAIN
    req.RecordType = "AAAA"
    req.RecordLine = "默认"
    req.Value = ipv6
    req.TTL = 600
    try:
        resp = client.ModifyRecord(req)
        print(f"✅ DNS更新成功: {SUB_DOMAIN}.{DOMAIN} -> {ipv6}  (RecordId={resp.RecordId})")
        return True
    except TencentCloudSDKException as e:
        print(f"❌ DNS更新失败: {e}")
        return False


def main():
    # 初始化腾讯云客户端（DNSPod 为全局服务，Region 传空字符串即可）
    cred = credential.Credential(SECRET_ID, SECRET_KEY)
    client = dnspod_client.DnspodClient(cred, "")  # region 忽略

    # 先获取一次 RecordId
    record_id = get_record_id(client)
    if record_id is None:
        return

    last_ip = read_last_ip()
    print(f"启动 DDNS 监控 | 域名: {SUB_DOMAIN}.{DOMAIN} | RecordId: {record_id}")

    while True:
        current_ip = get_current_ipv6()
        if current_ip:
            if current_ip != last_ip:
                print(f"🔄 IPv6变化: {last_ip} -> {current_ip}")
                if update_dnspod_record(client, record_id, current_ip):
                    last_ip = current_ip
                    save_last_ip(current_ip)
            else:
                print(f"⏸️ IPv6未变化: {current_ip}")
        else:
            print("⚠️ 未能获取IPv6，跳过本次检查")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
