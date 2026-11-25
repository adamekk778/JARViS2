"""3.14 Zdraví jako ve filmu: the watch's numbers, the morning verdict, care at the PC (water, bedtime, posture)."""
from __future__ import annotations

from typing import Annotated

from .base import ToolResult, tool


@tool("body_status", "Stav systémů jako ve filmu: jak ses vyspal, klidový tep, variabilita tepu a kyslík z hodinek (přes "
      "Health Connect v telefonu) proti tvému normálu za 2 týdny, a co to znamená pro dnešek („doporučuji lehčí den“).",
      category="zdraví")
async def body_status(ctx) -> ToolResult:
    from .. import body

    s = body.status(ctx)
    if s["level"] == "unknown":
        hist = body.history(ctx, 7)
        if not hist:
            return ToolResult(True, "Z hodinek zatím nic nemám. V aplikaci JARVIS v telefonu otevři Návyky → Zdraví z telefonu "
                              "→ Propojit a povol Spánek, Kroky a Tep (hodinky musí zapisovat do Health Connect).", data=s)
        last = hist[-1]
        return ToolResult(True, f"Dnešní spánek ani tep z hodinek ještě nepřišly; poslední data jsou z {last['day']}.", data=s)
    return ToolResult(True, s["text"], data=s)


@tool("body_history", "Spánek, klidový tep a kroky z hodinek za posledních N dní – trend (lepší/horší než obvykle).",
      category="zdraví")
async def body_history(ctx, days: Annotated[int, "kolik dní zpět (7–90)"] = 7) -> ToolResult:
    from .. import body

    days = max(2, min(int(days or 7), 90))
    hist = body.history(ctx, days)
    if not hist:
        return ToolResult(True, "Z hodinek zatím žádná data nemám.", data={"days": []})

    def avg(k: str) -> float | None:
        v = [d[k] for d in hist if d.get(k) is not None]
        return round(sum(v) / len(v), 1) if v else None

    bits = []
    if (s := avg("sleep_h")) is not None:
        bits.append(f"průměrně {str(s).replace('.', ',')} h spánku")
    if (r := avg("rest_hr")) is not None:
        bits.append(f"klidový tep {int(r)}")
    if (st := avg("steps")) is not None:
        bits.append(f"{int(st):,} kroků denně".replace(",", " "))
    return ToolResult(True, f"Za posledních {days} dní: " + ", ".join(bits) + ".", data={"days": hist})


@tool("health_reminders", "Hlídání u PC: pitný režim (sklenice vody každých N minut), upozornění na moc dlouhý den u počítače, "
      "připomenutí spánku po zvolené hodině a hlídání držení těla webkamerou. Zapne, vypne nebo nastaví.",
      category="zdraví", perm="system")
async def health_reminders(ctx, water_minutes: Annotated[int, "voda každých N minut, 0 = vypnout, -1 = beze změny"] = -1,
                           bedtime: Annotated[str, "„23:30“, „off“ = vypnout, prázdné = beze změny"] = "",
                           posture: Annotated[str, "„on“ / „off“ / prázdné = beze změny"] = "",
                           long_day_h: Annotated[float, "upozornit po tolika hodinách u PC za den, 0 = vypnout, -1 = beze změny"] = -1) -> ToolResult:
    import re

    patch: dict = {}
    if int(water_minutes) >= 0:
        patch["water_minutes"] = max(0, min(int(water_minutes), 600))
    b = (bedtime or "").strip().lower()
    if b in ("off", "vypnout", "ne", "0"):
        patch["bedtime"] = ""
    elif b:
        m = re.match(r"^(\d{1,2})(?:[:.](\d{2}))?$", b)
        if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
            return ToolResult(False, "Čas spánku zadej jako 23:30.")
        patch["bedtime"] = f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}"
    p = (posture or "").strip().lower()
    if p in ("on", "zapnout", "ano", "true", "1"):
        patch["posture"] = True
    elif p in ("off", "vypnout", "ne", "false", "0"):
        patch["posture"] = False
    if float(long_day_h) >= 0:
        patch["long_day_h"] = max(0.0, min(float(long_day_h), 20.0))
    if patch:
        ctx.update_config({"health": patch})
    c = ctx.cfg.health
    parts = [f"voda každých {c.water_minutes} min" if c.water_minutes else "voda vypnutá",
             f"spát od {c.bedtime}" if c.bedtime else "připomínka spánku vypnutá",
             "držení těla hlídám kamerou" if c.posture else "držení těla nehlídám",
             f"dlouhý den po {str(c.long_day_h).replace('.0', '').replace('.', ',')} h" if c.long_day_h else "dlouhý den nehlídám"]
    note = ""
    if patch.get("posture"):
        note = (" Prvních pár kontrol si zapamatuji, jak sedíš – sedni si teď rovně. Kdykoli řekni „teď sedím dobře“ a "
                "nastavím to znovu. Fotky se nikam neukládají ani neposílají.")
    return ToolResult(True, ("Nastaveno: " if patch else "Teď: ") + ", ".join(parts) + "." + note, data=c.model_dump())


@tool("posture_calibrate", "„Teď sedím dobře“: webkamera si zapamatuje správné držení těla, podle kterého pak hlídá, jestli "
      "se nehrbíš nebo nejsi moc blízko monitoru.", category="zdraví", perm="screen")
async def posture_calibrate(ctx) -> ToolResult:
    from .. import body, webcam

    if not webcam.available():
        return ToolResult(False, "Na tomhle PC chybí OpenCV pro kameru.")
    try:
        text = await body.desk(ctx).calibrate()
    except webcam.NoCamera as e:
        return ToolResult(False, f"Kamera nejde: {e}.")
    return ToolResult(True, text)
