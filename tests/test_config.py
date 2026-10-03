"""配置加载测试：ddns.toml + .env 密钥。"""
import tempfile
import unittest
from pathlib import Path

from ddns.config import load_config
from ddns.exceptions import ConfigError


def write_toml(text, name="ddns.toml"):
    path = Path(tempfile.mkdtemp()) / name
    path.write_text(text, encoding="utf-8")
    return path

TENCENT_TOML = """
[ddns]
provider = "tencent"
record_type = "AAAA"
domain = "example.com"
sub_domain = "home"

[tencent]
"""

ALIYUN_TOML = """
[ddns]
provider = "aliyun"
domain = "example.com"

[aliyun]
region = "cn-hangzhou"
"""

CF_TOML = """
[ddns]
provider = "cloudflare"
domain = "example.com"

[cloudflare]
proxied = true
"""

HUAWEI_TOML = """
[ddns]
provider = "huawei"
domain = "example.com"

[huawei]
region = "cn-north-4"
"""


class TestLoadConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = load_config(write_toml(TENCENT_TOML),
                          env={"TENCENT_ACCESS_KEY_ID": "id",
                               "TENCENT_ACCESS_KEY_SECRET": "key"})
        self.assertEqual(cfg.provider, "tencent")
        self.assertEqual(cfg.record_type, "AAAA")
        self.assertEqual(cfg.ttl, 600)
        self.assertEqual(cfg.check_interval, 60)
        self.assertEqual(cfg.log_level, "INFO")
        self.assertEqual(cfg.sub_domain, "home")

    def test_missing_config_file(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(Path("/nonexistent/ddns.toml"), env={})
        self.assertIn("ddns.toml", str(ctx.exception))

    def test_missing_ddns_section(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_toml("[tencent]\n"), env={})
        self.assertIn("[ddns]", str(ctx.exception))

    def test_missing_provider(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_toml('[ddns]\ndomain = "example.com"\n'), env={})
        self.assertIn("provider", str(ctx.exception))

    def test_unknown_provider(self):
        toml = '[ddns]\nprovider = "nope"\n'
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_toml(toml), env={})
        self.assertIn("nope", str(ctx.exception))

    def test_invalid_record_type(self):
        toml = '[ddns]\nprovider = "tencent"\nrecord_type = "TXT"\n'
        with self.assertRaises(ConfigError):
            load_config(write_toml(toml), env={})

    def test_record_type_lowercased(self):
        toml = '[ddns]\nprovider = "tencent"\nrecord_type = "a"\n'
        cfg = load_config(write_toml(toml),
                          env={"TENCENT_ACCESS_KEY_ID": "i",
                               "TENCENT_ACCESS_KEY_SECRET": "k"})
        self.assertEqual(cfg.record_type, "A")

    def test_invalid_toml_syntax(self):
        with self.assertRaises(ConfigError):
            load_config(write_toml("this is not toml = = ="), env={})

    def test_missing_credentials_lists_var(self):
        toml = '[ddns]\nprovider = "tencent"\n'
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_toml(toml), env={"TENCENT_ACCESS_KEY_ID": "id"})
        self.assertIn("TENCENT_ACCESS_KEY_SECRET", str(ctx.exception))

    def test_only_selected_provider_credentials_required(self):
        # 选 tencent 时，未填阿里云密钥不应报错
        cfg = load_config(write_toml(TENCENT_TOML),
                          env={"TENCENT_ACCESS_KEY_ID": "i",
                               "TENCENT_ACCESS_KEY_SECRET": "k"})
        self.assertEqual(cfg.provider, "tencent")
        self.assertIsNone(cfg.credential("ALIYUN_ACCESS_KEY_ID"))

    def test_aliyun_region_option(self):
        cfg = load_config(write_toml(ALIYUN_TOML),
                          env={"ALIYUN_ACCESS_KEY_ID": "i",
                               "ALIYUN_ACCESS_KEY_SECRET": "s"})
        self.assertEqual(cfg.option("region"), "cn-hangzhou")

    def test_aliyun_region_default_not_required(self):
        toml = '[ddns]\nprovider = "aliyun"\n'
        cfg = load_config(write_toml(toml),
                          env={"ALIYUN_ACCESS_KEY_ID": "i",
                               "ALIYUN_ACCESS_KEY_SECRET": "s"})
        self.assertEqual(cfg.option("region", "cn-hangzhou"), "cn-hangzhou")

    def test_cloudflare_requires_token(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_toml(CF_TOML), env={})
        self.assertIn("CLOUDFLARE_API_TOKEN", str(ctx.exception))

    def test_cloudflare_proxied_option(self):
        cfg = load_config(write_toml(CF_TOML),
                          env={"CLOUDFLARE_API_TOKEN": "t"})
        self.assertTrue(cfg.option("proxied"))

    def test_huawei_requires_region(self):
        toml = '[ddns]\nprovider = "huawei"\n'
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_toml(toml),
                        env={"HUAWEI_ACCESS_KEY_ID": "i",
                             "HUAWEI_ACCESS_KEY_SECRET": "s"})
        self.assertIn("region", str(ctx.exception))

    def test_huawei_region_option(self):
        cfg = load_config(write_toml(HUAWEI_TOML),
                          env={"HUAWEI_ACCESS_KEY_ID": "i",
                               "HUAWEI_ACCESS_KEY_SECRET": "s"})
        self.assertEqual(cfg.option("region"), "cn-north-4")

    def test_custom_state_path(self):
        toml = '[ddns]\nprovider = "tencent"\nstate_file = "/tmp/x.json"\n'
        cfg = load_config(write_toml(toml),
                          env={"TENCENT_ACCESS_KEY_ID": "i",
                               "TENCENT_ACCESS_KEY_SECRET": "k"})
        self.assertEqual(cfg.state_path, Path("/tmp/x.json"))


if __name__ == "__main__":
    unittest.main()
