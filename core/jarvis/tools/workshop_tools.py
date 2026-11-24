"""3.15 Dílna (sekce C): text → CAD s úpravami hlasem, 3D model v HUD, 3D tiskárna s hlídáním, deník projektů, simulace."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool


async def _attach(ctx, path: Path, mime: str) -> list[str]:
    store = getattr(ctx, "store", None)
    if not store or not path.exists():
        return []
    att = await store.save(path.name, path.read_bytes(), mime, conv_id=ctx.memory.current_conversation)
    return [att.id]


async def _svg(ctx, name: str, svg: str) -> list[str]:
    out = paths.sub("grafy") / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.svg"
    out.write_text(svg, encoding="utf-8")
    return await _attach(ctx, out, "image/svg+xml")


# ------------------------------------------------------------------------------------------ text → CAD
async def _publish_part(ctx, part: dict, summary: str) -> ToolResult:
    import asyncio

    from .. import cad, models3d

    files = await asyncio.to_thread(cad.export, ctx, part)
    info = await asyncio.to_thread(models3d.add, Path(files["stl"]), part["name"])
    if "error" not in info:
        models3d.show(ctx, info)
    s = files["size_mm"]
    note = "" if files["exact"] else (f" Náhled má hrany zaoblené asi o {files['step_mm'] / 2:.1f} mm – přesný tvar je v .scad "
                                      "(s OpenSCADem udělám i přesné STL).")
    text = (f"{summary} Rozměry {s[0]:g}×{s[1]:g}×{s[2]:g} mm, asi {files['volume_cm3']:g} cm³ (≈ {files['grams_pla']:g} g PLA), "
            f"verze {part['version']}.{note}")
    atts = await _attach(ctx, Path(files["scad"]), "text/plain") + await _attach(ctx, Path(files["stl"]), "model/stl")
    return ToolResult(True, text, data={"part": part["name"], "template": part["template"], "params": part["params"],
                                        "version": part["version"], **{k: v for k, v in files.items() if k not in ("scad", "stl")}},
                      attachments=atts)


@tool("cad_part", "Text → 3D model (CAD) s úpravami hlasem: navrhne díl podle popisu (krabička, L-držák, deska s dírami, distanční "
      "sloupek, háček, knoflík) s rozměry z věty, ukáže ho v HUD jako hologram a dá OpenSCAD + STL k tisku. Pak jde měnit slovy: "
      "„o 5 mm širší“, „stěna 3 mm“, „díry na M4“, „6 děr“, „o 10 % větší“, „bez víka“; „vrať to“ = předchozí verze. "
      "Cokoli jiného (váza, držák na kolo, figurka…) navrhne AI z popisu a dá se stejně upravovat. "
      "Akce: create / design / edit / undo / show / list / history.", category="dílna")
async def cad_part(ctx, action: Annotated[str, "create / design / edit / undo / show / list / history"] = "create",
                   description: Annotated[str, "popis dílu nebo změny česky, např. „L-držák 40 mm široký na šrouby M4“ / „o 5 mm vyšší“"] = "",
                   name: Annotated[str, "jméno dílu (prázdné = ten poslední)"] = "",
                   template: Annotated[str, "box / bracket / plate / spacer / hook / knob (prázdné = podle popisu)"] = "",
                   project: Annotated[str, "projekt v deníku dílny (volitelně)"] = "") -> ToolResult:
    from .. import cad

    a = (action or "create").strip().lower()
    if a == "list":
        ps = cad.parts(ctx)
        if not ps:
            return ToolResult(True, "Zatím žádné díly. Řekni třeba „navrhni krabičku 60 × 40 × 25 mm“.")
        return ToolResult(True, "Díly: " + "; ".join(cad.describe(p) for p in ps[:10]) + ".", data={"parts": ps[:30]})
    if a == "design" or (a == "create" and not template.strip() and cad.match_template(description) is None and description.strip()):
        try:                                       # 3.17 any shape from the words: the AI designs, JARVIS checks and makes it
            nm, tree = await cad.design(ctx, description)
        except ValueError as e:
            return ToolResult(False, f"Tenhle díl se mi nepodařilo navrhnout: {e}. Zkus ho popsat jinak nebo jednodušeji.")
        part = cad.save(ctx, name.strip() or nm, "free", {"tree": tree}, "navrženo z popisu: " + description[:200], project)
        return await _publish_part(ctx, part, f"Navrhl jsem „{part['name']}“ podle popisu.")
    if a == "create":
        tpl = template.strip().lower() if template.strip().lower() in cad.TEMPLATES else cad.guess_template(description)
        params = dict(cad.TEMPLATES[tpl]["params"])
        params, changes = cad.parse_edit(description, tpl, params)
        nm = name.strip() or f"{cad.TEMPLATES[tpl]['label'].split(' /')[0].capitalize()} {time.strftime('%H%M')}"
        why = cad.check(tpl, params)
        if why:
            return ToolResult(False, f"Takhle by to nešlo: {why}.")
        part = cad.save(ctx, nm, tpl, params, "vytvořeno: " + description[:200], project)
        if project:
            from .. import workbench

            p = workbench.find(ctx, project) or workbench.create(ctx, project)
            workbench.add_entry(ctx, p, "cad", f"Nový díl {nm} ({cad.TEMPLATES[tpl]['label']})")
        return await _publish_part(ctx, part, f"Navrhl jsem {cad.TEMPLATES[tpl]['label']} „{nm}“"
                                   + (f" ({', '.join(changes)})." if changes else " (výchozí rozměry – řekni, co změnit)."))
    part = cad.get(ctx, name) if name.strip() else cad.latest(ctx)
    if not part:
        return ToolResult(False, "Ten díl neznám. Řekni „ukaž moje díly“, nebo nejdřív nějaký navrhni.")
    if a == "history":
        h = cad.history(ctx, part["name"])
        return ToolResult(True, f"{part['name']}: " + "; ".join(f"v{x['version']} {x['change']}" for x in h[-10:]) + ".",
                          data={"history": h})
    if a == "undo":
        back = cad.undo(ctx, part["name"])
        if not back:
            return ToolResult(False, "Není kam se vrátit – tohle je první verze.")
        return await _publish_part(ctx, back, f"Vráceno: {cad.describe(back)}.")
    if a == "show":
        return await _publish_part(ctx, part, f"{cad.describe(part)}.")
    if a == "edit" and part["template"] == "free":
        try:                                       # 3.17 a free-form part: the AI changes its own tree
            nm, tree = await cad.design(ctx, "", {"name": part["name"], "tree": part["params"]["tree"]}, description)
        except ValueError as e:
            return ToolResult(False, f"Tuhle změnu se nepodařilo udělat: {e}. Díl jsem nechal, jak byl.")
        new = cad.save(ctx, part["name"], "free", {"tree": tree}, description[:200])
        return await _publish_part(ctx, new, f"Upraveno: {description.strip()[:80]}.")
    if a == "edit":
        params, changes = cad.parse_edit(description, part["template"], part["params"])
        if not changes:
            keys = ", ".join(cad.PARAM_LABEL.get(k, k) for k in cad.TEMPLATES[part["template"]]["params"])
            return ToolResult(False, f"Nerozuměl jsem, co změnit. U {cad.TEMPLATES[part['template']]['label']} jde měnit: {keys} "
                                     "(např. „o 5 mm širší“, „stěna 3 mm“).")
        why = cad.check(part["template"], params)
        if why:
            return ToolResult(False, f"Tohle ne: {why}. Díl jsem nechal, jak byl.")
        new = cad.save(ctx, part["name"], part["template"], params, ", ".join(changes))
        return await _publish_part(ctx, new, f"Hotovo: {', '.join(changes)}.")
    return ToolResult(False, "Umím create, edit, undo, show, list a history.")


@tool("model_view", "Ukáže 3D model (STL, OBJ, GLB, 3MF, STEP) v HUD jako hologram: točí se, jde přiblížit gesty i hlasem a "
      "rozložit na díly (rozložený pohled sestavy). STEP převede FreeCAD, jinak ho HUD přečte sám.", category="dílna", perm="files_read")
async def model_view(ctx, path: Annotated[str, "cesta k souboru modelu"], explode: Annotated[bool, "rovnou rozložit na díly"] = False) -> ToolResult:
    import asyncio

    from .. import models3d

    info = await asyncio.to_thread(models3d.add, Path(path), "")
    if "error" in info:
        return ToolResult(False, info["error"])
    models3d.show(ctx, info, explode)
    return ToolResult(True, f"Model {info['title']} je v HUD" + (" rozložený na díly." if explode else
                                                                 ". Rozložíš ho slovy „rozlož model“ nebo zamáváním."),
                      data=info)


@tool("model_explode", "Rozloží / složí 3D model v HUD (rozložený pohled), otočí ho, přiblíží nebo zavře prohlížeč.", category="dílna")
async def model_explode(ctx, action: Annotated[str, "explode / collapse / rotate_left / rotate_right / zoom_in / zoom_out / reset / close"] = "explode") -> ToolResult:
    a = (action or "explode").strip().lower()
    names = {"explode": "rozložen", "collapse": "složen", "rotate_left": "otočen doleva", "rotate_right": "otočen doprava",
             "zoom_in": "přiblížen", "zoom_out": "oddálen", "reset": "vrácen do výchozí polohy", "close": "zavřen"}
    if a not in names:
        return ToolResult(False, "Umím explode, collapse, rotate_left, rotate_right, zoom_in, zoom_out, reset a close.")
    ctx.bus.publish("hud_cmd", action="model_" + a)
    return ToolResult(True, f"Model {names[a]}.")


# ------------------------------------------------------------------------------------------ the 3D printer
def _printer_danger(a: dict) -> bool:
    return str(a.get("action") or "").lower() in ("cancel", "print")


@tool("printer_control", "3D tiskárna (OctoPrint, Klipper/Moonraker, Bambu přes Home Assistant): stav tisku (%, zbývá, teploty), "
      "pauza, pokračovat, zrušit, poslat soubor k tisku (G-code; STL / 3MF nejdřív nakrájí PrusaSlicer s tvým profilem), "
      "fotka z kamery, kontrola tisku AI (špagety, odlepení). Zrušení a nový tisk se vždy ptají.",
      category="dílna", perm="home", danger_if=_printer_danger)
async def printer_control(ctx, action: Annotated[str, "status / pause / resume / cancel / print / snapshot / check"] = "status",
                          file: Annotated[str, "soubor k tisku (.gcode, .stl, .3mf) – jen u print"] = "") -> ToolResult:
    import asyncio

    from .. import printer3d

    a = (action or "status").strip().lower()
    c = ctx.cfg.workshop
    if not printer3d.configured(ctx):
        return ToolResult(False, "Tiskárnu nemám nastavenou – Nastavení → Dílna: typ (OctoPrint / Klipper / Bambu přes Home Assistant) "
                                 "a adresa; klíč API vložíš tamtéž (uloží se do klíčenky).")
    name = c.printer_name or "Tiskárna"
    if a == "status":
        s = await printer3d.status(ctx)
        return ToolResult(s.get("state") != "offline", printer3d.say(s, name), data=s)
    if a in ("pause", "resume", "cancel"):
        err = await printer3d.command(ctx, a)
        if err:
            return ToolResult(False, f"{name}: {err}.")
        return ToolResult(True, {"pause": "Tisk pozastaven.", "resume": "Tisk pokračuje.", "cancel": "Tisk zrušen."}[a])
    if a == "snapshot" or a == "check":
        jpg = await printer3d.snapshot(ctx)
        if not jpg:
            return ToolResult(False, "Z kamery tiskárny nemám obrázek (nastav adresu kamery v Nastavení → Dílna).")
        p = paths.sub("workshop") / "photos" / f"tiskarna-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(jpg)
        atts = await _attach(ctx, p, "image/jpeg")
        if a == "snapshot":
            return ToolResult(True, "Fotka z tiskárny.", attachments=atts)
        v = await printer3d.judge(ctx, jpg)
        text = (f"Vypadá to špatně: {printer3d.KIND_CS.get(v['kind'], v['kind'])}. {v['why']}" if v["fail"]
                else f"Tisk vypadá v pořádku. {v['why']}").strip()
        return ToolResult(True, text, data=v, attachments=atts)
    if a == "print":
        src = Path(file).expanduser()
        if not src.exists():
            return ToolResult(False, f"Soubor {file or '(žádný)'} nenajdu.")
        direct = c.printer == "bambu_lan" and src.suffix.lower() == ".3mf"     # 3.17 a sliced .3mf goes to Bambu as it is
        if src.suffix.lower() in (".stl", ".3mf", ".obj") and not direct:
            gcode, err = await asyncio.to_thread(printer3d.slice_model, src, c.slicer_profile)
            if not gcode:
                return ToolResult(False, f"Nejdřív to musím nakrájet na G-code, ale {err}.")
            src = gcode
        if src.suffix.lower() not in (".gcode", ".bgcode", ".gco", ".g") and not direct:
            return ToolResult(False, "Tisknout jde G-code (nebo STL / 3MF, které nakrájím).")
        err = await printer3d.upload_and_print(ctx, src)
        if err:
            return ToolResult(False, f"{name}: {err}.")
        try:
            from .. import workbench

            workbench.log_active(ctx, "print", f"Tisk spuštěn: {src.name}")
        except Exception:  # noqa: BLE001
            pass
        return ToolResult(True, f"Posláno na {name} a tisk startuje: {src.name}. Budu ho hlídat kamerou.")
    return ToolResult(False, "Umím status, pause, resume, cancel, print, snapshot a check.")


# ------------------------------------------------------------------------------------------ the project journal
@tool("workshop_project", "Deník projektů v dílně: založit projekt (cíl), zapsat poznámku, přidat fotku, změnit stav (nápad / plán / "
      "rozpracováno / čeká na díly / testování / hotovo / odloženo), nová verze, díly s cenami („2× BME280 za 150 Kč, ESP32“), "
      "co mám, co chybí → nákupní seznam „dílna“, přehled a seznam projektů.", category="dílna")
async def workshop_project(ctx, action: Annotated[str, "create / note / photo / status / version / parts / have / missing / shopping / show / list"] = "show",
                           project: Annotated[str, "název projektu (prázdné = aktivní)"] = "",
                           text: Annotated[str, "poznámka / cíl / stav / seznam dílů / co už mám"] = "",
                           path: Annotated[str, "fotka nebo soubor k přiložení (u photo)"] = "") -> ToolResult:
    from .. import workbench

    a = (action or "show").strip().lower()
    if a == "list":
        ps = workbench.projects(ctx)
        if not ps:
            return ToolResult(True, "Zatím žádný projekt. Řekni „založ projekt meteostanice“.")
        return ToolResult(True, "Projekty: " + "; ".join(f"{p['name']} ({p['status']}, v{p['version']})" for p in ps[:12]) + ".",
                          data={"projects": ps})
    if a == "create":
        if not project.strip():
            return ToolResult(False, "Jak se má projekt jmenovat?")
        p = workbench.create(ctx, project, text)
        return ToolResult(True, f"Projekt {p['name']} je založený a aktivní – poznámky, fotky, tisky i díly půjdou do něj.", data=p)
    p = workbench.find(ctx, project)
    if not p:
        return ToolResult(False, f"Projekt {project or '(aktivní)'} nemám. Založ ho: „založ projekt …“.")
    if a == "note":
        if not text.strip():
            return ToolResult(False, "Co mám zapsat?")
        workbench.add_entry(ctx, p, "note", text)
        return ToolResult(True, f"Zapsáno do {p['name']}.")
    if a == "photo":
        src = Path(path).expanduser() if path else None
        if not src or not src.exists():
            return ToolResult(False, "Pošli fotku (z telefonu nebo cestu k souboru).")
        e = workbench.add_entry(ctx, p, "photo", text or "Fotka", src)
        return ToolResult(True, f"Fotka je v deníku projektu {p['name']}.", data=e)
    if a == "status":
        st = workbench.set_status(ctx, p, text)
        if not st:
            return ToolResult(False, "Stav může být: " + ", ".join(workbench.STATUSES) + ".")
        return ToolResult(True, f"{p['name']}: {st}.")
    if a == "version":
        part = "major" if "velk" in text.lower() or "major" in text.lower() else "patch" if "oprav" in text.lower() else "minor"
        v = workbench.new_version(ctx, p, part, text)
        return ToolResult(True, f"{p['name']} je teď ve verzi {v}.")
    if a == "parts":
        items = workbench.parse_parts(text)
        if not items:
            return ToolResult(False, "Napiš díly, třeba „2× BME280 za 150 Kč, ESP32, 3 m kabelu“.")
        have = any(w in text.lower() for w in ("mám", "mam ", "doma"))
        added = workbench.add_parts(ctx, p, items, have=have)
        b = workbench.bom_summary(ctx, p)
        return ToolResult(True, f"Přidáno k {p['name']}: {', '.join(added)}. Celkem {b['parts']} položek"
                                + (f", asi {b['total_czk']} Kč." if b["total_czk"] else "."), data=b)
    if a == "have":
        done = workbench.mark_have(ctx, p, [x for x in text.replace(" a ", ",").split(",") if x.strip()])
        return ToolResult(bool(done), f"Mám: {', '.join(done)}." if done else "Takové díly v projektu nevidím.")
    if a in ("missing", "shopping"):
        miss = workbench.missing(ctx, p)
        if not miss:
            return ToolResult(True, f"Na {p['name']} máš všechno.")
        lines = [f"{workbench._fmt(m['need'])} {m['unit']} {m['part']}".replace(" ks ", "× ") for m in miss]
        if a == "shopping":
            workbench.to_shopping(ctx, p)
            b = workbench.bom_summary(ctx, p)
            return ToolResult(True, f"Na seznam „dílna“ jsem dal: {', '.join(lines)}" + (f" (asi {b['to_buy_czk']} Kč)." if b["to_buy_czk"] else "."))
        return ToolResult(True, f"Na {p['name']} chybí: {', '.join(lines)}.", data={"missing": miss})
    if a == "show":
        o = workbench.overview(ctx, p)
        b = o["bom"]
        last = "; ".join(e["text"] for e in o["last"][:3])
        return ToolResult(True, f"{o['name']} – {o['status']}, verze {o['version']}" + (f", cíl: {o['goal']}" if o["goal"] else "")
                          + f". Záznamů {o['entries']}, fotek {len(o['photos'])}, modelů {len(o['models'])}; díly {b['parts']}"
                          + (f", chybí {b['missing']}" if b["missing"] else "") + (f". Naposledy: {last}." if last else "."), data=o)
    return ToolResult(False, "Umím create, note, photo, status, version, parts, have, missing, shopping, show a list.")


# ------------------------------------------------------------------------------------------ simulations
@tool("simulate", "Simulace v dílně s grafem: nosník (průhyb a moment – konzola / prostý nosník, síla v bodě nebo spojité zatížení, "
      "materiál a průřez), teplo v desce (zdroj tepla na hliníku / mědi / FR4 → teplotní mapa), stejnosměrný obvod ze seznamu "
      "součástek („V1 vcc 0 5; R1 vcc out 10k; R2 out 0 4k7“ → napětí, proudy, výkon) a RC / RL přechod.", category="dílna")
async def simulate(ctx, kind: Annotated[str, "beam / heat / circuit / rc / rl"],
                   length_mm: float = 0, load_n: float = 0, support: Annotated[str, "konzola / prostý nosník"] = "konzola",
                   position_mm: Annotated[float, "kde působí síla (0 = na konci / uprostřed)"] = 0,
                   distributed: Annotated[bool, "spojité zatížení po celé délce"] = False,
                   material: str = "", profile: Annotated[str, "plný čtverec / kruhová trubka / čtvercová trubka"] = "plný čtverec",
                   size_mm: Annotated[float, "velikost průřezu (strana / průměr)"] = 20,
                   width_mm: float = 0, height_mm: float = 0, power_w: float = 0, thickness_mm: float = 2,
                   netlist: Annotated[str, "obvod: „název uzel uzel hodnota“ oddělené ;"] = "",
                   r: Annotated[str, "odpor (např. 10k)"] = "", c_or_l: Annotated[str, "kapacita / indukčnost (např. 100u, 10m)"] = "",
                   supply_v: float = 5) -> ToolResult:
    import asyncio

    from .. import sims

    k = (kind or "").strip().lower()
    try:
        if k == "beam":
            res = sims.beam(length_mm, load_n, support, position_mm or None, distributed, material or "ocel S235", profile, size_mm)
            atts = await _svg(ctx, "nosnik", res["svg"]) + await _svg(ctx, "moment", res["svg_moment"])
            sf = res["safety"]
            verdict = ("vydrží s rezervou" if sf and sf >= 2 else "vydrží, ale bez velké rezervy" if sf and sf >= 1 else "NEVYDRŽÍ – praskne / ohne se trvale")
            return ToolResult(True, f"{res['support'].capitalize()} {length_mm:g} mm, {res['section']}, {res['material']}: průhyb "
                                    f"{res['max_deflection_mm']:g} mm, napětí {res['max_stress_mpa']:g} MPa, bezpečnost {sf} – {verdict}.",
                              data={k2: v for k2, v in res.items() if not k2.startswith("svg")}, attachments=atts)
        if k == "heat":
            res = await asyncio.to_thread(sims.heat_plate, width_mm or 100, height_mm or 60, power_w or 1, None, 10,
                                          material or "hliník", thickness_mm)
            atts = await _svg(ctx, "teplo", res["svg"])
            warn = ""
            if res["max_c"] > 120:
                warn = " To je moc – přidej chladič, větší / tlustší desku nebo ofuk."
            elif res["max_c"] > 80:
                warn = " Na sáhnutí to pálí; elektronika to většinou vydrží, plast (PLA) ne."
            return ToolResult(True, f"Nejteplejší místo {res['max_c']:g} °C (o {res['rise_c']:g} °C nad okolím), průměr {res['mean_c']:g} °C.{warn}",
                              data={k2: v for k2, v in res.items() if k2 != "svg"}, attachments=atts)
        if k == "circuit":
            res = sims.dc(netlist)
            nodes = ", ".join(f"{n} {v:.3g} V".replace(".", ",") for n, v in res["nodes"].items())
            hot = f" Pozor, přehřeje se: {', '.join(res['too_hot'])}." if res["too_hot"] else ""
            return ToolResult(True, f"Napětí v uzlech: {nodes}.{hot}", data=res)
        if k in ("rc", "rl"):
            res = sims.transient(k, sims.value(r), sims.value(c_or_l), supply_v)
            atts = await _svg(ctx, k, res["svg"])
            tau = res["tau_s"]
            tt = f"{tau * 1000:.3g} ms" if tau < 1 else f"{tau:.3g} s"
            return ToolResult(True, f"Časová konstanta τ = {tt}".replace(".", ",") + "; na 63 % za τ, prakticky hotovo (99 %) za 4,6 τ.",
                              data={k2: v for k2, v in res.items() if k2 != "svg"}, attachments=atts)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(False, "Umím beam (nosník), heat (teplo v desce), circuit (obvod), rc a rl.")
