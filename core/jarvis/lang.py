"""Tiny Czech/English detector: JARVIS answers in English when spoken or written to in English (spec §8)."""
from __future__ import annotations

import re

_CS_CHARS = set("áčďéěíňóřšťúůýž")
_EN = {
    "the", "a", "an", "and", "or", "is", "are", "was", "be", "to", "of", "in", "on", "for", "with", "it", "this", "that",
    "what", "how", "why", "when", "where", "who", "can", "could", "would", "please", "me", "my", "you", "your", "i",
    "open", "play", "show", "tell", "time", "some", "music", "do", "does", "it's", "what's", "is", "at", "for", "from",
    "all", "thanks", "thank", "hello", "hi", "hey",
}


def detect(text: str) -> str:
    t = (text or "").lower()
    if any(c in _CS_CHARS for c in t):
        return "cs"
    words = re.findall(r"[a-z']+", t)
    if len(words) < 3:
        return "cs"
    return "en" if sum(w in _EN for w in words) / len(words) >= 0.25 else "cs"
