"""Tiny Czech/English detector: JARVIS answers in English when spoken or written to in English (spec §8)."""
from __future__ import annotations

import re

_CS_CHARS = set("áčďéěíňóřšťúůýž")
# Only words that are NOT also common Czech words (no "a", "to", "do", "me", "on", "i", "pro"…): Czech typed without
# diacritics ("pust to na youtube", "dej to do me slozky") must stay Czech.
_EN = {
    "the", "an", "and", "or", "is", "are", "was", "be", "of", "in", "for", "with", "it", "this", "that",
    "what", "how", "why", "when", "where", "who", "can", "could", "would", "please", "my", "you", "your",
    "open", "play", "show", "tell", "time", "some", "music", "does", "it's", "what's", "from", "weather",
    "all", "thanks", "thank", "hello", "hi", "hey", "today", "like", "calculator", "turn", "set", "find",
}


def detect(text: str) -> str:
    t = (text or "").lower()
    if any(c in _CS_CHARS for c in t):
        return "cs"
    words = re.findall(r"[a-z']+", t)
    if len(words) < 3:
        return "cs"
    hits = sum(w in _EN for w in words)
    return "en" if hits >= 2 and hits / len(words) >= 0.3 else "cs"
