"""命令行入口。"""
import argparse
import logging
import sys

from . import __version__
from .config import load_config
from .exceptions import DDNSError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="ddns",
        description="周期探测公网 IP 并同步到 DNS 服务商（腾讯云/阿里云/Cloudflare/华为云）。",
    )
    parser.add_argument("-v", "--version", action="version",
                        version=f"%(prog)s {__version__}")
    parser.add_argument("--donate", action="store_true",
                        help="查看捐赠方式")
    args = parser.parse_args(argv)

    if args.donate:
        from .donate import print_donate  # 延迟导入，保持 --help 轻量
        print_donate()
        return 0

    try:
        cfg = load_config()
    except DDNSError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    from .app import run  # 延迟导入，避免 --help 时加载网络模块

    try:
        run(cfg)
    except DDNSError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0
