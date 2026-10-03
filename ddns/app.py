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

    def __init__(self, target, provider, source=""):
        self.target = target
        self.provider = provider
        self.source = source or ""
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
        entries[target.fqdn] = _Entry(target, provider, rec.source)
    return entries


def sync_once(entries, store, provider_name):
    """执行一轮探测与同步。

    按 (记录类型, 出口) 缓存探测结果：相同出口只探测一次，不同出口分别探测。
    返回 (探测次数, 成功更新次数)，便于测试与统计。
    """
    detected = {}
    updates = 0
    for entry in entries:
        rt = entry.target.record_type
        cache_key = (rt, entry.source)
        if cache_key not in detected:
            detected[cache_key] = get_current_ip(rt, entry.source)
        current_ip = detected[cache_key]
        if not current_ip:
            log.warning("未能获取 %s 地址（source=%s），跳过 %s",
                        rt, entry.source or "默认", entry.target.fqdn)
            continue
        if current_ip == entry.last_ip:
            log.info("%s %s 未变化: %s", entry.target.fqdn, rt, current_ip)
            continue
        log.info("%s %s 变化: %s -> %s",
                 entry.target.fqdn, rt, entry.last_ip, current_ip)
        if entry.provider.update(entry.record_id, current_ip):
            if store is not None:
                store.set(state_key(provider_name, entry.target), current_ip)
            entry.last_ip = current_ip
            updates += 1
    return len(detected), updates


def run(cfg: Config) -> None:
    entries = _build_entries(cfg)
    store = StateStore(cfg.state_path)

    for entry in entries.values():
        rid = entry.provider.resolve_record_id()
        if rid is None:
            raise SystemExit(1)
        entry.record_id = rid
        entry.last_ip = store.get(state_key(cfg.provider, entry.target))

    log.info(
        "启动 DDNS 监控 | 服务商: %s | 记录 %d 条: %s",
        cfg.provider, len(entries),
        ", ".join(
            f"{e.target.fqdn}({e.target.record_type}"
            + (f",{e.source}" if e.source else "") + ")"
            for e in entries.values()
        ),
    )

    while True:
        sync_once(list(entries.values()), store, cfg.provider)
        time.sleep(cfg.check_interval)
