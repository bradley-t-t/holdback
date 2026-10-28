"""Reading a shell command the way the shell does, before anything decides what it means:
heredocs, quoting, operators, words and command substitutions.

Nothing here knows what a program does. It turns one command line into the pieces the rest
of Holdback judges.
"""

from __future__ import annotations

import re
import shlex

OPS = ["&>>", ";;&", "<<<", "&&", "||", ";;", ";&", "|&", ">>", ">|", "&>", ">&", "<&", "<>", "<(", ">(", "<<",
       "|", "&", ";", "<", ">", "(", ")", "\n"]
SEPARATORS = {"&&", "||", ";", ";;", ";&", ";;&", "|", "|&", "&", "(", ")", "<(", ">(", "\n"}
OUT_REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<>"}
REDIRECTS = OUT_REDIRECTS | {"<", "<<<", "<&", ">&", "<<"}
PUNCT = set(";&|<>()\n")
HEREDOC = re.compile(r"(?<!<)<<(-?)[ \t]*(?:'([^'\n]+)'|\"([^\"\n]+)\"|\\?([A-Za-z_][\w.-]*))")
HEREDOC_MARK = re.compile("\x01(\\d+)\x01")
PLACE = re.compile("\x00(\\d+)\x00")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=")
KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "{", "}", "!", "time", "coproc",
            "function", "in", "esac"}
HEADERS = {"for", "select", "case"}


def cut_heredocs(text: str, bodies: list) -> str:
    """The command with each heredoc's body taken out and its << replaced by < and a marker;
    the bodies are added to bodies."""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        waiting = []

        def mark(m):
            waiting.append((m.group(2) or m.group(3) or m.group(4), m.group(1) == "-"))
            bodies.append("")
            return "< \x01%d\x01" % (len(bodies) - 1)

        out.append(HEREDOC.sub(mark, lines[i]))
        i += 1
        first = len(bodies) - len(waiting)
        for k, (delim, tabs) in enumerate(waiting):
            body = []
            while i < len(lines):
                line = lines[i]
                i += 1
                if (line.lstrip("\t") if tabs else line).strip() == delim:
                    break
                body.append(line)
            bodies[first + k] = "\n".join(body)
    return "\n".join(out)


def closing(text: str, at: int) -> int:
    """Where the parenthesis opened at `at` closes, over the quotes inside it; -1 when it
    never does."""
    depth, i, n = 0, at, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c in "'\"":
            j = text.find(c, i + 1)
            if j == -1:
                return -1
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def mask(text: str):
    """The command with quoted text, escaped characters and command substitutions in
    backticks replaced by markers, so a quoted ";" or ">" isn't read as an operator; and what
    each marker stands for. (None, None) when a quote isn't closed."""
    out, table, i, n = [], [], 0, len(text)

    def keep(s):
        table.append(s)
        return "\x00%d\x00" % (len(table) - 1)

    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            out.append(keep(text[i + 1]) if text[i + 1] in PUNCT or text[i + 1] in " \t'\"\\$`#" else text[i + 1])
            i += 2
        elif c == "'":
            j = text.find("'", i + 1)
            if j == -1:
                return None, None
            out.append(keep(text[i + 1:j]))
            i = j + 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n and text[j + 1] in '"\\$`\n':
                    buf.append(text[j + 1])
                    j += 2
                elif text.startswith("$(", j):
                    end = closing(text, j + 1)   # $( ) quotes afresh: "$(cd "$(dirname "$0")")"
                    if end == -1:
                        return None, None
                    buf.append(text[j:end + 1])
                    j = end + 1
                else:
                    buf.append(text[j])
                    j += 1
            if j >= n:
                return None, None
            out.append(keep("".join(buf)))
            i = j + 1
        elif c == "`":
            j = text.find("`", i + 1)
            if j == -1:
                return None, None
            out.append(keep(text[i:j + 1]))
            i = j + 1
        elif text.startswith("$((", i):
            j = text.find("))", i + 3)
            if j == -1:
                return None, None
            out.append("0")          # arithmetic
            i = j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out), table


def tokenize(text: str) -> list:
    lex = shlex.shlex(text, posix=True, punctuation_chars=";&|<>()\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    out = []
    for tok in lex:
        if tok and set(tok) <= PUNCT:
            while tok:
                op = next(o for o in OPS + [tok[0]] if tok.startswith(o))
                out.append(op)
                tok = tok[len(op):]
        else:
            out.append(tok)
    return out


def substitutions(word: str) -> list:
    """The commands inside $(...) and `...` in a word."""
    out, i = [], 0
    while True:
        i = word.find("$(", i)
        if i == -1:
            break
        depth, j = 0, i + 1
        while j < len(word):
            if word[j] == "(":
                depth += 1
            elif word[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(word[i + 2:j])
        i = j
    return out + re.findall(r"`([^`]*)`", word)


def positional(args: list, with_value=()) -> list:
    """The arguments that aren't options or option values."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return out + args[i + 1:]
        if a in with_value:
            i += 2
            continue
        if a.startswith("-") and len(a) > 1:
            i += 1
            continue
        out.append(a)
        i += 1
    return out
