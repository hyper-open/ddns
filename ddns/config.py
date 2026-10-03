"""从环境变量加载并校验配置。"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

from .exceptions import ConfigError

VALID_RECORD_TYPES = ("A", "AAAA")

# 各服务商必填的配置字段名（对应 Config 的属性名）
REQUIRED_SETTINGS = {
    "dnspod": ("tencent_secret_id", "tencent_secret_key"),
    "aliyun": ("aliyun_access_key_id", "aliyun_access_key_secret"),
    "cloudflare": ("cloudflare_api_token",),
    "huawei": ("huawei_access_key_id", "huawei_secret_access_key", "huawei_region"),
}

# 字段名 -> .env 变量名，用于报错提示
SETTING_ENV_NAMES = {
    "tencent_secret_id": "TENCENT_SECRET_ID",
    "tencent_secret_key": "TENCENT_SECRET_KEY",
    "aliyun_access_key_id": "ALIYUN_ACCESS_KEY_ID",
    "aliyun_access_key_secret": "ALIYUN_ACCESS_KEY_SECRET",
    "cloudflare_api_token": "CLOUDFLARE_API_TOKEN",
    "huawei_access_key_id": "HUAWEI_ACCESS_KEY_ID",
    "huawei_secret_access_key": "HUAWEI_SECRET_ACCESS_KEY",
    "huawei_region": "HUAWEI_REGION",
}


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
    # 各厂商凭据（None 表示未配置）
    tencent_secret_id: Optional[str] = None
    tencent_secret_key: Optional[str] = None
    aliyun_access_key_id: Optional[str] = None
    aliyun_access_key_secret: Optional[str] = None
    aliyun_region: str = "cn-hangzhou"
    cloudflare_api_token: Optional[str] = None
    cloudflare_zone_id: Optional[str] = None
    cloudflare_proxied: bool = False
    huawei_access_key_id: Optional[str] = None
    huawei_secret_access_key: Optional[str] = None
    huawei_region: Optional[str] = None

    def missing_settings(self) -> list:
        """返回当前所选服务商缺失的必填字段对应的环境变量名。"""
        missing = []
        for attr in REQUIRED_SETTINGS[self.provider]:
            if not getattr(self, attr):
                missing.append(SETTING_ENV_NAMES[attr])
        return missing


def _get(env, key, default=None):
    value = env.get(key)
    return value if value not in (None, "") else default


def load_config(env: Optional[Mapping[str, str]] = None) -> Config:
    """读取环境变量构造 Config。

    env 为 None 时先加载同目录 .env（不覆盖已存在的环境变量）。
    """
    if env is None:
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        env = os.environ

    provider = _get(env, "DDNS_PROVIDER")
    if not provider:
        raise ConfigError(
            "未设置 DDNS_PROVIDER，请在 .env 中指定: "
            + ", ".join(REQUIRED_SETTINGS)
        )
    if provider not in REQUIRED_SETTINGS:
        raise ConfigError(
            f"未知的 DDNS_PROVIDER: {provider!r}，可选: "
            + ", ".join(REQUIRED_SETTINGS)
        )

    record_type = _get(env, "DDNS_RECORD_TYPE", "AAAA").upper()
    if record_type not in VALID_RECORD_TYPES:
        raise ConfigError(
            f"DDNS_RECORD_TYPE 只能是 {' 或 '.join(VALID_RECORD_TYPES)}，"
            f"收到: {record_type!r}"
        )

    state_path = _get(env, "DDNS_STATE_FILE")
    if state_path:
        state_path = Path(state_path)
    else:
        state_path = Path(__file__).resolve().parent.parent / "ddns_state.json"

    cfg = Config(
        provider=provider,
        record_type=record_type,
        domain=_get(env, "DDNS_DOMAIN", "example.com"),
        sub_domain=_get(env, "DDNS_SUB_DOMAIN", ""),
        ttl=int(_get(env, "DDNS_TTL", "600")),
        check_interval=int(_get(env, "DDNS_CHECK_INTERVAL", "60")),
        log_level=_get(env, "DDNS_LOG_LEVEL", "INFO").upper(),
        state_path=state_path,
        tencent_secret_id=_get(env, "TENCENT_SECRET_ID"),
        tencent_secret_key=_get(env, "TENCENT_SECRET_KEY"),
        aliyun_access_key_id=_get(env, "ALIYUN_ACCESS_KEY_ID"),
        aliyun_access_key_secret=_get(env, "ALIYUN_ACCESS_KEY_SECRET"),
        aliyun_region=_get(env, "ALIYUN_REGION", "cn-hangzhou"),
        cloudflare_api_token=_get(env, "CLOUDFLARE_API_TOKEN"),
        cloudflare_zone_id=_get(env, "CLOUDFLARE_ZONE_ID"),
        cloudflare_proxied=str(_get(env, "CLOUDFLARE_PROXIED", "false")).lower()
        in ("1", "true", "yes"),
        huawei_access_key_id=_get(env, "HUAWEI_ACCESS_KEY_ID"),
        huawei_secret_access_key=_get(env, "HUAWEI_SECRET_ACCESS_KEY"),
        huawei_region=_get(env, "HUAWEI_REGION"),
    )

    missing = cfg.missing_settings()
    if missing:
        raise ConfigError(
            f"服务商 {provider!r} 缺少必填配置: {', '.join(missing)}"
        )
    return cfg
