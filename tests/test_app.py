"""主编排测试。"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ddns import app
from ddns.state import StateStore


def make_cfg(**over):
    base = dict(provider="cloudflare", record_type="AAAA",
                domain="example.com", sub_domain="home")
    base.update(over)
    return SimpleNamespace(**base)


class FakeProvider:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def update(self, record_id, ip):
        self.calls.append((record_id, ip))
        return self.ok


class TestStateKey(unittest.TestCase):
    def test_key_with_sub(self):
        self.assertEqual(app.state_key(make_cfg()),
                         "cloudflare:AAAA:home.example.com")

    def test_key_apex(self):
        self.assertEqual(app.state_key(make_cfg(sub_domain="@")),
                         "cloudflare:AAAA:example.com")


class TestRunOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "state.json"
        self.store = StateStore(self.tmp)
        self.key = "k"

    def test_ip_unchanged_no_update(self):
        provider = FakeProvider()
        with mock.patch.object(app, "get_current_ip", return_value="2409:8a1e::1"):
            result = app.run_once(provider, "r", self.store, self.key, "AAAA", "2409:8a1e::1")
        self.assertEqual(result, "2409:8a1e::1")
        self.assertEqual(provider.calls, [])

    def test_ip_changed_updates_and_persists(self):
        provider = FakeProvider()
        with mock.patch.object(app, "get_current_ip", return_value="2409:8a1e::2"):
            result = app.run_once(provider, "r9", self.store, self.key, "AAAA", "2409:8a1e::1")
        self.assertEqual(result, "2409:8a1e::2")
        self.assertEqual(provider.calls, [("r9", "2409:8a1e::2")])
        self.assertEqual(self.store.get(self.key), "2409:8a1e::2")

    def test_update_failure_keeps_last(self):
        provider = FakeProvider(ok=False)
        with mock.patch.object(app, "get_current_ip", return_value="2409:8a1e::2"):
            result = app.run_once(provider, "r", self.store, self.key, "AAAA", "2409:8a1e::1")
        self.assertEqual(result, "2409:8a1e::1")
        self.assertIsNone(self.store.get(self.key))

    def test_no_ip_keeps_last(self):
        provider = FakeProvider()
        with mock.patch.object(app, "get_current_ip", return_value=None):
            result = app.run_once(provider, "r", self.store, self.key, "AAAA", "2409:8a1e::1")
        self.assertEqual(result, "2409:8a1e::1")
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
