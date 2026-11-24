"""How hard is this request? (návrh 4) – picks the model tier and how deeply it thinks.

fast    small talk, thanks, a yes/no – the provider's quick model (Groq / Gemini / Claude Haiku), no tools needed
normal  the everyday request – the main model, brief thinking
strong  planning, analysis, code, comparisons, long texts, agent mode, missions – the main model thinking deeper

Words only, no AI call (deciding must cost nothing); the evals check the examples in tests/test_brain314.py.
"""
from __future__ import annotations

import re
import unicodedata

SMALL_TALK = re.compile(
    r"^(ahoj|cau|cus|zdravim|dobry (den|vecer|rano)|dobrou( noc)?|diky|dekuju|dekuji|super|ok|okej|jo|ano|ne|nene|jasne|"
    r"v poradku|skvele|paradni|dobre|fajn|chapu|rozumim|jak se mas|co delas|kdo jsi|jak se jmenujes|hej|hello|hi|thanks)"
    r"( jarvis\w*)?( diky| moc| moc diky| za to)?$")
STRONG = re.compile(
    r"\b(naplanuj|planovani|plan na|analyz\w*|porovnej|srovnej|vyhodnot|navrhni|navrh\w* architektur\w*|strategi\w*|"
    r"vyzkum\w*|prozkoumej|rozepis|podrobne|do hloubky|krok za krokem|proc (je|se|nejde|to)|vysvetli (proc|jak funguje)|"
    r"naprogramuj|napis (kod|program|skript|funkci|aplikaci)|oprav (kod|chybu|bug)|refaktor\w*|debug\w*|"
    r"spocitej|vypocitej|odhadni|rozhodni|doporuc\w*|optimalizuj|business plan|smlouv\w*|pravn\w*|financ\w*|investic\w*|"
    r"zdravotn\w*|diagnoz\w*|esej|clanek|referat|seminarni|prezentac\w*)\b")


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", t).split())


def classify(text: str, *, attachments: int = 0, agent_mode: bool = False, mission: bool = False) -> str:
    t = _norm(text)
    if agent_mode or mission:
        return "strong"
    words = len(t.split())
    if attachments == 0 and words <= 6 and SMALL_TALK.match(t):
        return "fast"
    if words > 60 or STRONG.search(t) or (attachments and words > 12):
        return "strong"
    return "normal"


EFFORT = {"fast": "low", "normal": "low", "strong": "high"}
