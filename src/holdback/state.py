"""What Holdback keeps between hook runs, in ~/.local/state/holdback (%LOCALAPPDATA%\\holdback
on Windows): the log, and one file per session holding the verdict on each message, the
verdicts being worked out right now, and where each subagent was launched.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from . import system
from .config import KEEP, TIMEOUT, WAIT, log_path, state_dir
from .models import Verdict


def log(**fields) -> None:
    try:
        d = state_dir()
        d.mkdir(parents=True, exist_ok=True)
        fields = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "host": system.hostname(), **fields}
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(fields) + "\n")
    except OSError:
        pass


def digest(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()[:32]


def state_file(session: str) -> Path:
    return state_dir() / ("%s.json" % (re.sub(r"[^A-Za-z0-9_-]", "", session) or "unknown"))


def load(session: str) -> dict:
    try:
        s = json.loads(state_file(session).read_text(encoding="utf-8"))
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save(session: str, s: dict) -> None:
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = state_file(session)
    tmp = f.with_suffix(".%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(s), encoding="utf-8")
    os.replace(tmp, f)


def kept(session: str, key: str, work, fallback) -> Verdict:
    """The verdict kept for this message, else work() run now and kept. While another
    process is working it out, wait for that, up to WAIT seconds, then take fallback() so
    the hook never runs past its own time limit."""
    deadline = time.monotonic() + WAIT
    while True:
        s = load(session)
        v = (s.get("verdicts") or {}).get(key)
        if v:
            return Verdict.from_dict(v)
        p = (s.get("pending") or {}).get(key)
        if not (p and time.time() - p[0] < WAIT + TIMEOUT and system.alive(p[1]) and p[1] != os.getpid()):
            break
        if time.monotonic() >= deadline:
            v = fallback()
            v.error = "the verdict being worked out elsewhere took too long"
            return v
        time.sleep(0.25)
    s.setdefault("pending", {})[key] = [time.time(), os.getpid()]
    save(session, s)
    v = work()
    s = load(session)
    verdicts = s.setdefault("verdicts", {})
    verdicts[key] = v.as_dict()
    for k in list(verdicts)[:-KEEP]:
        del verdicts[k]
    (s.get("pending") or {}).pop(key, None)
    save(session, s)
    log(session=session[:8], kind="verdict", work=v.work, said=v.kind, reason=v.reason[:160],
        by=v.by, ms=v.ms, **({"error": v.error} if v.error else {}))
    return v


def agent_end(path: str, session: str, agent_id: str):
    """Where in the main transcript the subagent agent_id was launched (the end of the line
    that names it), so its calls go by that turn; None when it isn't there yet (a subagent
    still running inside the turn that launched it)."""
    s = load(session)
    if agent_id in (s.get("agents") or {}):
        return s["agents"][agent_id]
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    at = data.find(agent_id.encode("utf-8"))
    if at == -1:
        return None
    end = data.find(b"\n", at)
    end = len(data) if end == -1 else end + 1
    s = load(session)
    s.setdefault("agents", {})[agent_id] = end
    save(session, s)
    return end
