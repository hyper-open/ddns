"""主循环：探测 IP 并在变化时同步到所选服务商。"""
import logging
import time

from .config import Config
from .ip import get_current_ip
from .providers import get_provider
from .state import StateStore

log = logging.getLogger("ddns.app")


def state_key(cfg: Config) -> str:
    sub = cfg.sub_domain if cfg.sub_domain not in ("", "@") else "@"
    fqdn = cfg.domain if sub == "@" else f"{sub}.{cfg.domain}"
    return f"{cfg.provider}:{cfg.record_type}:{fqdn}"


def run_once(provider, record_id, store, key, record_type, last_ip):
    """执行一次探测与同步，返回本次的最新 IP（用于更新调用方的 last_ip）。"""
    current_ip = get_current_ip(record_type)
    if not current_ip:
        log.warning("未能获取 %s 地址，跳过本次检查", record_type)
        return last_ip
    if current_ip == last_ip:
        log.info("%s 未变化: %s", record_type, current_ip)
        return last_ip
    log.info("%s 变化: %s -> %s", record_type, last_ip, current_ip)
    if provider.update(record_id, current_ip):
        store.set(key, current_ip)
        return current_ip
    return last_ip


def run(cfg: Config) -> None:
    provider_cls = get_provider(cfg.provider)
    provider = provider_cls.from_config(cfg)

    record_id = provider.resolve_record_id()
    if record_id is None:
        raise SystemExit(1)

    store = StateStore(cfg.state_path)
    key = state_key(cfg)
    last_ip = store.get(key)

    log.info(
        "启动 DDNS 监控 | 服务商: %s | 记录: %s (%s) | RecordId: %s",
        cfg.provider, provider.target.fqdn, cfg.record_type, record_id,
    )

    while True:
        last_ip = run_once(
            provider, record_id, store, key, cfg.record_type, last_ip
        )
        time.sleep(cfg.check_interval)
