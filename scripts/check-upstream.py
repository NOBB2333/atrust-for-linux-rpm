#!/usr/bin/env python3
"""Read the official client list without executing its JavaScript."""

from pathlib import Path
import re
import sys
from urllib.error import URLError
from urllib.request import urlopen


OFFICIAL_LIST = "https://atrustcdn.sangfor.com/tools/clientVersion/data.js"


def find_latest(data):
    entries = re.findall(
        r"name:\s*['\"]Ubuntu_X86[：:]\s*(\d+(?:\.\d+){3})['\"]\s*,\s*"
        r"url:\s*['\"](https://atrustcdn\.sangfor\.com/standard/linux/"
        r"(\d+(?:\.\d+){3})/ubuntu/amd64/aTrustInstaller_amd64\.deb)['\"]",
        data,
    )
    if not entries:
        raise ValueError("official list contains no recognized Ubuntu_X86 package")
    for version, _, url_version in entries:
        if version != url_version:
            raise ValueError("official label and URL version disagree")
    version, url, _ = max(entries, key=lambda entry: tuple(map(int, entry[0].split("."))))
    return version, url


def main():
    source = (Path(__file__).resolve().parents[1] / "sources.env").read_text()
    locked = re.search(r"^ATRUST_VERSION=(\S+)$", source, re.MULTILINE).group(1)
    with urlopen(OFFICIAL_LIST, timeout=30) as response:
        latest, url = find_latest(response.read().decode("utf-8"))
    print(f"本仓库版本：{locked}\n官方 Ubuntu x86_64 版本：{latest}\n下载地址：{url}")
    if locked == latest:
        print("当前与官方公开清单一致。")
    else:
        print("版本不同；请按 README 更新 sources.env 和 atrust.spec，测试后再发布 Release。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, URLError, ValueError) as error:
        print(f"检查失败：{error}", file=sys.stderr)
        sys.exit(1)
