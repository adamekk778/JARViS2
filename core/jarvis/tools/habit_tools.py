"""3.12 Návyky a zdraví by voice / chat: "byl jsem v gymu", "spal jsem 7 hodin", "vypil jsem 3 sklenice vody",
"k obědu jsem měl kuře s rýží", "jak jsem na tom s návyky?"."""
from __future__ import annotations

from typing import Annotated

from .. import habits as hb
from .base import ToolResult, tool


@tool("habit_done", "Zapíše splněný návyk za dnešek (nebo jiný den): „byl jsem v gymu“, „dnes jsem meditoval“, "
      "„spal jsem 7 hodin“ (hodnota 7), „vypil jsem 3 sklenice vody“ (hodnota 3, přičte se). Když návyk neexistuje, "
      "nabídne ho přidat.", category="info", perm="apps")
async def habit_done(ctx, habit: Annotated[str, "název nebo popis návyku (gym, spánek, voda…)"],
                     value: Annotated[float, "množství u měřitelných návyků (hodiny, sklenice…); 0 = jen splněno"] = 0,
                     add: Annotated[bool, "u množství přičíst k dnešku (voda) místo přepsání (spánek)"] = False,
                     note: Annotated[str, "poznámka, např. co jsi cvičil"] = "",
                     day: Annotated[str, "den YYYY-MM-DD, prázdné = dnes"] = "") -> ToolResult:
    h = hb.find(ctx, habit)
    if not h:
        names = ", ".join(x["name"] for x in hb.habits(ctx)) or "žádné"
        return ToolResult(False, f"Návyk „{habit}“ nemám. Tvoje návyky: {names}. Můžu ho přidat (habit_add).")
    d = day or None
    if h["kind"] == "amount":
        if value <= 0:
            return ToolResult(False, f"U návyku {h['name']} potřebuju číslo ({h['unit'] or 'množství'}).")
        if add:
            snap = {i["id"]: i for i in hb.snapshot(ctx)["items"]}
            value += float((snap.get(h["id"]) or {}).get("value") or 0) if not d else 0
        hb.log(ctx, h["id"], value, d, note or None)
    else:
        hb.log(ctx, h["id"], 1, d, note or None)
    hb.publish(ctx)
    item = next((i for i in hb.snapshot(ctx)["items"] if i["id"] == h["id"]), {})
    t = hb.snapshot(ctx)["today"]
    streak = f" Série: {item.get('streak')} dní v řadě." if item.get("streak", 0) >= 2 else ""
    amount = f" ({value:g} {h['unit']})" if h["kind"] == "amount" else ""
    return ToolResult(True, f"Zapsáno: {h['name']}{amount}. Dnes splněno {t['done']} z {t['due']} ({t['pct'] or 0} %).{streak}")


@tool("habit_undo", "Zruší dnešní odškrtnutí návyku („to s gymem jsem spletl, zruš to“).", category="info", perm="apps")
async def habit_undo(ctx, habit: str, day: str = "") -> ToolResult:
    h = hb.find(ctx, habit)
    if not h:
        return ToolResult(False, f"Návyk „{habit}“ nemám.")
    hb.log(ctx, h["id"], 0, day or None, "")
    hb.publish(ctx)
    return ToolResult(True, f"Zrušeno: {h['name']}.")


@tool("habit_status", "Jak jsem na tom s návyky: dnešek, týden, série, co ještě zbývá. Na „jak jsem na tom“, „co mám "
      "dneska ještě splnit“, „kolik procent mám tento týden“.", category="info", perm="apps")
async def habit_status(ctx) -> ToolResult:
    return ToolResult(True, hb.summary(ctx), data=hb.snapshot(ctx)["today"])


@tool("habit_add", "Přidá nový návyk ke sledování: „chci sledovat čtení 10 stran“, „přidej běhání v úterý a čtvrtek“. "
      "kind=amount pro měřitelné (hodiny, sklenice, kroky) s cílem target.", category="info", perm="apps")
async def habit_add(ctx, name: str, kind: Annotated[str, "check nebo amount"] = "check", target: float = 1, unit: str = "",
                    days: Annotated[str, "dny v týdnu jako číslice 0=po … 6=ne, prázdné = každý den"] = "",
                    area: Annotated[str, "gym, jidlo, spanek, zdravi, mysl, jine"] = "jine") -> ToolResult:
    try:
        hb.save(ctx, {"name": name, "kind": kind, "target": target, "unit": unit, "days": days or hb.ALL_DAYS, "area": area,
                      "icon": {"gym": "barbell", "jidlo": "bowl-food", "spanek": "moon-stars", "zdravi": "heartbeat",
                               "mysl": "brain"}.get(area, "check-circle")})
    except ValueError as e:
        return ToolResult(False, str(e))
    hb.publish(ctx)
    return ToolResult(True, f"Přidáno: {name}. Najdeš ho v notchi v záložce Návyky.")


@tool("meal_log", "Zapíše jídlo do dnešního jídelníčku: „k snídani jsem měl ovesnou kaši“, „na oběd kuře s rýží“. "
      "slot: snidane, obed, vecere, svacina.", category="info", perm="apps")
async def meal_log(ctx, slot: Annotated[str, "snidane, obed, vecere nebo svacina"], text: str, day: str = "") -> ToolResult:
    from ..stark import _fold

    s = _fold(slot)
    stems = {"snidane": ("snida", "breakfast", "rano"), "obed": ("obed", "lunch"), "vecere": ("vecer", "dinner"),
             "svacina": ("svac", "snack")}
    slot_id = next((k for k, keys in stems.items() if any(x in s for x in keys)), None)
    if not slot_id:
        return ToolResult(False, "Které jídlo dne? Snídaně, oběd, večeře, nebo svačina.")
    hb.set_meal(ctx, slot_id, text, day or None)
    hb.publish(ctx)
    return ToolResult(True, f"Zapsáno do jídelníčku: {dict(hb.MEAL_SLOTS)[slot_id]} – {text}.")


@tool("gym_log", "Zapíše sérii z posilovny do gym deníku: „bench 60 kilo 8 opakování“, „3 série dřepů 80 kg po 5“. "
      "exercise = cvik, weight = kg (0 = vlastní váha), reps = opakování, sets = počet sérií.", category="info", perm="apps")
async def gym_log(ctx, exercise: str, weight: float, reps: int, sets: int = 1, day: str = "") -> ToolResult:
    from .. import gym

    gym.add_set(ctx, exercise, weight, reps, day or None, sets)
    gym.publish(ctx)
    hb.publish(ctx)
    ex = gym.name(exercise)
    best = next((e for e in gym.snapshot(ctx)["exercises"] if e["name"] == ex), None)
    pr = " Nový osobní rekord! 🔥" if best and best.get("pr_today") and best.get("gain") else ""
    return ToolResult(True, f"Zapsáno: {ex} {sets}× {reps} opakování po {weight:g} kg.{pr}")


@tool("mindset_log", "Zapíše, jak se dnes mám (večerní otázka „Jak se dnes máš?“): energy, focus, motivation 1–5 "
      "odhadni z toho, co uživatel řekl („dneska jsem unavený, ale soustředěný“ → energy 2, focus 4), a krátkou větu dne.",
      category="info", perm="apps")
async def mindset_log(ctx, energy: int = 0, focus: int = 0, motivation: int = 0, note: str = "") -> ToolResult:
    hb.set_mindset(ctx, note or None, energy=energy or None, focus=focus or None, motivation=motivation or None)
    hb.publish(ctx)
    parts = [f"{n} {v}/5" for n, v in (("energie", energy), ("soustředění", focus), ("motivace", motivation)) if v]
    return ToolResult(True, "Zapsáno do dnešního mindsetu" + (f": {', '.join(parts)}." if parts else "."))
