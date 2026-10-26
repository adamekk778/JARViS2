"""Masks API keys, tokens and passwords before text reaches logs, task history or exports (spec §9.2)."""
from __future__ import annotations

import logging
import re

MASK = "•••"
_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_\w{20,}"),
    re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+"),
]
_KEYVAL = re.compile(r"(?i)(api[_-]?key|key|token|secret|password|heslo|pass)(\"?\s*[=:]\s*\"?)[^\s\"]{6,}")   # also "key": "…" in JSON
_BARE = re.compile(r"(?i)\b(token|secret|api[_ -]?key|klíč|klic)(\s+)([A-Za-z0-9_\-]{16,})")
_WORD = re.compile(r"(?i)\b(heslo|password|pin|passwd|api[_ -]?key|token)\b")
_literals: set[str] = set()


def add_literal(s: str) -> None:
    """A concrete secret (e.g. the phone pairing token) that must never show up anywhere."""
    if s and len(s) >= 6:
        _literals.add(s)


def redact(text: str) -> str:
    if not text:
        return text
    for lit in _literals:
        text = text.replace(lit, MASK)
    for p in _PATTERNS:
        text = p.sub(MASK, text)
    text = _KEYVAL.sub(lambda m: m.group(1) + m.group(2) + MASK, text)
    return _BARE.sub(lambda m: m.group(1) + m.group(2) + MASK, text)


def looks_secret(text: str) -> bool:
    return redact(text) != text or bool(_WORD.search(text or ""))


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True
