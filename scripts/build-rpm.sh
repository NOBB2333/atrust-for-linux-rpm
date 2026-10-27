#!/usr/bin/env bash
# 本地与 GitHub Release 共用的打包入口，不安装或启动客户端。
# 用法：./scripts/build-rpm.sh [官方 deb 路径]
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=../sources.env
source "$repo_dir/sources.env"

die() { echo "Error: $*" >&2; exit 1; }

[[ $# -le 1 ]] || die "usage: $0 [official.deb]"
[[ $(uname -m) == x86_64 ]] || die "only x86_64 builds are supported"
for tool in ar tar curl sha256sum rpmbuild rpmspec; do
    command -v "$tool" >/dev/null || die "missing tool: $tool (see README.md)"
done
[[ $ATRUST_DEB_SHA256 =~ ^[0-9a-f]{64}$ ]] || die "invalid SHA256 in sources.env"

spec_version=$(rpmspec -q --qf '%{VERSION}' "$repo_dir/atrust.spec")
[[ $spec_version == "$ATRUST_VERSION" ]] || die "spec version $spec_version != $ATRUST_VERSION"
package_version=$(rpmspec --define 'dist %{nil}' -q --qf '%{VERSION}-%{RELEASE}' "$repo_dir/atrust.spec")
if [[ -n ${RELEASE_TAG:-} && $RELEASE_TAG != "v$package_version" ]]; then
    die "release tag $RELEASE_TAG must be v$package_version"
fi

mkdir -p "$repo_dir/.build"
build_dir=$(mktemp -d "$repo_dir/.build/rpmbuild.XXXXXX")
trap 'rm -rf -- "$build_dir"' EXIT
mkdir -p "$build_dir"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS,control}

deb=${1:-"$repo_dir/.cache/aTrustInstaller_amd64_$ATRUST_VERSION.deb"}
if [[ $# -eq 0 && ! -f $deb ]]; then
    echo "Downloading $ATRUST_DEB_URL"
    curl --fail --location --retry 3 --connect-timeout 20 --max-time 600 \
        --output "$build_dir/source.deb" "$ATRUST_DEB_URL"
    mkdir -p "$repo_dir/.cache"
    mv "$build_dir/source.deb" "$deb"
fi
[[ -f $deb ]] || die "deb file not found: $deb"
actual_sha256=$(sha256sum "$deb" | awk '{print $1}')
[[ $actual_sha256 == "$ATRUST_DEB_SHA256" ]] || die "SHA256 mismatch for $deb"
echo "SHA256 verified: $actual_sha256"

members=$(ar t "$deb")
control_member=$(awk '/^control\.tar(\.(gz|xz|zst|bz2))?$/ {print}' <<< "$members")
data_member=$(awk '/^data\.tar(\.(gz|xz|zst|bz2))?$/ {print}' <<< "$members")
[[ -n $control_member && -n $data_member ]] || die "invalid Debian archive"

extract_member() {
    local member=$1 destination=$2
    local compression=()
    case "$member" in
        *.gz) compression=(--gzip) ;;
        *.xz) compression=(--xz) ;;
        *.zst) compression=(--zstd) ;;
        *.bz2) compression=(--bzip2) ;;
    esac
    ar p "$deb" "$member" | tar "${compression[@]}" -xf - -C "$destination"
}

extract_member "$control_member" "$build_dir/control"
control="$build_dir/control/control"
deb_version=$(awk -F ': *' '$1 == "Version" {print $2}' "$control")
deb_arch=$(awk -F ': *' '$1 == "Architecture" {print $2}' "$control")
deb_package=$(awk -F ': *' '$1 == "Package" {print $2}' "$control")
[[ $deb_version == "$ATRUST_VERSION" ]] || die "deb version $deb_version != $ATRUST_VERSION"
[[ $deb_arch == amd64 ]] || die "deb architecture $deb_arch != amd64"
[[ $deb_package == cn.com.sangfor.atrust ]] || die "unexpected deb package: $deb_package"

mkdir -p "$build_dir/SOURCES/stage"
extract_member "$data_member" "$build_dir/SOURCES/stage"
cp "$repo_dir/patches/history-addr-fedora.js" "$build_dir/SOURCES/"
rpmbuild -bb --define "_topdir $build_dir" "$repo_dir/atrust.spec"

package_name=$(rpmspec -q --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}.rpm' "$repo_dir/atrust.spec")
package="$build_dir/RPMS/x86_64/$package_name"
[[ -f $package ]] || die "expected RPM was not produced: $package"
mkdir -p "$repo_dir/dist"
cp "$package" "$repo_dir/dist/"
(
    cd "$repo_dir/dist"
    sha256sum "$(basename -- "$package")" > SHA256SUMS
)
echo "RPM: $repo_dir/dist/$(basename -- "$package")"
