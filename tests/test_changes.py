"""What a tool call would change: the calls a question turn must still be able to make (reading,
searching, Tether's draft check, the scratchpad) and the ones Holdback holds. Nothing here
reaches the judge.

Run:  python3 -m unittest discover -s tests -v
"""
import os, unittest
from unittest import mock

from helpers import holdback

SP = "/private/tmp/claude-501/-Users-someone/0000/scratchpad"
TETHER = "/Users/someone/Development/tether/tether.py"
HOME = os.path.expanduser("~")
CWD = "/Users/someone/Development/project"

READS = [
    "ls -la 2>/dev/null && cat a | grep b; echo \"x > y\"",
    "cd /Users/someone/Development/tether && git log --oneline | head -20 && git remote -v",
    f'python3 "{TETHER}" check "{SP}/draft.md"',
    f'python3 "{TETHER}" hold 17:05',
    f'python3 "{TETHER}" wait 1234',
    f"cat > {SP}/draft.md <<'EOF'\nHello; it's > fine | rm -rf /\nEOF",
    "f=$(ls ~/.claude/projects/*/$ID.jsonl); python3 - \"$f\" <<'EOF'\nimport json,sys\n"
    "for l in open(sys.argv[1]):\n    print(json.loads(l))\nEOF",
    "grep -n \"def \\|^class \" tether.py | head -200; wc -l tether.py",
    "gh repo view bradley-t-t/tether --json visibility,defaultBranchRef; gh api user -q .login",
    "gh pr view 3 --json title -q .title", "gh pr checks 3", "gh run list --limit 5",
    "ssh -o ConnectTimeout=8 -o BatchMode=yes pi 'hostname; cd ~/src/tether && git log --oneline -1; "
    "cat ~/.claude/settings.json; which claude'",
    r"find . -name '*.py' -exec grep -l foo {} \;",
    "for f in *.py; do wc -l $f; done", "x=$(git rev-parse HEAD); echo $x", "echo $((1+2))",
    "sed -n '1,5p' file.txt", "awk -F, '$3 > 100 {print $1}' data.csv",
    "python3 -m pytest -q tests", "python3 -m unittest discover -s tests -v", "npm test", "npm run lint",
    "npx tsc --noEmit", "git diff --stat HEAD~1", "git branch -a", "git branch --contains abc123", "git tag -l 'v*'",
    "git config --get user.name", "git config user.name", "git fetch -q origin && git status -sb",
    "curl -s https://example.com | jq .", "curl -sSL -o /dev/null -w '%{http_code}' https://x.com",
    "docker ps -a", "kubectl -n prod get pods", "systemctl --user status voice-assistant", "brew list",
    f"mkdir -p {SP}/x && touch /tmp/a", f"rm -rf {SP}/old", f"cd {SP} && echo hi > draft.md",
    "sqlite3 db.sqlite 'select * from t limit 5'", "[[ -f x && -d y ]] && echo ok",
    "timeout 10 git status", "env FOO=1 git log -1", "ps aux | grep claude | head",
    "python3 -c 'import json,sys; print(json.load(sys.stdin)[\"a\"])'", "node -e 'console.log(1)'",
    "bash -n script.sh", "echo hi >&2", "cat <<< 'hello'", "diff <(ls a) <(ls b)", "ls | xargs grep foo",
    "pmset -g batt", "defaults read com.apple.finder", "vercel ls", "aws s3 ls", "echo x | tee /tmp/out.txt",
    "python3 -I - /tmp/x <<'EOF'\nimport sys\nprint(open(sys.argv[1]).read())\nEOF",
    f"D={SP}; cat > $D/draft.md <<'EOF'\nRight.\nEOF\npython3 \"{TETHER}\" check $D/draft.md",
    "export OUT=/tmp/o; mkdir -p \"$OUT\" && echo hi > ${OUT}/a.txt",
]
WORKS = [
    "rm -rf build", "echo hi > notes.txt", "git commit -m 'x'", "git push", "git checkout -b x", "git branch newbranch",
    "git tag v1.0", "git config user.name Bob", "git stash", "git reset --hard origin/main", "git merge feature",
    "npm install", "npm run build", "npm version patch", "pip install x", "python3 -m http.server",
    "sed -i '' 's/a/b/' f.txt", "perl -pi -e 's/a/b/' f", "python3 -c 'open(\"x\",\"w\").write(\"y\")'",
    "python3 -c 'import subprocess; subprocess.run([\"ls\"])'", "node -e 'require(\"fs\").writeFileSync(\"x\",\"y\")'",
    "curl -X POST https://api.x.com", "curl -d 'a=b' https://x.com", "curl -o out.html https://x.com",
    "wget https://x.com/f.zip", "gh pr create --fill", "gh pr merge 3", "gh release create v1",
    "gh api -X DELETE repos/a/b", "gh api repos/a/b/issues -f title=x", "docker run ubuntu", "kubectl apply -f x.yaml",
    "systemctl restart voice-assistant", "brew install jq", "mv a.txt b.txt", "cp a.txt b.txt", "mkdir newdir",
    "touch x", "chmod +x run.sh", "ln -s a b", "tee out.txt", "echo x | tee -a log.txt", "sort -o sorted.txt in.txt",
    "find . -name '*.pyc' -delete", r"find . -name x -exec rm {} \;", "xargs rm < files.txt",
    "ls | xargs -I{} mv {} {}.bak", "sqlite3 db 'delete from t'", "make", "make build", "cargo build",
    "go build ./...", "tsc", "eslint --fix .", "prettier --write .", "black .", "ruff check --fix",
    "osascript -e 'tell app \"Finder\" to quit'", "kill 123", "pkill node", "vercel --prod", "vercel",
    "supabase db push", "ssh pi 'sudo systemctl restart x'", "ssh pi 'rm -rf ~/x'", "ssh pi 'cat > ~/notes.txt'",
    "bash -c 'rm -rf x'", "echo \"$(rm -rf foo)\"", "echo `touch x`", "x=$(rm y)",
    f"python3 {TETHER} handoff 'do it'", "claude -p 'fix it' --permission-mode bypassPermissions", "sudo rm x",
    "crontab x", "defaults write com.x a b", "git -C /tmp/x commit -m y", "tar xzf a.tgz", "unzip a.zip",
    "gzip file", "dd if=a of=/dev/disk2", "cat a > b", "echo x >> ~/.zshrc", "2>&1 git push",
    "git commit -m \"$(cat <<'EOF'\nmsg\nEOF\n)\"", "aws s3 cp a s3://b/c", "echo hi; rm x",
    "scp a.txt pi:~/x.txt", "rsync -a src/ pi:~/dst/", "echo 'unclosed", "some-unknown-tool --flag",
    "D=/Users/someone/Development/project; echo x > $D/notes.txt", "echo x > $UNSET_THING/notes.txt",
    "D=$(pwd); rm -rf $D/build",
]


class Shell(unittest.TestCase):
    def test_reads(self):
        for c in READS:
            with self.subTest(command=c):
                self.assertIsNone(holdback.bash_change(c, CWD))

    def test_work(self):
        for c in WORKS:
            with self.subTest(command=c):
                self.assertTrue(holdback.bash_change(c, CWD))

    def test_says_what_it_would_change(self):
        self.assertEqual(holdback.bash_change("echo hi > notes.txt", CWD), "write notes.txt")
        self.assertEqual(holdback.bash_change("git push", CWD), "run git push")
        self.assertEqual(holdback.bash_change("rm -rf build", CWD), "delete build")

    def test_a_reply_drop_is_allowed_only_when_configured(self):
        cmd = "ssh pi \"cat > ~/voice-assistant/data/replies/abc.txt\" <<'EOF'\nIt is.\nEOF"
        self.assertTrue(holdback.bash_change(cmd, CWD))
        with mock.patch.dict(os.environ, {"HOLDBACK_ALLOW_PATHS": "~/voice-assistant/data/replies"}):
            self.assertIsNone(holdback.bash_change(cmd, CWD))

    def test_a_script_is_read_before_it_is_judged(self):
        folder = os.path.join("/tmp", "holdback-script-test")
        os.makedirs(folder, exist_ok=True)
        quiet, loud = os.path.join(folder, "report.py"), os.path.join(folder, "deploy.sh")
        with open(quiet, "w") as f:
            f.write("import json, sys\nprint(json.load(open(sys.argv[1])))\n")
        with open(loud, "w") as f:
            f.write("#!/bin/sh\ngit push origin main\n")
        self.assertIsNone(holdback.bash_change(f"python3 {quiet} data.json", CWD))
        self.assertIn("git push", holdback.bash_change(f"sh {loud}", CWD))


class Tools(unittest.TestCase):
    def check(self, name, inp=None, want=None):
        got = holdback.changes(name, inp or {}, CWD)
        if want is None:
            self.assertIsNone(got, name)
        else:
            self.assertTrue(got, name)

    def test_reading_and_answering_tools(self):
        for name in ("Read", "Glob", "Grep", "WebFetch", "WebSearch", "ToolSearch", "TodoWrite", "Agent", "Skill",
                     "AskUserQuestion", "SendUserFile", "mcp__ccd_turn__update_plan", "mcp__ccd_turn__wrap_up",
                     "mcp__ccd_view__show_pane", "mcp__ccd_session_mgmt__list_sessions",
                     "mcp__Claude_Browser__navigate", "mcp__Claude_Browser__get_page_text",
                     "mcp__claude-in-chrome__read_page", "mcp__0917__list_tables", "mcp__0917__search_docs",
                     "mcp__fcb3__outlook_email_search", "mcp__fcb3__teams_list_channels", "mcp__5882__get_screenshot",
                     "mcp__5882__create_session", "mcp__f786__handoff_wait", "mcp__terminal__read_terminal",
                     "mcp__computer-use__app_screenshot", "mcp__scheduled-tasks__list_scheduled_tasks",
                     "mcp__ca47__get_runtime_logs", "mcp__ca47__aggregate_pageviews", "mcp__visualize__show_widget"):
            with self.subTest(tool=name):
                self.check(name)

    def test_tools_that_change_things(self):
        for name in ("mcp__0917__apply_migration", "mcp__0917__deploy_edge_function", "mcp__fcb3__outlook_send_mail",
                     "mcp__fcb3__outlook_create_draft", "mcp__fcb3__teams_send_chat_message", "mcp__5882__use_figma",
                     "mcp__f786__handoff", "mcp__ccd_session__hand_off_to_session", "mcp__ccd_settings__set_setting",
                     "mcp__ccd_pr__set_auto_merge", "mcp__ccd_host__sync_with_base_branch",
                     "mcp__computer-use__app_click", "mcp__computer-use__app_type", "mcp__claude-in-chrome__form_input",
                     "mcp__scheduled-tasks__create_scheduled_task", "mcp__ca47__create_deployment",
                     "mcp__Read_and_Write_Apple_Notes__add_note", "mcp__unreal__call_tool", "CronCreate",
                     "ScheduleWakeup", "RemoteTrigger", "EnterWorktree", "SendMessage",
                     "mcp__ccd_session_mgmt__send_message", "mcp__ccd_session_mgmt__archive_session"):
            with self.subTest(tool=name):
                self.check(name, want=True)

    def test_files(self):
        self.check("Write", {"file_path": f"{SP}/draft.md"})
        self.check("Write", {"file_path": f"{HOME}/.claude/projects/-Users-x/memory/feedback.md"})
        self.check("Write", {"file_path": f"{HOME}/.claude/plans/plan.md"})
        self.check("Edit", {"file_path": f"{CWD}/src/app.py"}, want=True)
        self.check("Write", {"file_path": f"{HOME}/.claude/CLAUDE.md"}, want=True)
        self.check("NotebookEdit", {"notebook_path": f"{CWD}/a.ipynb"}, want=True)

    def test_inputs_decide(self):
        self.check("Bash", {"command": "git status"})
        self.check("Bash", {"command": "git push"}, want=True)
        self.check("mcp__terminal__run_in_terminal", {"command": "npm install"}, want=True)
        self.check("mcp__0917__execute_sql", {"query": "select * from users where id = 1"})
        self.check("mcp__0917__execute_sql", {"query": "select 1; delete from users"}, want=True)
        self.check("mcp__0917__execute_sql", {"query": "update users set name = 'x'"}, want=True)
        self.check("Artifact", {"action": "read", "url": "x"})
        self.check("Artifact", {"file_path": "/tmp/x.html"}, want=True)
        self.check("ArtifactData", {"action": "query"})
        self.check("ArtifactData", {"action": "set"}, want=True)
        self.check("mcp__ccd_session__start_session", {"initiation": "own_initiative"})
        self.check("mcp__ccd_session__start_session", {"initiation": "user_asked"}, want=True)
        self.check("mcp__Claude_Browser__computer", {"action": "screenshot"})
        self.check("mcp__Claude_Browser__computer", {"action": "left_click"}, want=True)
        self.check("mcp__Claude_Browser__browser_batch", {"actions": [
            {"name": "navigate", "input": {"url": "x"}}, {"name": "computer", "input": {"action": "screenshot"}}]})
        self.check("mcp__Claude_Browser__browser_batch", {"actions": [
            {"name": "computer", "input": {"action": "type", "text": "x"}}]}, want=True)
        self.check("mcp__Claude_Code_iOS_Simulator__control", {"action": "screenshot"})
        self.check("mcp__Claude_Code_iOS_Simulator__control", {"action": "tap"}, want=True)

    def test_a_project_session_answers_with_its_reply_tools(self):
        self.check("mcp__hearthbot__reply", {"text": "x"})
        self.check("mcp__hearthbot__post_message", {"text": "x"})
        self.check("mcp__hearthbot__start_thread_session", {"brief": "x"}, want=True)
        self.check("mcp__other__reply", {"text": "x"}, want=True)


if __name__ == "__main__":
    unittest.main()
