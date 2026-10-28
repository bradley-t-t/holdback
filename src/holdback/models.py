"""The shapes Holdback passes around.

A verdict is the one thing Holdback decides and the one thing it keeps, so it is a type
rather than a bag of keys: every judge returns one, the state file holds one per message,
and the refusal is written from one.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Verdict:
    """What was decided, who decided it, and why.

    work     whether the work may go ahead: the person asked for it, or, for an appeal,
             the command only reads
    kind     what the message was ("question", "instruction"), or for an appeal whether
             the command "reads" or "changes"
    reason   a few words the assistant will read, such as "a question about the build"
    by       who decided: "judge", "appeal", "scan", "command" or "plan"
    ms       how long it took
    error    why the judge couldn't be asked, when something stood in for it
    """

    work: bool
    kind: str = ""
    reason: str = ""
    by: str = ""
    ms: int = 0
    error: str = ""
    extra: dict = field(default_factory=dict, repr=False)

    def as_dict(self) -> dict:
        """The verdict as it is written to the state file and the log."""
        out = {"work": self.work, "kind": self.kind, "reason": self.reason, "by": self.by, "ms": self.ms}
        if self.error:
            out["error"] = self.error
        out.update(self.extra)
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Verdict":
        known = ("work", "kind", "reason", "by", "ms", "error")
        return cls(work=bool(d.get("work")), kind=str(d.get("kind") or ""),
                   reason=str(d.get("reason") or ""), by=str(d.get("by") or ""),
                   ms=int(d.get("ms") or 0), error=str(d.get("error") or ""),
                   extra={k: v for k, v in d.items() if k not in known})

    def said(self) -> str:
        """What the message was, for the refusal: the reason, or the kind on its own."""
        return (self.reason or ("a %s" % (self.kind or "message"))).rstrip(".")
