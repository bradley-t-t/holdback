"""`holdback setup`: put the hooks in Claude Code's settings and keep what the person chose.

There is little to choose - Holdback has one job - so setup asks at most two questions, and
with --yes or no terminal it asks none.
"""

from __future__ import annotations

from pathlib import Path

from .. import config, ui
from ..claude import settings
from ..hooks.prompt import rule_text

CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"


def add_arguments(p) -> None:
    p.add_argument("--allow-paths", help="More places Claude may always write to, comma separated")
    p.add_argument("--model", help="The judge model (default opus)")
    p.add_argument("--appeal", dest="appeal", action="store_true", default=None,
                   help="Let a command Holdback can't read be appealed (the default)")
    p.add_argument("--no-appeal", dest="appeal", action="store_false",
                   help="Hold every command Holdback can't read")
    p.add_argument("--update", dest="update", action="store_true", default=None,
                   help="Keep Holdback up to date in the background (the default)")
    p.add_argument("--no-update", dest="update", action="store_false", help="Never update itself")
    p.add_argument("--claude-md", dest="claude_md", action="store_true", default=None,
                   help="Also write the rule into ~/.claude/CLAUDE.md")
    p.add_argument("--no-claude-md", dest="claude_md", action="store_false",
                   help="Leave ~/.claude/CLAUDE.md alone")
    p.add_argument("-y", "--yes", action="store_true", help="Take the defaults, ask nothing")
    p.add_argument("--settings", help="Claude Code settings file")


def run(args) -> int:
    chosen = {}
    if args.allow_paths is not None:
        chosen["allow_paths"] = [p.strip() for p in args.allow_paths.split(",") if p.strip()]
    if args.model:
        chosen["model"] = args.model
    if args.appeal is not None:
        chosen["appeal"] = args.appeal
    if args.update is not None:
        chosen["update"] = args.update
    if chosen:
        config.write(chosen)

    ui.heading("Hooks")
    path = settings.install()
    print("Holdback runs on every tool call and every message you send, from %s" % path)

    claude_md = args.claude_md
    if claude_md is None:
        claude_md = (CLAUDE_MD.exists() and rule_in(CLAUDE_MD)) or (
            not args.yes and ui.interactive()
            and ui.confirm("Also write the rule into %s, for sessions that run no hooks?" % CLAUDE_MD, False))
    if claude_md:
        ui.heading("The rule")
        print("The rule is in %s" % write_rule())

    where = config.config_path()
    ui.heading("Settings")
    print("%s%s" % (where, "" if where.exists() else " (not written: the defaults are in use)"))
    s = config.settings()
    print("  judge model   %s" % s.model)
    print("  appeal        %s" % ("on" if s.appeal else "off"))
    print("  updates       %s" % ("on" if s.update else "off"))
    print("  allow paths   %s" % (", ".join(s.allow_paths) or "none beyond the scratchpad"))
    print()
    print(ui.green("Done.") + " Start a new Claude Code session to use it.")
    return 0


def title() -> str:
    """The rule's heading, which is how its section in CLAUDE.md is found again."""
    return rule_text().splitlines()[0] if rule_text() else ""


def rule_in(path: Path) -> bool:
    try:
        return title() in path.read_text(encoding="utf-8")
    except OSError:
        return False


def write_rule(path: Path | None = None) -> Path:
    """Put the rule in CLAUDE.md, replacing an older copy of it and leaving the rest."""
    path = path or CLAUDE_MD
    rule, head = rule_text(), title()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    start = text.find(head) if head else -1
    if start != -1:
        end = text.find("\n# ", start + len(head))
        text = text[:start] + (text[end + 1:] if end != -1 else "")
    path.write_text((text.rstrip() + "\n\n" if text.strip() else "") + rule + "\n", encoding="utf-8")
    return path
