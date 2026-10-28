"""Holdback's Claude Code hooks, run as `python3 -m holdback.hooks`.

  PreToolUse        refuse a call that would change something in a turn the person didn't
                    ask for work in
  UserPromptSubmit  put the rule in front of the session, and start working out the
                    verdict on the message just sent

Both arrive as JSON on stdin and say which event they are, so one command serves both.
Each hook imports only what it needs: the prompt hook, whose job is a line of context and a
background process, never loads the shell reader.

Nothing here raises and nothing exits non-zero: a hook that fails leaves the session as it
was.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ..transcript import project_session


def read_event() -> dict:
    """The JSON object Claude Code sends on stdin, or {}."""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def main_transcript(data: dict) -> str:
    """The session's own transcript, even when a subagent makes the call."""
    path = data.get("transcript_path") or ""
    if "/subagents/" in path:
        main = path.split("/subagents/")[0] + ".jsonl"
        if os.path.exists(main):
            return main
    if path and os.path.exists(path):
        return path
    session = data.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    found = sorted(Path.home().glob(".claude/projects/*/%s.jsonl" % session)) if session else []
    return str(found[0]) if found else ""


def watched(data: dict) -> bool:
    """Whether a person's words drive this session: an interactive one, one driven from a
    phone or the web, a Claude Projects session, or a headless run whose caller says so
    (HOLDBACK=1, TETHER=1). Routines and scripts are left alone."""
    if os.environ.get("HOLDBACK") == "1" or os.environ.get("TETHER") == "1":
        return True
    if os.environ.get("CLAUDE_CODE_BRIDGE_SESSION_ID") or os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        return True
    if not os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return True
    return project_session(main_transcript(data))


def installed_too() -> bool:
    """Whether this run is the plugin's hook on a machine where Holdback's hooks are also
    in the user settings, so every call would be gated twice."""
    if not os.environ.get("CLAUDE_PLUGIN_ROOT") or os.environ.get("HOLDBACK_PLUGIN") == "1":
        return False
    try:
        text = (Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8")
    except OSError:
        return False
    return "holdback.py" in text or "holdback.hooks" in text


def off() -> bool:
    """Whether this process must do nothing: turned off, or a judge of Holdback's or
    Tether's own, which would otherwise set itself off."""
    return (os.environ.get("HOLDBACK") == "0" or bool(os.environ.get("HOLDBACK_JUDGE"))
            or bool(os.environ.get("TETHER_JUDGE")) or installed_too())


def main(argv: list | None = None) -> int:
    """Run the hook the event on stdin names."""
    if off():
        return 0
    # Claude Code speaks UTF-8 JSON; Windows would otherwise use its ANSI code page.
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    data = read_event()
    if not data or not watched(data):
        return 0
    event = data.get("hook_event_name")
    if event == "PreToolUse":
        from .gate import gate
        gate(data)
    elif event == "UserPromptSubmit":
        from .prompt import prompted
        prompted(data)
    else:
        return 0
    from .. import update
    update.start_if_due()            # never waits, never prints
    return 0
