"""What Holdback does differently on Windows, with os.name standing in for it, plus the
checks that only mean anything on a real Windows machine.

Run:  python3 -m unittest discover -s tests -v
"""
import os
import unittest
from unittest import mock

import helpers  # noqa: F401  (puts src on the path)
from holdback import paths, system
from holdback.shell import bash_change
from holdback.unknown import Unknown


class AsWindows(unittest.TestCase):
    """system.windows() standing in for a Windows machine, so its branches run anywhere."""

    def setUp(self):
        self.nt = mock.patch.object(system, "windows", return_value=True)
        self.nt.start()
        self.addCleanup(self.nt.stop)

    def env(self, **values):
        return mock.patch.dict(os.environ, values, clear=False)

    def test_config_and_state_follow_windows_folders(self):
        with self.env(APPDATA=r"C:\Users\t\AppData\Roaming",
                      LOCALAPPDATA=r"C:\Users\t\AppData\Local"), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XDG_CONFIG_HOME", None)
            os.environ.pop("XDG_STATE_HOME", None)
            self.assertEqual(str(system.config_home()), r"C:\Users\t\AppData\Roaming")
            self.assertEqual(str(system.state_home()), r"C:\Users\t\AppData\Local")

    def test_temp_folders_are_the_windows_ones(self):
        with self.env(TEMP=r"C:\Temp", LOCALAPPDATA=r"C:\Users\t\AppData\Local"):
            dirs = [d.lower() for d in system.temp_dirs()]
        self.assertIn(r"c:\temp", dirs)
        self.assertIn(r"c:\users\t\appdata\local\temp", dirs)

    def test_a_cmd_file_runs_through_the_command_processor(self):
        with self.env(COMSPEC=r"C:\Windows\System32\cmd.exe"):
            cmd = system.program_command(r"C:\npm\claude.cmd", ["-p"])
        self.assertEqual(cmd[:4], [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c"])
        self.assertEqual(cmd[4:], [r"C:\npm\claude.cmd", "-p"])
        self.assertEqual(system.program_command(r"C:\x\claude.exe", []), [r"C:\x\claude.exe"])

    def test_paths_compare_without_case_or_separator(self):
        self.assertTrue(system.same_path(r"C:\Users\T\bin", "c:/users/t/bin/"))
        self.assertFalse(system.same_path(r"C:\Users\T\bin", r"C:\Users\T\other"))

    def test_a_scratch_write_is_recognized_whatever_the_case(self):
        with self.env(TEMP=r"C:\Temp"):
            self.assertTrue(paths.scratch(r"c:\temp\draft.md"))
            self.assertTrue(paths.scratch(r"C:\Temp\sub\draft.md"))
            self.assertFalse(paths.scratch(r"C:\Users\t\project\notes.txt"))

    def test_a_git_bash_path_is_read_as_the_drive_it_means(self):
        with self.env(TEMP=r"C:\Temp"):
            self.assertEqual(paths.expand("/c/Temp/draft.md"), r"C:\Temp\draft.md")
            self.assertTrue(paths.scratch("/c/Temp/draft.md"))

    def test_nul_is_a_sink(self):
        self.assertTrue(paths.scratch("NUL"))
        self.assertFalse(paths.scratch(r"C:\p\config.json"))   # not a sink just for starting "con"

    def test_powershell_is_held_but_appealable(self):
        what = bash_change('powershell -Command "Get-ComputerInfo"', r"C:\p")
        self.assertIsInstance(what, Unknown)
        self.assertIn("Get-ComputerInfo", what)

    def test_a_program_name_may_carry_its_extension(self):
        self.assertTrue(bash_change(r"git.exe push", r"C:\p"))
        self.assertIsNone(bash_change(r"git.exe status", r"C:\p"))


class Locking(unittest.TestCase):
    def test_only_one_process_holds_it(self):
        from holdback import config
        lock = config.state_dir() / "test.lock"
        with system.exclusive_lock(lock):
            with self.assertRaises(system.Locked):
                with system.exclusive_lock(lock):
                    pass
        with system.exclusive_lock(lock):
            pass                     # free again


class OnWindows(unittest.TestCase):
    """Only on a real Windows machine: the parts that call into the OS."""

    @helpers.windows_only
    def test_this_process_is_alive_and_a_freed_pid_is_not(self):
        self.assertTrue(system.alive(os.getpid()))
        self.assertFalse(system.alive(0x7FFFFFFF))

    @helpers.windows_only
    def test_the_lock_is_the_windows_one(self):
        self.assertIsNone(system._fcntl)
        self.assertIsNotNone(system._msvcrt)


if __name__ == "__main__":
    unittest.main()
