"""Holdback's hooks in ~/.claude/settings.json: they go in beside Tether's and the rest,
replace an older Holdback copy, and come out again leaving everything else.

Run:  python3 -m unittest discover -s tests -v
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (puts src on the path)
from holdback.claude import settings

TETHER = {"type": "command", "command": 'python3 "$HOME/Development/tether/tether.py"', "timeout": 120}
GUARD = {"type": "command", "command": 'python3 "$HOME/.claude/hooks/guard-claude-md.py"', "timeout": 10}
OLD_HOLDBACK = {"type": "command", "command": 'python3 "$HOME/holdback/holdback.py"', "timeout": 120}


class Settings(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / ".claude" / "settings.json"
        self.path.parent.mkdir(parents=True)
        self.write({"permissions": {"defaultMode": "bypassPermissions"}, "hooks": {
            "PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash", "hooks": [GUARD]},
                           {"matcher": "*", "hooks": [TETHER]}],
            "Stop": [{"hooks": [TETHER]}],
            "UserPromptSubmit": [{"hooks": [dict(TETHER, timeout=30)]}]}})

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def commands(self, event):
        return [h["command"] for g in self.read()["hooks"][event] for h in g["hooks"]]

    def test_it_goes_in_beside_tether_and_the_guard(self):
        settings.install(self.path)
        s = self.read()
        pre = self.commands("PreToolUse")
        self.assertEqual(len(pre), 3)
        self.assertIn(GUARD["command"], pre)
        self.assertIn(TETHER["command"], pre)
        mine = [g for g in s["hooks"]["PreToolUse"] if settings.is_ours(g)][0]
        self.assertEqual(mine["matcher"], "*")
        self.assertEqual(mine["hooks"][0]["timeout"], 120)
        self.assertIn("-m holdback.hooks", settings.command_text(mine["hooks"][0]))
        self.assertEqual(len(s["hooks"]["UserPromptSubmit"]), 2)
        self.assertEqual(s["hooks"]["Stop"], [{"hooks": [TETHER]}])
        self.assertEqual(s["permissions"], {"defaultMode": "bypassPermissions"})

    def test_again_replaces_its_own(self):
        settings.install(self.path)
        settings.install(self.path)
        for event in settings.EVENTS:
            self.assertEqual(sum(1 for c in self.commands(event) if settings.has_marker(c)), 1, event)

    def test_it_replaces_an_older_checkout_hook(self):
        s = self.read()
        s["hooks"]["PreToolUse"].append({"matcher": "*", "hooks": [OLD_HOLDBACK]})
        self.write(s)
        settings.install(self.path)
        pre = self.commands("PreToolUse")
        self.assertNotIn(OLD_HOLDBACK["command"], pre)
        self.assertEqual(sum(1 for c in pre if settings.has_marker(c)), 1)

    def test_uninstall_leaves_the_others(self):
        settings.install(self.path)
        settings.uninstall(self.path)
        s = self.read()
        self.assertEqual(self.commands("PreToolUse"), [GUARD["command"], TETHER["command"]])
        self.assertEqual(s["hooks"]["Stop"], [{"hooks": [TETHER]}])
        self.assertEqual(s["permissions"], {"defaultMode": "bypassPermissions"})
        self.assertFalse(any(settings.status(self.path)[e] for e in settings.EVENTS))

    def test_it_backs_the_file_up_and_keeps_a_few(self):
        # One backup per second, so a fast loop leaves fewer than it makes.
        for _ in range(5):
            settings.install(self.path)
            settings.uninstall(self.path)
        made = settings.backups(self.path)
        self.assertTrue(made)
        self.assertLessEqual(len(made), settings.KEEP_BACKUPS)
        self.assertIn("hooks", json.loads(made[-1].read_text(encoding="utf-8")))

    def test_the_windows_hook_starts_python_with_no_shell(self):
        with mock.patch.object(settings.system, "windows", return_value=True):
            entry = settings.hook_entry("PreToolUse")
        self.assertEqual(entry["hooks"][0]["args"], ["-m", "holdback.hooks"])
        self.assertEqual(entry["matcher"], "*")

    def test_the_plugin_carries_the_same_hooks(self):
        hooks = json.loads((helpers.ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertEqual(sorted(hooks), sorted(settings.EVENTS))
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "*")


if __name__ == "__main__":
    unittest.main()
