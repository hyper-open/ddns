"""配置加载与按服务商校验测试。"""
import unittest
from pathlib import Path

from ddns.config import load_config
from ddns.exceptions import ConfigError

BASE = {
    "DDNS_PROVIDER": "dnspod",
    "DDNS_DOMAIN": "example.com",
    "DDNS_SUB_DOMAIN": "home",
    "TENCENT_SECRET_ID": "id",
    "TENCENT_SECRET_KEY": "key",
}


class TestLoadConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = load_config(BASE)
        self.assertEqual(cfg.provider, "dnspod")
        self.assertEqual(cfg.record_type, "AAAA")
        self.assertEqual(cfg.ttl, 600)
        self.assertEqual(cfg.check_interval, 60)
        self.assertEqual(cfg.log_level, "INFO")
        self.assertEqual(cfg.state_path, Path(__file__).resolve().parent.parent / "ddns_state.json")

    def test_missing_provider(self):
        env = dict(BASE)
        del env["DDNS_PROVIDER"]
        with self.assertRaises(ConfigError):
            load_config(env)

    def test_unknown_provider(self):
        env = {**BASE, "DDNS_PROVIDER": "nope"}
        with self.assertRaises(ConfigError):
            load_config(env)

    def test_invalid_record_type(self):
        env = {**BASE, "DDNS_RECORD_TYPE": "TXT"}
        with self.assertRaises(ConfigError):
            load_config(env)

    def test_record_type_lowercased(self):
        env = {**BASE, "DDNS_RECORD_TYPE": "a"}
        self.assertEqual(load_config(env).record_type, "A")

    def test_missing_required_credentials(self):
        env = {**BASE, "TENCENT_SECRET_KEY": ""}
        with self.assertRaises(ConfigError) as ctx:
            load_config(env)
        self.assertIn("TENCENT_SECRET_KEY", str(ctx.exception))

    def test_only_selected_provider_validated(self):
        # 选 dnspod 时，即便阿里云凭据为空也不应报错
        cfg = load_config({**BASE, "DDNS_PROVIDER": "dnspod"})
        self.assertEqual(cfg.provider, "dnspod")
        self.assertIsNone(cfg.aliyun_access_key_id)

    def test_aliyun_provider_requires_only_aliyun(self):
        env = {
            "DDNS_PROVIDER": "aliyun",
            "DDNS_DOMAIN": "example.com",
            "ALIYUN_ACCESS_KEY_ID": "id",
            "ALIYUN_ACCESS_KEY_SECRET": "secret",
        }
        cfg = load_config(env)
        self.assertEqual(cfg.aliyun_region, "cn-hangzhou")

    def test_cloudflare_requires_token(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config({"DDNS_PROVIDER": "cloudflare", "DDNS_DOMAIN": "example.com"})
        self.assertIn("CLOUDFLARE_API_TOKEN", str(ctx.exception))

    def test_huawei_requires_region(self):
        env = {
            "DDNS_PROVIDER": "huawei",
            "DDNS_DOMAIN": "example.com",
            "HUAWEI_ACCESS_KEY_ID": "id",
            "HUAWEI_SECRET_ACCESS_KEY": "secret",
        }
        with self.assertRaises(ConfigError) as ctx:
            load_config(env)
        self.assertIn("HUAWEI_REGION", str(ctx.exception))

    def test_custom_state_path(self):
        env = {**BASE, "DDNS_STATE_FILE": "/tmp/x.json"}
        self.assertEqual(load_config(env).state_path, Path("/tmp/x.json"))

    def test_cloudflare_proxied_flag(self):
        env = {
            "DDNS_PROVIDER": "cloudflare",
            "DDNS_DOMAIN": "example.com",
            "CLOUDFLARE_API_TOKEN": "t",
            "CLOUDFLARE_PROXIED": "true",
        }
        self.assertTrue(load_config(env).cloudflare_proxied)


if __name__ == "__main__":
    unittest.main()
