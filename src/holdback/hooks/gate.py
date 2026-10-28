"""PreToolUse: refuse a call that would change something in a turn whose message from the
person isn't an instruction to do work.

A call that only reads never reaches the judge. A call that would change something, in a
turn the person didn't ask for work in, is refused - unless Holdback couldn't read the
command, in which case it gets one appeal.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .. import config, judge, state, turn
from ..changes import changes
from ..models import Verdict
from ..shell.programs import CLOUD, SUBCOMMANDS
from ..unknown import Unknown
from . import main_transcript

# Programs an appeal never clears, wherever they turn up in the command: the ones that
# change files, settings, software, services or another machine, and the ones that send. A
# command Holdback couldn't read that names one of these stays held, and no judge is asked.
NEVER_APPEAL = set("""
sudo doas su rm rmdir shred srm trash mv dd mkfs fdisk diskutil chmod chown chgrp chflags ln install patch
tee truncate touch mkdir cp ditto rsync scp sftp rclone
git gh glab hub npm pnpm yarn bun npx bunx pnpx pip pip3 uv poetry pipx brew port apt apt-get aptitude yum dnf
pacman apk gem cargo go deno make cmake gradle mvn ant bundle composer nix
docker docker-compose podman kubectl helm terraform pulumi ansible vagrant systemctl service launchctl crontab
defaults scutil csrutil spctl nvram networksetup dscl pmset mdutil tmutil security xattr plutil sysctl reg
ssh curl wget nc ncat netcat telnet ftp
kill killall pkill shutdown reboot halt osascript mail sendmail msmtp claude
""".split()) | CLOUD | set(SUBCOMMANDS)   # a program Holdback keeps a read list for is one it knows
APPEAL_WORDS = re.compile(r"[^\s|&;()<>'\"`$=]+")

HELD = ("{mark}. This call would {what}, and the person's message doesn't tell you to do any work (Holdback "
        "read it as: {said}). Nothing was changed, and nothing that changes anything runs this turn. Answer "
        "what they said, reading whatever you need. Don't do the work another way (another tool, a shell "
        "command, a subagent, another session, a schedule), and never hand this off. Don't offer to do it, "
        "don't ask whether to, and don't say a change was held or left undone: answer, and the person will say "
        "when they want it done.")


def appealable(name: str, what, command: str) -> bool:
    """Whether a hold can go to the appeal judge: a shell command Holdback didn't recognize,
    naming nothing that changes things. A change Holdback did read is never appealed, so an
    appeal can only ever widen what counts as reading."""
    if not isinstance(what, Unknown) or name != "Bash" or not config.settings().appeal:
        return False
    return not any(os.path.basename(w.strip("'\"")) in NEVER_APPEAL
                   for w in APPEAL_WORDS.findall(command or ""))


def held_text(what: str, verdict: Verdict) -> str:
    from .. import MARK
    return HELD.format(mark=MARK, what=what, said=verdict.said())


def gate(data: dict) -> None:
    name, inp = data.get("tool_name") or "", data.get("tool_input") or {}
    what = changes(name, inp, data.get("cwd") or "")
    if not what:
        return
    path = main_transcript(data)
    if not path:
        return
    session = data.get("session_id") or Path(path).stem
    verdict = turn.decided(path, session, data.get("agent_id") or "")
    if verdict is None or verdict.work:
        return
    command = inp.get("command") if isinstance(inp.get("command"), str) else ""
    if appealable(name, what, command) and cleared(session, name, what, command):
        return                       # it only reads, so a question turn may run it after all
    state.log(session=session[:8], kind="held", tool=name, what=what[:160], said=verdict.kind,
              reason=verdict.reason[:160],
              **({"agent": data["agent_id"]} if data.get("agent_id") else {}))
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": held_text(what, verdict)}}))


def cleared(session: str, name: str, what, command: str) -> bool:
    """Whether the appeal judge says this command only reads. One verdict per distinct
    command, kept, so a command run twice is judged once."""
    a = state.kept("appeals", state.digest("command\0" + command),
                   lambda: judge.appeal(command),
                   lambda: Verdict(work=False, kind="unsure", reason="the appeal took too long", by="appeal"))
    state.log(session=session[:8], kind="appeal", tool=name, what=str(what)[:160], allowed=a.work,
              reason=a.reason[:160], by=a.by, ms=a.ms, **({"error": a.error} if a.error else {}))
    return a.work
