# aTrust For Linux RPM

把深信服 aTrust（SDP / 零信任接入客户端）的**官方 Ubuntu amd64 deb** 重新打包成 Fedora 可用的 RPM，
并修掉它在 Fedora 上的几处水土不服。

> 适用：Fedora 40+ x86_64（在 Fedora 44 / KDE Plasma / Wayland 上实测通过）
> 客户端版本：`2.5.16.50`

---

## ⚠️ 先读这一段

- 本仓库**不包含**任何厂商二进制、安装包、图标或签名文件。`atrust.spec` 只是一个打包脚本，
  运行时读取你自己下载的 deb。
- 你需要自行从**有授权的渠道**获取 `aTrustInstaller_amd64_*.deb`（学校/单位门户，或厂商下载页）。
- 本项目与深信服（Sangfor）无关，未获其背书。`aTrust`、`Sangfor` 等名称与商标归其所有者。
- 打包会把 deb 里的 setuid 辅助程序（`dmidecode_processor_tool`、`uem_installer`）保留为 setuid，
  与原 deb 的行为一致。上生产前请自己评估。
- 请遵守你所在单位的信息安全规定。**不要**把单位的内网地址、域名、证书提交到本仓库。

---

## 它修了什么

| # | 问题 | 现象 | 修补 |
|---|---|---|---|
| 1 | 自带 `libxcb.so.1`（1.13）被 `RPATH` 优先加载，Shadow 掉系统 1.17 | 托盘进程无限重启，日志反复 `Try pulling up the QT tray` | 自带库改名 `.bundled`，让系统库生效 |
| 2 | deb 依赖 Ubuntu 的系统 Qt 插件目录，Fedora 没有 | `Cannot load library .../platforms/libqxcb.so` | 建 `resources/lib/platforms/libqxcb.so` 软链 |
| 3 | Qt 找不到插件路径 | 同上 | 加 `resources/bin/qt.conf` 指到自带插件目录 |
| 4 | 登录历史写在加密 MMKV 里，在本机写入失败 | 每次打开都要重输服务器地址 | `history_addr.js` 追加回落逻辑：读 `addr.conf` + `addr.list` |

所有修补都在 `%install` / `%post` 里完成，**不修改**厂商的 `.desktop` 与启动脚本，卸载即还原。

---

## 快速开始

### 1. 准备打包环境

```bash
sudo dnf install -y rpm-build rpmdevtools
rpmdev-setuptree
```

### 2. 取 deb 并解包到 `SOURCES/stage`

```bash
mkdir -p ~/Downloads/atrust && cd ~/Downloads/atrust
# 从你单位门户或厂商下载页取得，例如：
#   aTrustInstaller_amd64_2.5.16.50.deb
curl -# -O "<你的 deb 下载地址>"

mkdir -p ~/rpmbuild/SOURCES/stage
dpkg-deb -x aTrustInstaller_amd64_2.5.16.50.deb ~/rpmbuild/SOURCES/stage   # 有 dpkg 时
# 没有 dpkg 时（deb = ar + tar）：
#   ar x aTrustInstaller_amd64_2.5.16.50.deb
#   tar -xf data.tar.* -C ~/rpmbuild/SOURCES/stage
```

### 3. 放好 spec 与补丁，构建

```bash
cp atrust.spec ~/rpmbuild/SPECS/
cp patches/history-addr-fedora.js ~/rpmbuild/SOURCES/
rpmbuild -bb ~/rpmbuild/SPECS/atrust.spec
```

产物：`~/rpmbuild/RPMS/x86_64/atrust-<version>-<release>.fc<NN>.x86_64.rpm`（约 150 MB）
安装后约占 530 MB。

### 4. 安装

```bash
sudo dnf install -y ~/rpmbuild/RPMS/x86_64/atrust-*.rpm
sudo systemctl enable --now aTrustDaemon.service
```

然后从应用菜单启动 `aTrust`，填写服务器地址并登录。

`scripts/install-atrust.sh` 把 3、4 两步包在一起：

```bash
./scripts/install-atrust.sh /path/to/atrust-*.rpm
./scripts/install-atrust.sh remove      # 卸载
```

---

## 装完之后：两件与系统相关的事

这两条**不是** aTrust 的问题，而是「同时用 Clash / fake-ip 类代理」时的通用坑。只用 aTrust 可以跳过。

### 1. DNS 解析不到内网域名

aTrust 只接管 UDP/53，而 `systemd-resolved` 走 TCP/53，于是同一个域名两条路径两个答案。
把 `resolve` 从 NSS 的 hosts 链里去掉：

```
# /etc/nsswitch.conf
hosts:      files myhostname mdns4_minimal [NOTFOUND=return] dns
```

验证：

```bash
getent hosts app.example.edu.cn          # 失败
getent -s dns hosts app.example.edu.cn   # 成功 → 说明是 NSS 链路问题
resolvectl flush-caches
```

### 2. 内网域名被代理抢走

Clash 的 fake-ip 池（`198.18.0.0/16`）与 aTrust 的虚拟 IP 池同段，谁先解析谁赢。
必须让内网域名**根本不进代理**：

```bash
# GNOME 系统代理的例外（注意：Clash 启停系统代理时可能被覆盖）
gsettings set org.gnome.system.proxy ignore-hosts \
  "['localhost','127.0.0.1','::1','*.example.edu.cn','example.edu.cn']"

# 更稳：让浏览器自己记住例外，不依赖系统代理（Firefox 示例：profile/user.js）
# user_pref("network.proxy.no_proxies_on", "localhost, 127.0.0.1, ::1, *.example.edu.cn, example.edu.cn");
```

判断请求到底走了哪条路，最快的办法是对照实验：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://app.example.edu.cn/                       # 直连
curl -sS -o /dev/null -w '%{http_code}\n' -x http://127.0.0.1:7897 https://www.bing.com/    # 经代理访问公网
curl -sS -o /dev/null -w '%{http_code}\n' -x http://127.0.0.1:7897 https://app.example.edu.cn/  # 内网经代理（应失败）
```

内网地址经代理通常报 `SSL routines::unexpected eof`，浏览器里就是 `PR_END_OF_FILE_ERROR`。

---

## 登录地址的下拉列表

修补 4 让登录页记住服务器地址，来源按顺序为：

1. `/usr/share/sangfor/.aTrust/var/conf/addr.conf` —— 最近一次成功登录的地址（客户端自动写）
2. `/usr/share/sangfor/.aTrust/var/conf/addr.list` —— 手工维护，**一行一个**，`#` 开头为注释

```bash
sudoedit /usr/share/sangfor/.aTrust/var/conf/addr.list
```

```
# 一行一个，最多取前 10 条
https://vpn.example.edu.cn
https://vpn2.example.edu.cn
```

改完重启客户端（托盘右键 → 退出，再打开）生效。`addr.list` 在 `%post` 里只在不存在时创建，
升级不会覆盖你的内容。

---

## 已知限制

- **界面语言**：Linux 版启动脚本读 `/etc/default/locale`（Debian 路径），Fedora 没有此文件，
  客户端会回落到 `en-US`。可用 wrapper 注入 `LANG=zh_CN.UTF-8`。
- **UEM 组件**：`uem/` 下的终端管控模块缺 `libcrypto++.so.9` / `libuemlogger.so`，
  校园网纯接入场景用不到，未处理。若你的单位启用了终端合规检查，这部分需要另外补。
- **版本匹配**：`2.5.16.50` 实测可连服务端 `2.5.10.x`。若你的服务端做严格版本校验，
  换 `2.4.10.x` 的 deb，改 `Version:` 后重打即可，修补逻辑通用。
- **SELinux**：如遇权限拒绝，`sudo ausearch -m avc -ts recent` 查看；本项目未附带策略模块。
- **不提供预编译包**：见开头「先读这一段」。

---

## 卸载

```bash
sudo systemctl disable --now aTrustDaemon.service
sudo dnf remove -y atrust
# 需要彻底清干净时：
sudo rm -rf /usr/share/sangfor /root/.aTrust "$HOME/.aTrust"
```

---

## 反馈问题时请附上

```bash
rpm -q atrust
systemctl status aTrustDaemon --no-pager -l
journalctl -u aTrustDaemon -n 100 --no-pager
tail -50 ~/.aTrust/logs/aTrustTray.$(date +%Y%m%d).log
ip -brief addr show utun7
cat /etc/os-release | head -3
```

**先把域名、IP、用户名替换掉再贴。**

---

## 文档

- [`docs/porting-notes.md`](docs/porting-notes.md) —— 完整移植复盘：四个故障的定位过程、
  每条命令的预期输出、以及走过的弯路（Clash 规则、FoxyProxy、systemd-resolved 等）。
  遇到问题建议先按这份文档的排查顺序走一遍。

## 许可

打包脚本、补丁与文档：MIT。
厂商二进制不在本仓库内，其许可由深信服决定。
