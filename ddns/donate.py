"""捐赠信息。渠道链接留空时自动隐藏对应条目，填入后即生效。"""

# 渠道名称 -> 链接 / 说明。占位符请替换为真实链接，留空 "" 则不在 --donate 中展示。
DONATE_CHANNELS = {
    "GitHub Sponsors": "",  # 例如 https://github.com/sponsors/<user>
    "爱发电": "https://afdian.com/a/aiyuanchu",
    "支付宝": "",           # 例如收款码链接或 "手机支付宝扫码"
    "微信": "",             # 例如收款码链接或 "微信扫码"
}


def print_donate(stream=None) -> None:
    """打印捐赠信息到指定流（默认 stdout）。"""
    import sys

    stream = stream or sys.stdout
    print("如果 ddns 对你有帮助，欢迎捐赠支持：\n", file=stream)
    for name, link in DONATE_CHANNELS.items():
        if link:
            print(f"  {name}: {link}", file=stream)
    print("\n感谢支持！", file=stream)
