"""Holdback: an AI assistant does work only when the person told it to.

A question isn't telling the assistant to work, and neither is a critique of its answer, a
request for an explanation, an opinion, options or a plan, or a remark. In a turn whose
message from the person isn't an instruction to do work, Holdback refuses every tool call
that would change something: an edit, a write outside the scratchpad, a command that changes
files or state, a commit, push or deploy, a message sent, a session, agent message, schedule
or handoff started. Reading, searching, looking and running checks go through, so a question
still gets a real answer. The session is told why and answers without the work; when the
person wants it done, they say so.

Whether the person's message tells the assistant to work is decided once per message by a
second model (`claude -p`, Opus by default), which sees the message and the end of the
assistant's reply before it, so "yes, do it" after an offer counts, and nothing else. A
command Holdback can't read gets one appeal: a second judge is shown the command on its own
and asked whether running it would change anything.

The package:

    system      what differs on Windows: paths, processes, locks, the console
    config      settings, and where config and state live
    state       the log, and the verdict kept for each message
    judge       the two judges and the word scan that stands in for them
    transcript  reading a session's transcript, and whose words decide a turn
    verdict     the verdict for the turn a call is made in
    paths       where writing changes nothing of the person's
    changes     what a tool call would change
    shell       what a shell command would change
    hooks       the Claude Code hooks
    claude      Holdback's hooks in ~/.claude/settings.json
    package     how this copy was installed
    update      keeping it current
    cli         the `holdback` command
"""

__version__ = "1.0.0"

# How every refusal begins; Tether looks for it, so it doesn't hand off what Holdback held.
MARK = "Holdback: held"
