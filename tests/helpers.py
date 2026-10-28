"""Shared by the tests: Holdback's state in a temporary folder, transcripts written as
Claude Code writes them, and a judge that never leaves the machine."""

import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

STATE = tempfile.mkdtemp(prefix="holdback-test-")
os.environ["HOLDBACK_STATE"] = STATE
os.environ["HOLDBACK_CONFIG"] = os.path.join(STATE, "config.json")
os.environ["HOLDBACK_UPDATE"] = "0"          # the tests never reach GitHub
for var in ("HOLDBACK_ALLOW_PATHS", "HOLDBACK_APPEAL", "HOLDBACK_MODEL"):
    os.environ.pop(var, None)

from holdback.models import Verdict  # noqa: E402

HOLDBACK_PY = str(ROOT / "holdback.py")

posix_only = unittest.skipIf(os.name == "nt", "POSIX only")
windows_only = unittest.skipUnless(os.name == "nt", "Windows only")


def transcript(entries, folder=None) -> str:
    fd, path = tempfile.mkstemp(suffix=".jsonl", dir=folder)
    with os.fdopen(fd, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


def human(text, **extra):
    return {"type": "user", "uuid": str(uuid.uuid4()), "origin": {"kind": "human"},
            "message": {"role": "user", "content": text}, **extra}


def queued(text):
    return {"type": "attachment", "attachment": {"type": "queued_command", "prompt": text}}


def event(text, kind="task-notification"):
    return {"type": "user", "isMeta": True, "origin": {"kind": kind},
            "message": {"role": "user", "content": text}}


def peer(body, name="A session"):
    return {"type": "user", "isMeta": True, "origin": {"kind": "peer", "from": "local_x"},
            "message": {"role": "user", "content": "Another Claude session sent a message:\n<cross-session-message "
                        'from="local_x" name="%s">\n%s\n</cross-session-message>' % (name, body)}}


def said(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def called(tool, inp, tid=None):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid or "toolu_" + uuid.uuid4().hex[:12], "name": tool, "input": inp}]}}


def result(tid, text, error=False):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": error}]}}


class FakeJudge:
    """Stands in for holdback.judge.judge: work when the message says so, and counts its
    calls."""

    def __init__(self, work_words=("fix", "make", "add", "create", "change it", "do it", "yes")):
        self.calls, self.work_words = [], work_words

    def __call__(self, message, before=""):
        self.calls.append((message, before))
        work = any(w in message.lower() for w in self.work_words) and "?" not in message
        return Verdict(work=work, kind="instruction" if work else "question",
                       reason="an instruction" if work else "a question about the code",
                       by="judge", ms=1)


def reset_state():
    for name in os.listdir(STATE):
        try:
            os.unlink(os.path.join(STATE, name))
        except OSError:
            pass
