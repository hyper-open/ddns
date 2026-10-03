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

    def test_record_source_carried_to_entry(self):
        cfg = SimpleNamespace(provider="cloudflare", records=[
            RecordTarget("example.com", "home", "AAAA", 600, source="eth0"),
            RecordTarget("example.com", "www", "A", 300, source=""),
        ])
        with mock.patch.object(app, "get_provider",
                               return_value=FakeProviderClass([])):
            entries = app._build_entries(cfg)
        self.assertEqual(entries["home.example.com"].source, "eth0")
        self.assertEqual(entries["www.example.com"].source, "")

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


class FakeEntry:
    def __init__(self, target, provider, record_id=None, last_ip=None, source=""):
        self.target = target
        self.provider = provider
        self.record_id = record_id
        self.last_ip = last_ip
        self.source = source


class TestSyncOnce(unittest.TestCase):
    """直接测试 app.sync_once（真实扇出逻辑）。"""

    def _patched(self, ipmap):
        """ipmap: (record_type, source) -> ip，或 record_type -> ip。"""
        calls = []

        def fake(rt, source=None):
            calls.append((rt, source))
            if (rt, source) in ipmap:
                return ipmap[(rt, source)]
            return ipmap.get(rt)

        return mock.patch.object(app, "get_current_ip", side_effect=fake), calls

    def test_same_type_same_source_probed_once(self):
        t1 = Target("example.com", "home", "AAAA")
        t2 = Target("example.com", "www", "AAAA")
        p1, p2 = FakeProvider(), FakeProvider()
        entries = [FakeEntry(t1, p1, "r1"), FakeEntry(t2, p2, "r2")]
        with self._patched({"AAAA": "2409:8a1e::9"})[0]:
            app.sync_once(entries, None, "cloudflare")
        self.assertEqual(p1.calls, [("r1", "2409:8a1e::9")])
        self.assertEqual(p2.calls, [("r2", "2409:8a1e::9")])

    def test_mixed_record_types(self):
        ta = Target("example.com", "home", "AAAA")
        tb = Target("example.com", "www", "A")
        pa, pb = FakeProvider(), FakeProvider()
        entries = [FakeEntry(ta, pa, "r1"), FakeEntry(tb, pb, "r2")]
        with self._patched({"AAAA": "2409:8a1e::9", "A": "1.1.1.1"})[0]:
            app.sync_once(entries, None, "cloudflare")
        self.assertEqual(pa.calls, [("r1", "2409:8a1e::9")])
        self.assertEqual(pb.calls, [("r2", "1.1.1.1")])

    def test_different_sources_probed_separately(self):
        t1 = Target("example.com", "home1", "AAAA")
        t2 = Target("example.com", "home2", "AAAA")
        p1, p2 = FakeProvider(), FakeProvider()
        entries = [
            FakeEntry(t1, p1, "r1", source="eth0"),
            FakeEntry(t2, p2, "r2", source="2001:db8::10"),
        ]
        ipmap = {("AAAA", "eth0"): "2409:8a1e::1",
                 ("AAAA", "2001:db8::10"): "2409:8a1e::2"}
        patcher, calls = self._patched(ipmap)
        with patcher:
            n_probes, _ = app.sync_once(entries, None, "cloudflare")
        self.assertEqual(n_probes, 2)  # 两个出口分别探测
        self.assertEqual(p1.calls, [("r1", "2409:8a1e::1")])
        self.assertEqual(p2.calls, [("r2", "2409:8a1e::2")])

    def test_same_source_reused_across_records(self):
        t1 = Target("example.com", "a", "AAAA")
        t2 = Target("example.com", "b", "AAAA")
        p1, p2 = FakeProvider(), FakeProvider()
        entries = [
            FakeEntry(t1, p1, "r1", source="eth0"),
            FakeEntry(t2, p2, "r2", source="eth0"),
        ]
        patcher, calls = self._patched({("AAAA", "eth0"): "2409:8a1e::1"})
        with patcher:
            n_probes, _ = app.sync_once(entries, None, "cloudflare")
        self.assertEqual(n_probes, 1)  # 同出口只探测一次
        self.assertEqual(calls, [("AAAA", "eth0")])
        self.assertEqual(p1.calls, [("r1", "2409:8a1e::1")])
        self.assertEqual(p2.calls, [("r2", "2409:8a1e::1")])

    def test_unchanged_skipped(self):
        t = Target("example.com", "home", "AAAA")
        p = FakeProvider()
        entries = [FakeEntry(t, p, "r1", last_ip="2409:8a1e::9")]
        with self._patched({"AAAA": "2409:8a1e::9"})[0]:
            app.sync_once(entries, None, "cloudflare")
        self.assertEqual(p.calls, [])

    def test_missing_ip_skipped(self):
        t = Target("example.com", "home", "AAAA")
        p = FakeProvider()
        entries = [FakeEntry(t, p, "r1")]
        with self._patched({"AAAA": None})[0]:
            app.sync_once(entries, None, "cloudflare")
        self.assertEqual(p.calls, [])

    def test_state_persisted_on_success(self):
        store = StateStore(Path(tempfile.mkdtemp()) / "state.json")
        t = Target("example.com", "home", "AAAA")
        entries = [FakeEntry(t, FakeProvider(), "r1")]
        with self._patched({"AAAA": "2409:8a1e::9"})[0]:
            app.sync_once(entries, store, "cloudflare")
        self.assertEqual(store.get("cloudflare:AAAA:home.example.com"),
                         "2409:8a1e::9")


class TestStablePolicy(unittest.TestCase):
    """update_policy="stable" 的跳过/更新分支。"""

    def _run(self, entries, new_ip, policy, same_prefix, has_local):
        with mock.patch.multiple(
            app,
            get_current_ip=mock.Mock(return_value=new_ip),
            is_same_prefix=mock.Mock(return_value=same_prefix),
            has_local_address=mock.Mock(return_value=has_local),
        ):
            return app.sync_once(entries, None, "cloudflare", policy)

    def _entry(self, rt="AAAA", last_ip="2409:8a1e:991c:c4b0:0001::1"):
        t = Target("example.com", "home", rt)
        p = FakeProvider()
        return FakeEntry(t, p, "r1", last_ip=last_ip), p

    def test_skip_when_same_prefix_and_old_still_present(self):
        entry, p = self._entry()
        with mock.patch.multiple(
            app, get_current_ip=mock.Mock(return_value="2409:8a1e:991c:c4b0:0002::2"),
            is_same_prefix=mock.Mock(return_value=True),
            has_local_address=mock.Mock(return_value=True),
        ):
            app.sync_once([entry], None, "cloudflare", "stable")
        self.assertEqual(p.calls, [])            # 跳过，不更新
        self.assertEqual(entry.last_ip, "2409:8a1e:991c:c4b0:0001::1")

    def test_update_when_old_address_gone(self):
        # 旧地址已从系统消失 → 必须更新，避免 DNS 指向失效地址
        entry, p = self._entry()
        with mock.patch.multiple(
            app, get_current_ip=mock.Mock(return_value="2409:8a1e:991c:c4b0:0002::2"),
            is_same_prefix=mock.Mock(return_value=True),
            has_local_address=mock.Mock(return_value=False),
        ):
            _, updates = app.sync_once([entry], None, "cloudflare", "stable")
        self.assertEqual(len(p.calls), 1)
        self.assertEqual(updates, 1)

    def test_update_when_prefix_changed(self):
        entry, p = self._entry()
        with mock.patch.multiple(
            app, get_current_ip=mock.Mock(return_value="2409:8a1e:9fff::2"),
            is_same_prefix=mock.Mock(return_value=False),
            has_local_address=mock.Mock(return_value=True),
        ):
            _, updates = app.sync_once([entry], None, "cloudflare", "stable")
        self.assertEqual(updates, 1)

    def test_ipv4_not_skipped_by_stable_policy(self):
        entry, p = self._entry(rt="A", last_ip="8.8.8.1")
        with mock.patch.multiple(
            app, get_current_ip=mock.Mock(return_value="8.8.8.2"),
            is_same_prefix=mock.Mock(return_value=True),
            has_local_address=mock.Mock(return_value=True),
        ):
            _, updates = app.sync_once([entry], None, "cloudflare", "stable")
        self.assertEqual(updates, 1)  # 仅 IPv6 生效

    def test_exact_policy_always_updates(self):
        entry, p = self._entry()
        with mock.patch.multiple(
            app, get_current_ip=mock.Mock(return_value="2409:8a1e:991c:c4b0:0002::2"),
            is_same_prefix=mock.Mock(return_value=True),
            has_local_address=mock.Mock(return_value=True),
        ):
            _, updates = app.sync_once([entry], None, "cloudflare", "exact")
        self.assertEqual(updates, 1)  # exact 不看前缀

    def test_no_last_ip_updates(self):
        entry, p = self._entry(last_ip=None)
        with mock.patch.multiple(
            app, get_current_ip=mock.Mock(return_value="2409:8a1e:991c:c4b0:0002::2"),
            is_same_prefix=mock.Mock(return_value=True),
            has_local_address=mock.Mock(return_value=True),
        ):
            _, updates = app.sync_once([entry], None, "cloudflare", "stable")
        self.assertEqual(updates, 1)  # 首次没有旧值，正常更新


if __name__ == "__main__":
    unittest.main()
