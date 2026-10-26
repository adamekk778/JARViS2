"""OMEGA wave 16 by voice: engineering and science – calculations with units and formula dimension checks,
electronics, power consumption, statistics with quality warnings, A/B tests, frequency analysis, cleaning a CSV
dataset, tolerance stack-ups, checking a 3D model before printing, and an experiment logbook."""
from __future__ import annotations

import asyncio
import struct
from typing import Annotated

from .base import ToolResult, tool
from .files import resolve


def _n(x: float, digits: int = 4) -> str:
    if x == 0 or (1e-3 <= abs(x) < 1e7):
        return f"{round(x, digits):g}".replace(".", ",")
    return f"{x:.{digits}g}".replace(".", ",")


def _numbers(text: str) -> list[float]:
    import re

    return [float(x.replace(",", ".")) for x in re.findall(r"-?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?", text)]


@tool("unit_calc", "Výpočet s fyzikálními jednotkami a převody: „5 km / 2 h na m/s“, „3 kW * 2 h v kWh“, „20 °C na °F“, "
      "„60 km/h na m/s“. Pohlídá, že jednotky k sobě sedí.", category="věda")
async def unit_calc(ctx, expression: str) -> ToolResult:
    from .. import science

    try:
        r = science.calc(expression)
    except (ValueError, ZeroDivisionError, SyntaxError) as e:
        return ToolResult(False, f"Nejde spočítat: {e}")
    return ToolResult(True, f"{_n(r['value'], 6)} {r['unit']}".strip(), data=r)


@tool("check_formula_units", "Kontrola rozměrů vzorce: sedí jednotky na obou stranách? Např. vzorec „E = m * v^2 / 2“ s "
      "jednotkami {\"E\": \"J\", \"m\": \"kg\", \"v\": \"m/s\"}.", category="věda")
async def check_formula_units(ctx, formula: str, units: Annotated[dict[str, str], "proměnná → jednotka"]) -> ToolResult:
    from .. import science

    r = science.check_formula(formula, units)
    if r["error"]:
        return ToolResult(False, f"Vzorec nejde vyhodnotit: {r['error']}", data=r)
    if r["ok"]:
        return ToolResult(True, f"Rozměry sedí: obě strany jsou {r['left']}.", data=r)
    return ToolResult(True, f"Rozměry NESEDÍ: vlevo {r['left']}, vpravo {r['right']} – ve vzorci je chyba.", data=r)


@tool("circuit_calc", "Elektronika: Ohmův zákon (dvě ze čtyř: napětí V, proud I v A, odpor R, výkon P), odpor pro LED, dělič "
      "napětí z řady E12, sériové/paralelní odpory, RC článek, barevné proužky odporu, výdrž baterie.", category="věda")
async def circuit_calc(ctx, task: Annotated[str, "ohm | led | divider | series | parallel | rc | colors | bands | battery"],
                       V: float | None = None, I: float | None = None, R: float | None = None, P: float | None = None,  # noqa: E741
                       supply_v: float = 0, led_v: float = 2.0, current_ma: float = 20, leds: int = 1, vout: float | None = None,
                       r1: float | None = None, r2: float | None = None, values: list[float] | None = None, C: float = 0,
                       colors: list[str] | None = None, capacity_mah: float = 0, load_ma: float = 0, sleep_ma: float = 0,
                       duty: float = 1.0) -> ToolResult:
    from .. import science as s

    try:
        t = task.lower().strip()
        if t == "ohm":
            r = s.ohm(V, I, R, P)
            return ToolResult(True, f"U = {_n(r['V'])} V, I = {_n(r['I'])} A, R = {s.fmt_ohm(r['R'])}, P = {_n(r['P'])} W.", data=r)
        if t == "led":
            r = s.led_resistor(supply_v or V or 0, led_v, current_ma, leds)
            return ToolResult(True, f"Odpor {s.fmt_ohm(r['standard_ohm'])} (přesně {_n(r['exact_ohm'])} Ω), proud {_n(r['current_ma'])} mA, "
                                    f"ztráta {_n(r['power_w'])} W → stačí odpor na {r['rating_w']} W.", data=r)
        if t == "divider":
            r = s.divider(supply_v or V or 0, vout, r1, r2)
            return ToolResult(True, f"R1 = {s.fmt_ohm(r['r1'])}, R2 = {s.fmt_ohm(r['r2'])} → {_n(r['vout'])} V"
                                    + (f" (odchylka {r['error_pct']} %)" if "error_pct" in r else "") + f", proud {_n(r['current_ma'])} mA.", data=r)
        if t in ("series", "parallel", "serie", "paralelne"):
            if not values or len(values) < 2:
                return ToolResult(False, "Zadej aspoň dva odpory (values).")
            v = s.combine(values, "parallel" if t.startswith("par") else "series")
            return ToolResult(True, f"{'Paralelně' if t.startswith('par') else 'Sériově'}: {s.fmt_ohm(v)}.", data={"ohm": v})
        if t == "rc":
            r = s.rc(R or 0, C)
            return ToolResult(True, f"Časová konstanta τ = {_n(r['tau_s'])} s (nabití na 99 % za {_n(r['t_99'])} s), mezní kmitočet {_n(r['cutoff_hz'])} Hz.", data=r)
        if t == "colors":
            r = s.color_code(colors or [])
            return ToolResult(True, f"{r['text']} ± {r['tolerance_pct']} %.", data=r)
        if t == "bands":
            b = s.bands_for(R or 0)
            return ToolResult(True, f"{s.fmt_ohm(s.nearest_e(R or 0, s.E24))}: " + " – ".join(b) + ".", data={"bands": b})
        if t == "battery":
            r = s.battery_life(capacity_mah, load_ma, sleep_ma=sleep_ma, duty=duty)
            return ToolResult(True, f"Průměrný odběr {_n(r['avg_ma'])} mA → asi {_n(r['hours'])} h ({_n(r['days'])} dní).", data=r)
    except (ValueError, ZeroDivisionError, TypeError) as e:
        return ToolResult(False, f"Nejde spočítat: {e}")
    return ToolResult(False, "Úloha: ohm, led, divider, series, parallel, rc, colors, bands nebo battery.")


@tool("power_cost", "Spotřeba elektřiny a kolik stojí: spotřebiče s příkonem (W), hodinami denně a pohotovostí → kWh a Kč za "
      "měsíc a rok, i kolik stojí jen standby.", category="věda")
async def power_cost(ctx, devices: Annotated[list[dict], "[{name, watts, hours, standby_w}]"], price_kwh: float = 6.0) -> ToolResult:
    from .. import science

    if not devices:
        return ToolResult(False, "Zadej aspoň jeden spotřebič.")
    try:
        r = science.power_cost(devices, price_kwh)
    except (ValueError, TypeError) as e:
        return ToolResult(False, str(e))
    top = "; ".join(f"{d['name']} {_n(d['kwh_year'], 1)} kWh = {d['cost_year']} Kč/rok" for d in r["devices"][:5])
    sb = sum(d["standby_cost_year"] for d in r["devices"])
    return ToolResult(True, f"Celkem {_n(r['kwh_month'], 1)} kWh měsíčně ≈ {r['cost_month']} Kč (rok {r['cost_year']} Kč při {_n(price_kwh)} Kč/kWh). {top}."
                      + (f" Jen pohotovost stojí {sb} Kč ročně." if sb else ""), data=r)


@tool("compare_groups", "Porovná dvě skupiny čísel (např. časy před a po, výsledky dvou variant): Welchův t-test i "
      "Mann–Whitney, velikost efektu, interval spolehlivosti – a upozorní na malý vzorek, odlehlé hodnoty nebo nenormální data.",
      category="věda")
async def compare_groups(ctx, a: list[float] | str, b: list[float] | str, alpha: float = 0.05) -> ToolResult:
    from .. import science

    xa = a if isinstance(a, list) else _numbers(a)
    xb = b if isinstance(b, list) else _numbers(b)
    try:
        r = science.compare_groups([float(x) for x in xa], [float(x) for x in xb], alpha)
    except (ValueError, ZeroDivisionError) as e:
        return ToolResult(False, str(e))
    verdict = "rozdíl JE statisticky významný" if r["significant"] else "rozdíl není prokázaný"
    msg = (f"Průměr A {_n(r['a']['mean'])}, B {_n(r['b']['mean'])} (rozdíl {_n(r['diff'])}, 95% interval {_n(r['ci'][0])} až {_n(r['ci'][1])}); "
           f"{verdict} (Welch p = {_n(r['p_welch'], 3)}, Mann–Whitney p = {_n(r['p_mann_whitney'], 3)}), efekt {r['effect']} (d = {_n(r['cohen_d'], 2)}).")
    if r["warnings"]:
        msg += " Pozor: " + "; ".join(r["warnings"]) + "."
    return ToolResult(True, msg, data=r)


@tool("ab_test", "A/B test: buď kolik návštěv potřebuješ (výchozí konverze %, nejmenší změna, kterou chceš poznat, denní "
      "návštěvnost), nebo vyhodnocení výsledků (konverze a návštěvy obou variant) včetně kontroly rozbitého rozdělení (SRM).",
      category="věda")
async def ab_test(ctx, baseline_pct: float = 0, min_change_pct: float = 0, daily_visitors: int = 0,
                  conv_a: int = 0, visits_a: int = 0, conv_b: int = 0, visits_b: int = 0, alpha: float = 0.05, power: float = 0.8) -> ToolResult:
    from .. import science

    try:
        if visits_a and visits_b:
            r = science.ab_analyze(conv_a, visits_a, conv_b, visits_b, alpha)
            msg = (f"A {_n(100 * r['rate_a'], 3)} %, B {_n(100 * r['rate_b'], 3)} % (změna {_n(r['lift_pct'], 3)} %), p = {_n(r['p_value'], 3)} → "
                   + ("B je PROKAZATELNĚ jiná." if r["significant"] else "rozdíl zatím není prokázaný."))
            if r["warnings"]:
                msg += " Pozor: " + "; ".join(r["warnings"]) + "."
            return ToolResult(True, msg, data=r)
        r = science.ab_sample_size(baseline_pct, min_change_pct, alpha, power)
        msg = f"Potřebuješ {r['per_variant']:,} návštěv na variantu ({r['total']:,} celkem)".replace(",", " ")
        if daily_visitors:
            days = -(-r["total"] // daily_visitors)
            r["days"] = days
            msg += f" – při {daily_visitors} návštěvách denně asi {days} dní (nech běžet aspoň celé týdny)"
        return ToolResult(True, msg + ".", data=r)
    except (ValueError, ZeroDivisionError) as e:
        return ToolResult(False, str(e))


@tool("frequency_analysis", "Frekvenční analýza signálu: zvuk WAV nebo sloupec čísel v CSV (se vzorkovací frekvencí) → "
      "hlavní frekvence, jejich síla, stejnosměrná složka a RMS.", category="věda", perm="files_read")
async def frequency_analysis(ctx, file: str, sample_rate: float = 0, column: str = "", peaks: int = 5) -> ToolResult:
    from .. import science

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    try:
        if p.suffix.lower() == ".wav":
            xs, rate = await asyncio.to_thread(science.read_wav, p)
        else:
            if not sample_rate:
                return ToolResult(False, "U CSV zadej vzorkovací frekvenci (sample_rate v Hz).")
            header, rows, _, _ = science.read_csv(p)
            idx = header.index(column) if column in header else next((i for i in range(len(header)) if science._num(rows[0][i]) is not None), None) if rows else None
            if idx is None:
                return ToolResult(False, "V CSV nevidím číselný sloupec.")
            xs = [v for v in (science._num(r[idx]) for r in rows if idx < len(r)) if v is not None]
            rate = sample_rate
        r = await asyncio.to_thread(science.spectrum, xs, rate, max(1, min(peaks, 20)))
    except (ValueError, EOFError) as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001 – a broken WAV
        return ToolResult(False, f"Soubor nejde přečíst: {e}")
    return ToolResult(True, f"{r['samples']} vzorků ({_n(r['seconds'])} s při {_n(r['rate'])} Hz, rozlišení {_n(r['resolution_hz'])} Hz). "
                      f"Hlavní frekvence {_n(r['dominant_hz'])} Hz; další: " + ", ".join(f"{_n(x['hz'])} Hz ({x['db']} dB)" for x in r["peaks"][1:]) +
                      f". RMS {_n(r['rms'])}, DC {_n(r['dc'])}.", data=r)


@tool("dataset_check", "Kontrola tabulky dat (CSV): duplicity, prázdné hodnoty, mezery navíc, čísla s desetinnou čárkou nebo "
      "jako text, různé formáty data, různě napsané stejné kategorie, odlehlé hodnoty.", category="věda", perm="files_read")
async def dataset_check(ctx, file: str) -> ToolResult:
    from .. import science

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    try:
        r = await asyncio.to_thread(science.profile_csv, p)
    except (ValueError, UnicodeDecodeError) as e:
        return ToolResult(False, str(e))
    issues = []
    if r["duplicates"]:
        issues.append(f"{r['duplicates']} duplicitních řádků")
    if r["ragged_rows"]:
        issues.append(f"{r['ragged_rows']} řádků má jiný počet sloupců")
    for c in r["cols"]:
        bits = []
        if c["empty"]:
            bits.append(f"{c['empty']} prázdných")
        if c["spaces"]:
            bits.append(f"{c['spaces']}× mezery navíc")
        if c.get("comma_decimal"):
            bits.append(f"{c['comma_decimal']}× desetinná čárka")
        if c.get("not_number"):
            bits.append("text místo čísla: " + ", ".join(c["not_number"][:3]))
        if c.get("date_formats") and len(c["date_formats"]) > 1:
            bits.append("různé formáty data")
        if c.get("variants"):
            bits.append("různě napsané: " + "; ".join("/".join(g) for g in list(c["variants"].values())[:2]))
        if c.get("outliers"):
            bits.append("odlehlé: " + ", ".join(_n(x) for x in c["outliers"][:3]))
        if bits:
            issues.append(f"{c['name']} ({c['type']}): " + ", ".join(bits))
    head = f"{r['rows']} řádků × {r['columns']} sloupců"
    return ToolResult(True, head + (". " + " | ".join(issues[:10]) + "." if issues else ". Data vypadají čistě."), data=r)


@tool("dataset_clean", "Vyčistí tabulku dat (CSV) do NOVÉHO souboru: odstraní mezery navíc a duplicity, sjednotí čísla "
      "(tečka), data (RRRR-MM-DD) a různě napsané kategorie. Originál zůstane.", category="věda", perm="files_write")
async def dataset_clean(ctx, file: str, target: str = "") -> ToolResult:
    from .. import science

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    dest = resolve(target) if target else p.with_name(p.stem + "_ciste" + p.suffix)
    try:
        r = await asyncio.to_thread(science.clean_csv, p, dest)
    except ValueError as e:
        return ToolResult(False, str(e))
    after = await asyncio.to_thread(science.profile_csv, dest)
    r["after_duplicates"] = after["duplicates"]
    ch = ", ".join(f"{k} {v}" for k, v in r["changes"].items()) or "nic"
    return ToolResult(True, f"Uloženo {r['path']}: {r['rows_before']} → {r['rows_after']} řádků; opraveno: {ch}. Kontrola: duplicit {after['duplicates']}.", data=r)


@tool("tolerance_stackup", "Řetězec tolerancí (sestava dílů): nominální vůle, nejhorší případ a statisticky (RSS), které "
      "díly přispívají nejvíc a jestli se vejde do požadované vůle.", category="věda")
async def tolerance_stackup(ctx, dims: Annotated[list[dict], "[{name, nominal, plus, minus, dir: +1/−1}] v mm"],
                            gap_min: float | None = None, gap_max: float | None = None) -> ToolResult:
    from .. import science

    try:
        r = science.stackup([{**d, "plus": float(d.get("plus", 0)), "minus": float(d.get("minus", 0)), "nominal": float(d["nominal"])} for d in dims],
                            gap_min, gap_max)
    except (KeyError, ValueError, TypeError) as e:
        return ToolResult(False, f"Rozměry zadej jako name, nominal, plus, minus, dir: {e}")
    msg = (f"Nominálně {_n(r['nominal'])} mm; nejhorší případ {_n(r['worst_min'])} až {_n(r['worst_max'])} mm; statisticky {_n(r['rss_min'])} až "
           f"{_n(r['rss_max'])} mm. Nejvíc přispívá {r['contributors'][0]['name']} ({r['contributors'][0]['share_pct']} %).")
    if "worst_ok" in r:
        msg += " Požadavek: " + ("splněn i v nejhorším případě." if r["worst_ok"] else "statisticky splněn, v nejhorším případě NE." if r["rss_ok"] else "NESPLNĚN.")
    return ToolResult(True, msg, data=r)


@tool("check_3d_model", "Kontrola 3D modelu (STL) před tiskem: rozměry, objem, uzavřenost, otočené normály, převisy (podpěry), "
      "jestli se vejde na tiskárnu, odhad filamentu v gramech a metrech.", category="věda", perm="files_read")
async def check_3d_model(ctx, file: str, printer_mm: Annotated[list[float] | None, "tisková plocha x, y, z"] = None,
                         infill_pct: float = 20) -> ToolResult:
    from .. import science

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    try:
        r = await asyncio.to_thread(science.inspect_stl, p, tuple(printer_mm or (220, 220, 250)), infill_pct)
    except (ValueError, struct.error) as e:
        return ToolResult(False, str(e))
    sz = " × ".join(_n(x, 1) for x in r["size_mm"])
    msg = f"{sz} mm, objem {_n(r['volume_cm3'], 1)} cm³, {r['triangles']} trojúhelníků; filament asi {_n(r['filament_g'], 0)} g ({_n(r['filament_m_175'], 1)} m při 1,75 mm)."
    msg += " Připraveno k tisku." if r["printable"] else " Problémy: " + "; ".join(r["problems"]) + "."
    return ToolResult(True, msg, data=r)


@tool("experiment_log", "Deník experimentů: zapíše nový pokus (název, hypotéza, parametry, projekt, štítky).", category="věda")
async def experiment_log(ctx, title: str, hypothesis: str = "", params: dict | None = None, project: str = "", tags: str = "") -> ToolResult:
    from .. import science

    r = science.exp_add(ctx, title, hypothesis, params, project, tags)
    return ToolResult(True, f"Experiment č. {r['id']} „{title}“ zapsán" + (f" (hypotéza: {hypothesis})" if hypothesis else "") + ".", data=r)


@tool("experiment_result", "Zapíše výsledek experimentu a závěr – potvrzeno / vyvráceno.", category="věda")
async def experiment_result(ctx, experiment_id: int, result: str, conclusion: str = "", confirmed: bool | None = None) -> ToolResult:
    from .. import science

    try:
        r = science.exp_result(ctx, experiment_id, result, conclusion, confirmed)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Experiment č. {experiment_id} „{r['title']}“: {r['status']}.", data=r)


@tool("experiments", "Najde experimenty v deníku (podle slova, projektu) – hypotézy, parametry, výsledky.", category="věda")
async def experiments(ctx, query: str = "", project: str = "") -> ToolResult:
    from .. import science

    rows = science.exp_list(ctx, query, project)
    if not rows:
        return ToolResult(True, "V deníku nic takového není.", data=[])
    return ToolResult(True, "; ".join(f"č. {r['id']} {r['title']} – {r['status']}" + (f": {r['result'][:60]}" if r["result"] else "") for r in rows[:10]) + ".",
                      data=rows)
