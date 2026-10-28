"""The `holdback` command: setup writes the settings and the hooks, doctor reports what is
wrong, uninstall takes it all out again.

Run:  python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (puts src on the path and points the state at a temp folder)
from holdback import cli, config
from holdback.claude import settings
from holdback.commands import doctor, setup


class Home(unittest.TestCase):
    """A home folder of its own, so nothing touches the real one."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.settings = self.home / ".claude" / "settings.json"
        self.config = self.home / "config.json"
        self.env = mock.patch.dict(os.environ, {
            "CLAUDE_SETTINGS": str(self.settings), "HOLDBACK_CONFIG": str(self.config),
            "HOLDBACK_STATE": str(self.home / "state")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_cli(self, *argv, quiet=True) -> str:
        """Run the command and return what it printed."""
        out = io.StringIO()
        with redirect_stdout(out if quiet else sys.stdout):
            self.code = cli.main(list(argv))
        return out.getvalue()

    def read_settings(self) -> dict:
        return json.loads(self.settings.read_text())


class Setup(Home):
    def test_it_installs_the_hooks_and_keeps_what_was_chosen(self):
        self.run_cli("setup", "--yes", "--no-appeal", "--allow-paths", "~/drop, /srv/x")
        self.assertEqual(self.code, 0)
        for event in settings.EVENTS:
            self.assertTrue(settings.status(self.settings)[event], event)
        kept = json.loads(self.config.read_text())
        self.assertEqual(kept["allow_paths"], ["~/drop", "/srv/x"])
        self.assertIs(kept["appeal"], False)
        self.assertFalse(config.settings().appeal)
        self.assertEqual(config.settings().allow_paths, ["~/drop", "/srv/x"])

    def test_it_leaves_claude_md_alone_unless_asked(self):
        claude_md = self.home / ".claude" / "CLAUDE.md"
        claude_md.parent.mkdir(parents=True, exist_ok=True)
        claude_md.write_text("# My own notes\n\nKeep these.\n")
        with mock.patch.object(setup, "CLAUDE_MD", claude_md):
            self.run_cli("setup", "--yes")
            self.assertNotIn("Hold back", claude_md.read_text())
            self.run_cli("setup", "--yes", "--claude-md")
            text = claude_md.read_text()
        self.assertIn("Keep these.", text)
        self.assertIn(setup.title(), text)

    def test_writing_the_rule_twice_leaves_one_copy(self):
        claude_md = self.home / "CLAUDE.md"
        with mock.patch.object(setup, "CLAUDE_MD", claude_md):
            setup.write_rule()
            setup.write_rule()
        self.assertEqual(claude_md.read_text().count(setup.title()), 1)


class Doctor(Home):
    def test_it_says_the_hooks_are_missing_then_finds_them(self):
        levels = {t: lvl for lvl, t, _ in doctor.checks()}
        self.assertEqual(levels["Hook PreToolUse"], doctor.FAIL)
        self.run_cli("doctor")
        self.assertEqual(self.code, 1)
        self.run_cli("setup", "--yes")
        levels = {t: lvl for lvl, t, _ in doctor.checks()}
        self.assertEqual(levels["Hook PreToolUse"], doctor.OK)
        self.assertEqual(levels["Hook UserPromptSubmit"], doctor.OK)

    def test_it_warns_when_the_appeal_is_off(self):
        self.run_cli("setup", "--yes", "--no-appeal")
        levels = {t: lvl for lvl, t, _ in doctor.checks()}
        self.assertEqual(levels["Appeal"], doctor.WARN)


class Uninstall(Home):
    def test_it_takes_the_hooks_out_and_purges_on_request(self):
        self.run_cli("setup", "--yes", "--allow-paths", "/srv/x")
        self.assertTrue(self.config.exists())
        self.run_cli("uninstall", "--purge", "--yes")
        self.assertFalse(any(settings.status(self.settings)[e] for e in settings.EVENTS))
        self.assertFalse(self.config.exists())


class Status(Home):
    def test_it_prints_where_everything_is(self):
        self.run_cli("setup", "--yes")
        said = json.loads(self.run_cli("status"))
        self.assertTrue(said["PreToolUse"])
        self.assertEqual(said["settings"], str(self.config))


if __name__ == "__main__":
    unittest.main()
