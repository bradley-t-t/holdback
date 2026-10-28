"""Reading a session's transcript, and working out whose words decide the turn now running.

A person's message decides its own turn, together with anything they send while it runs. A
status check ("Status?") goes by the request it checks on, and so does a turn an automated
message started (CI, a background task, another session, a scheduled check-in): the person's
last request decides it. A subagent's calls go by the turn that launched it. A Claude
Projects session goes by the person's words in its envelopes, and words relayed by voice
(Sunday) count as the person's.
"""

from __future__ import annotations

import html
import json
import re

from .config import BEFORE_CAP
from .text import clip

# How an automated message begins: the desktop app's CI monitor, a background task or
# subagent finishing, news from a linked session, another session's message.
EVENTS = ("<ci-monitor-event", "<task-notification", "<side-sessions-event", "<cross-session-message",
          "<agent-message", "Another Claude session sent a message")
PEERS = ("<cross-session-message", "<agent-message", "Another Claude session sent a message")
ENVELOPES = ("<wake", "<relay", "<project_claude_message")   # a Claude Projects session's messages
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>\s*", re.S)
COMMAND = re.compile(r"<command-name>\s*/?([^<\s]+)\s*</command-name>(?:\s*<command-args>(.*?)</command-args>)?", re.S)
# Sunday relays what the person said by voice to a live session as another session's
# message, with one of these after their words.
VOICE = re.compile(r"\n\s*\((?:Asked by voice through|If this touches work you are running)")
PEER_BODY = re.compile(r"<cross-session-message\b[^>]*>\s*(.*?)\s*(?:</cross-session-message>|\Z)", re.S)
STATUS_PING = re.compile(
    r"^\W*(status|update|progress|eta|done|finished|ready|any (news|updates?|progress)|where are (we|things)( at)?|"
    r"how('?s| is) it (going|coming)( along)?|how far along|still (going|working))\b[\w\s']{0,20}\W*$|^\s*\?+\s*$", re.I)
STAMP = re.compile(r"^\[[A-Za-z]+ \d{1,2}:\d{2}\s?[AP]M\]\s*")
ANSWERED = re.compile(r"User has answered your questions?:\s*(.*?)(?:\.\s*You can now continue|\Z)", re.S)
PLAN_APPROVED = re.compile(r"\bUser has approved your plan\b|\bapproved (?:your|the) plan\b", re.I)
# A short follow-up that only corrects the person's own request just before it ("Downloads I
# mean", "I meant staging", "in src instead"): it carries that request, so both are read
# together.
CORRECTION = re.compile(r"\bI\s+mean(?:t)?\b|\binstead\b|\brather\b|^\W*(?:no|sorry|oops)\W+(?:in|to|on|at|into)\b",
                        re.I)
CORRECTION_WORDS = 8

# How far back to read, in bytes, until the turn's first message is in the window.
WINDOWS = (512 * 1024, 4 << 20, 32 << 20, None)
MORE = object()      # the window read so far doesn't reach far enough back


def correction(words: str) -> bool:
    """Whether a message is only a short correction of the person's previous request."""
    own = STAMP.sub("", words).strip()
    return (bool(own) and "?" not in own and len(own.split()) <= CORRECTION_WORDS
            and bool(CORRECTION.search(own)))


def prompt_text(e: dict):
    """(words, who) for a message that starts or joins a turn: who is "human" for a person
    (their typed message, a slash command, words relayed from Sunday), "peer" for another
    session's message, "event" for an automated one. None for tool results, reminders, hook
    feedback, a skill's text, Claude Projects envelopes and everything else."""
    if e.get("isSidechain") or e.get("isCompactSummary"):
        return None
    kind = (e.get("origin") or {}).get("kind")
    if e.get("type") == "attachment":
        a = e.get("attachment") or {}
        if a.get("type") != "queued_command" or not isinstance(a.get("prompt"), str):
            return None
        c, kind = a["prompt"], (a.get("origin") or {}).get("kind", "human")
    elif e.get("type") == "user":
        if e.get("isMeta") and kind in (None, "human"):
            return None
        c = (e.get("message") or {}).get("content")
        if isinstance(c, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                return None
            c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    else:
        return None
    if not isinstance(c, str):
        return None
    c = REMINDER.sub("", c).strip()
    if not c:
        return None
    if c.startswith(("<command-message>", "<command-name>")):
        m = COMMAND.search(c)
        return (("/" + m.group(1) + " " + (m.group(2) or "")).strip(), "human") if m else None
    if c.startswith(ENVELOPES + ("[Request interrupted", "Stop hook feedback", "Tether:", "Holdback:")):
        return None
    if kind == "peer" or c.startswith(PEERS):
        body = (PEER_BODY.search(c) or re.match(r"(.*)", c, re.S)).group(1)
        v = VOICE.search(body)
        return (body[:v.start()].strip(), "human") if v and body[:v.start()].strip() else (c, "peer")
    if kind not in (None, "human") or c.startswith(EVENTS):
        return c, "event"
    if c.startswith("<") and not c.startswith("<pasted_content"):
        return None                 # a local command's output and the like
    return c, "human"


def reply_text(entries: list) -> str:
    parts = []
    for e in entries:
        if e.get("type") == "assistant" and not e.get("isSidechain"):
            for b in (e.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
                    parts.append(b["text"].strip())
    return "\n\n".join(parts)


def read_window(path: str, size=None, end=None):
    """(entries, whole): the transcript's entries in the `size` bytes before `end` (the end
    of the file when None), and whether that reaches its start."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            total = f.tell()
            end = total if end is None else min(end, total)
            start = 0 if size is None else max(end - size, 0)
            f.seek(start)
            data = f.read(end - start)
    except OSError:
        return [], True
    lines = data.decode("utf8", "replace").splitlines()
    if start > 0:
        lines = lines[1:]            # the first line is cut
    out = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out, start == 0


def tool_results(entries: list):
    """(tool name, result text, is_error) for each tool call in entries that has come back."""
    names = {}
    for e in entries:
        content = (e.get("message") or {}).get("content") or [] if isinstance(e.get("message"), dict) else []
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                names[b.get("id")] = b.get("name", "")
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in names:
                c = b.get("content")
                text = c if isinstance(c, str) else "\n".join(
                    x.get("text", "") for x in c or [] if isinstance(x, dict))
                yield names[b["tool_use_id"]], text, bool(b.get("is_error"))


def case(entries: list, whole: bool):
    """(words, before, approved) for the person's message that decides the turn now running,
    None when no person asked for anything, MORE when the window doesn't reach back far
    enough. approved is True when the person approved a plan in that turn."""
    starts = [i for i, e in enumerate(entries) if e.get("type") == "user" and prompt_text(e)]
    if not starts:
        return None if whole else MORE
    start = starts[-1]
    words, who = prompt_text(entries[start])
    queued = [t for e in entries[start + 1:]
              if e.get("type") == "attachment" and (t := prompt_text(e)) and t[1] == "human"]
    if (who == "human" and not STATUS_PING.match(STAMP.sub("", words))) or (who != "human" and queued):
        at = start
    else:                            # a status check or an automated turn: the person's open request
        at = next((i for i in reversed(starts[:-1]) if (p := prompt_text(entries[i]))[1] == "human"
                   and not STATUS_PING.match(STAMP.sub("", p[0]))), None)
        if at is None:
            return None if whole else MORE
    after = next((s for s in starts if s > at), len(entries))
    w, who = prompt_text(entries[at])
    said = ([w] if who == "human" else []) + [
        t[0] for e in entries[at + 1:after]
        if e.get("type") == "attachment" and (t := prompt_text(e)) and t[1] == "human"]
    approved = False
    for name, text, error in tool_results(entries[at + 1:after]):
        if name == "AskUserQuestion" and not error and (m := ANSWERED.search(text)):
            said.append("(Answering the assistant's question) " + m.group(1).strip())
        elif name == "ExitPlanMode" and not error and PLAN_APPROVED.search(text):
            approved = True
    prev = max((s for s in starts if s < at), default=None)
    if prev is None and not whole and at == starts[0]:
        return MORE                  # what the assistant said before it is further back
    if who == "human" and len(said) == 1 and correction(w):
        asked_before = next((i for i in reversed(starts) if i < at
                             and (p := prompt_text(entries[i]))[1] == "human"
                             and not STATUS_PING.match(STAMP.sub("", p[0]))), None)
        if asked_before is not None:     # the request it corrects, then the correction
            said = [prompt_text(entries[asked_before])[0], "(Correcting that request) " + w]
    before = reply_text(entries[(prev + 1) if prev is not None else 0:at])
    return "\n\n".join(said), clip(before, BEFORE_CAP, "tail"), approved


# ---------------------------------------------------------------- Claude Projects

WAKE_MESSAGE = re.compile(r"<message\b([^>]*)>(.*?)</message>", re.S)
CITED = re.compile(r"<cited\b([^>]*)>(.*?)</cited>", re.S)
ATTR = re.compile(r'([\w-]+)="([^"]*)"')


def project_words(e: dict):
    """The person's words in a project message: the triggering human message of a <wake>, or
    the newest of the person's messages a coordinator relay cites."""
    if e.get("isSidechain") or e.get("isCompactSummary"):
        return None
    if e.get("type") == "attachment":
        a = e.get("attachment") or {}
        c = a.get("prompt") if a.get("type") == "queued_command" else None
    elif e.get("type") == "user":
        c = (e.get("message") or {}).get("content")
        if isinstance(c, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                return None
            c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    else:
        return None
    if not isinstance(c, str):
        return None
    if "<wake" in c:
        for attrs, body in WAKE_MESSAGE.findall(c):
            a = dict(ATTR.findall(attrs))
            if a.get("trigger") == "true" and a.get("from") == "human":
                return html.unescape(body).strip() or None
        return None
    if "<relay" in c:
        cited = [(a.get("at", ""), body) for attrs, body in CITED.findall(c)
                 if (a := dict(ATTR.findall(attrs))).get("author") == "user"]
        if cited:
            return html.unescape(max(cited)[1]).strip() or None
    return None


def project_session(path: str) -> bool:
    """Whether a transcript is a Claude Projects session: its first message is a project
    envelope."""
    try:
        with open(path, "rb") as f:
            head = f.read(64 * 1024).decode("utf8", "replace").splitlines()
    except OSError:
        return False
    for line in head:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        c = (e.get("message") or {}).get("content") if e.get("type") == "user" else None
        if isinstance(c, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                continue
            c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
        if isinstance(c, str) and c.strip() and not c.lstrip().startswith(("<system-reminder", "<local-command")):
            return c.lstrip().startswith(ENVELOPES)
    return False


def project_case(entries: list, whole: bool):
    """(words, before, False) for the person's last words in a project session; a status
    check goes by the request before it. None when the person's words aren't in it: a thread
    a coordinator started, which Holdback held to the person's words when it started it."""
    asks = [(i, w) for i, e in enumerate(entries) if (w := project_words(e))]
    real = [(i, w) for i, w in asks if not STATUS_PING.match(STAMP.sub("", w))]
    if not real:
        return None if whole else MORE
    i, w = real[-1]
    earlier = [j for j, _ in asks if j < i]
    posts = []
    for e in entries[(earlier[-1] if earlier else 0):i]:
        for b in (e.get("message") or {}).get("content") or [] if e.get("type") == "assistant" else []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and "hearthbot" in b.get("name", "") \
                    and b.get("name", "").endswith(("__reply", "__post_message")):
                inp = b.get("input") or {}
                posts.append(str(inp.get("text") or inp.get("message") or ""))
    return w, clip("\n\n".join(posts), BEFORE_CAP, "tail"), False
