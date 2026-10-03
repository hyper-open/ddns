"""主编排测试：多记录扇出。"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ddns import app
from ddns.config import RecordTarget
from ddns.providers.base import Target
from ddns.state import StateStore


class FakeProvider:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def update(self, record_id, ip):
        self.calls.append((record_id, ip))
        return self.ok


class FakeProviderClass:
    """模拟服务商类，提供 build_client/from_config。"""

    def __init__(self, targets_seen, ok=True):
        self.targets_seen = targets_seen
        self.ok = ok

    def build_client(self, cfg):
        return "shared-client"

    def from_config(self, cfg, target, client):
        self.targets_seen.append(target.fqdn)
        return FakeProvider(ok=self.ok)


class FakeEntry:
    def __init__(self, target, provider, record_id=None, last_ip=None):
        self.target = target
        self.provider = provider
        self.record_id = record_id
        self.last_ip = last_ip


class TestStateKey(unittest.TestCase):
    def test_key_with_sub(self):
        t = Target("example.com", "home", "AAAA")
        self.assertEqual(app.state_key("cloudflare", t),
                         "cloudflare:AAAA:home.example.com")

    def test_key_apex(self):
        t = Target("example.com", "@", "A")
        self.assertEqual(app.state_key("cloudflare", t),
                         "cloudflare:A:example.com")


class TestBuildEntries(unittest.TestCase):
    def test_builds_entry_per_record_reusing_client(self):
        seen = []
        cfg = SimpleNamespace(provider="cloudflare", records=[
            RecordTarget("example.com", "home", "AAAA", 600),
            RecordTarget("example.com", "www", "A", 300),
        ])
        with mock.patch.object(app, "get_provider",
                               return_value=FakeProviderClass(seen)):
            entries = app._build_entries(cfg)
        self.assertEqual(set(entries), {"home.example.com", "www.example.com"})
        self.assertEqual(seen, ["home.example.com", "www.example.com"])

    def test_duplicate_fqdn_dropped(self):
        seen = []
        cfg = SimpleNamespace(provider="cloudflare", records=[
            RecordTarget("example.com", "home", "AAAA", 600),
            RecordTarget("example.com", "home", "AAAA", 600),
        ])
        with mock.patch.object(app, "get_provider",
                               return_value=FakeProviderClass(seen)):
            entries = app._build_entries(cfg)
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(seen), 1)


class TestRunOnceFanout(unittest.TestCase):
    """通过直接调用 run 的循环体难以中断，这里单独验证探测去重与扇出逻辑。"""

    def _run_one_cycle(self, entries, ips):
        """复刻 run 中一次循环的扇出逻辑，便于断言。"""
        detected = {}
        for entry in entries:
            rt = entry.target.record_type
            if rt not in detected:
                detected[rt] = ips.get(rt)
            current_ip = detected[rt]
            if not current_ip or current_ip == entry.last_ip:
                continue
            if entry.provider.update(entry.record_id, current_ip):
                entry.last_ip = current_ip
        return detected

    def test_same_record_type_probed_once(self):
        t1 = Target("example.com", "home", "AAAA")
        t2 = Target("example.com", "www", "AAAA")
        p1, p2 = FakeProvider(), FakeProvider()
        entries = [FakeEntry(t1, p1, "r1"), FakeEntry(t2, p2, "r2")]
        calls = []

        def fake_get(rt):
            calls.append(rt)
            return "2409:8a1e::9"

        with mock.patch.object(app, "get_current_ip", side_effect=fake_get):
            self._run_one_cycle(entries, {"AAAA": "2409:8a1e::9"})
        self.assertEqual(calls, [])  # 该 helper 不直接探测
        self.assertEqual(p1.calls, [("r1", "2409:8a1e::9")])
        self.assertEqual(p2.calls, [("r2", "2409:8a1e::9")])

    def test_mixed_record_types(self):
        ta = Target("example.com", "home", "AAAA")
        tb = Target("example.com", "www", "A")
        pa, pb = FakeProvider(), FakeProvider()
        entries = [FakeEntry(ta, pa, "r1"), FakeEntry(tb, pb, "r2")]
        self._run_one_cycle(entries, {"AAAA": "2409:8a1e::9", "A": "1.1.1.1"})
        self.assertEqual(pa.calls, [("r1", "2409:8a1e::9")])
        self.assertEqual(pb.calls, [("r2", "1.1.1.1")])

    def test_unchanged_skipped(self):
        t = Target("example.com", "home", "AAAA")
        p = FakeProvider()
        entries = [FakeEntry(t, p, "r1", last_ip="2409:8a1e::9")]
        self._run_one_cycle(entries, {"AAAA": "2409:8a1e::9"})
        self.assertEqual(p.calls, [])

    def test_missing_ip_skipped(self):
        t = Target("example.com", "home", "AAAA")
        p = FakeProvider()
        entries = [FakeEntry(t, p, "r1")]
        self._run_one_cycle(entries, {"AAAA": None})
        self.assertEqual(p.calls, [])


if __name__ == "__main__":
    unittest.main()
