"""The verdict for the turn a call is made in.

One verdict per message, kept in the session's state file, so a turn asks the judge once
however many calls it makes. A slash command and a plan the person approved are
instructions and need no judge at all.
"""

from __future__ import annotations

import os

from . import judge as judges
from . import state, transcript
from .models import Verdict
from .transcript import MORE


def decided(path: str, session: str, agent_id: str = ""):
    """The verdict on the person's message that decides this turn (or the turn that
    launched agent_id), or None when no person asked for anything."""
    project = transcript.project_session(path)
    end = state.agent_end(path, session, agent_id) if agent_id else None
    found = None
    for size in transcript.WINDOWS:
        entries, whole = transcript.read_window(path, size, end)
        found = (transcript.project_case if project else transcript.case)(entries, whole)
        if found is not MORE:
            break
    if found is None or found is MORE:
        return None
    words, before, approved = found
    asked = os.environ.get("HOLDBACK_QUESTION") or os.environ.get("TETHER_QUESTION")
    if asked and not project:
        words = asked            # a caller that wraps the person's words passes them on their own
    if approved:
        return Verdict(work=True, kind="go-ahead", reason="the person's approval of the plan", by="plan")
    own = transcript.STAMP.sub("", judges.PASTED.sub(" ", words).strip() or words).lstrip()
    if own.startswith("/"):
        return Verdict(work=True, kind="command", reason="the command %s" % own.split()[0], by="command")
    return state.kept(session, state.digest(before + "\0" + words),
                      lambda: judges.judge(words, before),
                      lambda: judges.scan(words, before))
