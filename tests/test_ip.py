"""IP 探测模块测试。"""
import unittest
from unittest import mock

from ddns import ip as ipmod
from tests.fakes import FakeResp, FakeSession


class TestIsValidPublicIP(unittest.TestCase):
    def test_public_v6_ok(self):
        self.assertTrue(ipmod.is_valid_public_ip("2409:8a1e:991c::1", "AAAA"))

    def test_public_v4_ok(self):
        self.assertTrue(ipmod.is_valid_public_ip("1.1.1.1", "A"))

    def test_strips_whitespace(self):
        self.assertTrue(ipmod.is_valid_public_ip("  2409:8a1e::1\n", "AAAA"))

    def test_rejects_loopback(self):
        self.assertFalse(ipmod.is_valid_public_ip("::1", "AAAA"))
        self.assertFalse(ipmod.is_valid_public_ip("127.0.0.1", "A"))

    def test_rejects_link_local(self):
        self.assertFalse(ipmod.is_valid_public_ip("fe80::1", "AAAA"))
        self.assertFalse(ipmod.is_valid_public_ip("169.254.1.1", "A"))

    def test_rejects_ula_and_private(self):
        self.assertFalse(ipmod.is_valid_public_ip("fd00::1", "AAAA"))
        self.assertFalse(ipmod.is_valid_public_ip("fc00::1", "AAAA"))
        self.assertFalse(ipmod.is_valid_public_ip("192.168.1.1", "A"))
        self.assertFalse(ipmod.is_valid_public_ip("100.64.0.1", "A"))  # CGNAT

    def test_rejects_unspecified(self):
        self.assertFalse(ipmod.is_valid_public_ip("::", "AAAA"))

    def test_rejects_wrong_family_and_html(self):
        self.assertFalse(ipmod.is_valid_public_ip("1.2.3.4", "AAAA"))
        self.assertFalse(ipmod.is_valid_public_ip("<html>Error: 502</html>", "AAAA"))

    def test_rejects_empty(self):
        self.assertFalse(ipmod.is_valid_public_ip("", "AAAA"))
        self.assertFalse(ipmod.is_valid_public_ip("   ", "AAAA"))


class TestGetPublicIP(unittest.TestCase):
    def test_first_api_success_v6(self):
        good = "2409:8a1e:991c:c4b0:eca8:8231:7682:a471"
        session = FakeSession({ipmod.IP_APIS["AAAA"][0]: FakeResp(good)})
        self.assertEqual(ipmod.get_public_ip("AAAA", http=session), good)

    def test_first_api_success_v4(self):
        session = FakeSession({ipmod.IP_APIS["A"][0]: FakeResp("8.8.8.8")})
        self.assertEqual(ipmod.get_public_ip("A", http=session), "8.8.8.8")

    def test_fallback_to_second_api(self):
        good = "2409:8a1e::1"
        session = FakeSession({
            ipmod.IP_APIS["AAAA"][0]: RuntimeError("conn refused"),
            ipmod.IP_APIS["AAAA"][1]: FakeResp(good),
        })
        self.assertEqual(ipmod.get_public_ip("AAAA", http=session), good)

    def test_all_apis_fail_returns_none(self):
        session = FakeSession(
            {u: RuntimeError("down") for u in ipmod.IP_APIS["A"]})
        self.assertIsNone(ipmod.get_public_ip("A", http=session))

    def test_html_error_page_rejected(self):
        session = FakeSession(
            {u: FakeResp("<html><body>Error: 502 Bad Gateway</body></html>")
             for u in ipmod.IP_APIS["AAAA"]})
        self.assertIsNone(ipmod.get_public_ip("AAAA", http=session))

    def test_multiline_takes_first_line(self):
        session = FakeSession({ipmod.IP_APIS["AAAA"][0]: FakeResp("2409:8a1e::1\nextra")})
        self.assertEqual(ipmod.get_public_ip("AAAA", http=session), "2409:8a1e::1")

    def test_empty_response_rejected(self):
        session = FakeSession({u: FakeResp("") for u in ipmod.IP_APIS["A"]})
        self.assertIsNone(ipmod.get_public_ip("A", http=session))

    def test_http_error_status_triggers_fallback(self):
        good = "2409:8a1e::5"
        session = FakeSession({
            ipmod.IP_APIS["AAAA"][0]: FakeResp("", status=503),
            ipmod.IP_APIS["AAAA"][1]: FakeResp(good),
        })
        self.assertEqual(ipmod.get_public_ip("AAAA", http=session), good)

    def test_v4_private_response_rejected(self):
        session = FakeSession({u: FakeResp("10.0.0.1") for u in ipmod.IP_APIS["A"]})
        self.assertIsNone(ipmod.get_public_ip("A", http=session))


class TestGetLocalIP(unittest.TestCase):
    def test_success_v6(self):
        fake_sock = mock.MagicMock()
        fake_sock.getsockname.return_value = ("2409:8a1e::9", 80, 0, 0)
        with mock.patch.object(ipmod.socket, "socket", return_value=fake_sock):
            self.assertEqual(ipmod.get_local_ip("AAAA"), "2409:8a1e::9")
        fake_sock.close.assert_called_once()
        fake_sock.connect.assert_called_once_with(ipmod.PROBE_TARGETS["AAAA"])

    def test_success_v4(self):
        fake_sock = mock.MagicMock()
        fake_sock.getsockname.return_value = ("8.8.8.8", 80)
        with mock.patch.object(ipmod.socket, "socket", return_value=fake_sock):
            self.assertEqual(ipmod.get_local_ip("A"), "8.8.8.8")
        fake_sock.connect.assert_called_once_with(ipmod.PROBE_TARGETS["A"])

    def test_socket_creation_failure_returns_none(self):
        with mock.patch.object(ipmod.socket, "socket", side_effect=OSError("no ipv6")):
            self.assertIsNone(ipmod.get_local_ip("AAAA"))

    def test_connect_failure_returns_none_and_closes(self):
        fake_sock = mock.MagicMock()
        fake_sock.connect.side_effect = OSError("unreachable")
        with mock.patch.object(ipmod.socket, "socket", return_value=fake_sock):
            self.assertIsNone(ipmod.get_local_ip("AAAA"))
        fake_sock.close.assert_called_once()

    def test_private_address_rejected(self):
        fake_sock = mock.MagicMock()
        fake_sock.getsockname.return_value = ("fd00::1", 80, 0, 0)
        with mock.patch.object(ipmod.socket, "socket", return_value=fake_sock):
            self.assertIsNone(ipmod.get_local_ip("AAAA"))

    def test_unsupported_record_type_raises(self):
        with self.assertRaises(ValueError):
            ipmod.get_local_ip("TXT")


class TestGetCurrentIP(unittest.TestCase):
    def _patch(self, local, public):
        return mock.patch.multiple(
            ipmod,
            get_local_ip=mock.Mock(return_value=local),
            get_public_ip=mock.Mock(return_value=public),
        )

    def test_both_equal_returns_that(self):
        with self._patch("2409:8a1e::1", "2409:8a1e::1"):
            self.assertEqual(ipmod.get_current_ip("AAAA"), "2409:8a1e::1")

    def test_mismatch_prefers_public(self):
        with self._patch("fd00::1", "2409:8a1e::1"):
            self.assertEqual(ipmod.get_current_ip("AAAA"), "2409:8a1e::1")

    def test_only_public(self):
        with self._patch(None, "2409:8a1e::1"):
            self.assertEqual(ipmod.get_current_ip("AAAA"), "2409:8a1e::1")

    def test_only_local_fallback(self):
        with self._patch("2409:8a1e::1", None):
            self.assertEqual(ipmod.get_current_ip("AAAA"), "2409:8a1e::1")

    def test_both_none(self):
        with self._patch(None, None):
            self.assertIsNone(ipmod.get_current_ip("AAAA"))


if __name__ == "__main__":
    unittest.main()
