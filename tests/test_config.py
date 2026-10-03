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
        self.assertEqual(len(cfg.records), 1)
        rec = cfg.records[0]
        self.assertEqual(rec.record_type, "AAAA")
        self.assertEqual(rec.domain, "example.com")
        self.assertEqual(rec.sub_domain, "home")
        self.assertEqual(rec.ttl, 600)
        self.assertEqual(cfg.check_interval, 60)
        self.assertEqual(cfg.log_level, "INFO")

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
        self.assertEqual(cfg.records[0].record_type, "A")

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

    def test_default_state_path_next_to_config(self):
        path = write_toml(TENCENT_TOML)
        cfg = load_config(path, env={"TENCENT_ACCESS_KEY_ID": "i",
                                     "TENCENT_ACCESS_KEY_SECRET": "k"})
        self.assertEqual(cfg.state_path, path.parent / "ddns_state.json")

    def test_relative_state_path_resolved_against_config_dir(self):
        toml = '[ddns]\nprovider = "tencent"\nstate_file = "s.json"\n'
        path = write_toml(toml)
        cfg = load_config(path, env={"TENCENT_ACCESS_KEY_ID": "i",
                                     "TENCENT_ACCESS_KEY_SECRET": "k"})
        self.assertEqual(cfg.state_path, path.parent / "s.json")

    def test_records_list(self):
        toml = """
[ddns]
provider = "aliyun"

[[records]]
domain = "example.com"
sub_domain = "home"
record_type = "AAAA"

[[records]]
domain = "example.com"
sub_domain = "www"
record_type = "A"
ttl = 300

[aliyun]
"""
        cfg = load_config(write_toml(toml),
                          env={"ALIYUN_ACCESS_KEY_ID": "i",
                               "ALIYUN_ACCESS_KEY_SECRET": "s"})
        self.assertEqual(len(cfg.records), 2)
        self.assertEqual(cfg.records[0].sub_domain, "home")
        self.assertEqual(cfg.records[1].sub_domain, "www")
        self.assertEqual(cfg.records[1].record_type, "A")
        self.assertEqual(cfg.records[1].ttl, 300)

    def test_records_inherit_common_defaults(self):
        toml = """
[ddns]
provider = "aliyun"
domain = "example.com"
record_type = "A"
ttl = 900

[[records]]
sub_domain = "a"

[[records]]
sub_domain = "b"
record_type = "AAAA"
"""
        cfg = load_config(write_toml(toml),
                          env={"ALIYUN_ACCESS_KEY_ID": "i",
                               "ALIYUN_ACCESS_KEY_SECRET": "s"})
        self.assertEqual(cfg.records[0].domain, "example.com")
        self.assertEqual(cfg.records[0].record_type, "A")
        self.assertEqual(cfg.records[0].ttl, 900)
        self.assertEqual(cfg.records[1].record_type, "AAAA")
        self.assertEqual(cfg.records[1].ttl, 900)

    def test_record_missing_domain(self):
        toml = """
[ddns]
provider = "aliyun"
domain = "example.com"

[[records]]
sub_domain = "a"

[[records]]
sub_domain = "b"
domain = ""
"""
        with self.assertRaises(ConfigError):
            load_config(write_toml(toml),
                        env={"ALIYUN_ACCESS_KEY_ID": "i",
                             "ALIYUN_ACCESS_KEY_SECRET": "s"})

    def test_empty_records_rejected(self):
        toml = '[ddns]\nprovider = "aliyun"\ndomain = "example.com"\nrecords = []\n'
        with self.assertRaises(ConfigError):
            load_config(write_toml(toml),
                        env={"ALIYUN_ACCESS_KEY_ID": "i",
                             "ALIYUN_ACCESS_KEY_SECRET": "s"})

    def test_env_loaded_from_config_dir(self):
        """密钥从配置文件同级目录的 .env 读取，支持每实例独立目录。"""
        import os
        from unittest import mock

        d = Path(tempfile.mkdtemp())
        (d / "ddns.toml").write_text(ALIYUN_TOML, encoding="utf-8")
        (d / ".env").write_text(
            "ALIYUN_ACCESS_KEY_ID=file-id\nALIYUN_ACCESS_KEY_SECRET=file-secret\n",
            encoding="utf-8",
        )
        clean = {k: v for k, v in os.environ.items()
                 if not k.startswith(("ALIYUN_", "DDNS_"))}
        with mock.patch.dict(os.environ, clean, clear=True):
            os.environ["DDNS_CONFIG"] = str(d / "ddns.toml")
            cfg = load_config()
        self.assertEqual(cfg.credential("ALIYUN_ACCESS_KEY_ID"), "file-id")
        self.assertEqual(cfg.provider, "aliyun")


if __name__ == "__main__":
    unittest.main()
