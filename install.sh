#!/bin/sh
# Put Holdback's hooks in this machine's ~/.claude/settings.json, pointing at a holdback.py:
# this checkout's unless one is named. Any older Holdback hook is replaced; Tether's hooks and
# every other hook stay as they are.
#   install.sh [--claude-md] [path/to/holdback.py]
# --claude-md also writes the rule into ~/.claude/CLAUDE.md, for a session that doesn't run
# these hooks (a cloud session); where they run, the UserPromptSubmit hook supplies it.
# HOLDBACK_ALLOW_PATHS, when set, is kept in Holdback's settings.json so its hooks see it: more
# places, comma separated, where writing changes nothing of the person's (a reply drop, say).
set -e
CLAUDE_MD=
[ "$1" = "--claude-md" ] && { CLAUDE_MD=1; shift; }
HOLDBACK=${1:-$(cd "$(dirname "$0")" && pwd)/holdback.py}
[ -f "$HOLDBACK" ] || { echo "no holdback.py at $HOLDBACK" >&2; exit 1; }
python3 - "$HOLDBACK" "$CLAUDE_MD" <<'PY'
import json, os, sys
from pathlib import Path
path, claude_md = sys.argv[1], sys.argv[2]
home = str(Path.home())
cmd = 'python3 "' + (path.replace(home, "$HOME", 1) if path.startswith(home + "/") else path) + '"'
settings = Path.home() / ".claude" / "settings.json"
settings.parent.mkdir(parents=True, exist_ok=True)
try:
    s = json.loads(settings.read_text())
except (OSError, ValueError):
    s = {}
hooks = s.setdefault("hooks", {})
def mine(group):
    return any("holdback.py" in h.get("command", "") for h in group.get("hooks", []))
for event in ("PreToolUse", "UserPromptSubmit"):
    hooks[event] = [g for g in hooks.get(event, []) if not mine(g)]
hook = {"type": "command", "command": cmd, "timeout": 120}
hooks["PreToolUse"].append({"matcher": "*", "hooks": [hook]})    # every call that could change something
hooks["UserPromptSubmit"].append({"hooks": [dict(hook, timeout=30)]})
tmp = settings.with_suffix(".json.holdback")
tmp.write_text(json.dumps(s, indent=2) + "\n")
os.replace(tmp, settings)
print(f"holdback: hooks in {settings} run {cmd}")

allow = os.environ.get("HOLDBACK_ALLOW_PATHS")
if allow is not None:
    state = Path(os.environ.get("HOLDBACK_STATE", Path.home() / ".local" / "state" / "holdback"))
    state.mkdir(parents=True, exist_ok=True)
    conf = state / "settings.json"
    try:
        old = json.loads(conf.read_text())
    except (OSError, ValueError):
        old = {}
    old["allow_paths"] = [p.strip() for p in allow.split(",") if p.strip()]
    conf.write_text(json.dumps(old, indent=2) + "\n")
    print(f"holdback: allow_paths={old['allow_paths']} in {conf}")

if claude_md:
    snippet = (Path(path).parent / "claude-md.md").read_text()
    md = Path.home() / ".claude" / "CLAUDE.md"
    text = md.read_text() if md.exists() else ""
    title = snippet.splitlines()[0]
    start = text.find(title)
    if start != -1:
        end = text.find("\n# ", start + len(title))
        text = text[:start] + (text[end + 1:] if end != -1 else "")
    md.write_text((text.rstrip() + "\n\n" if text.strip() else "") + snippet)
    print(f"holdback: the rule is in {md}")
PY
