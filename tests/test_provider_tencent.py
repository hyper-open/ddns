"""腾讯云 DNSPod 服务商测试（注入假 client/models，无需真实 SDK）。"""
import unittest

from ddns.providers.base import Target
from ddns.providers.tencent import TencentProvider


class SdkError(Exception):
    pass


class FakeRequest:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeModels:
    DescribeRecordListRequest = FakeRequest
    ModifyRecordRequest = FakeRequest


class FakeRec:
    def __init__(self, rid, ip=None):
        self.RecordId = rid
        self.Value = ip


class FakeDescribeResp:
    def __init__(self, records):
        self.RecordList = records


class FakeModifyResp:
    def __init__(self, rid):
        self.RecordId = rid


class FakeClient:
    def __init__(self, records=None, modify_ok=True):
        self._records = records if records is not None else []
        self._modify_ok = modify_ok
        self.last_req = None

    def DescribeRecordList(self, req):
        self.last_req = req
        return FakeDescribeResp(self._records)

    def ModifyRecord(self, req):
        self.last_req = req
        if not self._modify_ok:
            raise SdkError("boom")
        return FakeModifyResp(req.RecordId)


def make_provider(client, target=None):
    target = target or Target("example.com", "home", "AAAA", 600)
    return TencentProvider(target, client, models=FakeModels, sdk_error=SdkError)


class TestResolveRecordId(unittest.TestCase):
    def test_found(self):
        provider = make_provider(FakeClient(records=[FakeRec(123)]))
        self.assertEqual(provider.resolve_record_id(), 123)

    def test_empty_returns_none(self):
        provider = make_provider(FakeClient(records=[]))
        self.assertIsNone(provider.resolve_record_id())

    def test_sdk_exception_returns_none(self):
        client = FakeClient()
        client.DescribeRecordList = lambda req: (_ for _ in ()).throw(SdkError("x"))
        provider = make_provider(client)
        self.assertIsNone(provider.resolve_record_id())

    def test_request_uses_prefix_host(self):
        client = FakeClient(records=[FakeRec(9)])
        provider = make_provider(client)
        provider.resolve_record_id()
        self.assertEqual(client.last_req.Domain, "example.com")
        self.assertEqual(client.last_req.Subdomain, "home")
        self.assertEqual(client.last_req.RecordType, "AAAA")


class TestUpdate(unittest.TestCase):
    def test_success(self):
        client = FakeClient()
        provider = make_provider(client)
        self.assertTrue(provider.update(123, "2409:8a1e::1"))
        self.assertEqual(client.last_req.RecordId, 123)
        self.assertEqual(client.last_req.Value, "2409:8a1e::1")
        self.assertEqual(client.last_req.SubDomain, "home")
        self.assertEqual(client.last_req.RecordType, "AAAA")
        self.assertEqual(client.last_req.TTL, 600)

    def test_failure(self):
        provider = make_provider(FakeClient(modify_ok=False))
        self.assertFalse(provider.update(123, "2409:8a1e::1"))

    def test_apex_uses_at(self):
        client = FakeClient()
        provider = make_provider(client, Target("example.com", "", "A"))
        provider.update(1, "1.1.1.1")
        self.assertEqual(client.last_req.SubDomain, "@")
        self.assertEqual(client.last_req.RecordType, "A")


if __name__ == "__main__":
    unittest.main()
