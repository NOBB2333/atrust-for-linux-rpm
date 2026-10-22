# 从「学校只发 Windows 包」到「Fedora 上能用」——aTrust 移植全过程复盘

> 目标：在 Fedora 44（KDE / Wayland）上装好某高校（example.edu.cn）的深信服 aTrust 客户端，
> 并且在不关 Clash 的前提下，让 `*.example.edu.cn` 走隧道直连、其它流量继续走 Clash。

---

## 0. 一句话结论

整个过程不是「找一个 Linux 包然后装上」，而是**四个独立故障串起来**：

1. 包不存在（学校门户没有 Linux 版）→ 从厂商 CDN 取官方 Ubuntu deb，自己重打成 rpm
2. 装上了但托盘起不来（Qt 插件路径 + libxcb 版本冲突）→ 在 rpm 内部打三处补丁
3. 隧道起来了但域名解析不了（aTrust 接管 UDP/53，systemd-resolved 走 TCP）→ 改 nsswitch
4. 浏览器能解析但连不上（系统代理把内网域名送进了 Clash）→ 加代理例外列表

**关键认知：每一层都必须单独验证通过，再往上叠。** 混在一起调，永远不知道是谁的错。

---

## 1. 先把它拆成四层

一开始就要画清楚「一次访问」经过哪些环节，否则会瞎试：

```
Firefox → DNS 解析 → 选路（直连 / Clash） → aTrust 隧道(utun7) → 学校网关 → 财务系统
```

对应四层，各有各的验证手段：

| 层 | 验证手段 | 通过标志 |
|---|---|---|
| 安装 | `rpm -q atrust`、托盘进程存活 | 托盘图标出现 |
| 隧道 | `ip addr show utun7`、路由表 | 有 `2.0.0.1/24` 和一堆路由 |
| DNS | `getent hosts app.example.edu.cn` | 返回 `198.18.0.2` |
| 分流 | `curl` 三条路径对比 | 直连 302、经 Clash 报错 |

---

## 2. 第一层：包从哪来

### 2.1 学校门户的坑

门户 `https://vpn.example.edu.cn/portal/#/down_client_new` 上 Windows exe、macOS pkg 都能直下，
点 Linux 却是 `file not found`；顺手试了 apk，也是 404。

这里有个容易踩的误判：**不是学校没买 Linux 授权，而是门户没配。**
aTrust 2.3.10 之后，Linux 包是从控制台「stable 版本」里取的，管理员没上传，前端就空着。

所以「官方渠道拿不到」这件事，只说明前端拿不到，不代表厂商没发过。

### 2.2 从 Windows 包读出服务端版本

为什么要读？因为后面要判断「能不能装个别的版本」。方法：Windows 安装包的 PE 版本资源里通常写着客户端版本，
而客户端版本一般要和服务端对齐。

```bash
exiftool aTrustInstaller.exe | grep -i version
# 或者不装 exiftool：
strings -el aTrustInstaller.exe | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | sort -u
```

读出来是 **2.5.10.32**。这个数字后面很重要。

### 2.3 找到官方 CDN

厂商的公开下载页：`https://atrustcdn.sangfor.com/tools/clientVersion/index.html`

页面本身是壳，真正的清单在同目录的 `data.js` 里：

```bash
curl -s https://atrustcdn.sangfor.com/tools/clientVersion/index.html | grep -o 'src="[^"]*"'
curl -s https://atrustcdn.sangfor.com/tools/clientVersion/data.js | head -c 2000
```

`data.js` 里能看到 2.5.16 / 2.4.10 / 2.3.10 三条线，每条线下面各平台直链齐全，包括 `amd64.deb`。
直接 curl 就能下，不用登录、不用 Referer。

```bash
mkdir -p ~/Downloads/atrust && cd ~/Downloads/atrust
curl -# -O https://atrustcdn.sangfor.com/.../aTrustInstaller_amd64_2.5.16.50.deb
sha256sum aTrustInstaller_amd64_2.5.16.50.deb | tee SHA256SUMS
```

**这里做了一个决定**：装 2.5.16.50，而不是硬凑服务端的 2.5.10.32。
理由是 Linux 客户端很少做严格版本门禁，先用新版本试；真被拒再退 2.4.10.50。
事后证明能用，这个赌注赢了。

---

## 3. 第二层：deb → rpm

### 3.1 解包（不用装 dpkg）

Fedora 上 `dpkg-deb` 属于 `dpkg` 包，装它只为解个包不值。两种都行：

```bash
# 有 dpkg 时
dpkg-deb -x aTrustInstaller_amd64_2.5.16.50.deb stage   # 文件树
dpkg-deb -e aTrustInstaller_amd64_2.5.16.50.deb stage/DEBIAN  # 控制脚本

# 没有 dpkg 时（ar + tar，deb 就是这两层）
ar x aTrustInstaller_amd64_2.5.16.50.deb
tar -xf data.tar.* -C stage
tar -xf control.tar.* -C stage/DEBIAN
```

解出来是标准布局：`usr/share/sangfor/aTrust/`（主程序 + 自带 Qt 库）、`opt/apps/`、几个 systemd unit。

**注意 `.deb` 里的 `postinst` 一定要读。** 里面有 deb 安装时做的运行目录创建、setuid、CA 别名等动作，
这些在 rpm 里必须用 `%post` 重现，否则「装完能启动但登录失败」。

### 3.2 依赖体检（这一步能省掉后面 80% 的玄学）

拿到二进制先别急着跑，先看它缺什么：

```bash
cd stage/usr/share/sangfor/aTrust/resources/bin
for f in aTrustDaemon aTrustTray2 aTrustAgent; do echo "== $f"; ldd "$f" | grep 'not found'; done
```

结论：**核心二进制在 Fedora 上不缺任何库**，只有 `uem/` 目录下的几个辅助程序缺
`libcrypto++.so.9`、`libuemlogger.so`——那是终端管控模块，校园网场景用不到，直接忽略。

如果这一步有缺库，正确做法是在 spec 里补 `Requires:`，而不是往 `/usr/lib` 里乱塞 vendor 的 so。

### 3.3 spec 的四个关键决定

```bash
rpmdev-setuptree
# 把 stage 当「已编译好的产物」，%install 直接 cp
```

完整 spec 在 `~/rpmbuild/SPECS/atrust.spec`，四个不显然的点：

**① `%global __os_install_post %{nil}` + `%global debug_package %{nil}`**
跳过 rpm 的 strip / brp 后处理。vendor 的 500MB 二进制被 strip 既慢又可能破坏签名校验，
而且我们不需要 debuginfo。

**② `AutoReqProv: no`**
关掉自动依赖解析。vendor 自带一整套 Qt/ssl 库，rpm 的自动扫描会把这些内部 so 当成系统依赖，
生成一堆根本不存在的 `Requires:`，装的时候直接失败。改为手写 `Requires:` 列表（glibc、gtk3、libxcb…）。

**③ `%install` 里 `cp -a /path/stage/. %{buildroot}/`**
不做任何「编译」，deb 解包树就是成品。整个包 158MB，装完 532MB。

**④ `%post` 复刻 deb 的 postinst**
创建 `/usr/share/sangfor/.aTrust/var/{conf,run}`、`/root/.aTrust/{var,conf,logs}`，
给 `dmidecode_processor_tool`、`uem_installer` 加 setuid，
跑 `linuxHelper -ah 127.0.0.1 localhost.sangfor.com.cn` 写 CA 主机别名。

```bash
rpmbuild -bb ~/rpmbuild/SPECS/atrust.spec
sudo dnf install -y ~/rpmbuild/RPMS/x86_64/atrust-2.5.16.50-<old-release>.fc44.x86_64.rpm
```

装完 `systemctl status aTrustDaemon` 是绿的，`utun7` 也起来了——**但托盘图标不出现**。于是进入第三层。

---

## 4. 第三层：让 Qt 托盘活下来

### 4.1 症状

不是「完全没反应」，而是**反复重启**。三个可观测信号：

```bash
# 1) 托盘进程在不在、重启了几次
systemctl show aTrustDaemon -p NRestarts
ps -eo pid,etime,cmd | grep -i aTrustTray2

# 2) 托盘日志里某个计数器在涨
tail -f ~/.aTrust/logs/aTrustTray.20261022.log
#   → "Try pulling up the QT tray" 从 1 涨到 678，说明它在无限重试

# 3) 守护进程自己反而很稳
journalctl -u aTrustDaemon -n 50 --no-pager
```

**读日志的技巧：找「会单调增长的数字」。** 一个正常进程的日志不会同一条重复几百次；
重复次数就是故障的强度计，也是修好之后最好的验收指标。

### 4.2 定位链

Qt 程序起不来，第一反应永远是插件加载：

```bash
QT_DEBUG_PLUGINS=1 /usr/share/sangfor/aTrust/resources/bin/aTrustTray2 2>&1 | head -40
```

输出直接把答案写在脸上：
`Cannot load library .../platforms/libqxcb.so`、`xcb_send_request_with_fds: symbol not found`。

再确认两件事：

```bash
# a) 插件目录存在吗？
ls /usr/share/sangfor/aTrust/resources/lib/platforms/    # 不存在
# b) 它自带的 libxcb 是什么版本？
ls -l /usr/share/sangfor/aTrust/resources/lib/libxcb.so.1
strings .../libxcb.so.1 | grep -m1 'libxcb 1\.'          # 1.13
rpm -q libxcb                                            # 系统是 1.17
```

两个独立故障叠在一起：

- **Qt 找不到插件**：deb 版依赖 Ubuntu 的系统 Qt 插件目录，Fedora 上根本没有这个路径
- **libxcb 版本倒挂**：vendor 塞了个 1.13 的 `libxcb.so.1` 在 `resources/lib`，被 `RPATH` 优先加载，
  而 `libxcb-shm` 是系统 1.17 编的，调用 1.17 才有的 `xcb_send_request_with_fds` → 符号未定义

### 4.3 三处修补（全部做进 rpm，不碰 vendor 的启动脚本）

```spec
# ① 让系统的 libxcb 1.17 生效：把自带的改名，别删（可回滚）
mv .../resources/lib/libxcb.so.1 .../resources/lib/libxcb.so.1.bundled

# ② 按 Qt 的约定建插件目录，软链到实际的 libqxcb.so
mkdir -p .../resources/lib/platforms
ln -sf ../libqxcb.so .../resources/lib/platforms/libqxcb.so

# ③ 用 qt.conf 指明插件路径，不依赖环境变量
cat > .../resources/bin/qt.conf <<'EOF'
[Paths]
Plugins = /usr/share/sangfor/aTrust/resources/lib
EOF
```

**为什么坚持写在 rpm 里，而不是手改 + 加个 wrapper 脚本？**
因为「改动必须可复现」。下次重装、升级、换机器，`dnf install` 一下全部还原；
手改的东西三天后自己都忘了改过什么。

**为什么用 qt.conf 而不是 `QT_PLUGIN_PATH`？**
环境变量只在从那个 shell 启动时有效。托盘是由 systemd 拉的，环境完全不同；
`qt.conf` 放在可执行文件旁边，Qt 自己会读，跟谁拉起它无关。

### 4.4 验收指标（比「看起来正常了」可靠）

| 指标 | 修前 | 修后 |
|---|---|---|
| `Try pulling up the QT tray` 计数 | 678 且持续增长 | 停止增长 |
| `systemctl show -p NRestarts` | 反复重启 | 0 |
| `utun7` 路由条数 | 没有 | 71 条 |
| 网卡 RX 字节 | 不动 | 持续增长 |

「路由有 71 条 + RX 在涨」这两条一起看，才能排除「进程活着但隧道没通」的假阳性。

---

## 5. 第四层：网络与 DNS

### 5.1 隧道长什么样

```bash
ip -brief addr show utun7
# utun7  UNKNOWN  2.0.0.1/24  fd53:414e:4746:4f52:.../128
ip route | wc -l
```

两个值得注意的细节：

- 虚拟网关是 `2.0.0.1/24`，不是常见的 `10.x`
- IPv6 前缀 `fd53:414e:4746:4f52` 按 ASCII 拆开正是 **"SANGFOR"**（53 41 4e 47 46 4f 52）
  ——厂商把商标编进了地址里，这种细节能在排障时帮你确认「这真的是 aTrust 的接口」

### 5.2 fake-ip 撞车（这次最阴的坑）

Clash 的 fake-ip 池是 `198.18.0.0/16`；aTrust 给内网域名分配的虚拟 IP **也是** `198.18.0.0/16`：

```
app.example.edu.cn → 198.18.0.2
jw.example.edu.cn    → 198.18.0.3
不存在的域名       → NXDOMAIN
```

后果：同一个 `198.18.0.2`，Clash 认为「这是我伪造的公网地址」，aTrust 认为「这是我校内主机」。
**谁先解析，流量就去谁那儿。** 这就是为什么一开始「关掉 Clash TUN 就通了」。

结论：这种冲突没法靠调路由表优雅解决，**只能从「谁解析这个域名」这一层切开**。
所以方案从「Clash 规则加 DIRECT」换成了「让浏览器自己判断」——见第 6 节。

### 5.3 DNS 的三条路径

现象很反直觉：

```bash
getent hosts app.example.edu.cn          # 失败
getent -s dns hosts app.example.edu.cn   # 成功，返回 198.18.0.2
resolvectl query app.example.edu.cn      # 失败
```

原因在 `/etc/nsswitch.conf` 的顺序：`hosts: files ... resolve ... dns`。
`resolve` 模块走 systemd-resolved，而 resolved 用的是 **TCP/53** 上游；
aTrust 的 DNS 代理只接管了 **UDP/53**。于是同一个域名，两条路径两个答案（一个有、一个没有）。

修法（一行）：

```bash
# /etc/nsswitch.conf
hosts:      files myhostname mdns4_minimal [NOTFOUND=return] dns
```

把 `resolve` 拿掉，`dns` 模块直接用 glibc 发 UDP 查询 → 命中 aTrust → 拿到虚拟 IP。

顺手清缓存（这个不需要 sudo）：

```bash
resolvectl flush-caches
```

**方法论**：`getent` 和 `getent -s <module>` 的差异，是判断「NSS 哪一环坏了」最快的手段。
`getent -s dns` 能过而 `getent` 不能过，答案就只剩「前面的模块在捣乱」。

---

## 6. 第五层：浏览器分流（花时间最多的一段）

### 6.1 先读懂错误码

`PR_END_OF_FILE_ERROR` 的字面意思是「TLS 握手时对端把连接关了」。
它**不是** DNS 错（那会是 `NS_ERROR_UNKNOWN_HOST`），**也不是**证书错（那会是 `SEC_ERROR_*`）。

能造成它的只有两类原因：中间设备主动 reset，或者你去连了一个根本不提供 TLS 的端口。
在本案里就是：**请求被送进 Clash，Clash 拿自己的出口去连校内地址，被学校网关 reset。**

看到这个错误码，第一件事不是清缓存，而是问「这个请求到底走的哪条路」。

### 6.2 对照实验（一次性定性）

不要猜，直接做三组 curl：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://app.example.edu.cn:800/                    # 直连
curl -sS -o /dev/null -w '%{http_code}\n' -x http://127.0.0.1:7897 https://vpn.example.edu.cn/ # 经 Clash 访问公网
curl -sS -o /dev/null -w '%{http_code}\n' -x http://127.0.0.1:7897 https://app.example.edu.cn:800/
```

结果：

| 路径 | 结果 | 含义 |
|---|---|---|
| 直连 | `302` | 隧道、DNS、证书全 OK |
| 公网经 Clash | `200` | Clash 本身没问题 |
| 内网经 Clash | `SSL routines::unexpected eof` | **完全复刻了浏览器的报错** |

三行一出来，问题范围从「整个网络」缩到「一行规则」。

### 6.3 三个方案的取舍

| 方案 | 做法 | 为什么没选 |
|---|---|---|
| A. Clash 规则加 DIRECT | 在 Clash 配置里给 `*.example.edu.cn` 加直连 | fake-ip 同段，Clash 已经把它解析成 `198.18.x`，DIRECT 之后目标地址是假的 |
| B. FoxyProxy | 浏览器扩展按域名切代理 | 多一层状态机，规则模式不对就静默失效（实际就栽在这） |
| C. 系统代理 + 例外列表 | GNOME `ignore-hosts` | **选了它**：只有一层，浏览器原生支持，所见即所得 |

### 6.4 FoxyProxy 为什么会翻车（值得记住的教训）

配置看起来完全正确：`Direct` + `Include/*example.edu.cn*`，`Clash` + `Include/*`。
但 FoxyProxy 有四种全局模式，默认可能停在 **“Use proxy Clash for all URLs”**——
这个模式下**所有 pattern 都被忽略**，`Direct` 那条永远不会命中。

更糟的是：扩展启用时会自己把 Firefox 切到 manual 代理，**GNOME 的例外列表随之失效**。
所以在 UI 上看到「规则都在」，行为上却是「全走 Clash」，两者完全不矛盾。

还有两个技术细节踩过：

- 它把配置存在 IndexedDB（`storage/default/moz-extension+++<uuid>/idb/*.sqlite`），
  是结构化克隆 + 压缩的二进制，**不要手改**，只能从 UI 改
- 用 `grep` 能从里面看到 `*example.edu.cn*` 字符串，这只能证明「规则存下来了」，
  **不能证明「规则生效了」**——存下来和命中是两件事

### 6.5 决定性验证：用无头 Firefox 真跑一遍

curl 只能证明「网络通」，不能证明「浏览器会这么走」。所以做了一次真实的浏览器测试：

```bash
# 复制一份 profile（避免和正在运行的实例抢锁）
cp -a ~/.config/mozilla/firefox/<profile> /tmp/fftest
rm -f /tmp/fftest/lock /tmp/fftest/.parentlock

# 写入待验证的代理配置
cat >> /tmp/fftest/user.js <<'EOF'
user_pref("network.proxy.type", 5);   // 5 = 使用系统代理
user_pref("network.trr.mode", 5);     // 5 = 关闭 DoH
user_pref("browser.startup.page", 0); // 不恢复上次会话
EOF

# 无头启动 + 截图
firefox --headless --profile /tmp/fftest \
        --window-size=1280,900 --screenshot=/tmp/shot.png \
        "https://app.example.edu.cn:800/"
```

然后直接看那张 png：**渲染出登录页 = 整条链路在真实浏览器里成立**；
渲染出错误页 = 把错误页截图拿来看，比读日志直观十倍。

两个坑：

- `--screenshot /path.png`（空格）有时静默不生成文件，用 `--screenshot=/path.png`
- 带扩展的 profile 在 headless 下可能初始化卡死（本案 FoxyProxy 就 100 秒超时）。
  这是**测试手段的局限**，不能据此判定「扩展配置错」

### 6.6 最终落点

```bash
gsettings set org.gnome.system.proxy mode 'manual'
gsettings set org.gnome.system.proxy.http  host '127.0.0.1'
gsettings set org.gnome.system.proxy.http  port 7897
gsettings set org.gnome.system.proxy.https host '127.0.0.1'
gsettings set org.gnome.system.proxy.https port 7897
gsettings set org.gnome.system.proxy ignore-hosts \
  "['localhost','127.0.0.1','192.168.0.0/16','10.0.0.0/8','172.16.0.0/12','::1','*.example.edu.cn','example.edu.cn']"
```

外加一条 Firefox 的保险（防止某些网络下 DoH 把内网域名送给公共 DNS）：

```javascript
// ~/.config/mozilla/firefox/<profile>/user.js
user_pref("network.trr.mode", 5);
```

**为什么用 `user.js` 而不是改 `prefs.js`？**
Firefox 运行时把 prefs 保存在内存里，退出时**整体覆盖写回** `prefs.js`。
运行中手改 `prefs.js`，重启后改动全丢。`user.js` 是启动时读取并强制写入的，正好用来做「持久化配置」。

最后一个坑，也是最难发现的一个：

```bash
grep -E 'network.proxy' <profile>/prefs.js   # 什么都没有
```

`prefs.js` 里没有 `network.proxy.*`，说明浏览器在用 **「使用系统代理设置」**（type=5），
那么真正生效的是 GNOME 的 `ignore-hosts`——而那里当时**没有** `example.edu.cn`。
所以哪怕 FoxyProxy 已经关掉，财务站依然被送进 Clash。

**「浏览器代理设置在哪一层生效」这件事，必须查清楚，不能凭 UI 猜。**

---

## 7. 方法论：我实际在用的五个套路

1. **分层验证，禁止叠着调**
   每一层都有独立的「通过标志」（进程存活 / 路由存在 / `getent` 有结果 / curl 有状态码）。
   一层没绿，不上下一层。

2. **对照实验，一次只改一个变量**
   三条 curl（直连 / 公网经代理 / 内网经代理）把范围从「整个网络」压到「一行规则」。
   这是整晚效率最高的一步。

3. **找单调增长的计数器**
   日志里重复 678 次的那行，比任何 `strace` 都直白。修完看它停不停，就是验收标准。

4. **让改动可复现**
   所有修补写进 rpm spec，而不是手改文件。手改的收益是一次性的，代价是下次全部重来。

5. **用最像生产的方式验证**
   curl 通了不等于浏览器通；`--headless --screenshot` 是零成本拿到「真实渲染结果」的办法。
   拿到图片，比争论「应该是 DNS 问题吧」有用得多。

---

## 8. 关键命令速查

**取包 / 拆包**

```bash
curl -s https://atrustcdn.sangfor.com/tools/clientVersion/data.js | head -c 2000
ar x aTrustInstaller_amd64_2.5.16.50.deb && tar -xf data.tar.* -C stage
dpkg-deb -x pkg.deb stage && dpkg-deb -e pkg.deb stage/DEBIAN
```

**依赖 / 插件**

```bash
ldd binary | grep 'not found'
QT_DEBUG_PLUGINS=1 binary 2>&1 | head -40
strings libxcb.so.1 | grep -m1 'libxcb 1\.'
```

**打包 / 安装**

```bash
rpmbuild -bb ~/rpmbuild/SPECS/atrust.spec
sudo dnf install -y ~/rpmbuild/RPMS/x86_64/atrust-2.5.16.50-<release>.fc44.x86_64.rpm
sudo systemctl enable --now aTrustDaemon.service
```

**看状态**

```bash
systemctl show aTrustDaemon -p NRestarts -p ActiveState
journalctl -u aTrustDaemon -n 100 --no-pager
tail -f ~/.aTrust/logs/aTrustTray.*.log
ip -brief addr show utun7 && ip route | wc -l
```

**DNS**

```bash
getent hosts app.example.edu.cn
getent -s dns hosts app.example.edu.cn
resolvectl query app.example.edu.cn
resolvectl flush-caches
grep '^hosts:' /etc/nsswitch.conf
```

**分流 / 浏览器**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://app.example.edu.cn:800/
curl -sS -o /dev/null -w '%{http_code}\n' -x http://127.0.0.1:7897 https://www.bing.com/
gsettings get org.gnome.system.proxy ignore-hosts
firefox --headless --profile /tmp/p --screenshot=/tmp/shot.png "https://..."
```

**SELinux（怀疑被拦时）**

```bash
sudo ausearch -m avc -ts recent
```

---

## 9. 维护手册

**当前状态**

| 项 | 值 |
|---|---|
| 包 | `atrust-2.5.16.50-<release>.fc44.x86_64.rpm`（158 MB，安装后 532 MB） |
| 服务 | `aTrustDaemon.service`，enabled |
| 服务端 | 2.5.10.32（客户端高一个小版本，实测可登录） |
| 系统代理 | `manual` → `127.0.0.1:7897`，例外含 `*.example.edu.cn` |
| DNS | `nsswitch.conf` 的 hosts 行不含 `resolve` |

**卸载**

```bash
~/Downloads/atrust/install-atrust.sh remove
# 或
sudo systemctl disable --now aTrustDaemon.service && sudo dnf remove -y atrust
```

**Clash 与代理的联动（最容易忘）**

系统代理指向 `127.0.0.1:7897`。**退出 Clash 前必须**：

```bash
gsettings set org.gnome.system.proxy mode 'none'
# 重开 Clash 后
gsettings set org.gnome.system.proxy mode 'manual'
```

否则所有走系统代理的应用会报「代理服务器拒绝连接」。

**如果哪天服务端拒绝这个版本**

换 `2.4.10.50` 的 deb，改 spec 里 `%install` 的源路径和 `Version:`，`rpmbuild -bb` 重打即可。
沿用同一套修补逻辑，不用重新排障。

**已知遗留（不影响使用）**

- 客户端界面是英文：启动脚本读 `/etc/default/locale`（Debian 的路径），Fedora 没有这个文件。
  想中文化可以加一个 wrapper 注入 `LANG=zh_CN.UTF-8`
- 偶有残留的 `aTrustAgent --plugin plugin-daemon` 进程 / defunct 进程：
  unit 里是 `KillMode=process`，只杀主进程不杀子进程；改 `KillMode=control-group` 可解决
- `uem/` 下的终端管控组件缺 `libcrypto++.so.9`，校园网场景用不到，未处理

---

## 10. 如果重做一次，哪里能省时间

1. **第一步就该查 `/etc/nsswitch.conf` 和 `getent -s dns`**，而不是先怀疑 DNS 服务器。
   `resolve` 模块和 UDP 被接管这个组合，是最常见的隐蔽故障。
2. **第一步就该看 `prefs.js` 里有没有 `network.proxy.*`**。
   一个 `grep` 就能知道浏览器到底听谁的，比在 UI 里翻十层菜单快。
3. **FoxyProxy 那一段可以直接跳过**：系统代理 + `ignore-hosts` 已经足够，
   多一层扩展只是多一个静默失效点。
4. **`QT_DEBUG_PLUGINS=1` 应该在托盘不出现的第一分钟就跑**，
   它把「插件找不到」和「符号缺失」两个问题一次全打印出来了。

---

## 附：交付物清单

| 路径 | 说明 |
|---|---|
| `~/rpmbuild/SPECS/atrust.spec` | 打包定义（含三处 Fedora 修补） |
| `~/rpmbuild/RPMS/x86_64/atrust-2.5.16.50-<release>.fc44.x86_64.rpm` | 当前使用版本 |
| `~/rpmbuild/RPMS/x86_64/atrust-2.5.16.50-<old-release>.fc44.x86_64.rpm` | 旧版（有 Qt bug），仅作对照 |
| `~/Downloads/atrust/aTrustInstaller_amd64_2.5.16.50.deb` | 官方原始包，重打源 |
| `~/Downloads/atrust/stage` | 解包树，`%install` 的输入 |
| `~/Downloads/atrust/install-atrust.sh` | 安装 / 卸载脚本 |
| `~/Desktop/aTrust-Fedora-项目复盘.md` | 本文 |
