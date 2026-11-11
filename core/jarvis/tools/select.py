"""Which tools go to the AI with a message.

JARVIS has ~650 tools. Sending every description with every message is ~85 000 tokens – free tiers (Groq: ~8 000
tokens a minute, ~200 000 a day) ran out after one or two messages, and every answer was slow and costly. Now a
message carries a small everyday set, the tools its words point to, the ones used in the last turn, and `find_tools`:
when nothing offered fits, the AI asks for more by describing what it needs and gets them in the next step. Nothing
JARVIS can do is lost; it just is not all sent every time.
"""
from __future__ import annotations

import re
import unicodedata

# what people ask for every day – always offered (only those that exist and are allowed are sent)
CORE = (
    "open_app", "close_app", "open_url", "web_search", "web_read", "get_time", "weather", "set_timer", "set_reminder",
    "media_control", "volume", "youtube_play", "remember", "search_memory", "clipboard_get", "type_text", "press_keys",
    "window_control", "screenshot", "system_info", "send_to_phone",
)
MAX_EXTRA = 10          # tools picked by the message's words
MAX_FOUND = 8           # tools one find_tools call adds
FIND = "find_tools"

_STOP = {"a", "i", "o", "u", "v", "z", "s", "k", "na", "se", "si", "je", "to", "ten", "ta", "do", "od", "po", "pro",
         "jak", "co", "kde", "kdy", "mi", "me", "mne", "muj", "moje", "tu", "ty", "the", "and", "for", "with", "prosim",
         "jarvis", "jarvisi", "muzes", "udelej", "dej", "chci", "bych", "by", "aby", "nebo", "ale", "tak", "jen", "uz"}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def stems(text: str) -> set[str]:
    """Rough Czech/English word stems: no accents, first 5 letters (so "fotku", "fotky", "fotka" meet)."""
    out = set()
    for w in re.findall(r"[a-z0-9]+", _norm(text).replace("_", " ")):
        if len(w) < 3 or w in _STOP:
            continue
        out.add(w[:5])
    return out


_INDEX: dict[str, tuple[set[str], set[str]]] = {}    # tool name → (stems of its name + category, stems of its description)


def _index(registry: dict) -> dict:
    if len(_INDEX) != len(registry) or any(n not in _INDEX for n in list(registry)[:5]):
        _INDEX.clear()
        for name, spec in registry.items():
            _INDEX[name] = (stems(name + " " + spec.category), stems(spec.description))
    return _INDEX


def _hits(q: set[str], words: set[str]) -> int:
    """How many of the query's stems the tool has – also when one is the start of the other ("web" ~ "websi")."""
    n = 0
    for w in q:
        if w in words or any(len(x) >= 3 and (x.startswith(w) or w.startswith(x)) for x in words):
            n += 1
    return n


def search(registry: dict, query: str, limit: int = MAX_FOUND, exclude: set[str] = frozenset()) -> list[str]:
    """Tool names that fit a few words, best first (a word in the tool's name or category counts more)."""
    q = stems(query)
    if not q:
        return []
    scored = []
    for name, (head, desc) in _index(registry).items():
        if name in exclude or name == FIND:
            continue
        s = 3 * _hits(q, head) + _hits(q, desc)
        if s:
            scored.append((s, name))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [n for _, n in scored[:limit]]


def pick(registry: dict, allowed: set[str], text: str, recent: list[str] = ()) -> list[str]:
    """The tool names to send with this message: the everyday set, what the words point to, the last turn's tools."""
    names = [n for n in CORE if n in allowed]
    for n in recent:
        if n in allowed and n not in names:
            names.append(n)
    for n in search(registry, text, MAX_EXTRA * 3, exclude=set(names)):
        if n in allowed and n not in names:
            names.append(n)
            if len(names) >= len(CORE) + len(recent) + MAX_EXTRA:
                break
    if FIND in allowed:
        names.append(FIND)
    return names
