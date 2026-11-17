"""3.12 Velín firmy: the weekly company report as a PDF – every Monday morning by itself, or on a click.

It is drawn from what JARVIS knows without asking any AI: the week's numbers (runs, success, approvals, time saved),
the departments, the latest results of the agents, what waits for approval and the company's newest notes. The PDF
lands in the JARVIS folder (Zprávy), the PC says it is ready and the phone gets a notice.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import textwrap
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
W, H, M = 1240, 1754, 80            # an A4 page at 150 dpi, margins


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    names = (("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf") if bold else
             ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"))
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _hours(minutes: float) -> str:
    """Minutes as hours the Czech way: 0, 1,5, 12."""
    v = round((minutes or 0) / 60, 1)
    return (f"{v:.0f}" if v >= 10 or v == int(v) else f"{v:.1f}").replace(".", ",")


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


class _Pages:
    def __init__(self, title: str):
        from PIL import Image, ImageDraw

        self.Image, self.ImageDraw = Image, ImageDraw
        self.pages: list = []
        self.title = title
        self._new()

    def _new(self) -> None:
        im = self.Image.new("RGB", (W, H), (248, 249, 252))
        d = self.ImageDraw.Draw(im)
        d.rectangle([0, 0, W, 12], fill=(124, 92, 255))
        d.text((M, H - 50), f"JARVIS · Velín firmy · {self.title} · strana {len(self.pages) + 1}", font=_font(18), fill=(140, 148, 170))
        self.pages.append(im)
        self.d, self.y = d, M

    def need(self, h: int) -> None:
        if self.y + h > H - 90:
            self._new()

    def text(self, s: str, size: int = 22, bold: bool = False, color=(30, 34, 52), width: int = 92, gap: int = 6) -> None:
        f = _font(size, bold)
        for para in str(s).split("\n"):
            for line in textwrap.wrap(para, width=width) or [""]:
                self.need(size + gap)
                self.d.text((M, self.y), line, font=f, fill=color)
                self.y += size + gap

    def space(self, h: int = 18) -> None:
        self.y += h


def build(rt: Any) -> dict:
    """The report's content (also used by the PDF and the tests)."""
    from . import bizagents, bizcompany

    n = bizcompany.numbers(rt)
    ags = bizagents.agents(rt)
    since = dt.datetime.now() - dt.timedelta(days=7)
    db = bizcompany._db(rt)
    approved = db.one("SELECT COUNT(*) AS n FROM biz_proposals WHERE status='done' AND decided >= ?", (since.timestamp(),))
    best = [a for a in ags if a.get("last_run") and a["last_run"] >= since.timestamp() and a.get("last_ok")]
    best.sort(key=lambda a: -(a.get("last_run") or 0))
    return {"company": bizcompany.profile(rt).get("name") or "Firma", "from": since.strftime("%d. %m."), "to": dt.datetime.now().strftime("%d. %m. %Y"),
            "numbers": n, "approved_week": int(approved["n"] or 0) if approved else 0,
            "depts": bizcompany.depts(rt), "results": [(a["name"], a.get("dept") or "", (a.get("last_result") or "")[:700]) for a in best[:12]],
            "pending": bizagents.proposals(rt)[:15], "notes": bizcompany.brain_notes(rt, 8), "agents": len(ags),
            "enabled": sum(1 for a in ags if a.get("enabled"))}


def make_pdf(rt: Any, folder: Path | None = None) -> str:
    from . import paths
    from .bizcompany import DEPTS

    r = build(rt)
    n = r["numbers"]
    pg = _Pages(f"týden {r['from']} – {r['to']}")
    d = pg.d
    # header
    d.rounded_rectangle([M, pg.y, W - M, pg.y + 190], radius=28, fill=(22, 24, 48))
    d.text((M + 36, pg.y + 30), "TÝDENNÍ ZPRÁVA FIRMY", font=_font(22, True), fill=(160, 170, 255))
    d.text((M + 36, pg.y + 66), r["company"], font=_font(52, True), fill=(255, 255, 255))
    d.text((M + 36, pg.y + 136), f"{r['from']} – {r['to']} · {r['agents']} agentů ({r['enabled']} zapnuto)", font=_font(22), fill=(190, 198, 230))
    pg.y += 222
    # the numbers
    kpis = [(str(n["runs_week"]), "běhů agentů"), (f"{round((n['ok_week'] or 0) / n['runs_week'] * 100) if n['runs_week'] else 0} %", "úspěšnost"),
            (str(r["approved_week"]), "schválených akcí"), (f"{_hours(n['saved_week_min'])} h", "ušetřeno (odhad)"),
            (str(n["pending"]), "čeká na schválení"), (str(n["ai_week"]), "dotazů na AI")]
    bw = (W - 2 * M - 2 * 24) // 3
    for i, (v, label) in enumerate(kpis):
        x = M + (i % 3) * (bw + 24)
        y = pg.y + (i // 3) * 150
        d.rounded_rectangle([x, y, x + bw, y + 130], radius=22, fill=(255, 255, 255), outline=(226, 230, 242), width=2)
        d.text((x + 26, y + 20), v, font=_font(46, True), fill=(52, 60, 160))
        d.text((x + 26, y + 84), label, font=_font(20), fill=(110, 118, 140))
    pg.y += 330
    # the week chart
    days = n.get("per_day") or []
    if days:
        pg.text("Práce za týden", 28, True)
        top = pg.y + 10
        mx = max(1, *(x["runs"] for x in days))
        cw = (W - 2 * M) // len(days)
        for i, x in enumerate(days):
            hh = int(220 * x["runs"] / mx)
            okh = int(220 * x["ok"] / mx)
            cx = M + i * cw + cw // 2
            d.rounded_rectangle([cx - 34, top + 220 - hh, cx + 34, top + 220], radius=10, fill=(255, 120, 140))
            if okh:
                d.rounded_rectangle([cx - 34, top + 220 - okh, cx + 34, top + 220], radius=10, fill=(92, 110, 255))
            d.text((cx - 12, top + 232), x["label"], font=_font(20), fill=(110, 118, 140))
            d.text((cx - 14, top + 220 - hh - 30), str(x["runs"]), font=_font(20, True), fill=(52, 60, 100))
        pg.y = top + 290
    # departments
    pg.text("Oddělení", 28, True)
    pg.space(6)
    per = n.get("per_dept") or {}
    for dep in r["depts"]:
        pr = per.get(dep["id"], {"runs": 0, "ok": 0})
        pg.need(46)
        c = _hex(DEPTS.get(dep["id"], {}).get("color", "#8aa8ff"))
        d = pg.d
        d.ellipse([M, pg.y + 8, M + 18, pg.y + 26], fill=c)
        d.text((M + 32, pg.y), dep["name"], font=_font(22, True), fill=(30, 34, 52))
        d.text((M + 420, pg.y), f"{dep['agents']} agentů · {pr['runs']} běhů · {pr['ok']} úspěšných", font=_font(22), fill=(90, 98, 120))
        pg.y += 44
    pg.space()
    # results
    if r["results"]:
        pg.text("Co agenti zjistili a udělali", 28, True)
        pg.space(4)
        for name, dept, res in r["results"]:
            pg.text(f"{name}  ·  {DEPTS.get(dept, {}).get('name', '')}", 22, True, (52, 60, 160))
            pg.text(res, 20, False, (60, 66, 88), 100, 4)
            pg.space(10)
    if r["pending"]:
        pg.text("Čeká na tvoje schválení", 28, True, (190, 90, 20))
        for p in r["pending"]:
            pg.text(f"• {p['agent']}: {p['description']}", 20, False, (60, 66, 88), 100, 4)
        pg.space()
    if r["notes"]:
        pg.text("Nové v mozku firmy", 28, True)
        for x in r["notes"]:
            pg.text(f"• {x['text'][:300]}", 20, False, (60, 66, 88), 100, 4)
    folder = folder or (paths.data_dir() / "Zprávy")
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"firma_{dt.date.today().isocalendar()[0]}-tyden-{dt.date.today().isocalendar()[1]:02d}.pdf"
    first, rest = pg.pages[0], pg.pages[1:]
    first.save(out, "PDF", resolution=150.0, save_all=True, append_images=rest)
    return str(out)


async def deliver(rt: Any) -> str:
    path = await asyncio.to_thread(make_pdf, rt)
    try:
        rt.notify("Týdenní zpráva firmy je hotová", f"PDF: {path}", speak=False)
        rt.phone_push("notify", title="Týdenní zpráva firmy", body="Zpráva za uplynulý týden je hotová – otevři ji na PC (Velín → Výsledky).")
    except Exception:  # noqa: BLE001
        pass
    return path


async def loop(rt: Any) -> None:
    """Every Monday from 7:00 once (also when the PC was off on Monday morning: the first start that week)."""
    from .bizcompany import _kv, _set

    await asyncio.sleep(300)
    while True:
        try:
            now = dt.datetime.now()
            week = f"{now.isocalendar()[0]}-{now.isocalendar()[1]}"
            from .bizagents import agents

            if now.hour >= 7 and _kv(rt, "biz_report_week") != week and agents(rt):
                _set(rt, "biz_report_week", week)
                await deliver(rt)
        except Exception as e:  # noqa: BLE001
            log.info("weekly report: %s", e)
        await asyncio.sleep(1800)
