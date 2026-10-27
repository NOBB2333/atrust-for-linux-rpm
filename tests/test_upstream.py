"""Only compare the official Ubuntu amd64 channel with our pinned source."""

from pathlib import Path
import runpy
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-upstream.py"


class UpstreamTests(unittest.TestCase):
    def latest(self, data):
        return runpy.run_path(str(SCRIPT))["find_latest"](data)

    def test_windows_and_kylin_do_not_override_ubuntu(self):
        data = """const downloadList = {'stable': [
          {name: 'Windows：9.0.0.0', url: 'https://atrustcdn.sangfor.com/windows/client.exe'},
          {name: 'Kylin_X86：8.0.0.0', url: 'https://atrustcdn.sangfor.com/linux/client.deb'},
          {name: 'Ubuntu_X86：2.5.16.50', url: 'https://atrustcdn.sangfor.com/standard/linux/2.5.16.50/ubuntu/amd64/aTrustInstaller_amd64.deb'}
        ]}"""
        self.assertEqual(self.latest(data), (
            "2.5.16.50",
            "https://atrustcdn.sangfor.com/standard/linux/2.5.16.50/ubuntu/amd64/aTrustInstaller_amd64.deb",
        ))

    def test_versions_are_sorted_numerically(self):
        data = """[
          {name: 'Ubuntu_X86：2.5.16.9', url: 'https://atrustcdn.sangfor.com/standard/linux/2.5.16.9/ubuntu/amd64/aTrustInstaller_amd64.deb'},
          {name: 'Ubuntu_X86：2.5.16.50', url: 'https://atrustcdn.sangfor.com/standard/linux/2.5.16.50/ubuntu/amd64/aTrustInstaller_amd64.deb'}
        ]"""
        self.assertEqual(self.latest(data)[0], "2.5.16.50")

    def test_changed_official_format_reports_no_ubuntu_package(self):
        with self.assertRaisesRegex(ValueError, "Ubuntu_X86"):
            self.latest("const downloadList = {}")

    def test_label_and_download_version_must_agree(self):
        data = """{name: 'Ubuntu_X86：2.5.16.51', url: 'https://atrustcdn.sangfor.com/standard/linux/2.5.16.50/ubuntu/amd64/aTrustInstaller_amd64.deb'}"""
        with self.assertRaisesRegex(ValueError, "version"):
            self.latest(data)


if __name__ == "__main__":
    unittest.main()
