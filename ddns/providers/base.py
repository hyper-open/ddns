"""服务商抽象：Target 承载归一化后的域名信息，BaseProvider 定义接口。"""
import importlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Optional, Tuple

from ..config import Config
from ..exceptions import ProviderDependencyError


def require_module(module: str, extra: str):
    """导入厂商 SDK，缺失时给出安装提示。"""
    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise ProviderDependencyError(
            f"服务商需要 {module}，请先安装: pip install \"ddns[{extra}]\""
        ) from e


@dataclass(frozen=True)
class Target:
    """一条待维护的 DNS 记录。"""

    domain: str  # 主域名 example.com
    sub_domain: str  # 主机前缀，如 home；根域名可空或 '@'
    record_type: str  # "A" | "AAAA"
    ttl: int = 600

    @property
    def host(self) -> str:
        """前缀形式（腾讯/阿里使用）：空或 '@' 归一为 '@'。"""
        return "@" if self.sub_domain in ("", "@") else self.sub_domain

    @property
    def fqdn(self) -> str:
        """完整域名形式（Cloudflare/华为使用）。"""
        if self.sub_domain in ("", "@"):
            return self.domain
        return f"{self.sub_domain}.{self.domain}"


class BaseProvider(ABC):
    """DNS 服务商基类。

    子类只需实现 :meth:`from_config`、:meth:`resolve_record_id` 与
    :meth:`update`。``required_settings`` 声明所选服务商必需的配置字段名
    （对应 :class:`~ddns.config.Config` 属性），供配置层做按需校验。
    """

    name: ClassVar[str]
    required_settings: ClassVar[Tuple[str, ...]] = ()

    def __init__(self, target: Target):
        self.target = target
        self.log = logging.getLogger(f"ddns.provider.{self.name}")

    @classmethod
    def build_client(cls, cfg: Config):
        """构造可跨多条记录复用的底层客户端；无状态客户端返回 None。"""
        return None

    @classmethod
    @abstractmethod
    def from_config(cls, cfg: Config, target: Optional[Target] = None,
                    client=None) -> "BaseProvider":
        """用配置构造实例（在此延迟导入厂商 SDK）。

        target 为 None 时回退到配置中的第一条记录；client 为 None 时自行构造，
        多记录场景由调用方传入共享的 client 以复用连接。
        """

    @abstractmethod
    def resolve_record_id(self) -> Optional[str]:
        """查询目标记录的 ID；不存在时返回 None。"""

    @abstractmethod
    def update(self, record_id: str, ip: str) -> bool:
        """将记录指向 ip，成功返回 True。"""
