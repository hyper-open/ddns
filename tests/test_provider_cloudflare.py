"""Cloudflare 服务商测试（用假 requests session，无网络）。"""
import unittest

from ddns.providers.base import Target
from ddns.providers.cloudflare import CloudflareProvider
from tests.fakes import FakeResp, FakeSession


def cf_responder(zones=None, records=None, patch_ok=True):
    zones = zones if zones is not None else [{"id": "zone1", "name": "example.com"}]
    records = records if records is not None else [{"id": "rec1"}]

    def responder(method, url, kwargs):
        if method == "GET" and "/dns_records" in url:
            return FakeResp(payload={"success": True, "result": records})
        if method == "GET" and url.endswith("/zones"):
            return FakeResp(payload={"success": True, "result": zones})
        if method == "PATCH":
            if not patch_ok:
                return FakeResp(payload={"success": False, "errors": [{"message": "no"}]})
            return FakeResp(payload={"success": True, "result": {}})
        return FakeResp(payload={"success": False, "errors": [{"message": "unexpected"}]})

    return responder


def make_provider(session, target=None, zone_id=None):
    target = target or Target("example.com", "home", "AAAA")
    return CloudflareProvider(target, "token", zone_id, session=session)


class TestResolveRecordId(unittest.TestCase):
    def test_found_with_zone_lookup(self):
        session = FakeSession(responder=cf_responder())
        self.assertEqual(make_provider(session).resolve_record_id(), "rec1")

    def test_uses_given_zone_id_skips_lookup(self):
        session = FakeSession(responder=cf_responder())
        self.assertEqual(make_provider(session, zone_id="z9").resolve_record_id(), "rec1")
        zone_calls = [c for c in session.requests if c[1].endswith("/zones")]
        self.assertEqual(zone_calls, [])

    def test_zone_not_found(self):
        session = FakeSession(responder=cf_responder(zones=[]))
        self.assertIsNone(make_provider(session).resolve_record_id())

    def test_record_not_found(self):
        session = FakeSession(responder=cf_responder(records=[]))
        self.assertIsNone(make_provider(session).resolve_record_id())

    def test_api_error_returns_none(self):
        session = FakeSession(responder=lambda m, u, k: FakeResp(status=500))
        self.assertIsNone(make_provider(session).resolve_record_id())


class TestUpdate(unittest.TestCase):
    def test_success(self):
        session = FakeSession(responder=cf_responder())
        self.assertTrue(make_provider(session).update("rec1", "2409:8a1e::1"))
        patch = [r for r in session.requests if r[0] == "PATCH"]
        self.assertEqual(len(patch), 1)
        self.assertEqual(patch[0][2]["json"], {"content": "2409:8a1e::1"})

    def test_failure_success_false(self):
        session = FakeSession(responder=cf_responder(patch_ok=False))
        self.assertFalse(make_provider(session).update("rec1", "2409:8a1e::1"))

    def test_a_record_sets_proxied(self):
        session = FakeSession(responder=cf_responder())
        provider = make_provider(session, Target("example.com", "home", "A"))
        provider.update("rec1", "1.1.1.1")
        patch = [r for r in session.requests if r[0] == "PATCH"]
        self.assertEqual(patch[0][2]["json"], {"content": "1.1.1.1", "proxied": False})


if __name__ == "__main__":
    unittest.main()
