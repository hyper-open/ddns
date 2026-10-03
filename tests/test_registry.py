"""服务商注册表与 Target 主机记录归一化测试。"""
import unittest

from ddns.exceptions import ConfigError
from ddns.providers import PROVIDER_NAMES, get_provider
from ddns.providers.base import Target


class TestRegistry(unittest.TestCase):
    def test_known_names(self):
        self.assertEqual(
            set(PROVIDER_NAMES), {"tencent", "aliyun", "cloudflare", "huawei"}
        )

    def test_unknown_provider_raises(self):
        with self.assertRaises(ConfigError):
            get_provider("nope")

    def test_get_provider_cloudflare_no_sdk_needed(self):
        cls = get_provider("cloudflare")
        self.assertEqual(cls.name, "cloudflare")

    def test_get_provider_missing_sdk_raises_dependency_error(self):
        # 未安装腾讯 SDK 时，选中 tencent 应给出友好依赖错误而非 ImportError。
        try:
            import tencentcloud  # noqa: F401
        except ImportError:
            from ddns.exceptions import ProviderDependencyError

            cls = get_provider("tencent")
            from ddns.config import RecordTarget
            cfg = type("C", (), {
                "records": [RecordTarget("example.com", "home", "AAAA", 600)],
                "credential": lambda self, k: "x",
                "option": lambda self, k, d=None: d,
            })()
            with self.assertRaises(ProviderDependencyError):
                cls.from_config(cfg)
        else:
            self.skipTest("tencentcloud 已安装，跳过依赖缺失用例")


class TestTarget(unittest.TestCase):
    def test_host_prefix(self):
        self.assertEqual(Target("example.com", "home", "AAAA").host, "home")

    def test_host_at_when_empty(self):
        self.assertEqual(Target("example.com", "", "AAAA").host, "@")

    def test_host_at_passthrough(self):
        self.assertEqual(Target("example.com", "@", "A").host, "@")

    def test_fqdn_with_sub(self):
        self.assertEqual(Target("example.com", "home", "AAAA").fqdn,
                         "home.example.com")

    def test_fqdn_apex(self):
        self.assertEqual(Target("example.com", "", "AAAA").fqdn, "example.com")
        self.assertEqual(Target("example.com", "@", "A").fqdn, "example.com")


if __name__ == "__main__":
    unittest.main()
