"""install.sh: Holdback's hooks go in beside Tether's and the rest, and replace an older copy.

Run:  python3 -m unittest discover -s tests -v
"""
import json, os, subprocess, tempfile, unittest

from helpers import ROOT

TETHER_HOOK = {"type": "command", "command": 'python3 "$HOME/Development/tether/tether.py"', "timeout": 120}
GUARD = {"type": "command", "command": 'python3 "$HOME/.claude/hooks/guard-claude-md.py"', "timeout": 10}


def install(home, *args, env=None):
    e = {**os.environ, "HOME": home, "HOLDBACK_STATE": os.path.join(home, "state"), **(env or {})}
    e.pop("HOLDBACK_ALLOW_PATHS", None) if "HOLDBACK_ALLOW_PATHS" not in (env or {}) else None
    return subprocess.run(["sh", os.path.join(ROOT, "install.sh"), *args], capture_output=True, text=True, env=e,
                          check=True)


class Install(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.home, ".claude"))
        self.settings = os.path.join(self.home, ".claude", "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"permissions": {"defaultMode": "bypassPermissions"}, "hooks": {
                "PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash", "hooks": [GUARD]},
                               {"matcher": "*", "hooks": [TETHER_HOOK]}],
                "Stop": [{"hooks": [TETHER_HOOK]}],
                "UserPromptSubmit": [{"hooks": [dict(TETHER_HOOK, timeout=30)]}]}}, f)

    def read(self):
        with open(self.settings) as f:
            return json.load(f)

    def test_beside_tether_and_the_guard(self):
        install(self.home)
        s = self.read()
        pre = [h["command"] for g in s["hooks"]["PreToolUse"] for h in g["hooks"]]
        self.assertEqual(len(pre), 3)
        self.assertIn(GUARD["command"], pre)
        self.assertIn(TETHER_HOOK["command"], pre)
        mine = [g for g in s["hooks"]["PreToolUse"] if "holdback.py" in g["hooks"][0]["command"]][0]
        self.assertEqual(mine["matcher"], "*")
        self.assertTrue(mine["hooks"][0]["command"].startswith('python3 "'))
        self.assertTrue(mine["hooks"][0]["command"].endswith('holdback.py"'))
        self.assertEqual(len(s["hooks"]["UserPromptSubmit"]), 2)
        self.assertEqual(s["hooks"]["Stop"], [{"hooks": [TETHER_HOOK]}])
        self.assertEqual(s["permissions"], {"defaultMode": "bypassPermissions"})

    def test_again_replaces_its_own(self):
        install(self.home)
        install(self.home)
        s = self.read()
        self.assertEqual(sum("holdback.py" in h["command"] for g in s["hooks"]["PreToolUse"] for h in g["hooks"]), 1)
        self.assertEqual(sum("holdback.py" in h["command"] for g in s["hooks"]["UserPromptSubmit"] for h in g["hooks"]), 1)

    def test_it_keeps_the_allowed_paths(self):
        install(self.home, env={"HOLDBACK_ALLOW_PATHS": "~/voice-assistant/data/replies, /srv/drop"})
        with open(os.path.join(self.home, "state", "settings.json")) as f:
            self.assertEqual(json.load(f)["allow_paths"], ["~/voice-assistant/data/replies", "/srv/drop"])

    def test_the_plugin_carries_the_same_hooks(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json")) as f:
            hooks = json.load(f)["hooks"]
        self.assertEqual(sorted(hooks), ["PreToolUse", "UserPromptSubmit"])
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "*")


if __name__ == "__main__":
    unittest.main()
