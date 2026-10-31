"""OMEGA wave 7 by voice: flashcards with spaced repetition, cards and tests from your documents, graded answers with
the kind of mistake, weak spots, an exam plan, study statistics, a real math step checker, mind maps, oral exam."""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Annotated

from .base import ToolResult, tool
from .files import resolve


async def _text_of(path_or_text: str) -> str:
    from .. import fileuniverse

    p = resolve(path_or_text) if len(path_or_text) < 400 else None
    if p is not None and p.is_file():
        t = await asyncio.to_thread(fileuniverse.doc_text, p, 60000)
        if not t:
            raise ValueError("Z toho souboru nejde přečíst text (PDF, Word, txt, md).")
        return t
    return path_or_text


@tool("flashcard_add", "Přidá kartičku na učení (otázka → odpověď) do balíčku.", category="učení")
async def flashcard_add(ctx, front: str, back: str, deck: str = "Obecné", topic: str = "") -> ToolResult:
    try:
        c = ctx.learning.add_card(deck, front, back, topic)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Kartička přidána do balíčku „{c['deck']}“.", data=c)


@tool("flashcards_from", "Vytvoří kartičky z dokumentu nebo textu (PDF, Word, poznámky) – jen z toho, co tam je.", category="učení")
async def flashcards_from(ctx, source: Annotated[str, "cesta k souboru nebo text"], deck: str = "", count: int = 10) -> ToolResult:
    from .. import learning

    try:
        text = await _text_of(source)
        cards = await learning.cards_from_text(ctx, text, max(1, min(40, count)))
    except ValueError as e:
        return ToolResult(False, str(e))
    deck = deck or "Z dokumentu"
    added = 0
    for c in cards:
        try:
            ctx.learning.add_card(deck, c["front"], c["back"], c.get("topic", ""))
            added += 1
        except ValueError:
            pass
    return ToolResult(added > 0, f"Vytvořil jsem {added} kartiček do balíčku „{deck}“. Opakovat: „zkoušej mě“.", data=cards)


@tool("flashcards_review", "Opakování kartiček: bez card_id vrátí další kartičku k zopakování (jen otázku); s card_id a "
      "grade (0 nevěděl – 3 těžké – 4 dobře – 5 snadné) ji ohodnotí a naplánuje další opakování.", category="učení")
async def flashcards_review(ctx, deck: str = "", card_id: str = "", grade: int = -1) -> ToolResult:
    lr = ctx.learning
    if card_id and grade >= 0:
        try:
            c = lr.review(card_id, grade)
        except ValueError as e:
            return ToolResult(False, str(e))
        nxt = dt.datetime.fromtimestamp(c["due"])
        when = "za 10 minut" if c["reps"] == 0 else f"{nxt:%d. %m.}"
        return ToolResult(True, f"Správná odpověď: {c['back']}. Další opakování {when}.", data=c)
    due = lr.due(deck, 1)
    if not due:
        decks = lr.decks()
        return ToolResult(True, "Teď není co opakovat. " + (", ".join(f"{d['deck']} ({d['cards']})" for d in decks) or "Zatím nemáš žádné kartičky."), data=decks)
    c = due[0]
    return ToolResult(True, f"Otázka ({c['deck']}): {c['front']}", data={"id": c["id"], "front": c["front"], "deck": c["deck"]})


@tool("quiz_from", "Vytvoří procvičovací test z dokumentu nebo textu (výběr z možností i otevřené otázky).", category="učení")
async def quiz_from(ctx, source: Annotated[str, "cesta k souboru nebo text"], count: int = 8) -> ToolResult:
    from .. import learning

    try:
        qs = await learning.quiz_from_text(ctx, await _text_of(source), max(1, min(30, count)))
    except ValueError as e:
        return ToolResult(False, str(e))
    if not qs:
        return ToolResult(False, "Z podkladu se nepodařilo udělat otázky.")
    lines = [f"{i + 1}. {q['q']}" + (" (" + " / ".join(q["options"]) + ")" if q["options"] else "") for i, q in enumerate(qs)]
    return ToolResult(True, "\n".join(lines) + "\nOdpovídej postupně, ohodnotím to (check_answer).", data=qs)


@tool("check_answer", "Ohodnotí odpověď na otázku (0–100), řekne co je dobře, co chybí a druh chyby; zapíše si to pro "
      "hledání slabých míst.", category="učení")
async def check_answer(ctx, question: str, answer: str, expected: str = "", subject: str = "", topic: str = "") -> ToolResult:
    from .. import learning

    try:
        g = await learning.grade(ctx, question, expected, answer)
    except ValueError as e:
        return ToolResult(False, str(e))
    ctx.learning.record_answer(subject, topic or question[:60], question, g["score"], g["mistake"])
    miss = f" Chybí: {'; '.join(g.get('missing') or [])}." if g.get("missing") else ""
    return ToolResult(True, f"{g['score']} / 100 – {g.get('feedback', '')}{miss} ({g['mistake']})", data=g)


@tool("learning_weak_spots", "Slabá místa v učení: témata s nejhoršími výsledky, druhy chyb a kartičky, které pořád zapomínáš.",
      category="učení")
async def learning_weak_spots(ctx, subject: str = "") -> ToolResult:
    w = ctx.learning.weak_spots(subject)
    if not w["topics"] and not w["hard_cards"]:
        return ToolResult(True, "Zatím nemám dost odpovědí, abych poznal slabá místa.", data=w)
    parts = []
    if w["topics"]:
        parts.append("Nejslabší témata: " + ", ".join(f"{t['topic']} ({t['avg']} %)" for t in w["topics"][:4]))
    if w["mistakes"]:
        parts.append("Nejčastější chyby: " + ", ".join(f"{m['mistake']} {m['n']}×" for m in w["mistakes"][:3]))
    if w["hard_cards"]:
        parts.append("Zapomínáš: " + ", ".join(c["front"][:40] for c in w["hard_cards"][:4]))
    return ToolResult(True, ". ".join(parts) + ".", data=w)


@tool("exam_plan", "Plán učení před zkouškou: rozloží témata do dnů do zkoušky, s opakováním a závěrečným testem den předem.",
      category="učení")
async def exam_plan(ctx, name: str, date: Annotated[str, "datum zkoušky RRRR-MM-DD nebo D. M."], topics: list[str]) -> ToolResult:
    import re

    s = date.strip()
    try:
        if m := re.fullmatch(r"(\d{1,2})\.\s*(\d{1,2})\.?(?:\s*(\d{4}))?", s):
            d = dt.date(int(m.group(3) or dt.date.today().year), int(m.group(2)), int(m.group(1)))
        else:
            d = dt.date.fromisoformat(s)
        p = ctx.learning.plan_exam(name, d, topics)
    except ValueError as e:
        return ToolResult(False, str(e))
    lines = [f"{dt.date.fromisoformat(k):%a %d. %m.}: {', '.join(v)}" for k, v in p["plan"].items()]
    return ToolResult(True, f"{name} za {p['days']} dní. " + "; ".join(lines), data=p)


@tool("study_stats", "Statistika učení: kolik opakování a odpovědí, úspěšnost a kolik dní v řadě se učíš.", category="učení")
async def study_stats(ctx, days: int = 14) -> ToolResult:
    s = ctx.learning.stats(days)
    if not s["reviews"] and not s["answers"]:
        return ToolResult(True, "Za tu dobu ses s JARVISem neučil.", data=s)
    return ToolResult(True, f"Za {days} dní: {s['reviews']} opakování kartiček" + (f" (úspěšnost {s['accuracy']} %)" if s["accuracy"] is not None else "")
                      + f", {s['answers']} odpovědí" + (f" (průměr {s['avg_score']} %)" if s["avg_score"] is not None else "")
                      + f". Učíš se {s['streak']} dní v řadě.", data=s)


@tool("check_math_steps", "Zkontroluje výpočet krok po kroku (každý krok na nový řádek, i rovnice) a najde první chybný krok – "
      "počítá doopravdy, nehádá.", category="učení")
async def check_math_steps(ctx, steps: Annotated[str, "kroky výpočtu, každý na řádku"]) -> ToolResult:
    from .. import learning

    try:
        r = learning.check_steps(steps.replace(";", "\n").splitlines())
    except (ValueError, SyntaxError, ZeroDivisionError) as e:
        return ToolResult(False, f"Tomu výrazu nerozumím: {e}")
    if r["ok"]:
        return ToolResult(True, f"Všech {len(r['steps']) + 1} kroků je správně.", data=r)
    e = r["first_error"]
    return ToolResult(True, f"Chyba je v kroku {e['step']}: „{e['line']}“ – " + ("rovnice už nemá stejné řešení." if r["equation"] else "výraz už nemá stejnou hodnotu.")
                      + " Předchozí kroky jsou v pořádku.", data=r)


@tool("mind_map", "Myšlenková mapa z tématu, textu nebo dokumentu (větve, pojmy, souvislosti); uloží ji jako Markdown s "
      "diagramem.", category="učení")
async def mind_map(ctx, source: Annotated[str, "téma, text nebo cesta k souboru"]) -> ToolResult:
    from .. import learning, thinking

    try:
        d = await learning.mind_map(ctx, await _text_of(source))
    except ValueError as e:
        return ToolResult(False, str(e))
    md = learning.mind_map_markdown(d)
    path = thinking.save_markdown("mapa", md)
    ctx.tasks.add_artifact(path, "Myšlenková mapa")
    return ToolResult(True, md.split("```")[0].strip() + f"\n\nUloženo: {path}", data=d)


@tool("oral_exam", "Ústní zkoušení: vrátí další otázku k tématu (a na odpověď pak použij check_answer se stejným topic). "
      "Obtížnost se sama přizpůsobuje: 3 dobré odpovědi za sebou → těžší, 2 slabé ze 3 → lehčí. Pro zkoušení nahlas.",
      category="učení")
async def oral_exam(ctx, topic: str, level: Annotated[str, "základní / střední / pokročilá; prázdné = podle výsledků"] = "") -> ToolResult:
    from .. import thinking

    ad = ctx.learning.adaptive_level(topic)            # OMEGA 451: difficulty follows the answers
    level = level if level in ctx.learning.LEVELS else ad["level"]
    asked = [r["question"] for r in ctx.db.all("SELECT question FROM quiz_answers WHERE topic=? ORDER BY ts DESC LIMIT 15", (topic[:80],))]
    weak = ctx.learning.weak_spots()
    try:
        d = await thinking.ask_json(ctx, "Jsi zkoušející u ústní zkoušky. Polož JEDNU otázku k tématu podle úrovně; neopakuj "
                                    "už položené a zaměř se na slabá místa.",
                                    f"Téma: {topic}\nÚroveň: {level}\nUž bylo: {asked}\nSlabá místa: {[t['topic'] for t in weak['topics']]}\n"
                                    'Formát: {"question": "…", "expected": "stručná správná odpověď"}')
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, d.get("question", ""), data={**d, "topic": topic, "level": level, "adaptive": ad})
