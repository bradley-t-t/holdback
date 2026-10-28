"""What a call would change when Holdback didn't recognize the command."""

from __future__ import annotations


class Unknown(str):
    """What a call would change when Holdback didn't recognize the command, rather than read
    a change in it: an unknown program, a subcommand or module it keeps no list for, a script
    it couldn't read, or code its patterns only guessed at. It is the plain words it says, so
    everything that handles a change handles one of these unchanged; the appeal judge is
    shown these and only these, so a change Holdback did read is never appealed."""
    __slots__ = ()


def like(inner, text: str):
    """text, still unrecognized when the change it wraps was."""
    return Unknown(text) if isinstance(inner, Unknown) else text
