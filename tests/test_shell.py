"""What a shell command would change: the commands a question turn must still be able to
run, the ones Holdback holds, and the ones it couldn't read. Nothing here reaches a judge.

Run:  python3 -m unittest discover -s tests -v
"""
import os
import unittest
from unittest import mock

import helpers  # noqa: F401  (puts src on the path and points the state at a temp folder)
from holdback.shell import bash_change
from holdback.shell import code as shell_code
from holdback.unknown import Unknown

SP = "/private/tmp/claude-501/-Users-someone/0000/scratchpad"
TETHER = "/Users/someone/Development/tether/tether.py"
CWD = "/Users/someone/Development/project"

READS = [
    "ls -la 2>/dev/null && cat a | grep b; echo \"x > y\"",
    "cd /Users/someone/Development/tether && git log --oneline | head -20 && git remote -v",
    'python3 "%s" check "%s/draft.md"' % (TETHER, SP),
    'python3 "%s" hold 17:05' % TETHER,
    'python3 "%s" wait 1234' % TETHER,
    "cat > %s/draft.md <<'EOF'\nHello; it's > fine | rm -rf /\nEOF" % SP,
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
    "mkdir -p %s/x && touch /tmp/a" % SP, "rm -rf %s/old" % SP, "cd %s && echo hi > draft.md" % SP,
    "sqlite3 db.sqlite 'select * from t limit 5'", "[[ -f x && -d y ]] && echo ok",
    "timeout 10 git status", "env FOO=1 git log -1", "ps aux | grep claude | head",
    "python3 -c 'import json,sys; print(json.load(sys.stdin)[\"a\"])'", "node -e 'console.log(1)'",
    "python3 -c 'import subprocess; print(subprocess.run([\"ls\", \"-la\"], capture_output=True).stdout)'",
    "python3 -c 'import subprocess; subprocess.check_output(\"git log --oneline -5\", shell=True)'",
    "python3 -c 'import subprocess,sys; subprocess.run([\"sw_vers\"], stdout=subprocess.PIPE, text=True)'",
    "ollama list", "ollama ps", "systeminfo",
    "bash -n script.sh", "echo hi >&2", "cat <<< 'hello'", "diff <(ls a) <(ls b)", "ls | xargs grep foo",
    "pmset -g batt", "defaults read com.apple.finder", "vercel ls", "aws s3 ls", "echo x | tee /tmp/out.txt",
    "python3 -I - /tmp/x <<'EOF'\nimport sys\nprint(open(sys.argv[1]).read())\nEOF",
    "D=%s; cat > $D/draft.md <<'EOF'\nRight.\nEOF\npython3 \"%s\" check $D/draft.md" % (SP, TETHER),
    "export OUT=/tmp/o; mkdir -p \"$OUT\" && echo hi > ${OUT}/a.txt",
    'ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cat "$ROOT/README.md"',
    'echo "$(basename "$(pwd)")"',
]
WORKS = [
    "rm -rf build", "echo hi > notes.txt", "git commit -m 'x'", "git push", "git checkout -b x", "git branch newbranch",
    "git tag v1.0", "git config user.name Bob", "git stash", "git reset --hard origin/main", "git merge feature",
    "npm install", "npm run build", "npm version patch", "pip install x", "python3 -m http.server",
    "sed -i '' 's/a/b/' f.txt", "perl -pi -e 's/a/b/' f", "python3 -c 'open(\"x\",\"w\").write(\"y\")'",
    "python3 -c 'import subprocess; subprocess.run([\"git\", \"push\"])'",
    "python3 -c 'import subprocess; subprocess.run(cmd)'",
    "python3 -c 'import subprocess; subprocess.run([\"rm\", \"-rf\", path])'",
    "python3 -c 'import subprocess; subprocess.run([\"ls\"]); open(\"x\",\"w\").write(\"y\")'",
    "ollama pull llama3", "ollama rm llama3", "node -e 'require(\"fs\").writeFileSync(\"x\",\"y\")'",
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
    "python3 %s handoff 'do it'" % TETHER, "claude -p 'fix it' --permission-mode bypassPermissions", "sudo rm x",
    "crontab x", "defaults write com.x a b", "git -C /tmp/x commit -m y", "tar xzf a.tgz", "unzip a.zip",
    "gzip file", "dd if=a of=/dev/disk2", "cat a > b", "echo x >> ~/.zshrc", "2>&1 git push",
    "git commit -m \"$(cat <<'EOF'\nmsg\nEOF\n)\"", "aws s3 cp a s3://b/c", "echo hi; rm x",
    "scp a.txt pi:~/x.txt", "rsync -a src/ pi:~/dst/", "echo 'unclosed", "some-unknown-tool --flag",
    "D=/Users/someone/Development/project; echo x > $D/notes.txt", "echo x > $UNSET_THING/notes.txt",
    "D=$(pwd); rm -rf $D/build", 'ROOT="$(cd "$(dirname "$0")/.." && pwd)"; rm -rf "$ROOT/build"',
]


@helpers.posix_only
class Shell(unittest.TestCase):
    def test_reads(self):
        for c in READS:
            with self.subTest(command=c):
                self.assertIsNone(bash_change(c, CWD))

    def test_work(self):
        for c in WORKS:
            with self.subTest(command=c):
                self.assertTrue(bash_change(c, CWD))

    def test_says_what_it_would_change(self):
        self.assertEqual(bash_change("echo hi > notes.txt", CWD), "write notes.txt")
        self.assertEqual(bash_change("git push", CWD), "run git push")
        self.assertEqual(bash_change("rm -rf build", CWD), "delete build")

    def test_a_reply_drop_is_allowed_only_when_configured(self):
        cmd = "ssh pi \"cat > ~/voice-assistant/data/replies/abc.txt\" <<'EOF'\nIt is.\nEOF"
        self.assertTrue(bash_change(cmd, CWD))
        with mock.patch.dict(os.environ, {"HOLDBACK_ALLOW_PATHS": "~/voice-assistant/data/replies"}):
            self.assertIsNone(bash_change(cmd, CWD))

    def test_what_holdback_could_not_read_is_marked_for_the_appeal(self):
        for c in ("some-unknown-tool --flag", "mystery.py --list", "echo 'unclosed", "powershell -Command x",
                  "python3 -m mystery_module", "ollama something-new", "python3 -c 'import ctypes'"):
            with self.subTest(command=c):
                self.assertIsInstance(bash_change(c, CWD), Unknown)

    def test_a_change_holdback_read_is_never_marked_unknown(self):
        for c in ("git push", "rm -rf build", "echo hi > notes.txt", "npm install", "curl -X POST https://x.com",
                  "sed -i '' 's/a/b/' f.txt", "ssh pi 'rm -rf ~/x'"):
            with self.subTest(command=c):
                what = bash_change(c, CWD)
                self.assertTrue(what)
                self.assertNotIsInstance(what, Unknown)

    def test_code_says_which_kind_of_change_it_would_make(self):
        self.assertIn("write files", bash_change("python3 -c 'open(\"x\",\"w\").write(\"y\")'", CWD))
        self.assertIn("run commands", bash_change("python3 -c 'import subprocess; subprocess.run(cmd)'", CWD))
        self.assertIn("send a request",
                      bash_change("python3 -c 'import requests; requests.post(url)'", CWD))

    def test_a_program_with_no_extension_is_read_as_the_script_it_is(self):
        folder = os.path.join("/tmp", "holdback-path-test")
        os.makedirs(folder, exist_ok=True)
        scripts = {"look": "#!/usr/bin/env bash\nROOT=\"$(cd \"$(dirname \"$0\")/..\" && pwd)\"\ncat \"$ROOT/x\"\n",
                   "report": "#!/usr/bin/env python3\nimport sys\nprint(open(sys.argv[1]).read())\n",
                   "deploy": "#!/bin/sh\nset -e\ngit push origin main\n"}
        for name, text in scripts.items():
            with open(os.path.join(folder, name), "w") as f:
                f.write(text)
            os.chmod(os.path.join(folder, name), 0o755)
        with open(os.path.join(folder, "binary"), "wb") as f:
            f.write(b"\xcf\xfa\xed\xfe\x00\x00\x00\x00not text")
        os.chmod(os.path.join(folder, "binary"), 0o755)
        self.assertIsNone(bash_change("%s/look" % folder, CWD))
        self.assertIsNone(bash_change("%s/report data.json" % folder, CWD))
        self.assertIn("git push", bash_change("%s/deploy" % folder, CWD))
        self.assertIsInstance(bash_change("%s/binary" % folder, CWD), Unknown)
        with mock.patch.object(shell_code.shutil, "which",
                               lambda p: os.path.join(folder, p) if p in scripts else None):
            self.assertIsNone(bash_change("look", CWD))
            self.assertIn("git push", bash_change("deploy", CWD))
            self.assertIsInstance(bash_change("not-there-at-all", CWD), Unknown)

    def test_a_script_is_read_before_it_is_judged(self):
        folder = os.path.join("/tmp", "holdback-script-test")
        os.makedirs(folder, exist_ok=True)
        quiet, loud = os.path.join(folder, "report.py"), os.path.join(folder, "deploy.sh")
        with open(quiet, "w") as f:
            f.write("import json, sys\nprint(json.load(open(sys.argv[1])))\n")
        with open(loud, "w") as f:
            f.write("#!/bin/sh\ngit push origin main\n")
        self.assertIsNone(bash_change("python3 %s data.json" % quiet, CWD))
        self.assertIn("git push", bash_change("sh %s" % loud, CWD))


if __name__ == "__main__":
    unittest.main()
