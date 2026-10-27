#!/usr/bin/env bash
# 在安装了构建产物的 Fedora 容器中运行；不启动客户端或连接 VPN。
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
app=/usr/share/sangfor/aTrust
result=0
for binary in "$app/aTrustTray" "$app/resources/bin/aTrustTray2" \
    "$app/resources/bin/aTrustAgent" "$app/resources/bin/aTrustXtunnel-64" \
    "$app/resources/bin/plugin-daemon/aTrustDaemon/"*.so \
    "$app/resources/lib/libqxcb.so"; do
    echo "Checking shared libraries: $binary"
    if ! libraries=$(ldd "$binary" 2>&1); then
        echo "$libraries" >&2
        result=1
    elif [[ $libraries == *'not found'* ]]; then
        echo "$libraries" >&2
        result=1
    fi
done
[[ $result -eq 0 ]] || exit "$result"

test -f "$app/resources/lib/libxcb.so.1.bundled"
test ! -e "$app/resources/lib/libxcb.so.1"
test "$(readlink "$app/resources/lib/platforms/libqxcb.so")" = ../libqxcb.so
test -u "$app/resources/bin/dmidecode_processor_tool"
test -u "$app/uem/bin/uem_installer"
test -f /usr/share/sangfor/.aTrust/var/conf/addr.list

python3 - "$repo_dir" <<'PY'
import configparser
from pathlib import Path
import sys

resources = Path("/usr/share/sangfor/aTrust/resources")
config = configparser.ConfigParser()
config.read(resources / "bin/qt.conf")
assert config["Paths"]["Plugins"] == str(resources / "lib")
patch = (Path(sys.argv[1]) / "patches/history-addr-fedora.js").read_text()
assert (resources / "app/src/service/history_addr.js").read_text().endswith(patch)
print("Installed package smoke checks passed.")
PY
