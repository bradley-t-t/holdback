"""The hooks end to end: holdback.py run as Claude Code runs it, with the hook's JSON on stdin,
and a stand-in `claude` on PATH as the judge.

Run:  python3 -m unittest discover -s tests -v
"""
import json, os, stat, subprocess, sys, tempfile, time, unittest

from helpers import HOLDBACK_PY, STATE, holdback, transcript, human, said, called, result, reset_state

SP = "/private/tmp/claude-501/-Users-someone/0000/scratchpad"
FAKE = tempfile.mkdtemp(prefix="holdback-fake-claude-")
# The stand-in judge: work when the message has "fix" in it and no "?". It logs each call.
with open(os.path.join(FAKE, "claude"), "w") as f:
    f.write(f"""#!{sys.executable}
import json, sys
case = sys.stdin.read()
open({json.dumps(os.path.join(FAKE, "calls.log"))}, "a").write(json.dumps(case) + "\\n")
msg = case.split("<message>")[1].split("</message>")[0]
work = "fix" in msg.lower() and "?" not in msg
print(json.dumps({{"structured_output": {{"work": work, "kind": "instruction" if work else "question",
                                        "reason": "an instruction to fix it" if work else "a question about the build"}}}}))
""")
os.chmod(os.path.join(FAKE, "claude"), stat.S_IRWXU)


def run(data, env=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("HOLDBACK", "TETHER", "CLAUDE_CODE", "CLAUDE_PLUGIN"))}
    e.update({"HOLDBACK_STATE": STATE, "PATH": FAKE + os.pathsep + e.get("PATH", ""), "HOLDBACK_NO_WARM": "1",
              "CLAUDE_CODE_ENTRYPOINT": "claude-desktop", **(env or {})})
    p = subprocess.run([sys.executable, HOLDBACK_PY], input=json.dumps(data), capture_output=True, text=True,
                       env=e, timeout=60)
    return json.loads(p.stdout) if p.stdout.strip() else None


def calls() -> int:
    try:
        with open(os.path.join(FAKE, "calls.log")) as f:
            return len(f.read().splitlines())
    except OSError:
        return 0


def pre(path, tool, inp, **extra):
    return {"hook_event_name": "PreToolUse", "session_id": "hook-test", "transcript_path": path, "cwd": "/Users/x/p",
            "tool_name": tool, "tool_input": inp, "tool_use_id": "toolu_1", **extra}


class Gate(unittest.TestCase):
    def setUp(self):
        reset_state()
        try:
            os.unlink(os.path.join(FAKE, "calls.log"))
        except OSError:
            pass

    def test_a_question_turn_holds_an_edit(self):
        path = transcript([human("Why is the build failing?")])
        out = run(pre(path, "Edit", {"file_path": "/Users/x/p/build.sh", "old_string": "a", "new_string": "b"}))
        h = out["hookSpecificOutput"]
        self.assertEqual(h["permissionDecision"], "deny")
        reason = h["permissionDecisionReason"]
        self.assertTrue(reason.startswith(holdback.MARK))
        self.assertIn("never hand this off", reason)          # Tether's handoff leaves it alone
        self.assertIn("change /Users/x/p/build.sh", reason)
        self.assertIn("a question about the build", reason)

    def test_a_question_turn_still_reads_and_checks_its_draft(self):
        path = transcript([human("Why is the build failing?")])
        for tool, inp in [("Read", {"file_path": "/Users/x/p/build.sh"}), ("Bash", {"command": "git log -5"}),
                          ("Write", {"file_path": f"{SP}/draft.md", "content": "x"}),
                          ("Bash", {"command": f'python3 "/Users/x/tether/tether.py" check "{SP}/draft.md"'}),
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
            json.dump({"hooks": {"PreToolUse": [{"hooks": [{"command": 'python3 "$HOME/holdback/holdback.py"'}]}]}}, f)
        path = transcript([human("Why is the build failing?")])
        data = pre(path, "Edit", {"file_path": "/Users/x/p/a.js"})
        self.assertIsNone(run(data, {"HOME": home, "CLAUDE_PLUGIN_ROOT": "/plugins/holdback"}))
        self.assertIsNotNone(run(data, {"HOME": home, "CLAUDE_PLUGIN_ROOT": "/plugins/holdback", "HOLDBACK_PLUGIN": "1"}))


class Prompt(unittest.TestCase):
    def setUp(self):
        reset_state()
        try:
            os.unlink(os.path.join(FAKE, "calls.log"))
        except OSError:
            pass

    def test_the_rule_goes_in_front_of_the_session(self):
        path = transcript([human("Why is the build failing?")])
        out = run({"hook_event_name": "UserPromptSubmit", "session_id": "p1", "transcript_path": path,
                   "prompt": "Why is the build failing?"})
        ctx = out["hookSpecificOutput"]["additionalContext"]
        with open(os.path.join(os.path.dirname(HOLDBACK_PY), "claude-md.md")) as f:
            self.assertEqual(ctx, f.read().strip())

    def test_the_verdict_is_worked_out_before_the_first_call(self):
        path = transcript([human("Fix the build.")])
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HOLDBACK", "TETHER", "CLAUDE_CODE"))}
        env.update({"HOLDBACK_STATE": STATE, "PATH": FAKE + os.pathsep + env.get("PATH", ""),
                    "CLAUDE_CODE_ENTRYPOINT": "claude-desktop"})
        subprocess.run([sys.executable, HOLDBACK_PY], input=json.dumps({
            "hook_event_name": "UserPromptSubmit", "session_id": "p2", "transcript_path": path,
            "prompt": "Fix the build."}), capture_output=True, text=True, env=env, timeout=30)
        deadline = time.time() + 20
        while time.time() < deadline and not holdback.load("p2").get("verdicts"):
            time.sleep(0.2)
        verdicts = holdback.load("p2").get("verdicts")
        self.assertTrue(verdicts)
        self.assertTrue(next(iter(verdicts.values()))["work"])
        self.assertIsNone(run(pre(path, "Edit", {"file_path": "/Users/x/p/a.js"}, session_id="p2")))
        self.assertEqual(calls(), 1)                          # the call used the verdict already kept


if __name__ == "__main__":
    unittest.main()
