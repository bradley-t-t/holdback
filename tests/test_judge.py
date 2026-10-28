"""The judges: the word scan that stands in for the message judge, and the appeal, which
is shown a command and nothing else and fails closed.

Run:  python3 -m unittest discover -s tests -v
"""
import os
import unittest
from unittest import mock

import helpers  # noqa: F401  (puts src on the path and points the state at a temp folder)
from holdback import judge as judges
from holdback.hooks.gate import appealable
from holdback.shell import bash_change
from holdback.unknown import Unknown

CWD = "/Users/someone/Development/project"


class Scan(unittest.TestCase):
    def test_messages(self):
        for message, before, want in [
            ("Fix it, test it, then release it.", "", True), ("Can you fix the login bug?", "", True),
            ("That's wrong, change it to 8080.", "", True), ("yes", "Want me to make that change?", True),
            ("/ship", "", True), ("Why is the build failing?", "", False),
            ("Explain again concisely.", "", False), ("Propose a plan to fix the issues.", "", False),
            ("That's wrong, the port is 8080 not 3000.", "", False), ("ok thanks", "The build is fixed.", False),
            ("Fix the bug. Actually wait, don't change anything yet.", "", False),
            ("It isn't supposed to say it left work undone.", "", False),
        ]:
            with self.subTest(message=message):
                self.assertEqual(judges.scan(message, before).work, want)

    def test_the_word_scan_decides_when_the_judge_cannot(self):
        with mock.patch.object(judges.system, "claude_bin", return_value="/nonexistent/claude"):
            v = judges.judge("Why is the build failing?")
            self.assertFalse(v.work)
            self.assertTrue(v.error)
            self.assertTrue(judges.judge("Fix it, test it, then release it.").work)


@helpers.posix_only
class Appeal(unittest.TestCase):
    def appealable(self, command):
        return appealable("Bash", bash_change(command, CWD), command)

    def test_only_an_unrecognized_command_naming_nothing_that_changes_can_be_appealed(self):
        self.assertTrue(self.appealable("some-unknown-tool --flag"))
        self.assertTrue(self.appealable("powershell -Command 'Get-ComputerInfo'"))
        self.assertTrue(self.appealable("echo 'unclosed"))
        self.assertTrue(self.appealable("python3 -m mystery_module --report"))
        self.assertFalse(self.appealable("git status"))               # read: nothing to appeal
        self.assertFalse(self.appealable("npm install"))              # a change Holdback read
        self.assertFalse(self.appealable("ollama pull llama3"))       # a program Holdback knows
        self.assertFalse(self.appealable("some-unknown-tool && git push"))
        self.assertFalse(self.appealable("some-unknown-tool | sudo tee /etc/hosts"))
        self.assertFalse(self.appealable("mystery-tool --out x; brew install jq"))
        self.assertFalse(appealable("Edit", Unknown("change a.py"), ""))
        with mock.patch.dict(os.environ, {"HOLDBACK_APPEAL": "0"}):
            self.assertFalse(self.appealable("some-unknown-tool --flag"))

    def test_it_fails_closed(self):
        with mock.patch.object(judges, "ask", side_effect=RuntimeError("no judge here")):
            v = judges.appeal("some-unknown-tool --flag")
        self.assertFalse(v.work)
        self.assertTrue(v.error)
        with mock.patch.object(judges, "ask", return_value={"reason": "no idea"}):
            self.assertFalse(judges.appeal("some-unknown-tool --flag").work)
        with mock.patch.object(judges, "ask", return_value={"reads": True, "reason": "lists models"}):
            self.assertTrue(judges.appeal("some-unknown-tool --flag").work)

    def test_it_is_shown_the_command_and_not_the_person(self):
        seen = {}

        def fake(system_prompt, schema, case, timeout=None):
            seen.update(system=system_prompt, case=case)
            return {"reads": True, "reason": "prints the version"}

        with mock.patch.object(judges, "ask", side_effect=fake):
            judges.appeal("some-unknown-tool --version")
        self.assertIn("<command>", seen["case"])
        self.assertIn("some-unknown-tool --version", seen["case"])
        self.assertIn("<scratch>", seen["case"])
        self.assertNotIn("<message>", seen["case"])
        self.assertNotIn("<before>", seen["case"])
        self.assertIs(seen["system"], judges.CALL_SYSTEM)


if __name__ == "__main__":
    unittest.main()
