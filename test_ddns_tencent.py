"""ddns_tencent 边界情况与单元测试。

运行:
    cd ddns && python -m unittest -v test_ddns_tencent
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 在导入被测模块前设置占位凭据，避免模块级 RuntimeError；
# load_dotenv 默认不覆盖已有环境变量，故 .env 中的真实值不会覆盖这里。
os.environ.setdefault("TENCENT_SECRET_ID", "test-id")
os.environ.setdefault("TENCENT_SECRET_KEY", "test-key")
os.environ.setdefault("DDNS_DOMAIN", "example.com")
os.environ.setdefault("DDNS_SUB_DOMAIN", "home")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ddns_tencent as ddns  # noqa: E402


class FakeResp:
    def __init__(self, text, status=200):
        self.text = text
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


class FakeSession:
    """按 url 返回预设响应；值可为异常实例以示连接失败。"""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        val = self.mapping.get(url, RuntimeError("no route"))
        if isinstance(val, Exception):
            raise val
        return val


class TestIsValidPublicIPv6(unittest.TestCase):
    def test_public_address_ok(self):
        self.assertTrue(ddns.is_valid_public_ipv6("2409:8a1e:991c::1"))

    def test_strips_whitespace(self):
        self.assertTrue(ddns.is_valid_public_ipv6("  2409:8a1e::1\n"))

    def test_rejects_loopback(self):
        self.assertFalse(ddns.is_valid_public_ipv6("::1"))

    def test_rejects_link_local(self):
        self.assertFalse(ddns.is_valid_public_ipv6("fe80::1"))

    def test_rejects_ula(self):
        self.assertFalse(ddns.is_valid_public_ipv6("fd00::1"))
        self.assertFalse(ddns.is_valid_public_ipv6("fc00::1"))

    def test_rejects_unspecified(self):
        self.assertFalse(ddns.is_valid_public_ipv6("::"))

    def test_rejects_ipv4_and_html(self):
        self.assertFalse(ddns.is_valid_public_ipv6("1.2.3.4"))
        self.assertFalse(ddns.is_valid_public_ipv6("<html>Error: 502</html>"))

    def test_rejects_empty_and_none_like(self):
        self.assertFalse(ddns.is_valid_public_ipv6(""))
        self.assertFalse(ddns.is_valid_public_ipv6("   "))


class TestGetPublicIPv6(unittest.TestCase):
    def setUp(self):
        self._orig = ddns.session
        self.addCleanup(lambda: setattr(ddns, "session", self._orig))

    def test_first_api_success(self):
        good = "2409:8a1e:991c:c4b0:eca8:8231:7682:a471"
        ddns.session = FakeSession({ddns.IPV6_APIS[0]: FakeResp(good)})
        self.assertEqual(ddns.get_public_ipv6(), good)

    def test_fallback_to_second_api(self):
        good = "2409:8a1e::1"
        ddns.session = FakeSession({
            ddns.IPV6_APIS[0]: RuntimeError("conn refused"),
            ddns.IPV6_APIS[1]: FakeResp(good),
        })
        self.assertEqual(ddns.get_public_ipv6(), good)

    def test_all_apis_fail_returns_none(self):
        ddns.session = FakeSession({u: RuntimeError("down") for u in ddns.IPV6_APIS})
        self.assertIsNone(ddns.get_public_ipv6())

    def test_html_error_page_rejected(self):
        """回归: 含冒号的 HTML 错误页不能被当作 IPv6。"""
        ddns.session = FakeSession(
            {u: FakeResp("<html><body>Error: 502 Bad Gateway</body></html>")
             for u in ddns.IPV6_APIS})
        self.assertIsNone(ddns.get_public_ipv6())

    def test_multiline_takes_first_line(self):
        ddns.session = FakeSession({ddns.IPV6_APIS[0]: FakeResp("2409:8a1e::1\nextra")})
        self.assertEqual(ddns.get_public_ipv6(), "2409:8a1e::1")

    def test_empty_response_rejected(self):
        ddns.session = FakeSession({u: FakeResp("") for u in ddns.IPV6_APIS})
        self.assertIsNone(ddns.get_public_ipv6())

    def test_http_error_status_triggers_fallback(self):
        good = "2409:8a1e::5"
        ddns.session = FakeSession({
            ddns.IPV6_APIS[0]: FakeResp("", status=503),
            ddns.IPV6_APIS[1]: FakeResp(good),
        })
        self.assertEqual(ddns.get_public_ipv6(), good)


class TestGetLocalIPv6(unittest.TestCase):
    def test_success(self):
        fake_sock = mock.MagicMock()
        fake_sock.getsockname.return_value = ("2409:8a1e::9", 80, 0, 0)
        with mock.patch.object(ddns.socket, "socket", return_value=fake_sock):
            self.assertEqual(ddns.get_local_ipv6(), "2409:8a1e::9")
        fake_sock.close.assert_called_once()
        fake_sock.connect.assert_called_once_with(ddns.PROBE_TARGET)

    def test_socket_creation_failure_returns_none(self):
        """回归: socket() 自身抛异常时不能崩溃，且 close 不应被误调。"""
        with mock.patch.object(ddns.socket, "socket", side_effect=OSError("no ipv6")):
            self.assertIsNone(ddns.get_local_ipv6())

    def test_connect_failure_returns_none_and_closes(self):
        fake_sock = mock.MagicMock()
        fake_sock.connect.side_effect = OSError("unreachable")
        with mock.patch.object(ddns.socket, "socket", return_value=fake_sock):
            self.assertIsNone(ddns.get_local_ipv6())
        fake_sock.close.assert_called_once()

    def test_private_address_rejected(self):
        fake_sock = mock.MagicMock()
        fake_sock.getsockname.return_value = ("fd00::1", 80, 0, 0)
        with mock.patch.object(ddns.socket, "socket", return_value=fake_sock):
            self.assertIsNone(ddns.get_local_ipv6())


class TestGetCurrentIPv6(unittest.TestCase):
    def _patch(self, local, public):
        return mock.patch.multiple(
            ddns, get_local_ipv6=mock.Mock(return_value=local),
            get_public_ipv6=mock.Mock(return_value=public))

    def test_both_equal_returns_that(self):
        with self._patch("2409:8a1e::1", "2409:8a1e::1"):
            self.assertEqual(ddns.get_current_ipv6(), "2409:8a1e::1")

    def test_mismatch_prefers_public(self):
        with self._patch("fd00::1", "2409:8a1e::1"):
            self.assertEqual(ddns.get_current_ipv6(), "2409:8a1e::1")

    def test_only_public(self):
        with self._patch(None, "2409:8a1e::1"):
            self.assertEqual(ddns.get_current_ipv6(), "2409:8a1e::1")

    def test_only_local_fallback(self):
        with self._patch("2409:8a1e::1", None):
            self.assertEqual(ddns.get_current_ipv6(), "2409:8a1e::1")

    def test_both_none(self):
        with self._patch(None, None):
            self.assertIsNone(ddns.get_current_ipv6())


class TestStateFile(unittest.TestCase):
    def setUp(self):
        self._orig = ddns.STATE_FILE
        self.tmp = Path(tempfile.mkdtemp()) / "last_ipv6.txt"
        ddns.STATE_FILE = self.tmp
        self.addCleanup(lambda: setattr(ddns, "STATE_FILE", self._orig))

    def test_read_missing_returns_none(self):
        self.assertIsNone(ddns.read_last_ip())

    def test_save_then_read(self):
        ddns.save_last_ip("2409:8a1e::1")
        self.assertEqual(ddns.read_last_ip(), "2409:8a1e::1")

    def test_read_strips_whitespace(self):
        self.tmp.write_text("  2409:8a1e::1\n")
        self.assertEqual(ddns.read_last_ip(), "2409:8a1e::1")


class TestDnsRecordOps(unittest.TestCase):
    def test_get_record_id_found(self):
        client = mock.MagicMock()
        rec = mock.MagicMock()
        rec.RecordId = 123
        client.DescribeRecordList.return_value.RecordList = [rec]
        self.assertEqual(ddns.get_record_id(client), 123)

    def test_get_record_id_empty(self):
        client = mock.MagicMock()
        client.DescribeRecordList.return_value.RecordList = []
        self.assertIsNone(ddns.get_record_id(client))

    def test_get_record_id_sdk_exception(self):
        client = mock.MagicMock()
        client.DescribeRecordList.side_effect = ddns.TencentCloudSDKException("err")
        self.assertIsNone(ddns.get_record_id(client))

    def test_update_success(self):
        client = mock.MagicMock()
        client.ModifyRecord.return_value.RecordId = 123
        self.assertTrue(ddns.update_dnspod_record(client, 123, "2409:8a1e::1"))

    def test_update_failure(self):
        client = mock.MagicMock()
        client.ModifyRecord.side_effect = ddns.TencentCloudSDKException("err")
        self.assertFalse(ddns.update_dnspod_record(client, 123, "2409:8a1e::1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
