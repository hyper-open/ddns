"""阿里云云解析服务商测试（注入假 client/models，无需真实 SDK）。"""
import unittest

from ddns.providers.aliyun import AliyunProvider
from ddns.providers.base import Target


class FakeRequest:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeModels:
    DescribeDomainRecordsRequest = FakeRequest
    UpdateDomainRecordRequest = FakeRequest


class FakeRecord:
    def __init__(self, rid):
        self.record_id = rid


class FakeBody:
    def __init__(self, records):
        self.domain_records = type("R", (), {"record": records})()


class FakeResp:
    def __init__(self, records):
        self.body = FakeBody(records)


class FakeClient:
    def __init__(self, records=None, raise_on_update=False):
        self._records = records if records is not None else []
        self._raise = raise_on_update
        self.last_req = None

    def describe_domain_records(self, req):
        self.last_req = req
        return FakeResp(self._records)

    def update_domain_record(self, req):
        self.last_req = req
        if self._raise:
            raise RuntimeError("boom")
        return object()


def make_provider(client, target=None):
    target = target or Target("example.com", "home", "AAAA", 600)
    return AliyunProvider(target, client, FakeModels)


class TestResolveRecordId(unittest.TestCase):
    def test_found(self):
        provider = make_provider(FakeClient(records=[FakeRecord("99")]))
        self.assertEqual(provider.resolve_record_id(), "99")

    def test_empty_returns_none(self):
        self.assertIsNone(make_provider(FakeClient(records=[])).resolve_record_id())

    def test_exception_returns_none(self):
        client = FakeClient()
        client.describe_domain_records = lambda req: (_ for _ in ()).throw(RuntimeError("x"))
        self.assertIsNone(make_provider(client).resolve_record_id())

    def test_request_uses_prefix_host(self):
        client = FakeClient(records=[FakeRecord("1")])
        make_provider(client).resolve_record_id()
        self.assertEqual(client.last_req.domain_name, "example.com")
        self.assertEqual(client.last_req.rr, "home")
        self.assertEqual(client.last_req.type, "AAAA")


class TestUpdate(unittest.TestCase):
    def test_success(self):
        client = FakeClient()
        self.assertTrue(make_provider(client).update("99", "2409:8a1e::1"))
        self.assertEqual(client.last_req.record_id, "99")
        self.assertEqual(client.last_req.value, "2409:8a1e::1")
        self.assertEqual(client.last_req.ttl, 600)

    def test_failure(self):
        self.assertFalse(make_provider(FakeClient(raise_on_update=True))
                         .update("99", "2409:8a1e::1"))

    def test_apex_uses_at(self):
        client = FakeClient()
        make_provider(client, Target("example.com", "@", "A")).update("1", "1.1.1.1")
        self.assertEqual(client.last_req.rr, "@")
        self.assertEqual(client.last_req.type, "A")


if __name__ == "__main__":
    unittest.main()
