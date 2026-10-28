"""install.sh puts the bin folder on PATH in the login shell's startup files, and
`holdback uninstall --all` takes that line out again.

Run:  python3 -m unittest discover -s tests -v
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers
from holdback import package

INSTALL_SH = helpers.ROOT / "install.sh"


@helpers.posix_only
class Harness(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.bin = str(self.home / ".local" / "bin")

    def check_path(self, shell, mac=False, orig_path="/usr/bin:/bin", **env):
        """Run install.sh's check_path for this login shell; returns its output."""
        script = ('. "%s"; %s BIN_DIR="%s"; ORIG_PATH="%s"; NEW_SHELL=""; check_path; '
                  'echo "NEW_SHELL=$NEW_SHELL"'
                  % (INSTALL_SH, "is_mac() { true; };" if mac else "is_mac() { false; };",
                     self.bin, orig_path))
        env.update({"HOME": str(self.home), "SHELL": shell, "PATH": "/usr/bin:/bin",
                    "HOLDBACK_INSTALL_FUNCTIONS": "1", "NO_COLOR": "1"})
        p = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def files(self):
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*") if p.is_file())

    def path_in(self, shell_cmd, rc):
        """PATH after a shell reads this startup file."""
        p = subprocess.run(shell_cmd + ['. "%s"; printf %%s "$PATH"' % rc],
                           env={"HOME": str(self.home), "PATH": "/usr/bin:/bin"},
                           capture_output=True, text=True)
        return p.stdout


class CheckPath(Harness):
    def test_zsh_gets_zshrc_not_profile(self):
        out = self.check_path("/bin/zsh")
        self.assertEqual(self.files(), [".zshrc"])
        self.assertIn("NEW_SHELL=1", out)
        self.assertIn(self.bin, (self.home / ".zshrc").read_text())

    def test_bash_on_a_mac_gets_bashrc_and_a_login_file(self):
        self.check_path("/bin/bash", mac=True)
        self.assertEqual(self.files(), [".bash_profile", ".bashrc"])

    def test_fish_gets_its_own_file(self):
        self.check_path("/usr/local/bin/fish")
        self.assertEqual(self.files(), [".config/fish/conf.d/holdback.fish"])

    def test_nothing_is_written_when_the_folder_is_already_on_path(self):
        out = self.check_path("/bin/zsh", orig_path="/usr/bin:%s:/bin" % self.bin)
        self.assertEqual(self.files(), [])
        self.assertIn("NEW_SHELL=\n", out)

    def test_running_it_twice_adds_one_line(self):
        self.check_path("/bin/zsh")
        self.check_path("/bin/zsh")
        text = (self.home / ".zshrc").read_text()
        self.assertEqual(text.count(package.PATH_MARK), 1)

    def test_the_line_a_shell_reads_puts_the_folder_on_path(self):
        self.check_path("/bin/zsh")
        got = self.path_in(["sh", "-c"], self.home / ".zshrc")
        self.assertTrue(got.startswith(self.bin + ":"), got)

    def test_uninstall_takes_the_line_out_again(self):
        self.check_path("/bin/zsh")
        before = (self.home / ".zshrc").read_text()
        self.assertIn(self.bin, before)
        with mock.patch.object(package.Path, "home", staticmethod(lambda: self.home)), \
                mock.patch.dict(os.environ, {"ZDOTDIR": "", "XDG_CONFIG_HOME": ""}):
            removed = package.remove_path_lines()
        self.assertTrue(removed)
        self.assertNotIn(self.bin, (self.home / ".zshrc").read_text())

    def test_uninstall_deletes_the_fish_file_it_wrote(self):
        self.check_path("/usr/local/bin/fish")
        fish = self.home / ".config" / "fish" / "conf.d" / "holdback.fish"
        self.assertTrue(fish.exists())
        with mock.patch.object(package.Path, "home", staticmethod(lambda: self.home)), \
                mock.patch.dict(os.environ, {"ZDOTDIR": "", "XDG_CONFIG_HOME": str(self.home / ".config")}):
            package.remove_path_lines()
        self.assertFalse(fish.exists())


@helpers.posix_only
class Script(unittest.TestCase):
    def test_it_is_valid_shell(self):
        p = subprocess.run(["sh", "-n", str(INSTALL_SH)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_it_installs_the_package_the_updater_reinstalls(self):
        text = INSTALL_SH.read_text()
        self.assertIn("claude-holdback", text)
        self.assertIn("pipx install --force", text)
        self.assertIn("uv tool install --force --reinstall", text)
        self.assertIn("holdback setup", text)


if __name__ == "__main__":
    unittest.main()
