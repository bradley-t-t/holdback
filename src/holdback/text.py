"""Trimming text down to what a judge or a log line should hold."""

from __future__ import annotations


def clip(text: str, cap: int, keep: str = "head") -> str:
    """text, no longer than cap characters: its start, or its end when keep is "tail"."""
    text = (text or "").strip()
    if len(text) <= cap:
        return text
    return (text[:cap] + " [...]") if keep == "head" else ("[...] " + text[-cap:])
