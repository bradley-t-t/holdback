"""Whether a piece of SQL only reads, for a database tool and for `sqlite3`, `psql` and
`mysql` on the command line."""

from __future__ import annotations

import re

SQL_WRITES = re.compile(
    r"\b(?:insert|update|delete|merge|upsert|drop|alter|create|truncate|grant|revoke|copy|vacuum|reindex|cluster|"
    r"refresh|call|do|lock|set|reset|import|attach|detach|discard|prepare|execute|notify|listen|comment\s+on)\b", re.I)
SQL_READS = re.compile(r"^\s*(?:select|with|explain|show|describe|desc|values|table|pragma)\b", re.I)
SQLITE_DOTS = {".tables", ".schema", ".indexes", ".indices", ".headers", ".mode", ".width", ".dbinfo", ".fullschema",
               ".show", ".databases", ".timer", ".nullvalue", ".separator", ".echo", ".eqp", ".print", ".quit",
               ".exit", ".help", ".stats", ".header"}


def reads(sql: str) -> bool:
    """Whether every statement in sql only reads."""
    s = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)
    s = re.sub(r"'(?:[^']|'')*'|\"[^\"]*\"", "''", s)
    statements = [x for x in s.split(";") if x.strip()]
    dots = [x for x in statements if x.strip().startswith(".")]
    if any(x.strip().split()[0] not in SQLITE_DOTS for x in dots):
        return False
    return bool(statements) and all(SQL_READS.match(x) for x in statements if x not in dots) \
        and not SQL_WRITES.search(" ".join(x for x in statements if x not in dots))
