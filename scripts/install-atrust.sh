#!/usr/bin/env bash
# 安装 / 卸载 aTrust 客户端（Fedora 版，由官方 Ubuntu deb 重打包）
#
#   ./install-atrust.sh /path/to/atrust-<ver>-<rel>.fc<NN>.x86_64.rpm
#   ./install-atrust.sh remove
#
# 不传路径时，自动取 ~/rpmbuild/RPMS/x86_64/ 下最新的一只。
set -euo pipefail

if [ "${1:-install}" = "remove" ]; then
    sudo systemctl disable --now aTrustDaemon.service 2>/dev/null || true
    sudo dnf remove -y atrust
    echo "已卸载。"
    echo "如需清理残留数据："
    echo "  sudo rm -rf /usr/share/sangfor /root/.aTrust \"\$HOME/.aTrust\""
    exit 0
fi

if [ $# -ge 1 ]; then
    RPM="$1"
else
    RPM="$(ls -1 "$HOME"/rpmbuild/RPMS/x86_64/atrust-*.rpm 2>/dev/null | sort -V | tail -1 || true)"
fi

if [ -z "${RPM:-}" ] || [ ! -f "$RPM" ]; then
    echo "找不到 RPM。用法：$0 /path/to/atrust-*.rpm" >&2
    exit 1
fi

echo "==> 安装 $RPM"
sudo dnf install -y "$RPM"

echo "==> 启动守护进程"
sudo systemctl enable --now aTrustDaemon.service

echo "==> 状态"
systemctl is-active aTrustDaemon.service || true
sudo systemctl status aTrustDaemon.service --no-pager -l | head -20 || true

cat <<'EOF'

完成。接下来：
  1) 应用菜单里点 "aTrust" 启动托盘
  2) 服务器地址填你单位的 aTrust 门户，例如 https://vpn.example.edu.cn
  3) 用单位统一身份认证登录

排障：
  journalctl -u aTrustDaemon -n 100 --no-pager
  tail -50 ~/.aTrust/logs/aTrustTray.$(date +%Y%m%d).log
  sudo ausearch -m avc -ts recent          # 怀疑 SELinux 拦截时

如果更新过客户端：
  pkill -f aTrustTray2 ; sudo systemctl restart aTrustDaemon
  然后重新从菜单启动
EOF
