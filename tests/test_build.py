"""Exercise the packaging entry point with a small, real Debian archive."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        spec = (REPO / "atrust.spec").read_text()
        spec = re.sub(r"^Version:\s*.+$", "Version:        2.5.16.50", spec, flags=re.MULTILINE)
        spec = re.sub(r"^Release:\s*.+$", "Release:        1%{?dist}", spec, flags=re.MULTILINE)
        (self.root / "atrust.spec").write_text(spec)
        shutil.copytree(REPO / "patches", self.root / "patches")
        shutil.copytree(REPO / "scripts", self.root / "scripts")
        self.deb = self.make_deb()
        self.write_source()

    def make_deb(self, version="2.5.16.50", arch="amd64"):
        control = self.root / "control"
        control.mkdir(exist_ok=True)
        (control / "control").write_text(
            f"Package: cn.com.sangfor.atrust\nVersion: {version}\nArchitecture: {arch}\n"
        )
        payload = self.root / "payload"
        paths = [
            "usr/share/sangfor/aTrust/resources/bin/aTrustDaemon",
            "usr/share/sangfor/aTrust/resources/lib/libxcb.so.1",
            "usr/share/sangfor/aTrust/resources/lib/libqxcb.so",
            "usr/share/sangfor/aTrust/resources/app/src/service/history_addr.js",
            "usr/share/applications/cn.com.sangfor.atrust.desktop",
            "usr/share/pixmaps/aTrust.png",
            "usr/lib/systemd/system/aTrustDaemon.service",
            "usr/lib/systemd/system/aTrustShell.service",
            "usr/lib/systemd/system/aTrustTray@.service",
            "usr/lib/systemd/user/aTrustShell.service",
            "usr/lib/systemd/user/aTrustTray.service",
            "opt/apps/cn.com.sangfor.atrust/info",
        ]
        for name in paths:
            path = payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("vendor fixture\n")
        for directory, name in [(control, "control.tar.gz"), (payload, "data.tar.gz")]:
            with tarfile.open(self.root / name, "w:gz") as archive:
                archive.add(directory, arcname=".")
        (self.root / "debian-binary").write_text("2.0\n")
        deb = self.root / "client.deb"
        if deb.exists():
            deb.unlink()
        subprocess.run(
            ["ar", "rc", str(deb), "debian-binary", "control.tar.gz", "data.tar.gz"],
            cwd=self.root, check=True, capture_output=True,
        )
        return deb

    def write_source(self, checksum=None):
        digest = checksum or hashlib.sha256(self.deb.read_bytes()).hexdigest()
        (self.root / "sources.env").write_text(
            "ATRUST_VERSION=2.5.16.50\n"
            f"ATRUST_DEB_URL={self.deb.as_uri()}\n"
            f"ATRUST_DEB_SHA256={digest}\n"
        )

    def build(self, tag="", download=False):
        env = dict(os.environ, RELEASE_TAG=tag)
        args = ["bash", str(self.root / "scripts/build-rpm.sh")]
        if not download:
            args.append(str(self.deb))
        return subprocess.run(args, env=env, text=True, capture_output=True)

    def test_download_builds_rpm_with_fedora_patches_and_valid_checksum(self):
        result = self.build(download=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        packages = list((self.root / "dist").glob("atrust-*.x86_64.rpm"))
        self.assertEqual(len(packages), 1)
        query = subprocess.check_output(
            ["rpm", "-qp", "--qf", "%{VERSION} %{ARCH}", str(packages[0])], text=True,
        )
        self.assertEqual(query, "2.5.16.50 x86_64")
        filelist = subprocess.check_output(["rpm", "-qpl", str(packages[0])], text=True)
        self.assertIn("/resources/lib/libxcb.so.1.bundled\n", filelist)
        self.assertNotIn("/resources/lib/libxcb.so.1\n", filelist)
        self.assertIn("/resources/bin/qt.conf\n", filelist)
        subprocess.run(
            ["sha256sum", "--check", "SHA256SUMS"], cwd=self.root / "dist", check=True,
            capture_output=True,
        )

    def test_corrupt_source_is_rejected_before_packaging(self):
        self.write_source(checksum="0" * 64)
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA256", result.stderr + result.stdout)
        self.assertFalse((self.root / "dist").exists())

    def test_deb_version_must_match_locked_version(self):
        self.make_deb(version="2.5.16.51")
        self.write_source()
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("deb version", result.stderr)

    def test_deb_architecture_must_be_amd64(self):
        self.make_deb(arch="arm64")
        self.write_source()
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("deb architecture", result.stderr)

    def test_spec_version_must_match_locked_version(self):
        spec = self.root / "atrust.spec"
        spec.write_text(spec.read_text().replace("Version:        2.5.16.50", "Version:        2.5.16.51"))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("spec version", result.stderr)

    def test_release_tag_must_match_version_and_rpm_release(self):
        result = self.build(tag="v2.5.16.50-999")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release tag", result.stderr)

    def test_matching_release_tag_builds_successfully(self):
        result = self.build(tag="v2.5.16.50-1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(list((self.root / "dist").glob("atrust-*.rpm"))), 1)


if __name__ == "__main__":
    unittest.main()
