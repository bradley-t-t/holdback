"""UserPromptSubmit: put the rule in front of the session, and start working out whether
this message asks for work, so the first call that changes something doesn't wait for it.

The rule itself lives in rule.md beside the package, which is also what `holdback setup
--claude-md` writes into ~/.claude/CLAUDE.md for sessions that run no hooks.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from .. import config, package, state, system
from ..transcript import REMINDER, prompt_text, read_window

RULE = Path(__file__).resolve().parent.parent / "rule.md"
WINDOW = 512 * 1024


def rule_text() -> str:
    try:
        return RULE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def prompted(data: dict) -> None:
    path = data.get("transcript_path") or ""
    if path and not os.environ.get("HOLDBACK_NO_WARM"):
        said = state.digest(REMINDER.sub("", str(data.get("prompt") or "")).strip())
        start_warm(path, data.get("session_id") or "", said)
    rule = rule_text()
    if rule:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": rule}}))


def start_warm(path: str, session: str, said: str) -> None:
    """Work the verdict out in the background, so the hook returns at once."""
    try:
        system.start_detached([sys.executable, "-m", "holdback", "warm", path, session, said],
                              cwd=tempfile.gettempdir(), env=package.child_env())
    except OSError:
        pass


def warm(path: str, session: str, said: str) -> None:
    """Work out the verdict on the message just sent (said is its digest) once it is the
    latest in the transcript, or after WARM_WAIT seconds whatever the transcript shows."""
    from .. import turn
    deadline = time.monotonic() + config.WARM_WAIT
    while time.monotonic() < deadline:
        entries, _ = read_window(path, WINDOW)
        latest = next((p for e in reversed(entries) if (p := prompt_text(e))), None)
        if latest and state.digest(latest[0]) == said:
            break
        time.sleep(0.2)
    turn.decided(path, session)
