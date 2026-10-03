"""支持的服务商注册表，惰性导入实现模块以避免拉起未安装的 SDK。"""
import importlib
from typing import TYPE_CHECKING

from ..exceptions import ConfigError

if TYPE_CHECKING:  # pragma: no cover
    from .providers.base import BaseProvider

# name -> "module:ClassName"
_PROVIDERS = {
    "dnspod": "ddns.providers.dnspod:DnsPodProvider",
    "aliyun": "ddns.providers.aliyun:AliyunProvider",
    "cloudflare": "ddns.providers.cloudflare:CloudflareProvider",
    "huawei": "ddns.providers.huawei:HuaweiProvider",
}

PROVIDER_NAMES = tuple(_PROVIDERS)


def get_provider(name: str) -> "type[BaseProvider]":
    """按名字返回服务商类。

    只有在真正选中某个服务商时才导入其模块，因此未安装的厂商 SDK 不会影响其他厂商。
    """
    target = _PROVIDERS.get(name)
    if target is None:
        raise ConfigError(
            f"未知的 DDNS_PROVIDER: {name!r}，可选: {', '.join(PROVIDER_NAMES)}"
        )
    module_name, class_name = target.split(":")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)
