"""3.20 what the agent does for Hlas+ and Mozek+ (kept out of agent.py, which stays short): the quick commands that
depend on what is going on now, how deeply / boldly / cheaply a message is thought about, režim učitele, the quick
draft, the plan to approve, the numbers and confidence added to an answer, the second look after a task."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Callable

from . import brainx, voicex

log = logging.getLogger(__name__)

# (32) "udělej to v noci": a task, not a question about the night
NIGHT_TASK = re.compile(r"^(udelej|zpracuj|projdi|priprav|najdi|stahni|prepis|shrn|zjisti|vyhledej|sepis|preloz|uklid|zalohuj|"
                        r"porovnej|analyzuj|serad|roztrid|vytvor|napis|prejmenuj|zkontroluj)\w*\b")
READING = ((r"pokracuj( ve cteni)?|cti dal|dal cti", "resume"), (r"zastav( cteni)?|stop|pauza|prestan cist", "pause"),
           (r"(cti )?rychleji", "faster"), (r"(cti )?pomaleji", "slower"), (r"kde (jsem|jsme) skoncil\w*|kolik zbyva", "where"))


PHOTO_MEM = re.compile(r"^(pamatuj si|zapamatuj si|zapamatuj|uloz si)\b.*\b(tohle|to|tuhle|tenhle|tuto|toto|fotk\w*|obrazek|misto)\b")


def quick320(rt: Any, text: str, attachments: list | None = None) -> tuple[str, dict] | None:
    """Commands that depend on what is going on right now: a running sum, a long answer just said, reading aloud, a
    note, "proč", the answer style, a task for the night, a memory with a photo. (tool, args) or None."""
    w = voicex.words(text).strip(" .?!")
    if attachments:                                       # (49) "pamatuj si tohle" with a photo
        att = rt.store.get(attachments[0]) if getattr(rt, "store", None) is not None else None
        if att is not None and getattr(att, "kind", "") == "image" and PHOTO_MEM.match(w):
            what = re.sub(r"^\s*(pamatuj si|zapamatuj si|zapamatuj|ulož si|uloz si)\s*(tohle|to|tuhle|tenhle)?[:,]?\s*", "", text, flags=re.I)
            return "memory_kit", {"action": "photo", "text": what.strip() or "Vzpomínka", "attachment": attachments[0]}
        return None
    if not w:
        return None
    st = getattr(rt, "voicex_read", None)
    if st and st.get("sentences") and st.get("pos", 0) < len(st["sentences"]):
        for rx, act in READING:
            if re.fullmatch(rx, w):
                return "read_aloud", {"action": act}
    if voicex.TALLY_START.match(w) or (voicex.tally_active(rt) and voicex.TALLY_MORE.match(w) and (
            voicex.cz_number(w) is not None or re.match(r"^(kolik|celkem|soucet|vysledek|konec|zrus|vynuluj|vrat)", w))):
        return "voice_kit", {"action": "tally", "text": text}
    nk = voicex.nav_kind(text)
    said = getattr(rt, "voicex_said", None)
    if nk == "slow" and said and time.time() - said["ts"] < 120:
        return "voice_kit", {"action": "slow"}
    if nk and nk != "slow" and voicex.nav_active(rt):
        return "voice_kit", {"action": nk}
    if voicex.NOTE.match(w):
        body = re.sub(r"^\s*(poznamenej si|zapiš si|zapis si|hlasov[áa] pozn[áa]mka|pozn[áa]mka)\b[:,]?\s*", "", text, flags=re.I)
        return "voice_kit", {"action": "note", "text": body.strip() or text}
    if brainx.WHY.match(w):
        return "brain_kit", {"action": "why"}
    style = brainx.style_from_words(text)
    if style and len(w.split()) <= 6:
        return "brain_kit", {"action": "style", "value": style}
    if brainx.NIGHT.search(w) and NIGHT_TASK.match(w):
        return "brain_kit", {"action": "night", "text": text}
    from . import memx

    return memx.quick(rt, text)                          # 3.20 Paměť+ (kam jsem to dal, doporučení, přání, deník…)


def facts_for(rt: Any, facts: list[str], voice: bool) -> list[str]:
    """(51) a household member (not the owner) speaking: only what is shared with the family; (59) locked: never."""
    vid = getattr(rt, "voiceid", None)
    household = False
    try:
        owner = vid.profiles.owner() if vid is not None else ""
        household = bool(voice and owner and vid.last_speaker and vid.last_speaker != owner and time.time() - vid.last_at < 120)
    except Exception:  # noqa: BLE001
        household = False
    from . import memx

    try:
        return memx.facts_for_speaker(rt, facts, household)
    except Exception as e:  # noqa: BLE001
        log.debug("facts for speaker: %s", e)
        return facts


def tune_routing(rt: Any, text: str, tier_kw: dict, private: bool, only: str | None) -> None:
    """(21, 22) deeper for money / deleting / sending or "promysli to důkladně", (40) bolder for wild ideas, (32) the
    cheapest brain for a night task, (35) the AI on this PC once today's budget for playing / working is used up."""
    if getattr(rt.cfg.brain, "risk_depth", True) and (brainx.risky_action(text) or brainx.deep_request(text)):
        tier_kw["effort"] = "high"
        tier_kw.pop("fast", None)
    if brainx.creative_request(text):
        tier_kw["temperature"] = 1.0
    if getattr(rt, "cheap_turn", False) and not only and not private:
        cheap = brainx.cheap_provider(rt)
        if cheap:
            tier_kw["prefer"] = cheap
            tier_kw.pop("fast", None)
    if only or private:
        return
    why = brainx.over_budget(rt)
    if not why:
        return
    from . import brainplus

    lid = brainplus.local_provider(rt)
    if not lid:
        return
    tier_kw["only"] = lid
    tier_kw.pop("prefer", None)
    day = time.strftime("%Y-%m-%d")
    if getattr(rt, "_budget_told", "") != day:            # said once a day, then quietly on this PC's AI
        rt._budget_told = day
        rt.notify("Rozpočet AI", why, speak=False)


def teach_filter(rt: Any, text: str, schemas: list[dict]) -> list[dict] | None:
    """(36) režim učitele: only reading tools go with the message (it explains, it does not do)."""
    if not (brainx.teach_request(text) or getattr(rt.cfg.brain, "teach", False)):
        return None
    from . import tools
    from . import toolcatalog as tc
    from .permissions import is_reading
    from .tools import select as sel

    return [sc for sc in schemas if (n := sc.get("function", sc).get("name")) == sel.FIND or
            (n in tools.REGISTRY and n != tc.USE and is_reading(tools.REGISTRY[n]))]


def draft(rt: Any, text: str, written: Callable[[], str]) -> None:
    """(34) one quick sentence in the chat at once; the full answer replaces it as soon as it starts."""
    if not getattr(rt.cfg.brain, "quick_draft", True) or getattr(rt.cfg.agent, "mode", False):
        return                                            # agent mode: long tasks, the plan / steps say more than a line

    async def _draft() -> None:
        from . import brainplus

        line = await brainplus.preface(rt, text)
        if line and not written().strip():
            rt.bus.publish("assistant_draft", text=line)
    asyncio.get_running_loop().create_task(_draft())


async def plan_gate(agent: Any, text: str, tier: str, msgs: list[dict]) -> str | None:
    """(29) a big task: the plan first; approved → it goes into the instructions, declined → nothing is done."""
    rt = agent.rt
    if not brainx.needs_plan(rt, text, tier):
        return None
    try:
        steps = await brainx.make_plan(rt, text)
    except Exception as e:  # noqa: BLE001
        log.info("plan first: %s", e)
        return None
    if not steps:
        return None
    from .llm.base import ToolCall

    ok = await agent._ask_confirm(ToolCall(id="plan", name="plan_approval", arguments={"steps": steps}))
    if not ok:
        return "Dobře, podle toho plánu nic nedělám. Napiš, co mám udělat jinak."
    plan = "\n".join(f"{i}. {st}" for i, st in enumerate(steps, 1))
    if msgs and msgs[0].get("role") == "system":
        msgs[0]["content"] = f"{msgs[0]['content']}\n\nUživatel schválil tento plán – drž se ho:\n{plan}"
    return None


def finish_add(rt: Any, text: str, voice: bool, sources: list) -> str:
    """(28) a wrong calculation corrected under the answer, (23) how sure it is about facts from the web."""
    add = brainx.numbers_line(text) if getattr(rt.cfg.brain, "check_numbers", True) else ""
    if getattr(rt.cfg.brain, "confidence", True) and not voice and sources:
        add += brainx.confidence_line(text, sources)
    return add


async def post_check(rt: Any, msg_id: str, goal: str, cards: list[dict], answer: str) -> None:
    """(27) a quick second look after a longer task: does the result match what was asked?"""
    r = await brainx.after_check(rt, goal, cards, answer)
    if r and not r["ok"]:
        rt.bus.publish("answer_check", id=msg_id, issues=[r["why"]], title="Kontrola úkolu – možná nesedí:")
        rt.notify("Kontrola úkolu", f"Možná to úplně nesedí: {r['why']}", speak=False)
