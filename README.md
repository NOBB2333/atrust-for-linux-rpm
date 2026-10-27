# aTrust For Linux RPM

把深信服 aTrust（SDP / 零信任接入客户端）的**官方 Ubuntu amd64 deb** 重新打包成 Fedora 可用的 RPM，
并修掉它在 Fedora 上的几处水土不服。

> 适用：Fedora 40+ x86_64（在 Fedora 44 / KDE Plasma / Wayland 上实测通过）
> 客户端版本：`2.5.16.50`
> RPM 打包版本：`5`；Release 标签：`v2.5.16.50-5`
>
> 2026-10-27 核对[官方清单](https://atrustcdn.sangfor.com/tools/clientVersion/index.html)：
> Ubuntu x86_64 为 `2.5.16.50`（同页的麒麟 / UOS 是其他构建，不用于本项目）。

---

## ⚠️ 先读这一段

- Git 源码**不包含**任何厂商二进制、安装包、图标或签名文件。
  构建脚本下载 `sources.env` 固定的官方 deb，验证 SHA256 后重新打包；Release 附件提供构建出的 RPM。
- 厂商客户端的使用、分发许可仍由深信服决定；本仓库的 MIT 许可只覆盖打包脚本、补丁与文档。
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
| 5 | 干净 Fedora 环境缺少 Qt/XCB 和 Electron 依赖 | 缺 `libGL.so.1`、`libX11-xcb.so.1` 等，托盘 / 登录界面无法启动 | RPM 显式声明所需共享库依赖 |

兼容性文件修补在 `%install` / `%post` 里完成，系统库通过 RPM 依赖安装，
**不修改**厂商的 `.desktop` 与启动脚本。

---

## 快速开始

### 1. 准备打包环境

```bash
sudo dnf install -y rpm-build systemd-rpm-macros binutils tar gzip xz curl
```

### 2. 构建安装包

```bash
./scripts/build-rpm.sh
# 已下载同一个官方包时也可以直接传入，仍然会校验 SHA256、版本和架构：
# ./scripts/build-rpm.sh /path/to/aTrustInstaller_amd64.deb
```

产物在 `dist/atrust-2.5.16.50-5.fc44.x86_64.rpm` 和 `dist/SHA256SUMS`。
`fc44` 随构建环境变化。官方 deb 缓存在 `.cache/`；临时构建目录退出时清理。
构建不需要 root，不会安装或启动客户端。

也可以用 Podman 在 Fedora 44 中构建（与 Actions 使用同一 Fedora 版本）：

```bash
podman run --rm -v "$PWD:/work:Z" -w /work registry.fedoraproject.org/fedora:44 \
  bash -c 'dnf install -y --setopt=install_weak_deps=False rpm-build systemd-rpm-macros binutils tar gzip xz curl && ./scripts/build-rpm.sh'
```

### 3. 安装

```bash
(cd dist && sha256sum --check SHA256SUMS)
sudo dnf install -y ./dist/atrust-*.rpm
sudo systemctl enable --now aTrustDaemon.service
```

然后从应用菜单启动 `aTrust`，填写服务器地址并登录。

也可以用安装脚本安装已有 RPM 或卸载：

```bash
./scripts/install-atrust.sh /path/to/atrust-*.rpm
./scripts/install-atrust.sh remove      # 卸载
```

---

## 发布 Release（仅发布时执行 Actions）

工作流：[`release.yml`](.github/workflows/release.yml)。唯一触发条件是
`release: types: [published]`：发布正式版或预发布版时构建，push、PR、仅推送 tag、
保存 Release 草稿及编辑 Release 说明都不会触发。

1. 本地构建和测试通过后提交 PR，合并进 `main`。
2. 在你的仓库 **Releases → Draft a new release**，创建标签 `v2.5.16.50-5`，
   Target 选择合并后的 `main`。标签必须与 `Version-Release` 一致（不含 `.fc44`）。
3. 点击 **Publish release**。Actions 在 Fedora 44 x86_64 容器中测试、下载固定 deb、
   校验并构建，安装 RPM 检查共享库和 Fedora 修补，最后将 RPM 和 `SHA256SUMS` 上传到这次 Release。

只使用仓库自带的 `GITHUB_TOKEN`，无需额外 Secret；fork 的 Actions 必须启用。
构建失败时可从 Actions 页面重新运行失败任务，同名附件会被替换。
Release 发布后需要等待构建完成，附件才会出现。

## 与官方及原仓库保持同步

**深信服客户端版本**由[官方公开清单](https://atrustcdn.sangfor.com/tools/clientVersion/index.html)
的 `Ubuntu_X86` 条目决定；检查命令（需要 Python 3）：

```bash
python3 scripts/check-upstream.py
```

它只报告版本和下载地址，不修改仓库，也不自动发布。按需手动检查即可；本项目没有定时任务，
符合「只在发布 Release 时执行构建」的设置。新版本的同步流程：

1. 下载官方 Ubuntu amd64 deb，用 `sha256sum` 计算 SHA256。
2. 更新 `sources.env` 的版本、URL、SHA256，以及 `atrust.spec` 的 `Version`；
   客户端升级时将 `Release` 重置为 `1`，同一客户端的打包修改则递增 `Release`。
3. 运行测试和本地构建，确认新 deb 的文件布局仍适用 Fedora 补丁，再提 PR、合并和发布。
   例如新客户端 `2.5.16.51` 的首个 RPM 标签为 `v2.5.16.51-1`。

```bash
sudo dnf install -y python3 ShellCheck
shellcheck -x scripts/build-rpm.sh tests/smoke-installed.sh
python3 -m unittest discover -s tests -v
./scripts/build-rpm.sh
```

在 Fedora 测试容器中安装 RPM 后，还可以运行 `./tests/smoke-installed.sh`，
检查 Electron、Qt 托盘、Agent、守护进程插件、隧道程序和 XCB 插件的共享库，
以及 Qt 配置、历史地址补丁和安装权限。
此检查不会启动客户端；桌面显示和 VPN 登录仍需实际验证。

**原作者仓库的打包补丁**与客户端更新是两件事。保留 `upstream` remote 后可手动合并：

```bash
# 首次配置；已有 upstream 时跳过第一条
git remote add upstream https://github.com/ZhenwanLi/atrust-for-linux-rpm.git
git fetch upstream
git switch -c sync-upstream
git merge upstream/main
# 解决可能的冲突，测试通过后向自己的 main 提 PR
```

客户端版本与单位服务端是否兼容仍需实际登录确认；此打包流程不替代连接测试。

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
  需选用兼容的 deb，并更新 `sources.env` 和 spec 后重新测试、打包。
- **SELinux**：如遇权限拒绝，`sudo ausearch -m avc -ts recent` 查看；本项目未附带策略模块。
- **预编译包**：由发布 Release 时的 Actions 生成，仅提供 Fedora x86_64 RPM。

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
