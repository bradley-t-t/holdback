"""`holdback doctor`: check Python, the judge, the hooks, the settings and the update, and
say what to fix."""

from __future__ import annotations

import os
import re
import shlex
import sys
import time
from pathlib import Path

from .. import __version__, config, package, system, ui, update
from ..claude import settings
from ..hooks.prompt import RULE
from .setup import CLAUDE_MD, rule_in

OK, WARN, FAIL = "ok", "warn", "fail"


def checks() -> list:
    """[(level, title, detail)] for everything doctor looks at."""
    out = []

    def add(level: str, title: str, detail: str = "") -> None:
        out.append((level, title, detail))

    _python(add)
    _judge(add)
    _hooks(add)
    _rule(add)
    _settings(add)
    _state(add)
    _updates(add)
    return out


def _python(add) -> None:
    v = sys.version_info
    add(OK if v >= (3, 9) else FAIL, "Python %d.%d.%d" % v[:3],
        "" if v >= (3, 9) else "Holdback needs Python 3.9 or newer")


def _judge(add) -> None:
    found = system.claude_bin()
    if found == "claude" and not Path(found).exists():
        add(FAIL, "Judge", "The Claude Code CLI isn't on PATH, so every message falls back to the "
                           "word scan")
        return
    add(OK, "Judge", "%s, model %s" % (found, config.settings().model))


def _hooks(add) -> None:
    path = settings.settings_path()
    data = settings.read(path)
    for event in settings.EVENTS:
        title = "Hook %s" % event
        ours = settings.our_commands(data, event)
        if not ours:
            add(FAIL, title, "Not installed in %s. Run `holdback setup`." % path)
            continue
        if len(ours) > 1:
            add(WARN, title, "%d Holdback entries; `holdback setup` keeps one" % len(ours))
        problems = _command_problems(ours[0])
        add(WARN if problems else OK, title, "; ".join(problems) or "installed")


def _command_problems(cmd: str) -> list:
    """The Python and package folder a hook command points at must still exist. A Windows
    hook names only its Python."""
    m = re.search(r'PYTHONPATH="([^"]+)"\s+"([^"]+)"', cmd) or re.match(r'"([^"]+)" -m ', cmd)
    if not m:
        return []
    root, py = (Path(m.group(1)), m.group(2)) if m.lastindex == 2 else (None, m.group(1))
    problems = []
    if not Path(py).exists():
        problems.append("Python %s is gone; run `holdback setup` again" % py)
    if root and not (root / "holdback").is_dir():
        problems.append("package folder %s is gone; run `holdback setup` again" % shlex.quote(str(root)))
    return problems


def _rule(add) -> None:
    if not RULE.exists():
        add(FAIL, "Rule", "%s is missing, so no rule goes in front of a session" % RULE)
        return
    where = "in front of every session"
    if rule_in(CLAUDE_MD):
        where += ", and in %s" % CLAUDE_MD
    add(OK, "Rule", where)


def _settings(add) -> None:
    s = config.settings()
    path = config.config_path()
    add(OK, "Settings", str(path) if path.exists() else "%s (not written; the defaults are in use)" % path)
    add(OK if s.appeal else WARN, "Appeal",
        "on: a command Holdback can't read gets one appeal" if s.appeal
        else "off: every command Holdback can't read stays held")
    if s.allow_paths:
        add(OK, "Allowed paths", ", ".join(s.allow_paths))


def _state(add) -> None:
    d = config.state_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".writable"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        add(FAIL, "State", "%s can't be written: %s" % (d, e))
        return
    add(OK, "State", str(d))


def _updates(add) -> None:
    title = "Version %s" % __version__
    how = package.installer()
    if not config.settings().update:
        add(WARN, title, "Updates are off. `holdback update` still updates it by hand.")
        return
    if not package.upgrade_command():
        add(WARN, title, "This copy wasn't installed with pipx, uv or git, so it can't update "
                         "itself. Reinstall with: " + package.install_command())
        return
    last = update.last()
    if not last.get("checked_at"):
        add(OK, title, "Installed with %s; hooks check for a new version at most once a minute" % how)
        return
    checked = float(last["checked_at"])
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(checked))
    outcome = last.get("outcome") or "checking"
    detail = "%s; last check %s: %s" % (how, when, outcome)
    if outcome.startswith("failed"):
        detail += "; next try after %s" % time.strftime("%H:%M", time.localtime(checked + update.wait(last)))
    add(WARN if outcome.startswith("failed") else OK, title, detail)


def run(args) -> int:
    if getattr(args, "settings", None):
        os.environ["CLAUDE_SETTINGS"] = args.settings
    results = checks()
    mark = {OK: ui.green("ok  "), WARN: ui.yellow("warn"), FAIL: ui.red("fail")}
    for level, title, detail in results:
        print("%s  %s%s" % (mark[level], ui.bold(title), ("  " + detail) if detail else ""))
    fails = sum(1 for r in results if r[0] == FAIL)
    warns = sum(1 for r in results if r[0] == WARN)
    print()
    if fails:
        print(ui.red("%d problem%s to fix." % (fails, "" if fails == 1 else "s")))
        return 1
    print(ui.green("All good.") + (" %d warning%s." % (warns, "" if warns == 1 else "s") if warns else ""))
    return 0
