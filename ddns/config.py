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
class Config:
    provider: str
    record_type: str
    domain: str
    sub_domain: str
    ttl: int
    check_interval: int
    log_level: str
    state_path: Path
    options: dict = field(default_factory=dict)  # [<provider>] 段非敏感选项
    credentials: dict = field(default_factory=dict)  # 从 .env 读取的密钥

    def option(self, key, default=None):
        value = self.options.get(key, default)
        return default if value in (None, "") else value

    def credential(self, key):
        return self.credentials.get(key)


def _default_state_path() -> Path:
    return Path(__file__).resolve().parent.parent / "ddns_state.json"


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
    env 为 None 时加载同级 .env 并读取 os.environ；传入 Mapping 便于测试。
    """
    if env is None:
        load_dotenv(DEFAULT_CONFIG_PATH.parent / ".env")
        env = os.environ

    if config_path is None:
        config_path = env.get("DDNS_CONFIG") or DEFAULT_CONFIG_PATH
    config_path = Path(config_path)

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

    record_type = str(common.get("record_type", "AAAA")).upper()
    if record_type not in VALID_RECORD_TYPES:
        raise ConfigError(
            f"record_type 只能是 {' 或 '.join(VALID_RECORD_TYPES)}，"
            f"收到: {record_type!r}"
        )

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
    state_path = Path(state_file) if state_file else _default_state_path()

    return Config(
        provider=provider,
        record_type=record_type,
        domain=common.get("domain", "example.com"),
        sub_domain=str(common.get("sub_domain", "")),
        ttl=int(common.get("ttl", 600)),
        check_interval=int(common.get("check_interval", 60)),
        log_level=str(common.get("log_level", "INFO")).upper(),
        state_path=state_path,
        options=options,
        credentials=credentials,
    )
