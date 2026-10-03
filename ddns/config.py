"""配置加载：非敏感项读 ddns.toml，密钥读 .env。

凭证变量按服务商统一命名（``{PROVIDER}_ACCESS_KEY_ID`` / ``..._SECRET``），
每个服务商可选的额外项（区域、zone id 等）放在 TOML 的 ``[<provider>]`` 分段里。
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

from .exceptions import ConfigError

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.8~3.10 回退
    import tomli as tomllib

VALID_RECORD_TYPES = ("A", "AAAA")
VALID_UPDATE_POLICIES = ("exact", "stable")

# 各服务商需要的密钥变量（.env），统一命名
CREDENTIALS = {
    "tencent": ("TENCENT_ACCESS_KEY_ID", "TENCENT_ACCESS_KEY_SECRET"),
    "aliyun": ("ALIYUN_ACCESS_KEY_ID", "ALIYUN_ACCESS_KEY_SECRET"),
    "cloudflare": ("CLOUDFLARE_API_TOKEN",),
    "huawei": ("HUAWEI_ACCESS_KEY_ID", "HUAWEI_ACCESS_KEY_SECRET"),
}
PROVIDER_NAMES = tuple(CREDENTIALS)

# [<provider>] 段中除密钥外还必填的选项
REQUIRED_OPTIONS = {
    "tencent": (),
    "aliyun": (),
    "cloudflare": (),
    "huawei": ("region",),
}

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "ddns.toml"


@dataclass
class RecordTarget:
    """一条待维护的 DNS 记录。"""

    domain: str
    sub_domain: str
    record_type: str
    ttl: int
    source: str = ""  # 出口：源 IP 或网卡名；空则走默认路由


@dataclass
class Config:
    provider: str
    records: list  # list[RecordTarget]
    check_interval: int
    log_level: str
    state_path: Path
    update_policy: str = "exact"  # exact | stable（IPv6 同前缀抗抖动）
    options: dict = field(default_factory=dict)  # [<provider>] 段非敏感选项
    credentials: dict = field(default_factory=dict)  # 从 .env 读取的密钥

    def option(self, key, default=None):
        value = self.options.get(key, default)
        return default if value in (None, "") else value

    def credential(self, key):
        return self.credentials.get(key)


def _read_toml(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(
            f"未找到配置文件 {path}，请复制 ddns.toml.example 为 ddns.toml 并填写。"
        )
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ConfigError(f"读取配置文件失败: {e}") from e


def load_config(
    config_path: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Config:
    """加载配置。

    config_path 为 None 时依次取 DDNS_CONFIG 环境变量、默认 ddns.toml。
    密钥从**配置文件同级**的 .env 加载，因此每个实例可以放在各自目录、
    各带一份 ddns.toml 与 .env 来运行不同服务商。
    env 为 None 时读取 os.environ；传入 Mapping 便于测试（跳过 .env 加载）。
    """
    if config_path is None:
        config_path = (
            env.get("DDNS_CONFIG") if env is not None
            else os.environ.get("DDNS_CONFIG")
        ) or DEFAULT_CONFIG_PATH
    config_path = Path(config_path)

    if env is None:
        load_dotenv(config_path.parent / ".env")
        env = os.environ

    data = _read_toml(config_path)
    common = data.get("ddns")
    if not isinstance(common, dict):
        raise ConfigError(f"{config_path} 缺少 [ddns] 段。")

    provider = common.get("provider")
    if not provider:
        raise ConfigError(f"{config_path} 的 [ddns] 段缺少 provider。")
    if provider not in CREDENTIALS:
        raise ConfigError(
            f"未知的 provider: {provider!r}，可选: {', '.join(PROVIDER_NAMES)}"
        )

    # 记录列表：优先 [[records]]（顶层或 [ddns] 内），否则回退单条 domain/sub_domain
    raw_records = data.get("records", common.get("records"))
    if raw_records is None:
        raw_records = [common]
    if not isinstance(raw_records, list) or not raw_records:
        raise ConfigError("至少需要一条记录（[[records]] 或 [ddns] 中的 domain/sub_domain）。")

    records = []
    for i, item in enumerate(raw_records, 1):
        if not isinstance(item, dict):
            raise ConfigError(f"第 {i} 条记录格式不正确，应为表（[[records]]）。")
        rtype = str(item.get("record_type", common.get("record_type", "AAAA"))).upper()
        if rtype not in VALID_RECORD_TYPES:
            raise ConfigError(
                f"第 {i} 条记录的 record_type 只能是 {' 或 '.join(VALID_RECORD_TYPES)}，"
                f"收到: {rtype!r}"
            )
        domain = item.get("domain", common.get("domain", "example.com"))
        if not domain:
            raise ConfigError(f"第 {i} 条记录缺少 domain。")
        records.append(RecordTarget(
            domain=domain,
            sub_domain=str(item.get("sub_domain", common.get("sub_domain", ""))),
            record_type=rtype,
            ttl=int(item.get("ttl", common.get("ttl", 600))),
            source=str(item.get("source", common.get("source", "")) or ""),
        ))

    options = data.get(provider) or {}
    if not isinstance(options, dict):
        raise ConfigError(f"[{provider}] 段格式不正确。")

    credentials = {
        name: env.get(name) for name in CREDENTIALS[provider]
    }

    missing = [n for n, v in credentials.items() if not v]
    missing += [
        k for k in REQUIRED_OPTIONS[provider] if options.get(k) in (None, "")
    ]
    if missing:
        raise ConfigError(
            f"provider {provider!r} 缺少必填配置: {', '.join(missing)}。"
            f"密钥写入 .env，选项写入 ddns.toml 的 [{provider}] 段。"
        )

    state_file = common.get("state_file")
    if not state_file:
        # 默认放在配置文件同级目录，使每个实例天然独立
        state_path = config_path.parent / "ddns_state.json"
    else:
        state_path = Path(state_file)
        if not state_path.is_absolute():
            state_path = config_path.parent / state_path

    update_policy = str(common.get("update_policy", "exact")).lower()
    if update_policy not in VALID_UPDATE_POLICIES:
        raise ConfigError(
            f"update_policy 只能是 {' 或 '.join(VALID_UPDATE_POLICIES)}，"
            f"收到: {update_policy!r}"
        )

    return Config(
        provider=provider,
        records=records,
        check_interval=int(common.get("check_interval", 60)),
        log_level=str(common.get("log_level", "INFO")).upper(),
        state_path=state_path,
        update_policy=update_policy,
        options=options,
        credentials=credentials,
    )
