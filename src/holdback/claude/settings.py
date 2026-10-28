"""Holdback's hooks in Claude Code's ~/.claude/settings.json: add, remove, inspect.

Each hook runs `python3 -m holdback.hooks` with this package on PYTHONPATH, so it works
from any folder. On Windows the hook starts Python directly (exec form: "command" plus
"args"), with no shell, because Claude Code would otherwise run it through Git Bash or
PowerShell depending on what is installed.

Other hooks in the file - Tether's, your own - are kept exactly as they are, and the file
is backed up before each change.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from .. import system

# What marks our own entries in the hooks lists, so install replaces them instead of
# running both, and uninstall removes them. The older form, which ran holdback.py from a
# checkout, counts too.
MARKERS = ("-m holdback.hooks", "holdback.py")

EVENTS = ("PreToolUse", "UserPromptSubmit")
MATCHERS = {"PreToolUse": "*"}          # every call that could change something
TIMEOUTS = {"PreToolUse": 120, "UserPromptSubmit": 30}

KEEP_BACKUPS = 3
BACKUP_NAME = re.compile(r"\.bak-\d{8}-\d{6}$")


def package_root() -> Path:
    """The folder that holds the holdback package, put on the hooks' PYTHONPATH."""
    return Path(__file__).resolve().parent.parent.parent


def settings_path() -> Path:
    p = os.environ.get("CLAUDE_SETTINGS")
    if p:
        return Path(os.path.expanduser(p))
    return Path.home() / ".claude" / "settings.json"


def hook_command() -> str:
    """The shell command Claude Code runs. Paths are absolute so it works from any folder.
    It always exits 0, so a hook that runs while an update is reinstalling Holdback is
    skipped instead of flagged as an error."""
    return 'PYTHONPATH="%s" "%s" -m holdback.hooks || true' % (
        package_root(), sys.executable or system.python_command())


def hook_args() -> list:
    """The arguments of the Windows hook, whose command is this Python."""
    return ["-m", "holdback.hooks"]


def hook_entry(event: str) -> dict:
    if system.windows():
        hook = {"type": "command", "command": sys.executable, "args": hook_args()}
    else:
        hook = {"type": "command", "command": hook_command()}
    hook["timeout"] = TIMEOUTS[event]
    entry = {"hooks": [hook]}
    if event in MATCHERS:
        entry["matcher"] = MATCHERS[event]
    return entry


def command_text(h: dict) -> str:
    """A hook's command as one line: the shell command, or an exec-form program and its
    arguments with the program quoted."""
    args = h.get("args")
    if isinstance(args, list):
        return " ".join(['"%s"' % h.get("command", "")] + [str(a) for a in args])
    return str(h.get("command") or "")


def has_marker(cmd) -> bool:
    return any(m in (cmd or "") for m in MARKERS)


def is_ours(entry) -> bool:
    """True for a hooks-list entry that runs Holdback."""
    if not isinstance(entry, dict):
        return False
    for h in entry.get("hooks") or []:
        if isinstance(h, dict) and has_marker(command_text(h)):
            return True
    return has_marker(command_text(entry))


def our_commands(data: dict, event: str) -> list:
    """The commands of our hooks for this event in loaded settings."""
    out = []
    for e in ((data.get("hooks") or {}).get(event) or []):
        if not isinstance(e, dict):
            continue
        for h in (e.get("hooks") or [e]):
            if isinstance(h, dict) and has_marker(command_text(h)):
                out.append(command_text(h))
    return out


def read(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or settings_path()).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def backups(path: Path | None = None) -> list:
    """The settings backups Holdback made, oldest first."""
    path = path or settings_path()
    if not path.parent.is_dir():
        return []
    return sorted(q for q in path.parent.glob(path.name + ".bak-*")
                  if BACKUP_NAME.search(q.name) and q.is_file())


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak-%s" % time.strftime("%Y%m%d-%H%M%S")))
        for old in backups(path)[:-KEEP_BACKUPS]:
            old.unlink()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def install(path: Path | None = None) -> Path:
    """Add our hooks, replacing any earlier Holdback ones and leaving every other hook as it
    is. The file is left alone when they're already there as they'd be written."""
    path = path or settings_path()
    data = read(path)
    before = json.dumps(data, sort_keys=True)
    hooks = data.setdefault("hooks", {})
    for event in EVENTS:
        hooks[event] = [e for e in (hooks.get(event) or []) if not is_ours(e)] + [hook_entry(event)]
    if not path.exists() or json.dumps(data, sort_keys=True) != before:
        _write(path, data)
    return path


def uninstall(path: Path | None = None) -> Path:
    """Remove our hooks and leave everything else, dropping lists that end up empty."""
    path = path or settings_path()
    data = read(path)
    hooks = data.get("hooks") or {}
    changed = False
    for event in list(hooks):
        before = hooks[event] or []
        after = [e for e in before if not is_ours(e)]
        changed = changed or after != before
        if after:
            hooks[event] = after
        else:
            hooks.pop(event, None)
    if changed:
        if hooks:
            data["hooks"] = hooks
        else:
            data.pop("hooks", None)
        _write(path, data)
    return path


def status(path: Path | None = None) -> dict:
    path = path or settings_path()
    hooks = read(path).get("hooks") or {}
    out = {"settings": str(path)}
    for event in EVENTS:
        out[event] = any(is_ours(e) for e in hooks.get(event) or [])
    return out
