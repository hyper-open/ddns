"""状态存储测试。"""
import json
import tempfile
import unittest
from pathlib import Path

from ddns.state import StateStore


class TestStateStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "state.json"

    def test_get_missing_returns_none(self):
        self.assertIsNone(StateStore(self.tmp).get("k"))

    def test_set_then_get(self):
        store = StateStore(self.tmp)
        store.set("k", "2409:8a1e::1")
        self.assertEqual(StateStore(self.tmp).get("k"), "2409:8a1e::1")

    def test_persists_multiple_keys(self):
        store = StateStore(self.tmp)
        store.set("a", "1.1.1.1")
        store.set("b", "2409:8a1e::1")
        reloaded = StateStore(self.tmp)
        self.assertEqual(reloaded.get("a"), "1.1.1.1")
        self.assertEqual(reloaded.get("b"), "2409:8a1e::1")

    def test_corrupt_file_treated_as_empty(self):
        self.tmp.write_text("{not json")
        self.assertIsNone(StateStore(self.tmp).get("k"))

    def test_non_dict_json_treated_as_empty(self):
        self.tmp.write_text(json.dumps(["a", "b"]))
        self.assertIsNone(StateStore(self.tmp).get("k"))


if __name__ == "__main__":
    unittest.main()
