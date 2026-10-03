"""华为云 DNS 服务商测试（注入假 client/models，无需真实 SDK）。"""
import unittest

from ddns.providers.base import Target
from ddns.providers.huawei import HuaweiProvider


class FakeRequest:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeModels:
    ListPublicZonesRequest = FakeRequest
    ListRecordSetsByZoneRequest = FakeRequest
    UpdateRecordSetRequest = FakeRequest


class FakeZone:
    def __init__(self, zid):
        self.id = zid


class FakeRecordSet:
    def __init__(self, rid):
        self.id = rid


class FakeResp:
    def __init__(self, zones=None, recordsets=None):
        self.zones = zones
        self.recordsets = recordsets


class FakeClient:
    def __init__(self, zones=None, recordsets=None, raise_on_update=False):
        self._zones = zones if zones is not None else [FakeZone("z1")]
        self._recordsets = recordsets if recordsets is not None else [FakeRecordSet("r1")]
        self._raise = raise_on_update
        self.last_req = None

    def list_public_zones(self, req):
        return FakeResp(zones=self._zones)

    def list_record_sets_by_zone(self, req):
        self.last_req = req
        return FakeResp(recordsets=self._recordsets)

    def update_record_set(self, req):
        self.last_req = req
        if self._raise:
            raise RuntimeError("boom")
        return object()


def make_provider(client, target=None):
    target = target or Target("example.com", "home", "AAAA", 600)
    return HuaweiProvider(target, client, FakeModels)


class TestResolveRecordId(unittest.TestCase):
    def test_found(self):
        self.assertEqual(make_provider(FakeClient()).resolve_record_id(), "r1")

    def test_zone_not_found(self):
        self.assertIsNone(make_provider(FakeClient(zones=[])).resolve_record_id())

    def test_record_not_found(self):
        self.assertIsNone(make_provider(FakeClient(recordsets=[])).resolve_record_id())

    def test_exception_returns_none(self):
        client = FakeClient()
        client.list_record_sets_by_zone = lambda req: (_ for _ in ()).throw(RuntimeError("x"))
        self.assertIsNone(make_provider(client).resolve_record_id())

    def test_request_uses_fqdn(self):
        client = FakeClient()
        make_provider(client).resolve_record_id()
        self.assertEqual(client.last_req.zone_id, "z1")
        self.assertEqual(client.last_req.type, "AAAA")
        self.assertEqual(client.last_req.name, "home.example.com")


class TestUpdate(unittest.TestCase):
    def test_success(self):
        client = FakeClient()
        self.assertTrue(make_provider(client).update("r1", "2409:8a1e::1"))
        self.assertEqual(client.last_req.zone_id, "z1")
        self.assertEqual(client.last_req.recordset_id, "r1")
        self.assertEqual(client.last_req.records, ["2409:8a1e::1"])

    def test_failure(self):
        self.assertFalse(make_provider(FakeClient(raise_on_update=True))
                         .update("r1", "2409:8a1e::1"))

    def test_apex_uses_domain_as_fqdn(self):
        client = FakeClient()
        make_provider(client, Target("example.com", "", "A")).resolve_record_id()
        self.assertEqual(client.last_req.name, "example.com")


if __name__ == "__main__":
    unittest.main()
