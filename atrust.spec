# aTrust For Linux RPM
#
# 把官方 Ubuntu amd64 deb 重打包为 Fedora 可用的 RPM。
#
# 构建前准备：
#   rpmdev-setuptree
#   mkdir -p ~/rpmbuild/SOURCES/stage
#   dpkg-deb -x aTrustInstaller_amd64_<version>.deb ~/rpmbuild/SOURCES/stage
#   cp patches/history-addr-fedora.js ~/rpmbuild/SOURCES/
#   rpmbuild -bb atrust.spec
#
# 推荐入口：./scripts/build-rpm.sh（自动下载、校验并解包官方 deb）。
# 本文件不含任何厂商二进制；Version 请与 sources.env 保持一致。

%global __os_install_post %{nil}
%global debug_package %{nil}

Name:           atrust
Version:        2.5.16.50
Release:        5%{?dist}
Summary:        Sangfor aTrust SDP client (repacked from official Ubuntu deb)
License:        Proprietary
URL:            https://www.sangfor.com.cn
AutoReqProv:    no
BuildArch:      x86_64
BuildRequires:  systemd-rpm-macros
Requires:       glibc
Requires:       libstdc++
Requires:       systemd
Requires:       gtk3
Requires:       nss
Requires:       mesa-libgbm
Requires:       libdrm
Requires:       libxkbcommon
Requires:       alsa-lib
Requires:       at-spi2-atk
Requires:       at-spi2-core
Requires:       cups-libs
Requires:       pango
Requires:       libX11
Requires:       libXcomposite
Requires:       libXdamage
Requires:       libXrandr
Requires:       libXfixes
Requires:       libXext
Requires:       libXcursor
Requires:       libXi
Requires:       libXtst
Requires:       libxshmfence
Requires:       libxcb
Requires:       libnotify
# Qt/XCB and Electron also need these on a minimal Fedora installation.
Requires:       libGL.so.1()(64bit)
Requires:       libX11-xcb.so.1()(64bit)
Requires:       libXss.so.1()(64bit)
Requires:       libSM.so.6()(64bit)
Requires:       libICE.so.6()(64bit)
Requires:       libxcb-render-util.so.0()(64bit)
Requires:       libxcb-image.so.0()(64bit)
Requires:       libxcb-icccm.so.4()(64bit)
Requires:       libxcb-keysyms.so.1()(64bit)
Requires:       libxkbcommon-x11.so.0()(64bit)

%description
Sangfor aTrust (SDP / zero trust access client), Linux x86_64 build %{version}.
This RPM is repacked from the official Sangfor Ubuntu amd64 deb package and
installs to /usr/share/sangfor/aTrust with the bundled aTrustDaemon.service.
The build script downloads and verifies the official deb pinned in sources.env.

%prep

%build

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}
cp -a %{_sourcedir}/stage/. %{buildroot}/

# --- Fedora adjustments -------------------------------------------------
# 1) the bundled libxcb is 1.13 and shadows Fedora's 1.17, which breaks
#    libxcb-shm (undefined symbol: xcb_send_request_with_fds) -> use system one
mv %{buildroot}/usr/share/sangfor/aTrust/resources/lib/libxcb.so.1 \
   %{buildroot}/usr/share/sangfor/aTrust/resources/lib/libxcb.so.1.bundled

# 2) Qt needs plugins at <Plugins>/platforms/libqxcb.so; the deb relies on the
#    Ubuntu system Qt plugin dir, which does not exist here
mkdir -p %{buildroot}/usr/share/sangfor/aTrust/resources/lib/platforms
ln -sf ../libqxcb.so \
   %{buildroot}/usr/share/sangfor/aTrust/resources/lib/platforms/libqxcb.so

# 3) point Qt at the bundled plugin dir without depending on env vars,
#    so the Qt tray works no matter how it is launched
cat > %{buildroot}/usr/share/sangfor/aTrust/resources/bin/qt.conf <<'QTEOF'
[Paths]
Plugins = /usr/share/sangfor/aTrust/resources/lib
QTEOF

# 4) the native history addon (aTrustAddonUtils.node) writes an encrypted MMKV
#    store that may end up empty (seen on Fedora), so the login page never
#    remembers the server address. Fall back to addr.conf / addr.list.
cat %{_sourcedir}/history-addr-fedora.js \
    >> %{buildroot}/usr/share/sangfor/aTrust/resources/app/src/service/history_addr.js
# -----------------------------------------------------------------------

%pre
# stop an existing daemon before upgrade
if [ -x /usr/bin/systemctl ]; then
    /usr/bin/systemctl stop aTrustDaemon.service >/dev/null 2>&1 || :
fi

%post
# runtime directories (same layout the deb postinst creates)
mkdir -p /usr/share/sangfor/.aTrust/var/conf \
         /usr/share/sangfor/.aTrust/var/run/TrayTheme \
         /root/.aTrust/var/conf \
         /root/.aTrust/logs
chmod -R 777 /usr/share/sangfor/.aTrust/var
chmod -R 755 /root/.aTrust/var
chmod -R 777 /usr/share/sangfor/aTrust/resources/app
# setuid helpers used by the deb install (same as the original deb)
[ -f /usr/share/sangfor/aTrust/resources/bin/dmidecode_processor_tool ] && \
    chmod a+s /usr/share/sangfor/aTrust/resources/bin/dmidecode_processor_tool
[ -f /usr/share/sangfor/aTrust/uem/bin/uem_installer ] && \
    chmod a+s /usr/share/sangfor/aTrust/uem/bin/uem_installer
# local CA host alias
[ -x /usr/share/sangfor/aTrust/resources/bin/linuxHelper ] && \
    /usr/share/sangfor/aTrust/resources/bin/linuxHelper -ah "127.0.0.1" "localhost.sangfor.com.cn" >/dev/null 2>&1 || :

# Extra login addresses (one URL per line, '#' for comments).
# Only created when missing, so user edits survive upgrades.
if [ ! -f /usr/share/sangfor/.aTrust/var/conf/addr.list ]; then
    cat > /usr/share/sangfor/.aTrust/var/conf/addr.list <<'ADDRLIST'
# 登录服务器地址，一行一个，最多取前 10 条；'#' 开头为注释。
# 例：
# https://vpn.example.edu.cn
ADDRLIST
    chmod 666 /usr/share/sangfor/.aTrust/var/conf/addr.list
fi

%systemd_post aTrustDaemon.service

%preun
%systemd_preun aTrustDaemon.service

%postun
%systemd_postun_with_restart aTrustDaemon.service

%files
%defattr(-,root,root,-)
/usr/share/sangfor
/usr/share/applications/cn.com.sangfor.atrust.desktop
/usr/share/pixmaps/aTrust.png
/usr/lib/systemd/system/aTrustDaemon.service
/usr/lib/systemd/system/aTrustShell.service
/usr/lib/systemd/system/aTrustTray@.service
/usr/lib/systemd/user/aTrustShell.service
/usr/lib/systemd/user/aTrustTray.service
/opt/apps

%changelog
* Tue Oct 27 2026 NOBB2333 - 2.5.16.50-5
- Pin and verify the official Ubuntu amd64 source for local and Release builds.
- Add x86_64 build metadata and require systemd RPM macros.
- Declare missing Qt/XCB and Electron shared-library dependencies.
