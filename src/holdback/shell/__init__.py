"""What a shell command would change.

One tokenizer (parse.py) turns the command line into words, operators and heredoc bodies.
This module walks them: a redirect writes its target, a substitution is a command of its
own, and each simple command goes to programs.py, which knows what one program does.

A command Holdback doesn't recognize changes something - an unknown program could do
anything - but it says so as an Unknown, which the appeal may still clear.
"""

from __future__ import annotations

from ..paths import SHELL_VARS, expand, scratch, variables
from ..unknown import Unknown
from .parse import (ASSIGN, HEREDOC_MARK, KEYWORDS, OUT_REDIRECTS, PLACE, REDIRECTS, SEPARATORS,
                    cut_heredocs, mask, substitutions, tokenize)
from .programs import command_change

MAX_DEPTH = 4


def bash_change(cmd: str, cwd: str = "", depth: int = 0, stdin=None, bodies=None):
    """What a shell command would change, or None when every command in it only reads. A
    command Holdback doesn't know changes something; writing to the scratchpad doesn't."""
    if depth > MAX_DEPTH:
        return "run deeply nested commands"
    if depth == 0:
        SHELL_VARS.clear()
    bodies = [] if bodies is None else bodies
    text = cut_heredocs((cmd or "").replace("\\\n", " "), bodies)
    masked, table = mask(text)
    if masked is None:
        return Unknown("run a command with an unclosed quote")
    try:
        toks = tokenize(masked)
    except ValueError:
        return Unknown("run a command Holdback can't read")

    def word(t):
        return PLACE.sub(lambda m: table[int(m.group(1))], t)

    here, seg = cwd, []
    for t in toks + ["\n"]:
        if t not in SEPARATORS:
            seg.append(t)
            continue
        words, body, i = [], stdin, 0
        while i < len(seg):
            t, nxt = seg[i], seg[i + 1] if i + 1 < len(seg) else ""
            if t.isdigit() and nxt in REDIRECTS:
                i += 1               # the 2 in 2>/dev/null
            elif t in OUT_REDIRECTS or (t == ">&" and not (nxt.isdigit() or nxt == "-")):
                target = word(nxt)
                if not scratch(target, here):
                    return "write %s" % (target or "a file")
                i += 2
            elif t in REDIRECTS:
                m = HEREDOC_MARK.fullmatch(nxt)
                if m and int(m.group(1)) < len(bodies):
                    body = bodies[int(m.group(1))]
                i += 2
            else:
                words.append(word(t))
                i += 1
        for w in words:
            for inner in substitutions(w):
                what = bash_change(inner, here, depth + 1, bodies=bodies)
                if what:
                    return what
        what = command_change(words, here, body, depth)
        if what:
            return what
        remember(words)
        bare = [w for w in words if w not in KEYWORDS]
        if bare and bare[0] in ("cd", "pushd"):
            target = next((w for w in bare[1:] if not w.startswith("-")), "~")
            here = expand(target, here) or ""
        seg = []
    return None


def remember(words: list) -> None:
    """Keep the variables a command sets (D=/tmp/x, export OUT=...), so a later $D/draft.md
    can be told."""
    words = [w for w in words if w not in KEYWORDS]
    if words and words[0] in ("export", "declare", "local", "typeset", "readonly"):
        words = [w for w in words[1:] if not w.startswith("-")]
    for w in words:
        if not ASSIGN.match(w):
            break
        name, value = w.split("=", 1)
        SHELL_VARS[name.rstrip("+").split("[")[0]] = variables(value)
