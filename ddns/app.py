"""主循环：探测 IP 并在变化时同步到所选服务商（可含多条记录）。"""
import logging
import time

from .config import Config
from .ip import get_current_ip
from .providers import get_provider
from .providers.base import Target
from .state import StateStore

log = logging.getLogger("ddns.app")


def state_key(provider, target) -> str:
    return f"{provider}:{target.record_type}:{target.fqdn}"


class _Entry:
    """一条待维护记录：target + 已解析的 provider 实例与 record_id。"""

    def __init__(self, target, provider):
        self.target = target
        self.provider = provider
        self.record_id = None
        self.last_ip = None


def _build_entries(cfg: Config):
    provider_cls = get_provider(cfg.provider)
    client = provider_cls.build_client(cfg)  # 一个进程内复用同一 client
    entries = {}
    for rec in cfg.records:
        target = Target(rec.domain, rec.sub_domain, rec.record_type, rec.ttl)
        if target.fqdn in entries:
            log.warning("记录 %s 在配置中重复，仅保留一条", target.fqdn)
            continue
        provider = provider_cls.from_config(cfg, target, client)
        entries[target.fqdn] = _Entry(target, provider)
    return entries


def run(cfg: Config) -> None:
    entries = _build_entries(cfg)
    store = StateStore(cfg.state_path)

    # 每种记录类型只探测一次 IP，避免重复请求外部接口
    for entry in entries.values():
        rid = entry.provider.resolve_record_id()
        if rid is None:
            raise SystemExit(1)
        entry.record_id = rid
        entry.last_ip = store.get(state_key(cfg.provider, entry.target))

    log.info(
        "启动 DDNS 监控 | 服务商: %s | 记录 %d 条: %s",
        cfg.provider, len(entries),
        ", ".join(f"{e.target.fqdn}({e.target.record_type})" for e in entries.values()),
    )

    while True:
        detected = {}
        for entry in entries.values():
            rt = entry.target.record_type
            if rt not in detected:
                detected[rt] = get_current_ip(rt)
            current_ip = detected[rt]
            if not current_ip:
                log.warning("未能获取 %s 地址，跳过 %s", rt, entry.target.fqdn)
                continue
            if current_ip == entry.last_ip:
                log.info("%s %s 未变化: %s", entry.target.fqdn, rt, current_ip)
                continue
            log.info("%s %s 变化: %s -> %s",
                     entry.target.fqdn, rt, entry.last_ip, current_ip)
            if entry.provider.update(entry.record_id, current_ip):
                store.set(state_key(cfg.provider, entry.target), current_ip)
                entry.last_ip = current_ip
        time.sleep(cfg.check_interval)
