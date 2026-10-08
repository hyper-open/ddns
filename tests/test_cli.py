"""命令行入口测试。"""
import io
import unittest

from ddns import cli


class TestDonateFlag(unittest.TestCase):
    def test_donate_returns_zero_without_config(self):
        ret = cli.main(["--donate"])
        self.assertEqual(ret, 0)

    def test_donate_prints_channels(self):
        buf = io.StringIO()
        from ddns.donate import print_donate
        print_donate(buf)
        self.assertIn("捐赠", buf.getvalue())
