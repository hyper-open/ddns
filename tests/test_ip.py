"""IP 探测模块测试。"""
import socket
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

    def test_binds_source_ip(self):
        fake_sock = mock.MagicMock()
        fake_sock.getsockname.return_value = ("8.8.8.8", 80)
        with mock.patch.object(ipmod.socket, "socket", return_value=fake_sock):
            self.assertEqual(ipmod.get_local_ip("A", source="192.168.1.2"), "8.8.8.8")
        fake_sock.bind.assert_called_once_with(("192.168.1.2", 0))
        fake_sock.connect.assert_called_once_with(ipmod.PROBE_TARGETS["A"])

    def test_no_bind_when_no_source(self):
        fake_sock = mock.MagicMock()
        fake_sock.getsockname.return_value = ("8.8.8.8", 80)
        with mock.patch.object(ipmod.socket, "socket", return_value=fake_sock):
            ipmod.get_local_ip("A")
        fake_sock.bind.assert_not_called()

    def test_binds_source_for_v6(self):
        fake_sock = mock.MagicMock()
        fake_sock.getsockname.return_value = ("2409:8a1e::9", 80, 0, 0)
        with mock.patch.object(ipmod.socket, "socket", return_value=fake_sock):
            self.assertEqual(ipmod.get_local_ip("AAAA", source="2001:db8::10"),
                             "2409:8a1e::9")
        fake_sock.bind.assert_called_once_with(("2001:db8::10", 0))


class TestResolveSource(unittest.TestCase):
    def test_empty_returns_none(self):
        self.assertIsNone(ipmod.resolve_source(None, "A"))
        self.assertIsNone(ipmod.resolve_source("", "A"))

    def test_ipv4_passthrough(self):
        self.assertEqual(ipmod.resolve_source("192.168.1.2", "A"), "192.168.1.2")

    def test_ipv6_passthrough(self):
        self.assertEqual(ipmod.resolve_source("2001:db8::10", "AAAA"), "2001:db8::10")

    def test_family_mismatch_raises(self):
        with self.assertRaises(ValueError):
            ipmod.resolve_source("192.168.1.2", "AAAA")

    def test_link_local_rejected(self):
        with self.assertRaises(ValueError):
            ipmod.resolve_source("fe80::1", "AAAA")

    def test_interface_name_resolved_via_psutil(self):
        snic4 = type("S", (), {"family": ipmod.socket.AF_INET,
                              "address": "192.168.1.2"})()
        snic6 = type("S", (), {"family": ipmod.socket.AF_INET6,
                              "address": "2001:db8::5%eth0"})()
        fake_psutil = mock.MagicMock()
        fake_psutil.net_if_addrs.return_value = {"eth0": [snic4, snic6]}
        with mock.patch.dict("sys.modules", {"psutil": fake_psutil}):
            self.assertEqual(ipmod.resolve_source("eth0", "AAAA"), "2001:db8::5")
            self.assertEqual(ipmod.resolve_source("eth0", "A"), "192.168.1.2")

    def test_unknown_interface_raises(self):
        fake_psutil = mock.MagicMock()
        fake_psutil.net_if_addrs.return_value = {"eth0": []}
        with mock.patch.dict("sys.modules", {"psutil": fake_psutil}):
            with self.assertRaises(ValueError):
                ipmod.resolve_source("nosuchif", "A")

    def test_interface_without_family_address_raises(self):
        snic4 = type("S", (), {"family": ipmod.socket.AF_INET,
                              "address": "192.168.1.2"})()
        fake_psutil = mock.MagicMock()
        fake_psutil.net_if_addrs.return_value = {"eth0": [snic4]}
        with mock.patch.dict("sys.modules", {"psutil": fake_psutil}):
            with self.assertRaises(ValueError):
                ipmod.resolve_source("eth0", "AAAA")


class TestSourcedSession(unittest.TestCase):
    def test_same_source_reuses_session(self):
        a = ipmod._session_for_source("192.168.1.2")
        b = ipmod._session_for_source("192.168.1.2")
        self.assertIs(a, b)

    def test_public_ip_uses_sourced_session(self):
        ipmod._sourced_sessions.clear()
        fake = FakeSession({ipmod.IP_APIS["A"][0]: FakeResp("8.8.8.8")})
        with mock.patch.object(ipmod, "_session_for_source", return_value=fake) as m:
            self.assertEqual(ipmod.get_public_ip("A", source="192.168.1.2"), "8.8.8.8")
        m.assert_called_once_with("192.168.1.2")

    def test_public_ip_default_session_when_no_source(self):
        fake = FakeSession({ipmod.IP_APIS["A"][0]: FakeResp("8.8.8.8")})
        with mock.patch.object(ipmod, "_session_for_source") as m:
            self.assertEqual(ipmod.get_public_ip("A", http=fake), "8.8.8.8")
        m.assert_not_called()


class TestIsSamePrefix(unittest.TestCase):
    def test_same_v6_prefix(self):
        a = "2409:8a1e:991c:c4b0:3f:abb5:22f6:483e"
        b = "2409:8a1e:991c:c4b0:eca8:8231:7682:a471"
        self.assertTrue(ipmod.is_same_prefix(a, b, "AAAA"))

    def test_different_v6_prefix(self):
        self.assertFalse(ipmod.is_same_prefix(
            "2409:8a1e:991c:c4b0::1", "2409:8a1e:991c:c4b1::1", "AAAA"))

    def test_same_v4_24(self):
        self.assertTrue(ipmod.is_same_prefix("8.8.8.1", "8.8.8.200", "A"))

    def test_different_v4_24(self):
        self.assertFalse(ipmod.is_same_prefix("8.8.8.1", "8.8.9.1", "A"))

    def test_cross_family_false(self):
        self.assertFalse(ipmod.is_same_prefix("8.8.8.1", "2409:8a1e::1", "AAAA"))

    def test_invalid_returns_false(self):
        self.assertFalse(ipmod.is_same_prefix("nope", "2409:8a1e::1", "AAAA"))


class TestHasLocalAddress(unittest.TestCase):
    def _fake_psutil(self, addrs):
        f = mock.MagicMock()
        f.net_if_addrs.return_value = addrs
        return f

    def _snic(self, family, address):
        return type("S", (), {"family": family, "address": address})()

    def test_found_including_deprecated(self):
        f = self._fake_psutil({
            "eth0": [self._snic(socket.AF_INET6, "2409:8a1e::9")]
        })
        with mock.patch.dict("sys.modules", {"psutil": f}):
            self.assertTrue(ipmod.has_local_address("2409:8a1e::9", "AAAA"))

    def test_zone_id_stripped(self):
        f = self._fake_psutil({
            "eth0": [self._snic(socket.AF_INET6, "fe80::1%eth0")]
        })
        with mock.patch.dict("sys.modules", {"psutil": f}):
            self.assertTrue(ipmod.has_local_address("fe80::1%eth0", "AAAA"))

    def test_not_found(self):
        f = self._fake_psutil({"eth0": []})
        with mock.patch.dict("sys.modules", {"psutil": f}):
            self.assertFalse(ipmod.has_local_address("2409:8a1e::9", "AAAA"))

    def test_wrong_family_not_matched(self):
        f = self._fake_psutil({
            "eth0": [self._snic(socket.AF_INET, "8.8.8.8")]
        })
        with mock.patch.dict("sys.modules", {"psutil": f}):
            self.assertFalse(ipmod.has_local_address("2409:8a1e::9", "AAAA"))

    def test_psutil_missing_returns_false(self):
        with mock.patch.dict("sys.modules", {"psutil": None}):
            self.assertFalse(ipmod.has_local_address("2409:8a1e::9", "AAAA"))


class TestPreferStableIPv6(unittest.TestCase):
    def test_picks_stable_in_same_prefix(self):
        stable = {"en0": ["2409:8a1e:991c:c4b0:3f:abb5:22f6:483e"]}
        with mock.patch.object(ipmod, "stable_ipv6_addresses",
                               return_value=stable):
            out = ipmod.prefer_stable_ipv6(
                "2409:8a1e:991c:c4b0:eca8:8231:7682:a471")
        self.assertEqual(out, "2409:8a1e:991c:c4b0:3f:abb5:22f6:483e")

    def test_no_stable_returns_original(self):
        with mock.patch.object(ipmod, "stable_ipv6_addresses",
                               return_value={}):
            tmp = "2409:8a1e:991c:c4b0:eca8:8231:7682:a471"
            self.assertEqual(ipmod.prefer_stable_ipv6(tmp), tmp)

    def test_stable_in_different_prefix_ignored(self):
        stable = {"en0": ["2409:8a1e:991c:c4b1:3f:abb5:22f6:483e"]}
        with mock.patch.object(ipmod, "stable_ipv6_addresses",
                               return_value=stable):
            tmp = "2409:8a1e:991c:c4b0:eca8:8231:7682:a471"
            self.assertEqual(ipmod.prefer_stable_ipv6(tmp), tmp)

    def test_none_passthrough(self):
        self.assertIsNone(ipmod.prefer_stable_ipv6(None))

    def test_ifname_scopes_lookup(self):
        # 同 /64 双网卡：指定网卡时只能取该网卡的稳定地址，不得串号
        stable = {
            "eth0": ["2409:8a1e:991c:c4b0:aaaa::1"],
            "en0": ["2409:8a1e:991c:c4b0:bbbb::2"],
        }
        probe = "2409:8a1e:991c:c4b0:cccc::3"
        with mock.patch.object(ipmod, "stable_ipv6_addresses",
                               return_value=stable):
            self.assertEqual(ipmod.prefer_stable_ipv6(probe, ifname="eth0"),
                             "2409:8a1e:991c:c4b0:aaaa::1")
            self.assertEqual(ipmod.prefer_stable_ipv6(probe, ifname="en0"),
                             "2409:8a1e:991c:c4b0:bbbb::2")

    def test_ifname_without_stable_falls_back(self):
        # 指定网卡在该 /64 下没有稳定地址时应回退原值，而不是取别网卡的
        stable = {"eth0": ["2409:8a1e:991c:c4b0:aaaa::1"]}
        probe = "2409:8a1e:991c:c4b0:cccc::3"
        with mock.patch.object(ipmod, "stable_ipv6_addresses",
                               return_value=stable):
            self.assertEqual(ipmod.prefer_stable_ipv6(probe, ifname="en0"), probe)

    def test_ifname_none_scans_all(self):
        stable = {"eth0": ["2409:8a1e:991c:c4b0:aaaa::1"]}
        probe = "2409:8a1e:991c:c4b0:cccc::3"
        with mock.patch.object(ipmod, "stable_ipv6_addresses",
                               return_value=stable):
            self.assertEqual(ipmod.prefer_stable_ipv6(probe, ifname=None),
                             "2409:8a1e:991c:c4b0:aaaa::1")


class TestIfnameOf(unittest.TestCase):
    def _snic(self, family, address):
        return type("S", (), {"family": family, "address": address})()

    def test_finds_interface(self):
        f = mock.MagicMock()
        f.net_if_addrs.return_value = {
            "eth0": [self._snic(socket.AF_INET6, "2409:8a1e::9")],
            "en0": [self._snic(socket.AF_INET6, "2409:8a1e::10")],
        }
        with mock.patch.dict("sys.modules", {"psutil": f}):
            self.assertEqual(ipmod.ifname_of("2409:8a1e::10", "AAAA"), "en0")

    def test_not_found_returns_none(self):
        f = mock.MagicMock()
        f.net_if_addrs.return_value = {"eth0": []}
        with mock.patch.dict("sys.modules", {"psutil": f}):
            self.assertIsNone(ipmod.ifname_of("2409:8a1e::9", "AAAA"))

    def test_psutil_missing_returns_none(self):
        with mock.patch.dict("sys.modules", {"psutil": None}):
            self.assertIsNone(ipmod.ifname_of("2409:8a1e::9", "AAAA"))


class TestSourceIfname(unittest.TestCase):
    def test_interface_name_returned(self):
        self.assertEqual(ipmod._source_ifname("eth0", "AAAA"), "eth0")

    def test_explicit_ip_returns_none(self):
        self.assertIsNone(ipmod._source_ifname("2409:8a1e::1", "AAAA"))

    def test_empty_returns_none(self):
        self.assertIsNone(ipmod._source_ifname("", "AAAA"))
        self.assertIsNone(ipmod._source_ifname(None, "AAAA"))


class TestGetCurrentIP(unittest.TestCase):
    def _patch(self, local, public, stable=None, ifname=None):
        return mock.patch.multiple(
            ipmod,
            get_local_ip=mock.Mock(return_value=local),
            get_public_ip=mock.Mock(return_value=public),
            stable_ipv6_addresses=mock.Mock(return_value=stable or {}),
            ifname_of=mock.Mock(return_value=ifname),
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

    def test_prefers_stable_address(self):
        stable = {"en0": ["2409:8a1e:991c:c4b0:3f:abb5:22f6:483e"]}
        with self._patch("2409:8a1e:991c:c4b0:eca8:8231:7682:a471",
                         "2409:8a1e:991c:c4b0:eca8:8231:7682:a471", stable,
                         ifname="en0"):
            self.assertEqual(
                ipmod.get_current_ip("AAAA"),
                "2409:8a1e:991c:c4b0:3f:abb5:22f6:483e")

    def test_explicit_source_ip_not_replaced(self):
        stable = {"en0": ["2409:8a1e:991c:c4b0:3f:abb5:22f6:483e"]}
        explicit = "2409:8a1e:991c:c4b0:eca8:8231:7682:a471"
        with self._patch(explicit, explicit, stable):
            self.assertEqual(ipmod.get_current_ip("AAAA", source=explicit),
                             explicit)

    def test_ipv4_untouched_by_stable_logic(self):
        stable = {"en0": ["2409:8a1e:991c:c4b0:3f:abb5:22f6:483e"]}
        with self._patch("8.8.8.8", "8.8.8.8", stable):
            self.assertEqual(ipmod.get_current_ip("A"), "8.8.8.8")

    def test_multi_egress_same_prefix_no_cross_interface(self):
        """多出口同 /64：指定 source=eth0 时不得选到 en0 的稳定地址。"""
        stable = {
            "eth0": ["2409:8a1e:991c:c4b0:aaaa::1"],
            "en0": ["2409:8a1e:991c:c4b0:bbbb::2"],
        }
        probe = "2409:8a1e:991c:c4b0:cccc::3"
        for src, expected in (("eth0", "2409:8a1e:991c:c4b0:aaaa::1"),
                              ("en0", "2409:8a1e:991c:c4b0:bbbb::2")):
            with mock.patch.multiple(
                ipmod,
                resolve_source=mock.Mock(return_value=probe),
                get_local_ip=mock.Mock(return_value=probe),
                get_public_ip=mock.Mock(return_value=probe),
                stable_ipv6_addresses=mock.Mock(return_value=stable),
            ):
                self.assertEqual(
                    ipmod.get_current_ip("AAAA", source=src), expected)

    def test_auto_ifname_used_when_no_source(self):
        """未指定 source 时用探测地址反查网卡，限定查找范围。"""
        stable = {
            "eth0": ["2409:8a1e:991c:c4b0:aaaa::1"],
            "en0": ["2409:8a1e:991c:c4b0:bbbb::2"],
        }
        probe = "2409:8a1e:991c:c4b0:cccc::3"
        with self._patch(probe, probe, stable, ifname="en0"):
            self.assertEqual(ipmod.get_current_ip("AAAA"),
                             "2409:8a1e:991c:c4b0:bbbb::2")


if __name__ == "__main__":
    unittest.main()
