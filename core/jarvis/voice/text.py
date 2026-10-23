"""Text helpers for speech: strip Markdown, understand yes/no."""
from __future__ import annotations

import re

YES = {"ano", "jo", "jasně", "jasne", "určitě", "urcite", "potvrzuji", "potvrzuju", "proveď", "proved", "udělej",
       "udelej", "ok", "okej", "dobře", "dobre", "yes", "yeah", "sure", "do it", "souhlasím", "souhlasim", "klidně", "klidne"}
NO = {"ne", "nee", "nech", "nedělej", "nedelej", "zruš", "zrus", "stop", "no", "nope", "cancel", "počkej", "pockej", "nikdy"}


def strip_markdown(text: str) -> str:
    t = re.sub(r"```.*?```", " (kód najdeš v chatu) ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "odkaz", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*\|.*\|\s*$", "", t, flags=re.M)  # tables are for reading
    t = re.sub(r"[*_~>#|]", "", t)
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", t)
    t = re.sub(r"\s*\n\s*", ". ", t.strip())
    t = re.sub(r"\.\s*\.", ".", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def parse_yes_no(text: str) -> bool | None:
    words = re.findall(r"[\wěščřžýáíéůúňťď]+", text.lower())
    joined = " ".join(words)
    if any(w in NO for w in words) or "nech to" in joined or "to ne" in joined:
        return False
    if any(w in YES for w in words) or "do it" in joined:
        return True
    return None


class Endpointer:
    """Decides when the user stopped talking: speech followed by `silence_s` of silence."""

    def __init__(self, frame_s: float, silence_s: float = 0.8, no_speech_s: float = 6.0, max_s: float = 20.0):
        self.frame_s = frame_s
        self.silence_s = silence_s
        self.no_speech_s = no_speech_s
        self.max_s = max_s
        self.reset()

    def reset(self) -> None:
        self.t = 0.0
        self.heard = False
        self.quiet = 0.0

    def feed(self, is_speech: bool) -> str | None:
        """Returns None (keep listening), 'done' (got an utterance) or 'timeout' (nobody spoke)."""
        self.t += self.frame_s
        if is_speech:
            self.heard = True
            self.quiet = 0.0
        else:
            self.quiet += self.frame_s
        if self.heard and self.quiet >= self.silence_s - 1e-6:
            return "done"
        if not self.heard and self.t >= self.no_speech_s - 1e-6:
            return "timeout"
        if self.t >= self.max_s:
            return "done" if self.heard else "timeout"
        return None
