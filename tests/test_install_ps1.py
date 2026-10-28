"""install.ps1's own logic, run with PowerShell (pwsh) when it's installed. The script runs
a test file with its functions (HOLDBACK_INSTALL_TEST) instead of installing; the registry
is stood in for by plain variables.

Run:  python3 -m unittest discover -s tests -v
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import helpers

SCRIPT = helpers.ROOT / "install.ps1"
# Windows PowerShell 5.1 counts: install.ps1 has to run there too.
PWSH = shutil.which("pwsh") or (os.name == "nt" and shutil.which("powershell"))

# Replaces the registry functions and prints what a test asks for as JSON.
FAKES = r"""
$script:UserPath = $env:FAKE_USER_PATH
$script:Marked = ''
function Get-UserPath { $script:UserPath }
function Set-UserPath([string]$Value) { $script:UserPath = $Value }
function Get-MachinePath { $env:FAKE_MACHINE_PATH }
function Save-PathMark([string]$Dir) { $script:Marked = $Dir }
"""


@unittest.skipUnless(PWSH, "needs PowerShell")
class InstallPs1(unittest.TestCase):
    def run_ps(self, body: str, **env) -> dict:
        d = Path(tempfile.mkdtemp())
        test = d / "t.ps1"
        test.write_text(FAKES + body)
        full = dict(os.environ, HOLDBACK_INSTALL_TEST=str(test), FAKE_USER_PATH="",
                    FAKE_MACHINE_PATH="")
        full.update(env)
        p = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-File", str(SCRIPT)], capture_output=True, text=True, env=full, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout.strip().splitlines()[-1])

    def add(self, user="", machine="", session="/usr/bin"):
        return self.run_ps(r"""
$env:Path = $env:FAKE_SESSION
$a = Add-BinToPath 'C:\Users\t\.local\bin' 6>$null
$b = Add-BinToPath 'C:\Users\t\.local\bin' 6>$null
@{first=$a; second=$b; user=$script:UserPath; marked=$script:Marked; session=$env:Path} | ConvertTo-Json -Compress
""", FAKE_USER_PATH=user, FAKE_MACHINE_PATH=machine, FAKE_SESSION=session)

    def test_adds_the_folder_once_and_marks_it(self):
        r = self.add(user="%USERPROFILE%\\x;C:\\Python")
        self.assertEqual((r["first"], r["second"]), (True, False))
        self.assertEqual(r["user"], "C:\\Users\\t\\.local\\bin;%USERPROFILE%\\x;C:\\Python")
        self.assertEqual(r["marked"], "C:\\Users\\t\\.local\\bin")
        self.assertTrue(r["session"].startswith("C:\\Users\\t\\.local\\bin;"))
        self.assertEqual(r["session"].count(".local"), 1)

    def test_already_there_in_any_case_or_with_a_backslash(self):
        for user, machine in (("c:\\users\\t\\.local\\bin\\", ""), ("", "C:\\Users\\t\\.local\\bin")):
            with self.subTest(user=user, machine=machine):
                r = self.add(user=user, machine=machine)
                self.assertFalse(r["first"])
                self.assertEqual(r["marked"], "")

    def test_the_source_url_follows_the_ref(self):
        r = self.run_ps(r"@{url=(Get-SourceUrl)} | ConvertTo-Json -Compress", HOLDBACK_REF="v1.2.3")
        self.assertTrue(r["url"].endswith("@v1.2.3") or r["url"].endswith("/v1.2.3.tar.gz"), r["url"])


@unittest.skipUnless(PWSH, "needs PowerShell")
class Script(unittest.TestCase):
    def test_it_parses(self):
        p = subprocess.run(
            [PWSH, "-NoProfile", "-NonInteractive", "-Command",
             "$null = [System.Management.Automation.Language.Parser]::ParseFile("
             "'%s', [ref]$null, [ref]$errors); if ($errors) { $errors; exit 1 }" % SCRIPT],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
