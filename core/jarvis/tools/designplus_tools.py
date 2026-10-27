"""Wave 44 by voice: a page on four displays, animation curves, glass material, an icon set, a motion timeline and a heatmap
of how the space in a UI is used."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .files import resolve


def _out(kind: str) -> Path:
    d = paths.data_dir() / "studio" / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


@tool("responsive_check", "Jak se stránka chová na telefonu, tabletu, notebooku a monitoru: vodorovné posouvání (co přečnívá), "
      "drobné písmo, malá tlačítka na dotyk, překrývající se prvky – se snímky vedle sebe.", category="design", perm="network")
async def responsive_check(ctx, url: str) -> ToolResult:
    from .. import designplus

    try:
        r = await designplus.analyze_layout(url, _out("responzivita"))
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Stránku nejde načíst: {str(e).splitlines()[0][:200]}")
    bad = [f"{d['label']} ({d['width']} px): " + "; ".join(d["issues"]) for d in r["displays"] if d["issues"]]
    return ToolResult(True, f"Skóre {r['score']}/100. " + (" | ".join(bad) if bad else "Na všech šířkách v pořádku."), data=r, attachments=[r["sheet"]])


@tool("animation_curve", "Animační křivka: rozbor easing funkce (zrychlení, zpomalení, přešvih), nejbližší známá křivka, "
      "graf a editor s tahacími úchyty a živým náhledem. Umí i proložit křivku naměřeným pohybem.", category="design")
async def animation_curve(ctx, easing: Annotated[str, "např. ease-in-out nebo cubic-bezier(.34,1.56,.64,1)"] = "ease-in-out",
                          samples: Annotated[list[list[float]], "volitelně body [x, y] naměřeného pohybu k proložení"] | None = None) -> ToolResult:
    from .. import designplus

    try:
        c = designplus.fit_bezier([tuple(p) for p in samples]) if samples else designplus.parse_easing(easing)
    except (ValueError, TypeError) as e:
        return ToolResult(False, str(e))
    info = designplus.describe_curve(c)
    d = _out("krivka")
    (d / "krivka.svg").write_text(designplus.curve_svg(c), encoding="utf-8")
    (d / "editor.html").write_text(designplus.curve_editor_html(c), encoding="utf-8")
    extra = (" s přešvihem (zhoupne se přes cíl)" if info["overshoot"] else "") + (" s nápřahem" if info["anticipation"] else "")
    return ToolResult(True, f"{info['css']}: {info['kind']}{extra}; nejpodobnější je {info['closest']}. Editor s úchyty je v příloze.",
                      data=info, attachments=[str(d / "editor.html"), str(d / "krivka.svg")])


@tool("glass_material", "Skleněný materiál (glassmorphism, „liquid glass“) jako CSS: barva, průhlednost, rozmazání, světlá hrana – "
      "a hlídá, aby text byl čitelný na tmavém i světlém pozadí (případně zvýší neprůhlednost).", category="design")
async def glass_material(ctx, tint: str = "#ffffff", opacity: float = 0.18, blur: int = 18,
                         backgrounds: Annotated[list[str], "barvy pozadí, na kterých panel bude"] | None = None) -> ToolResult:
    from .. import designplus

    try:
        g = designplus.glass(tint, opacity, blur, backgrounds)
    except (ValueError, KeyError) as e:
        return ToolResult(False, f"Barvu nerozumím: {e}")
    d = _out("sklo")
    (d / "glass.css").write_text(g["css"], encoding="utf-8")
    (d / "nahled.html").write_text(designplus.glass_preview(g), encoding="utf-8")
    msg = f"Sklo s neprůhledností {g['opacity']:g}, rozmazání {blur} px; nejhorší kontrast textu {g['worst_contrast']}:1"
    msg += (" – neprůhlednost jsem zvýšil kvůli čitelnosti." if g["raised"] else ".") + ("" if g["ok"] else " Ani tak text nesplní AA – změň barvu textu nebo odstín.")
    return ToolResult(True, msg, data={k: v for k, v in g.items()}, attachments=[str(d / "nahled.html"), str(d / "glass.css")])


@tool("icon_set", "Z volných ikon SVG ve složce udělá jednotnou sadu: jeden sprite, barvy převedené na currentColor, CSS a "
      "náhled – a upozorní na různé velikosti plátna, tloušťky čar a míchání obrysových a vyplněných ikon.", category="design", perm="files_read")
async def icon_set(ctx, folder: str) -> ToolResult:
    from .. import designplus

    d = resolve(folder)
    files = sorted(d.glob("*.svg")) if d.is_dir() else []
    if not files:
        return ToolResult(False, f"Ve složce {d} nejsou soubory .svg.")
    try:
        r = await asyncio.to_thread(designplus.build_icon_set, files)
    except ValueError as e:
        return ToolResult(False, str(e))
    out = _out("ikony")
    (out / "icons.svg").write_text(r["sprite"], encoding="utf-8")
    (out / "icons.css").write_text(r["css"], encoding="utf-8")
    (out / "nahled.html").write_text(r["preview"], encoding="utf-8")
    msg = f"Sada {r['count']} ikon (použití: <svg class=\"icon\"><use href=\"icons.svg#i-název\"/></svg>)."
    if r["recolored"]:
        msg += f" Pevné barvy převedeny na currentColor u {len(r['recolored'])} ikon."
    if r["report"]:
        msg += " Nejednotnosti: " + "; ".join(r["report"][:5]) + "."
    return ToolResult(True, msg, data={k: v for k, v in r.items() if k in ("count", "names", "report", "recolored")},
                      attachments=[str(out / "nahled.html"), str(out / "icons.svg"), str(out / "icons.css")])


@tool("motion_timeline", "Časová osa animace z popisu po řádcích („logo: opacity 0→1 0–0.5s ease-out“): zkontroluje překryvy "
      "a skoky, vytvoří CSS @keyframes, náhled a přehled vrstev v čase.", category="design")
async def motion_timeline(ctx, spec: str) -> ToolResult:
    from .. import designplus

    try:
        tracks = designplus.parse_timeline(spec)
    except ValueError as e:
        return ToolResult(False, str(e))
    issues = designplus.timeline_check(tracks)
    r = designplus.timeline_css(tracks)
    d = _out("casova-osa")
    (d / "animace.css").write_text(r["css"], encoding="utf-8")
    (d / "nahled.html").write_text(r["preview"], encoding="utf-8")
    msg = f"{len(r['layers'])} vrstev, {len(tracks)} animací, celkem {r['duration']:g} s."
    msg += (" Pozor: " + "; ".join(issues) + "." if issues else " Bez překryvů a skoků.")
    return ToolResult(True, msg, data={"issues": issues, "layers": r["layers"], "duration": r["duration"]},
                      attachments=[str(d / "nahled.html"), str(d / "animace.css")])


@tool("layout_heatmap", "Teplotní mapa rozložení obrazovky / návrhu: kde je UI přeplněné a kde dýchá, kolik je volného místa a "
      "jestli je vizuální váha vyvážená. Ze snímku nebo aktuální obrazovky.", category="design", perm="files_read")
async def layout_heatmap(ctx, image: Annotated[str, "obrázek (prázdné = aktuální obrazovka)"] = "") -> ToolResult:
    import io

    from PIL import Image

    from .. import designplus

    if image:
        p = resolve(image)
        if not p.is_file():
            return ToolResult(False, f"Soubor neexistuje: {p}")
        img = Image.open(p)
    else:
        try:
            img = Image.open(io.BytesIO(await asyncio.to_thread(ctx.platform.screenshot)))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"Snímek obrazovky nejde pořídit: {type(e).__name__}")
    r = await asyncio.to_thread(designplus.layout_heatmap, img)
    out = _out("heatmapa") / "heatmapa.png"
    r.pop("image").save(out)
    return ToolResult(True, f"Volné místo {round(r['empty_share'] * 100)} %, {r['balance']}."
                            + (" " + "; ".join(r["advice"]).capitalize() + "." if r["advice"] else ""), data=r, attachments=[str(out)])
