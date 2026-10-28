"""The hooks end to end: Holdback run as Claude Code runs it, with the hook's JSON on
stdin, and a stand-in `claude` on PATH as the judge.

Run:  python3 -m unittest discover -s tests -v
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest

import helpers
from helpers import HOLDBACK_PY, STATE, called, human, reset_state, said, transcript
from holdback import MARK, state

SP = "/private/tmp/claude-501/-Users-someone/0000/scratchpad"
FAKE = tempfile.mkdtemp(prefix="holdback-fake-claude-")
# The stand-in judge: on a message, work when it has "fix" in it and no "?"; on an appeal,
# reads when the command says "readsonly-tool". It logs each call, so the tests can count them.
with open(os.path.join(FAKE, "claude"), "w") as f:
    f.write("""#!%s
import json, sys
case = sys.stdin.read()
open(%s, "a").write(json.dumps(case) + "\\n")
if "<command>" in case:
    cmd = case.split("<command>")[1].split("</command>")[0]
    reads = "readsonly-tool" in cmd
    print(json.dumps({"structured_output": {"reads": reads,
                                            "reason": "lists things" if reads else "writes a file"}}))
else:
    msg = case.split("<message>")[1].split("</message>")[0]
    work = "fix" in msg.lower() and "?" not in msg
    print(json.dumps({"structured_output": {"work": work, "kind": "instruction" if work else "question",
                                            "reason": "an instruction to fix it" if work else
                                                      "a question about the build"}}))
""" % (sys.executable, json.dumps(os.path.join(FAKE, "calls.log"))))
os.chmod(os.path.join(FAKE, "claude"), stat.S_IRWXU)


def run(data, env=None):
    e = {k: v for k, v in os.environ.items()
         if not k.startswith(("HOLDBACK", "TETHER", "CLAUDE_CODE", "CLAUDE_PLUGIN"))}
    e.update({"HOLDBACK_STATE": STATE, "HOLDBACK_CONFIG": os.path.join(STATE, "config.json"),
              "HOLDBACK_UPDATE": "0", "PATH": FAKE + os.pathsep + e.get("PATH", ""),
              "HOLDBACK_NO_WARM": "1", "CLAUDE_CODE_ENTRYPOINT": "claude-desktop", **(env or {})})
    p = subprocess.run([sys.executable, HOLDBACK_PY], input=json.dumps(data), capture_output=True,
                       text=True, env=e, timeout=60)
    return json.loads(p.stdout) if p.stdout.strip() else None


def calls() -> int:
    try:
        with open(os.path.join(FAKE, "calls.log")) as f:
            return len(f.read().splitlines())
    except OSError:
        return 0


def appeals() -> int:
    try:
        with open(os.path.join(FAKE, "calls.log")) as f:
            return len([ln for ln in f.read().splitlines() if "<command>" in ln])
    except OSError:
        return 0


def pre(path, tool, inp, **extra):
    return {"hook_event_name": "PreToolUse", "session_id": "hook-test", "transcript_path": path,
            "cwd": "/Users/x/p", "tool_name": tool, "tool_input": inp, "tool_use_id": "toolu_1", **extra}


class Fresh(unittest.TestCase):
    def setUp(self):
        reset_state()
        try:
            os.unlink(os.path.join(FAKE, "calls.log"))
        except OSError:
            pass


@helpers.posix_only
class Gate(Fresh):
    def test_a_question_turn_holds_an_edit(self):
        path = transcript([human("Why is the build failing?")])
        out = run(pre(path, "Edit", {"file_path": "/Users/x/p/build.sh", "old_string": "a", "new_string": "b"}))
        h = out["hookSpecificOutput"]
        self.assertEqual(h["permissionDecision"], "deny")
        reason = h["permissionDecisionReason"]
        self.assertTrue(reason.startswith(MARK))
        self.assertIn("never hand this off", reason)          # Tether's handoff leaves it alone
        self.assertIn("change /Users/x/p/build.sh", reason)
        self.assertIn("a question about the build", reason)

    def test_a_question_turn_still_reads_and_checks_its_draft(self):
        path = transcript([human("Why is the build failing?")])
        for tool, inp in [("Read", {"file_path": "/Users/x/p/build.sh"}), ("Bash", {"command": "git log -5"}),
                          ("Write", {"file_path": "%s/draft.md" % SP, "content": "x"}),
                          ("Bash", {"command": 'python3 "/Users/x/tether/tether.py" check "%s/draft.md"' % SP}),
                          ("mcp__ccd_turn__wrap_up", {"recap": "x"})]:
            with self.subTest(tool=tool):
                self.assertIsNone(run(pre(path, tool, inp)))
        self.assertEqual(calls(), 0)                          # reading never asks the judge

    def test_an_instruction_turn_lets_work_through(self):
        path = transcript([human("Why is the build failing?"), said("A stale lockfile."), human("Fix it.")])
        self.assertIsNone(run(pre(path, "Bash", {"command": "npm install"})))
        self.assertIsNone(run(pre(path, "Edit", {"file_path": "/Users/x/p/a.js"})))
        self.assertEqual(calls(), 1)                          # one verdict, kept

    def test_a_critique_after_work_holds_more_work(self):
        path = transcript([human("Fix the port."), said("I set it to 3000."), human("That's wrong, it's 8080.")])
        self.assertEqual(run(pre(path, "Edit", {"file_path": "/Users/x/p/c.yml"}))["hookSpecificOutput"]
                         ["permissionDecision"], "deny")

    def test_a_subagent_in_a_question_turn_is_held(self):
        path = transcript([human("Why is the build failing?"), called("Agent", {"prompt": "x"}, tid="a")])
        out = run(pre(path, "Write", {"file_path": "/Users/x/p/x.js"}, agent_id="abc123", agent_type="general"))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_a_question_turn_runs_an_unknown_command_the_appeal_clears(self):
        path = transcript([human("Why is the build failing?")])
        cmd = {"command": "readsonly-tool --report"}
        self.assertIsNone(run(pre(path, "Bash", cmd)))
        self.assertEqual(appeals(), 1)
        self.assertIsNone(run(pre(path, "Bash", cmd)))
        self.assertEqual(appeals(), 1)                        # the second call used the verdict kept

    def test_a_question_turn_still_holds_an_unknown_command_that_changes_something(self):
        path = transcript([human("Why is the build failing?")])
        out = run(pre(path, "Bash", {"command": "mystery-tool --out notes.txt"}))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertTrue(out["hookSpecificOutput"]["permissionDecisionReason"].startswith(MARK))
        self.assertEqual(appeals(), 1)

    def test_a_command_naming_something_that_changes_things_is_never_appealed(self):
        path = transcript([human("Why is the build failing?")])
        for cmd in ("readsonly-tool && git push", "readsonly-tool | sudo tee /etc/hosts", "npm install",
                    "rm -rf build"):
            with self.subTest(command=cmd):
                out = run(pre(path, "Bash", {"command": cmd}))
                self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(appeals(), 0)

    def test_the_appeal_can_be_turned_off(self):
        path = transcript([human("Why is the build failing?")])
        out = run(pre(path, "Bash", {"command": "readsonly-tool --report"}), {"HOLDBACK_APPEAL": "0"})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(appeals(), 0)

    def test_an_instruction_turn_never_asks_for_an_appeal(self):
        path = transcript([human("Fix the build.")])
        self.assertIsNone(run(pre(path, "Bash", {"command": "mystery-tool --out notes.txt"})))
        self.assertEqual(appeals(), 0)

    def test_headless_runs_are_left_alone_unless_the_caller_says(self):
        path = transcript([human("Why is the build failing?")])
        data = pre(path, "Edit", {"file_path": "/Users/x/p/a.js"})
        self.assertIsNone(run(data, {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}))
        self.assertIsNotNone(run(data, {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", "TETHER": "1"}))
        self.assertIsNotNone(run(data, {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", "HOLDBACK": "1"}))

    def test_holdback_0_turns_it_off(self):
        path = transcript([human("Why is the build failing?")])
        self.assertIsNone(run(pre(path, "Edit", {"file_path": "/Users/x/p/a.js"}), {"HOLDBACK": "0"}))

    def test_the_plugin_steps_aside_for_the_installed_hooks(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, ".claude"))
        with open(os.path.join(home, ".claude", "settings.json"), "w") as f:
            json.dump({"hooks": {"PreToolUse": [{"hooks": [{"command": 'python3 -m holdback.hooks'}]}]}}, f)
        path = transcript([human("Why is the build failing?")])
        data = pre(path, "Edit", {"file_path": "/Users/x/p/a.js"})
        self.assertIsNone(run(data, {"HOME": home, "CLAUDE_PLUGIN_ROOT": "/plugins/holdback"}))
        self.assertIsNotNone(run(data, {"HOME": home, "CLAUDE_PLUGIN_ROOT": "/plugins/holdback",
                                        "HOLDBACK_PLUGIN": "1"}))


@helpers.posix_only
class AsInstalled(Fresh):
    """The installed hook command, `python -m holdback.hooks`, which runs wherever the
    session is - including this checkout, where holdback.py sits next to the package."""

    def test_it_runs_from_inside_the_checkout(self):
        path = transcript([human("Why is the build failing?")])
        e = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE", "CLAUDE_PLUGIN"))}
        e.update({"HOLDBACK_STATE": STATE, "HOLDBACK_CONFIG": os.path.join(STATE, "config.json"),
                  "HOLDBACK_UPDATE": "0", "PATH": FAKE + os.pathsep + e.get("PATH", ""),
                  "HOLDBACK_NO_WARM": "1", "CLAUDE_CODE_ENTRYPOINT": "claude-desktop",
                  "PYTHONPATH": str(helpers.ROOT / "src")})
        p = subprocess.run([sys.executable, "-m", "holdback.hooks"],
                           input=json.dumps(pre(path, "Edit", {"file_path": "/Users/x/p/a.js"})),
                           capture_output=True, text=True, env=e, cwd=str(helpers.ROOT), timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")


@helpers.posix_only
class Prompt(Fresh):
    def test_the_rule_goes_in_front_of_the_session(self):
        path = transcript([human("Why is the build failing?")])
        out = run({"hook_event_name": "UserPromptSubmit", "session_id": "p1", "transcript_path": path,
                   "prompt": "Why is the build failing?"})
        ctx = out["hookSpecificOutput"]["additionalContext"]
        with open(os.path.join(helpers.ROOT, "src", "holdback", "rule.md")) as f:
            self.assertEqual(ctx, f.read().strip())

    def test_the_verdict_is_worked_out_before_the_first_call(self):
        path = transcript([human("Fix the build.")])
        run({"hook_event_name": "UserPromptSubmit", "session_id": "p2", "transcript_path": path,
             "prompt": "Fix the build."}, {"HOLDBACK_NO_WARM": ""})
        deadline = time.time() + 20
        while time.time() < deadline and not state.load("p2").get("verdicts"):
            time.sleep(0.2)
        verdicts = state.load("p2").get("verdicts")
        self.assertTrue(verdicts)
        self.assertTrue(next(iter(verdicts.values()))["work"])
        self.assertIsNone(run(pre(path, "Edit", {"file_path": "/Users/x/p/a.js"}, session_id="p2")))
        self.assertEqual(calls(), 1)                          # the call used the verdict already kept


if __name__ == "__main__":
    unittest.main()
