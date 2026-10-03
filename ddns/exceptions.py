"""异常层级。"""


class DDNSError(Exception):
    """本工具所有异常的基类。"""


class ConfigError(DDNSError):
    """配置缺失或非法。"""


class ProviderDependencyError(DDNSError):
    """所选服务商依赖的 SDK 未安装。"""
