"""Keeping Holdback current: comparing versions, when a check is due, and what one run of
the check does. Nothing here reaches GitHub.

Run:  python3 -m unittest discover -s tests -v
"""
import json
import time
import unittest
from unittest import mock

import helpers
from helpers import reset_state
from holdback import config, package, update


class Versions(unittest.TestCase):
    def test_newer(self):
        self.assertTrue(update.is_newer("1.0.1", "1.0.0"))
        self.assertTrue(update.is_newer("1.1", "1.0.9"))
        self.assertTrue(update.is_newer("2.0", "1.9.9"))
        self.assertFalse(update.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(update.is_newer("1.0", "1.0.0"))
        self.assertFalse(update.is_newer("0.9.9", "1.0.0"))

    def test_not_a_version(self):
        with self.assertRaises(ValueError):
            update.parse("main")


class Due(unittest.TestCase):
    def setUp(self):
        reset_state()
        self.installed = mock.patch.object(package, "installer", return_value="pipx")
        self.installed.start()
        self.addCleanup(self.installed.stop)
        self.on = mock.patch.object(config, "settings",
                                    return_value=config.Settings(update=True))
        self.on.start()
        self.addCleanup(self.on.stop)

    def record(self, **fields):
        (config.state_dir()).mkdir(parents=True, exist_ok=True)
        (config.state_dir() / update.STATE_FILE).write_text(json.dumps(fields), encoding="utf-8")

    def test_the_first_check_is_due(self):
        self.assertTrue(update.due())

    def test_at_most_one_a_minute(self):
        self.record(checked_at=time.time())
        self.assertFalse(update.due())
        self.record(checked_at=time.time() - update.THROTTLE - 1)
        self.assertTrue(update.due())

    def test_a_failure_waits_longer_each_time(self):
        self.assertEqual(update.wait({"outcome": "failed: x", "failures": 1}), update.BACKOFF)
        self.assertEqual(update.wait({"outcome": "failed: x", "failures": 3}), update.BACKOFF * 4)
        self.assertEqual(update.wait({"outcome": "failed: x", "failures": 99}), update.MAX_BACKOFF)
        self.assertEqual(update.wait({"outcome": "up to date"}), update.THROTTLE)

    def test_a_windows_reinstall_holds_the_next_check_off(self):
        self.assertEqual(update.wait({"outcome": "updating 1.0.0 -> 1.0.1 once Holdback exits"}),
                         update.UPGRADE_TIMEOUT)

    def test_nothing_is_checked_when_updates_are_off(self):
        with mock.patch.object(config, "settings", return_value=config.Settings(update=False)):
            self.assertFalse(update.due())

    def test_nothing_is_checked_when_it_cannot_update_itself(self):
        with mock.patch.object(package, "installer", return_value=""):
            self.assertFalse(update.due())


class Run(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_up_to_date_records_the_check(self):
        with mock.patch.object(update, "latest_version", return_value=("0.0.1", "etag")):
            result = update.update()
        self.assertEqual(result.outcome, "up to date")
        self.assertFalse(result.upgraded)
        self.assertTrue(update.last()["checked_at"])
        self.assertEqual(update.last()["etag"], "etag")

    def test_a_check_only_run_reports_without_installing(self):
        with mock.patch.object(update, "latest_version", return_value=("999.0.0", "")), \
                mock.patch.object(package, "upgrade_command", return_value=["false"]) as cmd:
            result = update.update(check_only=True)
        self.assertEqual(result.outcome, "999.0.0 is available")
        self.assertFalse(result.upgraded)
        cmd.assert_not_called()
        self.assertNotIn("checked_at", update.last())   # a look never holds an update back

    @helpers.posix_only
    def test_a_newer_version_is_installed(self):
        ran = []
        with mock.patch.object(update, "latest_version", return_value=("999.0.0", "")), \
                mock.patch.object(package, "upgrade_command", return_value=["pipx", "install"]), \
                mock.patch.object(package, "checkout_held_back", return_value=""), \
                mock.patch.object(update, "_run", side_effect=lambda cmd, timeout: ran.append(cmd)):
            result = update.update()
        self.assertTrue(result.upgraded)
        self.assertEqual(ran, [["pipx", "install"]])
        self.assertTrue(update.last()["outcome"].startswith("updated"))

    def test_on_windows_the_reinstall_waits_for_this_process_to_exit(self):
        after = []
        with mock.patch.object(update, "latest_version", return_value=("999.0.0", "")), \
                mock.patch.object(package, "upgrade_command", return_value=["pipx", "install"]), \
                mock.patch.object(package, "installer", return_value="pipx"), \
                mock.patch.object(package, "checkout_held_back", return_value=""), \
                mock.patch.object(update.system, "run_after_exit", side_effect=after.append), \
                mock.patch.object(update.system, "windows", side_effect=lambda: True):
            result = update.update()
        self.assertTrue(result.upgraded)
        self.assertIn("once Holdback exits", result.outcome)
        self.assertEqual(after[0][0], ["pipx", "install"])

    def test_a_checkout_with_work_in_it_is_left_alone(self):
        ran = []
        with mock.patch.object(update, "latest_version", return_value=("999.0.0", "")), \
                mock.patch.object(package, "checkout_held_back",
                                  return_value="this checkout has changes of its own"), \
                mock.patch.object(update, "_run", side_effect=lambda cmd, timeout: ran.append(cmd)):
            result = update.update()
        self.assertFalse(result.upgraded)
        self.assertEqual(ran, [])
        self.assertIn("changes of its own", update.last()["outcome"])

    def test_a_failure_is_recorded_and_counted(self):
        with mock.patch.object(update, "latest_version", side_effect=OSError("no network")):
            for _ in range(2):
                with self.assertRaises(OSError):
                    update.update()
        self.assertTrue(update.last()["outcome"].startswith("failed"))
        self.assertEqual(update.last()["failures"], 2)

    def test_two_updates_never_run_at_once(self):
        with update._lock():
            self.assertTrue(update.running())
            self.assertFalse(update.start_if_due())
        self.assertFalse(update.running())


if __name__ == "__main__":
    unittest.main()
