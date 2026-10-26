"""OMEGA §37 / §57 engineering and science: calculations with physical units (and dimension checks of formulas),
electronics (Ohm, LED resistor, divider, RC, colour code, battery life), power consumption and its cost, statistics
with honest quality warnings, A/B test design and evaluation, frequency analysis of signals, cleaning a CSV dataset,
tolerance stack-ups, 3D models for printing (STL) and an experiment logbook."""
from __future__ import annotations

import ast
import csv
import io
import json
import math
import re
import statistics
import struct
import time
import wave
from collections import Counter
from pathlib import Path
from typing import Any

# ============================================================================================== 772 units
DIMS = ("m", "kg", "s", "A", "K", "mol", "cd")


class Q:
    """A value with a dimension vector (m, kg, s, A, K, mol, cd) in SI."""
    __slots__ = ("v", "d")

    def __init__(self, v: float, d: tuple[int, ...] = (0,) * 7):
        self.v, self.d = float(v), tuple(d)

    def _same(self, o: "Q", op: str) -> None:
        if self.d != o.d:
            raise ValueError(f"nesouhlasí rozměry u „{op}“: {fmt_dims(self.d)} a {fmt_dims(o.d)}")

    def __add__(self, o):
        o = q(o)
        self._same(o, "+")
        return Q(self.v + o.v, self.d)

    def __sub__(self, o):
        o = q(o)
        self._same(o, "−")
        return Q(self.v - o.v, self.d)

    def __mul__(self, o):
        o = q(o)
        return Q(self.v * o.v, tuple(a + b for a, b in zip(self.d, o.d)))

    def __truediv__(self, o):
        o = q(o)
        return Q(self.v / o.v, tuple(a - b for a, b in zip(self.d, o.d)))

    def __pow__(self, n):
        n = q(n)
        if any(n.d):
            raise ValueError("exponent musí být bez jednotky")
        if any(x * n.v != int(x * n.v) for x in self.d):
            raise ValueError("neceločíselná mocnina jednotky")
        return Q(self.v ** n.v, tuple(int(x * n.v) for x in self.d))

    def __neg__(self):
        return Q(-self.v, self.d)


def q(x) -> Q:
    return x if isinstance(x, Q) else Q(float(x))


def _u(v, m=0, kg=0, s=0, A=0, K=0, mol=0, cd=0) -> Q:
    return Q(v, (m, kg, s, A, K, mol, cd))


BASE_UNITS: dict[str, Q] = {
    "m": _u(1, m=1), "g": _u(1e-3, kg=1), "s": _u(1, s=1), "A": _u(1, A=1), "K": _u(1, K=1), "mol": _u(1, mol=1), "cd": _u(1, cd=1),
    "N": _u(1, m=1, kg=1, s=-2), "J": _u(1, m=2, kg=1, s=-2), "W": _u(1, m=2, kg=1, s=-3), "Pa": _u(1, m=-1, kg=1, s=-2),
    "V": _u(1, m=2, kg=1, s=-3, A=-1), "Ω": _u(1, m=2, kg=1, s=-3, A=-2), "ohm": _u(1, m=2, kg=1, s=-3, A=-2), "C": _u(1, s=1, A=1),
    "F": _u(1, m=-2, kg=-1, s=4, A=2), "H": _u(1, m=2, kg=1, s=-2, A=-2), "Hz": _u(1, s=-1), "L": _u(1e-3, m=3), "l": _u(1e-3, m=3),
    "Wh": _u(3600, m=2, kg=1, s=-2), "Ah": _u(3600, s=1, A=1), "eV": _u(1.602176634e-19, m=2, kg=1, s=-2), "T": _u(1, kg=1, s=-2, A=-1),
    "bar": _u(1e5, m=-1, kg=1, s=-2), "S": _u(1, m=-2, kg=-1, s=3, A=2), "Wb": _u(1, m=2, kg=1, s=-2, A=-1), "lm": _u(1, cd=1),
}
PLAIN_UNITS: dict[str, Q] = {
    "min": _u(60, s=1), "h": _u(3600, s=1), "d": _u(86400, s=1), "den": _u(86400, s=1), "dní": _u(86400, s=1), "rok": _u(31557600, s=1),
    "t": _u(1000, kg=1), "ha": _u(1e4, m=2), "in": _u(0.0254, m=1), "inch": _u(0.0254, m=1), "ft": _u(0.3048, m=1), "yd": _u(0.9144, m=1),
    "mi": _u(1609.344, m=1), "mile": _u(1609.344, m=1), "nmi": _u(1852, m=1), "lb": _u(0.45359237, kg=1), "oz": _u(0.028349523125, kg=1),
    "psi": _u(6894.757, m=-1, kg=1, s=-2), "atm": _u(101325, m=-1, kg=1, s=-2), "cal": _u(4.184, m=2, kg=1, s=-2), "kcal": _u(4184, m=2, kg=1, s=-2),
    "hp": _u(745.69987, m=2, kg=1, s=-3), "PS": _u(735.49875, m=2, kg=1, s=-3), "kmh": _u(1 / 3.6, m=1, s=-1), "mph": _u(0.44704, m=1, s=-1),
    "kn": _u(1852 / 3600, m=1, s=-1), "gal": _u(3.785411784e-3, m=3), "rad": _u(1), "deg": _u(math.pi / 180), "rpm": _u(1 / 60, s=-1),
    "pct": _u(0.01), "ppm": _u(1e-6), "byte": _u(1), "B": _u(1), "bit": _u(0.125),
}
PREFIX = {"Y": 1e24, "Z": 1e21, "E": 1e18, "P": 1e15, "T": 1e12, "G": 1e9, "M": 1e6, "k": 1e3, "h": 1e2, "da": 1e1, "d": 1e-1,
          "c": 1e-2, "m": 1e-3, "µ": 1e-6, "u": 1e-6, "μ": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
NAMED = {(1, 1, -2, 0, 0, 0, 0): "N", (2, 1, -2, 0, 0, 0, 0): "J", (2, 1, -3, 0, 0, 0, 0): "W", (-1, 1, -2, 0, 0, 0, 0): "Pa",
         (2, 1, -3, -1, 0, 0, 0): "V", (2, 1, -3, -2, 0, 0, 0): "Ω", (0, 0, 1, 1, 0, 0, 0): "C", (0, 0, -1, 0, 0, 0, 0): "Hz",
         (-2, -1, 4, 2, 0, 0, 0): "F", (2, 1, -2, -2, 0, 0, 0): "H", (0, 1, -2, -1, 0, 0, 0): "T"}
SUP = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def unit(name: str) -> Q:
    if name in PLAIN_UNITS:
        return PLAIN_UNITS[name]
    if name in BASE_UNITS:
        return BASE_UNITS[name]
    for p in sorted(PREFIX, key=len, reverse=True):
        if name.startswith(p) and name[len(p):] in BASE_UNITS:
            b = BASE_UNITS[name[len(p):]]
            return Q(b.v * PREFIX[p], b.d)
    raise ValueError(f"neznámá jednotka „{name}“")


def fmt_dims(d: tuple[int, ...]) -> str:
    if not any(d):
        return "bez jednotky"
    if d in NAMED:
        return NAMED[d]
    return "·".join(f"{n}{str(e).translate(SUP) if e != 1 else ''}" for n, e in zip(DIMS, d) if e)


_UNIT_TOKEN = r"[A-Za-zΩµμ°%][A-Za-z0-9Ωµμ°%^·*/_]*(?:\^-?\d+)?"


def _prep_units(expr: str) -> str:
    e = expr.replace("²", "^2").replace("³", "^3").replace("·", "*").replace("×", "*").replace("−", "-").replace("km/h", "kmh")
    e = re.sub(r"(?<=\d),(?=\d)", ".", e)
    e = e.replace("%", "pct")
    # "5 km" → (5*km), "9.81 m/s^2" → (9.81*m/s^2): a number with its unit binds tighter than / between quantities
    e = re.sub(r"(\d(?:[\d.]*)(?:[eE][+-]?\d+)?)\s*(" + _UNIT_TOKEN + ")", lambda m: f"({m.group(1)}*{m.group(2)})", e)
    return e.replace("^", "**")


def evaluate(expr: str) -> Q:
    tree = ast.parse(_prep_units(expr).strip(), mode="eval")
    funcs = {"sqrt": lambda x: x ** 0.5 if isinstance(x, Q) else Q(math.sqrt(x)), "abs": lambda x: Q(abs(x.v), x.d)}
    consts = {"pi": Q(math.pi), "π": Q(math.pi), "e": Q(math.e), "g0": _u(9.80665, m=1, s=-2), "c0": _u(299792458, m=1, s=-1)}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return Q(n.value)
        if isinstance(n, ast.Name):
            return consts.get(n.id) or unit(n.id)
        if isinstance(n, ast.BinOp) and type(n.op) in (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b.v) > 64:
                raise ValueError("příliš velká mocnina")
            return {ast.Add: a.__add__, ast.Sub: a.__sub__, ast.Mult: a.__mul__, ast.Div: a.__truediv__, ast.Pow: a.__pow__}[type(n.op)](b)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in funcs and len(n.args) == 1:
            return funcs[n.func.id](ev(n.args[0]))
        raise ValueError("výraz obsahuje něco, co nejde spočítat")
    return ev(tree)


TEMP = {"°C": (1, 273.15), "C": (1, 273.15), "K": (1, 0), "°F": (5 / 9, 459.67 * 5 / 9), "F": (5 / 9, 459.67 * 5 / 9)}


def calc(text: str) -> dict:
    """„5 km / 2 h na m/s“, „3 kW * 2 h v kWh“, „20 °C na °F“. Without a target unit the result is in SI."""
    m = re.match(r"^\s*(.+?)\s+(?:na|v|to|in|->|→)\s+([^\s].*?)\s*$", text)
    expr, target = (m.group(1), m.group(2)) if m else (text, "")
    tm = re.fullmatch(r"\s*(-?[\d.,]+)\s*(°C|°F|K)\s*", expr)
    if tm and target in TEMP:
        a, off = TEMP[tm.group(2)]
        kelvin = float(tm.group(1).replace(",", ".")) * a + off
        a2, off2 = TEMP[target]
        val = (kelvin - off2) / a2
        return {"value": round(val, 6), "unit": target, "si": round(kelvin, 6), "dims": "K"}
    res = evaluate(expr)
    if target:
        t = evaluate(target)
        if t.d != res.d:
            raise ValueError(f"výsledek má rozměr {fmt_dims(res.d)}, ale „{target}“ je {fmt_dims(t.d)} – nejde převést")
        return {"value": res.v / t.v, "unit": target, "si": res.v, "dims": fmt_dims(res.d)}
    return {"value": res.v, "unit": fmt_dims(res.d) if any(res.d) else "", "si": res.v, "dims": fmt_dims(res.d)}


def check_formula(formula: str, units: dict[str, str]) -> dict:
    """Dimension check: „F = m * a“ with {F: N, m: kg, a: m/s^2} → do both sides have the same dimension?"""
    if "=" not in formula:
        raise ValueError("Vzorec musí mít levou a pravou stranu (=).")
    left, right = formula.split("=", 1)

    names = sorted(units, key=len, reverse=True)
    rx = re.compile(r"(?<![\w])(" + "|".join(map(re.escape, names)) + r")(?![\w])") if names else None

    def side(expr: str) -> Q:
        e = rx.sub(lambda m: f"(1 {units[m.group(1)]})", expr) if rx else expr     # one pass: units are never re-substituted
        return evaluate(e)
    try:
        a = side(left)
        b = side(right)
    except ValueError as e:
        return {"ok": False, "left": "", "right": "", "error": str(e)}
    return {"ok": a.d == b.d, "left": fmt_dims(a.d), "right": fmt_dims(b.d), "error": ""}


# ============================================================================================== 473 / 474 electronics
E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]


def eseries(series: list[float], lo: float = 1, hi: float = 1e7) -> list[float]:
    out, dec = [], 1.0
    while dec <= hi:
        out += [round(v * dec, 6) for v in series if lo <= v * dec <= hi]
        dec *= 10
    return out


def nearest_e(value: float, series=E12, up: bool = False) -> float:
    vals = eseries(series, 0.1, 1e8)
    if up:
        return min((v for v in vals if v >= value * 0.9999), default=vals[-1])
    return min(vals, key=lambda v: abs(math.log(v / value)))


def ohm(V: float | None = None, I: float | None = None, R: float | None = None, P: float | None = None) -> dict:  # noqa: E741
    known = {k: v for k, v in {"V": V, "I": I, "R": R, "P": P}.items() if v is not None}
    if len(known) < 2:
        raise ValueError("Zadej aspoň dvě ze čtyř hodnot (napětí V, proud I, odpor R, výkon P).")
    if V is not None and I is not None:
        R, P = (V / I if I else math.inf), V * I
    elif V is not None and R is not None:
        I = V / R
        P = V * I
    elif V is not None and P is not None:
        I = P / V
        R = V / I if I else math.inf
    elif I is not None and R is not None:
        V = I * R
        P = V * I
    elif I is not None and P is not None:
        V = P / I
        R = V / I
    else:
        I = math.sqrt(P / R)
        V = I * R
    return {"V": V, "I": I, "R": R, "P": P}


def led_resistor(supply_v: float, led_v: float, current_ma: float, leds_in_series: int = 1) -> dict:
    drop = supply_v - led_v * leds_in_series
    if drop <= 0:
        raise ValueError(f"Napájení {supply_v} V nestačí na {leds_in_series}× LED po {led_v} V.")
    r = drop / (current_ma / 1000)
    std = nearest_e(r, E12, up=True)
    i_real = drop / std
    p = drop * i_real
    rating = next(x for x in (0.125, 0.25, 0.5, 1, 2, 5) if x >= p * 2) if p * 2 <= 5 else math.ceil(p * 2)
    return {"exact_ohm": round(r, 1), "standard_ohm": std, "current_ma": round(i_real * 1000, 2), "power_w": round(p, 4), "rating_w": rating}


def divider(vin: float, vout: float | None = None, r1: float | None = None, r2: float | None = None, series=E12) -> dict:
    if r1 and r2:
        return {"vout": vin * r2 / (r1 + r2), "r1": r1, "r2": r2, "current_ma": vin / (r1 + r2) * 1000}
    if vout is None or not 0 < vout < vin:
        raise ValueError("Zadej R1 a R2, nebo požadované výstupní napětí menší než vstupní.")
    best = None
    vals = eseries(series, 1000, 1e6)
    for a in vals:
        for b in vals:
            v = vin * b / (a + b)
            err = abs(v - vout)
            if best is None or err < best[0] - 1e-12:
                best = (err, a, b, v)
    _, a, b, v = best
    return {"vout": round(v, 4), "r1": a, "r2": b, "error_pct": round(100 * abs(v - vout) / vout, 2), "current_ma": round(vin / (a + b) * 1000, 4)}


def combine(values: list[float], mode: str) -> float:
    if mode.startswith(("p", "par")):
        return 1 / sum(1 / v for v in values)
    return sum(values)


def rc(r: float, c: float) -> dict:
    tau = r * c
    return {"tau_s": tau, "cutoff_hz": 1 / (2 * math.pi * tau), "t_63": tau, "t_99": 5 * tau}


COLORS = {"černá": 0, "black": 0, "hnědá": 1, "brown": 1, "červená": 2, "red": 2, "oranžová": 3, "orange": 3, "žlutá": 4, "yellow": 4,
          "zelená": 5, "green": 5, "modrá": 6, "blue": 6, "fialová": 7, "violet": 7, "purple": 7, "šedá": 8, "grey": 8, "gray": 8,
          "bílá": 9, "white": 9, "zlatá": -1, "gold": -1, "stříbrná": -2, "silver": -2}
TOL = {1: 1, 2: 2, 5: 0.5, 6: 0.25, 7: 0.1, 8: 0.05, -1: 5, -2: 10}
CZ_NAMES = ["černá", "hnědá", "červená", "oranžová", "žlutá", "zelená", "modrá", "fialová", "šedá", "bílá"]


def color_code(bands: list[str]) -> dict:
    """4 or 5 coloured bands → value and tolerance."""
    try:
        idx = [COLORS[b.strip().lower()] for b in bands]
    except KeyError as e:
        raise ValueError(f"neznámá barva {e}") from e
    if len(idx) not in (3, 4, 5):
        raise ValueError("Odpor má 3, 4 nebo 5 proužků.")
    digits = idx[:2] if len(idx) <= 4 else idx[:3]
    mult = idx[2] if len(idx) <= 4 else idx[3]
    if any(d < 0 for d in digits):
        raise ValueError("zlatá / stříbrná nemůže být číslice")
    val = int("".join(map(str, digits))) * 10 ** mult
    tol = TOL.get(idx[-1], None) if len(idx) >= 4 else 20
    return {"ohm": round(val, 4), "tolerance_pct": tol, "text": fmt_ohm(val)}


def bands_for(ohms: float) -> list[str]:
    std = nearest_e(ohms, E24)
    exp = math.floor(math.log10(std)) - 1
    digits = round(std / 10 ** exp)
    if digits >= 100:
        digits //= 10
        exp += 1
    return [CZ_NAMES[digits // 10], CZ_NAMES[digits % 10], CZ_NAMES[exp] if exp >= 0 else ("zlatá" if exp == -1 else "stříbrná"), "zlatá"]


def fmt_ohm(v: float) -> str:
    for lim, suf in ((1e6, "MΩ"), (1e3, "kΩ")):
        if v >= lim:
            return f"{v / lim:g} {suf}"
    return f"{v:g} Ω"


def battery_life(capacity_mah: float, load_ma: float, efficiency: float = 0.85, sleep_ma: float = 0, duty: float = 1.0) -> dict:
    avg = load_ma * duty + sleep_ma * (1 - duty)
    if avg <= 0:
        raise ValueError("Odběr musí být větší než 0.")
    h = capacity_mah * efficiency / avg
    return {"avg_ma": round(avg, 4), "hours": round(h, 1), "days": round(h / 24, 1)}


def power_cost(devices: list[dict], price_kwh: float = 6.0) -> dict:
    """Devices [{name, watts, hours (per day), standby_w}] → kWh and cost per day / month / year."""
    rows = []
    for d in devices:
        w, h = float(d.get("watts", 0)), float(d.get("hours", 24))
        sb = float(d.get("standby_w", 0))
        kwh_day = (w * h + sb * (24 - h)) / 1000
        rows.append({"name": d.get("name", "?"), "kwh_day": round(kwh_day, 3), "kwh_year": round(kwh_day * 365, 1),
                     "cost_year": round(kwh_day * 365 * price_kwh), "standby_cost_year": round(sb * (24 - h) / 1000 * 365 * price_kwh)})
    total = sum(r["kwh_day"] for r in rows)
    return {"devices": sorted(rows, key=lambda r: -r["kwh_day"]), "kwh_day": round(total, 3), "kwh_month": round(total * 30.44, 1),
            "kwh_year": round(total * 365, 1), "cost_month": round(total * 30.44 * price_kwh), "cost_year": round(total * 365 * price_kwh),
            "price_kwh": price_kwh}


# ============================================================================================== 779 / 780 statistics
def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > 1e-30 else 1e-30)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1 + aa / c if abs(1 + aa / c) > 1e-30 else 1e-30
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1 + aa / c if abs(1 + aa / c) > 1e-30 else 1e-30
        de = d * c
        h *= de
        if abs(de - 1) < 3e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1 - math.exp(lbt) * _betacf(b, a, 1 - x) / b


def t_pvalue(t: float, df: float) -> float:
    """Two-sided p-value of Student's t."""
    return betainc(df / 2, 0.5, df / (df + t * t))


def describe(xs: list[float]) -> dict:
    n = len(xs)
    if n < 2:
        raise ValueError("Potřebuju aspoň 2 hodnoty.")
    mean, sd = statistics.fmean(xs), statistics.stdev(xs)
    qs = statistics.quantiles(xs, n=4, method="inclusive")
    iqr = qs[2] - qs[0]
    lo, hi = qs[0] - 1.5 * iqr, qs[2] + 1.5 * iqr
    out = [x for x in xs if x < lo or x > hi]
    skew = sum((x - mean) ** 3 for x in xs) / n / (sd ** 3) if sd else 0.0
    kurt = sum((x - mean) ** 4 for x in xs) / n / (sd ** 4) - 3 if sd else 0.0
    jb = n / 6 * (skew ** 2 + kurt ** 2 / 4)
    return {"n": n, "mean": mean, "median": statistics.median(xs), "sd": sd, "min": min(xs), "max": max(xs), "q1": qs[0], "q3": qs[2],
            "outliers": out, "skew": round(skew, 3), "kurtosis": round(kurt, 3), "normal_p": round(math.exp(-jb / 2), 4)}


def _rank(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def compare_groups(a: list[float], b: list[float], alpha: float = 0.05) -> dict:
    """OMEGA 779: Welch's t-test AND Mann–Whitney, effect size, CI of the difference – plus what makes the result weak."""
    da, db = describe(a), describe(b)
    va, vb = da["sd"] ** 2 / da["n"], db["sd"] ** 2 / db["n"]
    se = math.sqrt(va + vb)
    t = (db["mean"] - da["mean"]) / se if se else 0.0
    df = (va + vb) ** 2 / ((va ** 2) / (da["n"] - 1) + (vb ** 2) / (db["n"] - 1)) if se else 1.0
    p_t = t_pvalue(t, df) if se else 1.0
    pooled = math.sqrt(((da["n"] - 1) * da["sd"] ** 2 + (db["n"] - 1) * db["sd"] ** 2) / (da["n"] + db["n"] - 2))
    d = (db["mean"] - da["mean"]) / pooled if pooled else 0.0
    tcrit = _t_crit(df, alpha)
    diff = db["mean"] - da["mean"]
    ranks = _rank(a + b)
    u = sum(ranks[: len(a)]) - len(a) * (len(a) + 1) / 2
    mu, su = len(a) * len(b) / 2, math.sqrt(len(a) * len(b) * (len(a) + len(b) + 1) / 12)
    z = (u - mu) / su if su else 0.0
    p_u = math.erfc(abs(z) / math.sqrt(2))
    warn = []
    if min(da["n"], db["n"]) < 20:
        warn.append(f"malý vzorek ({min(da['n'], db['n'])}) – výsledek je nejistý")
    if min(da["normal_p"], db["normal_p"]) < 0.05:
        warn.append("data nevypadají normálně rozdělená – spolehni se spíš na Mann–Whitney")
    if da["outliers"] or db["outliers"]:
        warn.append(f"odlehlé hodnoty: {len(da['outliers']) + len(db['outliers'])}")
    if (p_t < alpha) != (p_u < alpha):
        warn.append("testy se neshodnou – rozdíl je na hraně")
    if p_t < alpha and abs(d) < 0.2:
        warn.append("statisticky významné, ale prakticky zanedbatelné (malý efekt)")
    eff = "zanedbatelný" if abs(d) < 0.2 else "malý" if abs(d) < 0.5 else "střední" if abs(d) < 0.8 else "velký"
    return {"a": da, "b": db, "diff": diff, "ci": [diff - tcrit * se, diff + tcrit * se], "t": t, "df": df, "p_welch": p_t,
            "p_mann_whitney": p_u, "cohen_d": d, "effect": eff, "significant": p_t < alpha and p_u < alpha, "warnings": warn}


def _t_crit(df: float, alpha: float) -> float:
    lo, hi = 0.0, 100.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if t_pvalue(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def ab_sample_size(baseline: float, mde: float, alpha: float = 0.05, power: float = 0.8, relative: bool = True) -> dict:
    """OMEGA 780: visitors per variant to detect a change of the conversion rate (two-sided z-test)."""
    p1 = baseline / 100 if baseline > 1 else baseline
    delta = (p1 * (mde / 100 if mde > 1 else mde)) if relative else (mde / 100 if mde > 1 else mde)
    p2 = p1 + delta
    if not (0 < p1 < 1 and 0 < p2 < 1) or delta == 0:
        raise ValueError("Konverze musí být mezi 0 a 100 % a změna nenulová.")
    nd = statistics.NormalDist()
    za, zb = nd.inv_cdf(1 - alpha / 2), nd.inv_cdf(power)
    pbar = (p1 + p2) / 2
    n = ((za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2) / (delta ** 2)
    return {"per_variant": math.ceil(n), "total": 2 * math.ceil(n), "p1": p1, "p2": p2}


def ab_analyze(conv_a: int, n_a: int, conv_b: int, n_b: int, alpha: float = 0.05, expected_split: float = 0.5) -> dict:
    if min(n_a, n_b) <= 0 or conv_a > n_a or conv_b > n_b:
        raise ValueError("Počty konverzí musí být ≤ počtu návštěv a návštěvy > 0.")
    pa, pb = conv_a / n_a, conv_b / n_b
    p = (conv_a + conv_b) / (n_a + n_b)
    se0 = math.sqrt(p * (1 - p) * (1 / n_a + 1 / n_b))
    z = (pb - pa) / se0 if se0 else 0.0
    pval = math.erfc(abs(z) / math.sqrt(2))
    se = math.sqrt(pa * (1 - pa) / n_a + pb * (1 - pb) / n_b)
    zc = statistics.NormalDist().inv_cdf(1 - alpha / 2)
    total = n_a + n_b
    ea, eb = total * expected_split, total * (1 - expected_split)
    chi = (n_a - ea) ** 2 / ea + (n_b - eb) ** 2 / eb
    srm_p = math.erfc(math.sqrt(chi / 2))
    warn = []
    if srm_p < 0.001:
        warn.append(f"nepoměr skupin (SRM, p = {srm_p:.2g}) – rozdělení návštěv je rozbité, výsledku nevěř")
    if min(conv_a, conv_b) < 10:
        warn.append("málo konverzí – výsledek je nejistý")
    return {"rate_a": pa, "rate_b": pb, "lift_pct": (pb / pa - 1) * 100 if pa else math.inf, "p_value": pval, "significant": pval < alpha and srm_p >= 0.001,
            "ci_diff": [pb - pa - zc * se, pb - pa + zc * se], "srm_p": srm_p, "warnings": warn}


# ============================================================================================== 778 frequency
def read_wav(path: Path, max_seconds: float = 60) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as w:
        ch, sw, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        frames = w.readframes(min(w.getnframes(), int(rate * max_seconds)))
    import numpy as np

    if sw == 1:
        data = (np.frombuffer(frames, np.uint8).astype(np.float64) - 128) / 128
    elif sw == 2:
        data = np.frombuffer(frames, "<i2").astype(np.float64) / 32768
    elif sw == 3:
        b = np.frombuffer(frames, np.uint8).reshape(-1, 3)
        ints = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        data = np.where(ints & 0x800000, ints - 0x1000000, ints).astype(np.float64) / 8388608
    elif sw == 4:
        data = np.frombuffer(frames, "<i4").astype(np.float64) / 2147483648
    else:
        raise ValueError("Nepodporovaný formát WAV.")
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data.tolist(), rate


def spectrum(samples: list[float], rate: float, peaks: int = 5) -> dict:
    import numpy as np

    x = np.asarray(samples, dtype=np.float64)
    if len(x) < 16:
        raise ValueError("Málo vzorků (aspoň 16).")
    dc = float(x.mean())
    x = x - dc
    rms = float(np.sqrt(np.mean(x ** 2)))
    win = np.hanning(len(x))
    mag = np.abs(np.fft.rfft(x * win)) * 2 / win.sum()
    freqs = np.fft.rfftfreq(len(x), 1 / rate)
    mag[0] = 0
    found = []
    order = np.argsort(mag)[::-1]
    res = rate / len(x)
    for i in order:
        if mag[i] <= 0 or len(found) >= peaks:
            break
        if any(abs(freqs[i] - f["hz"]) < 3 * res for f in found):
            continue
        if 0 < i < len(mag) - 1 and mag[i - 1] + mag[i + 1] > 0:                     # parabolic peak interpolation
            a, b, c = mag[i - 1], mag[i], mag[i + 1]
            off = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) else 0
        else:
            off = 0
        found.append({"hz": round(float(freqs[i] + off * res), 2), "amplitude": round(float(mag[i]), 5),
                      "db": round(20 * math.log10(max(float(mag[i]), 1e-12) / max(float(mag.max()), 1e-12)), 1)})
    return {"rate": rate, "samples": len(x), "seconds": round(len(x) / rate, 3), "resolution_hz": round(res, 3), "dc": round(dc, 6),
            "rms": round(rms, 6), "peaks": found, "dominant_hz": found[0]["hz"] if found else None}


# ============================================================================================== 767 dataset cleaning
DATE_FORMATS = [("%Y-%m-%d", r"\d{4}-\d{2}-\d{2}"), ("%d.%m.%Y", r"\d{1,2}\.\s?\d{1,2}\.\s?\d{4}"), ("%d/%m/%Y", r"\d{1,2}/\d{1,2}/\d{4}"),
                ("%Y/%m/%d", r"\d{4}/\d{1,2}/\d{1,2}")]


def read_csv(path: Path) -> tuple[list[str], list[list[str]], str, str]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if text[:2000].count(";") > text[:2000].count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not rows:
        raise ValueError("Soubor je prázdný.")
    return rows[0], rows[1:], delim, enc


def _num(s: str) -> float | None:
    t = s.strip().replace(" ", "").replace(" ", "")
    if re.fullmatch(r"-?\d+(,\d+)?", t):
        t = t.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", t):
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _date(s: str):
    import datetime as dt

    t = re.sub(r"\s", "", s.strip())
    for f, rx in DATE_FORMATS:
        if re.fullmatch(rx.replace(r"\s?", ""), t):
            try:
                return f, dt.datetime.strptime(t, f).date()
            except ValueError:
                return None
    return None


def profile_csv(path: Path) -> dict:
    """What is wrong with the dataset: duplicates, gaps, stray spaces, numbers with a decimal comma or stored as text,
    mixed date formats, spelling variants of the same category, outliers."""
    header, rows, delim, enc = read_csv(path)
    width = len(header)
    ragged = sum(1 for r in rows if len(r) != width)
    seen, dups = set(), 0
    for r in rows:
        k = tuple(c.strip() for c in r)
        dups += k in seen
        seen.add(k)
    cols = []
    for i, name in enumerate(header):
        vals = [r[i] if i < len(r) else "" for r in rows]
        filled = [v for v in vals if v.strip()]
        nums = [_num(v) for v in filled]
        n_num = sum(x is not None for x in nums)
        dates = [_date(v) for v in filled]
        fmts = Counter(d[0] for d in dates if d)
        c: dict[str, Any] = {"name": name, "empty": len(vals) - len(filled), "spaces": sum(1 for v in filled if v != v.strip() or "  " in v)}
        if filled and n_num / len(filled) >= 0.8:
            c["type"] = "číslo"
            c["comma_decimal"] = sum(1 for v in filled if re.search(r"\d,\d", v))
            c["not_number"] = [v for v, x in zip(filled, nums) if x is None][:5]
            xs = [x for x in nums if x is not None]
            if len(xs) >= 8:
                qs = statistics.quantiles(xs, n=4)
                iqr = qs[2] - qs[0]
                c["outliers"] = [x for x in xs if x < qs[0] - 3 * iqr or x > qs[2] + 3 * iqr][:5]
        elif filled and sum(fmts.values()) / len(filled) >= 0.8:
            c["type"] = "datum"
            c["date_formats"] = dict(fmts)
        else:
            c["type"] = "text"
            groups: dict[str, Counter] = {}
            for v in filled:
                groups.setdefault(re.sub(r"\s+", " ", v.strip().lower()), Counter())[v.strip()] += 1
            if len(groups) <= max(30, len(filled) // 5):
                c["variants"] = {k: dict(g) for k, g in groups.items() if len(g) > 1}
        cols.append(c)
    return {"rows": len(rows), "columns": width, "delimiter": delim, "encoding": enc, "duplicates": dups, "ragged_rows": ragged, "cols": cols}


def clean_csv(path: Path, dest: Path) -> dict:
    """A cleaned NEW file (UTF-8, same delimiter): trimmed spaces, exact duplicates removed, numbers with a dot, dates
    as YYYY-MM-DD, category variants unified to the most common spelling. The original is not touched."""
    if dest.exists():
        raise ValueError(f"{dest.name} už existuje.")
    prof = profile_csv(path)
    header, rows, delim, _ = read_csv(path)
    changes = Counter()
    canon: dict[int, dict[str, str]] = {}
    for i, c in enumerate(prof["cols"]):
        if c.get("variants"):
            canon[i] = {}
            for _, g in c["variants"].items():
                best = max(g.items(), key=lambda kv: kv[1])[0]
                for v in g:
                    canon[i][v] = best
    out, seen = [], set()
    for r in rows:
        r = (r + [""] * len(header))[: len(header)]
        new = []
        for i, v in enumerate(r):
            s = re.sub(r"\s{2,}", " ", v.strip())
            if s != v:
                changes["mezery"] += 1
            t = prof["cols"][i]["type"]
            if t == "číslo" and s:
                x = _num(s)
                if x is not None:
                    ns = repr(int(x)) if x.is_integer() and not re.search(r"[.,]\d", s) else repr(x)
                    if ns != s:
                        changes["čísla"] += 1
                    s = ns
            elif t == "datum" and s:
                d = _date(s)
                if d and d[1].isoformat() != s:
                    s = d[1].isoformat()
                    changes["data"] += 1
            elif i in canon and s in canon[i] and canon[i][s] != s:
                s = canon[i][s]
                changes["varianty"] += 1
            new.append(s)
        key = tuple(new)
        if key in seen:
            changes["duplicity"] += 1
            continue
        seen.add(key)
        out.append(new)
    with open(dest, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=delim)
        w.writerow([h.strip() for h in header])
        w.writerows(out)
    return {"path": str(dest), "rows_before": len(rows), "rows_after": len(out), "changes": dict(changes)}


# ============================================================================================== 773 tolerances
def stackup(dims: list[dict], gap_min: float | None = None, gap_max: float | None = None) -> dict:
    """Tolerance chain: each {name, nominal, plus, minus, dir (+1 adds to the gap, −1 subtracts)} → nominal gap,
    worst case and statistical (RSS) range, and whether it meets the required gap."""
    nom = sum(d.get("dir", 1) * d["nominal"] for d in dims)
    wc_max = sum(d.get("dir", 1) * d["nominal"] + (d["plus"] if d.get("dir", 1) > 0 else d["minus"]) for d in dims)
    wc_min = sum(d.get("dir", 1) * d["nominal"] - (d["minus"] if d.get("dir", 1) > 0 else d["plus"]) for d in dims)
    centre = sum(d.get("dir", 1) * (d["nominal"] + (d["plus"] - d["minus"]) / 2) for d in dims)
    rss = math.sqrt(sum(((d["plus"] + d["minus"]) / 2) ** 2 for d in dims))
    res = {"nominal": round(nom, 6), "worst_min": round(wc_min, 6), "worst_max": round(wc_max, 6), "rss_min": round(centre - rss, 6),
           "rss_max": round(centre + rss, 6), "contributors": sorted(({"name": d.get("name", "?"), "share_pct": round(100 * (d["plus"] + d["minus"]) /
                                                                     max(1e-12, sum(x["plus"] + x["minus"] for x in dims)))} for d in dims), key=lambda x: -x["share_pct"])}
    if gap_min is not None or gap_max is not None:
        lo, hi = gap_min if gap_min is not None else -math.inf, gap_max if gap_max is not None else math.inf
        res["worst_ok"] = lo <= wc_min and wc_max <= hi
        res["rss_ok"] = lo <= res["rss_min"] and res["rss_max"] <= hi
    return res


# ============================================================================================== 467 / 468 / 775 STL
def read_stl(path: Path) -> list[tuple[tuple[float, float, float], ...]]:
    data = path.read_bytes()
    tris = []
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + n * 50 == len(data):
            for i in range(n):
                v = struct.unpack_from("<12f", data, 84 + i * 50)
                tris.append((v[3:6], v[6:9], v[9:12]))
            return tris
    text = data.decode("utf-8", errors="replace")
    if "facet" not in text:
        raise ValueError("Soubor není STL (ani binární, ani textový).")
    verts = [tuple(float(x) for x in m.groups()) for m in re.finditer(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)]
    return [tuple(verts[i:i + 3]) for i in range(0, len(verts) - 2, 3)]


def inspect_stl(path: Path, printer: tuple[float, float, float] = (220, 220, 250), infill_pct: float = 20, density: float = 1.24) -> dict:
    """Size, volume, surface, watertight / flipped / degenerate, whether it fits the printer, overhangs needing support,
    and an estimate of filament."""
    tris = read_stl(path)
    if not tris:
        raise ValueError("Model nemá žádné trojúhelníky.")
    xs = [v[0] for t in tris for v in t]
    ys = [v[1] for t in tris for v in t]
    zs = [v[2] for t in tris for v in t]
    size = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    vol = area = over_area = 0.0
    degenerate = 0
    edges: Counter = Counter()
    zmin = min(zs)

    def key(p):
        return tuple(round(c, 5) for c in p)
    for a, b, c in tris:
        ab = [b[i] - a[i] for i in range(3)]
        ac = [c[i] - a[i] for i in range(3)]
        cr = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])
        ar = 0.5 * math.sqrt(sum(x * x for x in cr))
        if ar < 1e-12:
            degenerate += 1
            continue
        area += ar
        vol += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6
        nz = cr[2] / (2 * ar)
        if nz < -math.cos(math.radians(45)) and min(a[2], b[2], c[2]) > zmin + 0.2:
            over_area += ar
        ka, kb, kc = key(a), key(b), key(c)
        for e in ((ka, kb), (kb, kc), (kc, ka)):
            edges[e] += 1
    open_edges = sum(1 for (u, v), n in edges.items() if edges.get((v, u), 0) != n)
    fits = sorted(size) <= sorted(printer) and all(s <= p for s, p in zip(sorted(size), sorted(printer)))
    cm3 = abs(vol) / 1000
    shell = min(1.0, area * 0.8 / 1000 / cm3) if cm3 else 1.0                       # ~0.8 mm of walls
    grams = cm3 * density * (shell + (1 - shell) * infill_pct / 100)
    problems = []
    if open_edges:
        problems.append(f"model není uzavřený ({open_edges} otevřených hran) – slicer ho může vytisknout špatně")
    if vol < 0:
        problems.append("normály jsou otočené dovnitř")
    if degenerate:
        problems.append(f"{degenerate} zdegenerovaných trojúhelníků")
    if not fits:
        problems.append(f"nevejde se na tiskárnu {printer[0]}×{printer[1]}×{printer[2]} mm")
    if area and over_area / area > 0.05:
        problems.append(f"převisy přes 45° na {round(100 * over_area / area)} % povrchu – budou potřeba podpěry")
    if max(size) < 1:
        problems.append("model je menší než 1 mm – nejsou jednotky v metrech nebo palcích?")
    return {"triangles": len(tris), "size_mm": [round(s, 2) for s in size], "volume_cm3": round(cm3, 2), "area_cm2": round(area / 100, 2),
            "watertight": not open_edges, "inverted": vol < 0, "degenerate": degenerate, "fits": fits, "overhang_pct": round(100 * over_area / area, 1) if area else 0,
            "filament_g": round(grams, 1), "filament_m_175": round(grams / density / (math.pi * 0.0875 ** 2) / 100, 2), "problems": problems,
            "printable": not problems}


# ============================================================================================== 769 / 479 experiments
EXP_SQL = ("CREATE TABLE IF NOT EXISTS experiments (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, title TEXT, hypothesis TEXT, "
           "params TEXT, result TEXT, conclusion TEXT, status TEXT, project TEXT, tags TEXT, updated REAL)")


def exp_add(rt, title: str, hypothesis: str = "", params: dict | None = None, project: str = "", tags: str = "") -> dict:
    rt.db.exec(EXP_SQL)
    now = time.time()
    cur = rt.db.exec("INSERT INTO experiments (ts, title, hypothesis, params, result, conclusion, status, project, tags, updated) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (now, title.strip()[:200], hypothesis, json.dumps(params or {}, ensure_ascii=False), "", "",
                                                      "běží", project, tags, now))
    return {"id": cur.lastrowid, "title": title}


def exp_result(rt, exp_id: int, result: str, conclusion: str = "", confirmed: bool | None = None) -> dict:
    rt.db.exec(EXP_SQL)
    row = rt.db.one("SELECT * FROM experiments WHERE id=?", (exp_id,))
    if not row:
        raise ValueError(f"Experiment {exp_id} neexistuje.")
    status = "potvrzeno" if confirmed else "vyvráceno" if confirmed is False else "hotovo"
    rt.db.exec("UPDATE experiments SET result=?, conclusion=?, status=?, updated=? WHERE id=?", (result, conclusion, status, time.time(), exp_id))
    return {**dict(row), "result": result, "conclusion": conclusion, "status": status}


def exp_list(rt, query: str = "", project: str = "") -> list[dict]:
    rt.db.exec(EXP_SQL)
    sql, args = "SELECT * FROM experiments WHERE 1=1", []
    if query:
        sql += " AND (title LIKE ? OR hypothesis LIKE ? OR result LIKE ? OR conclusion LIKE ? OR tags LIKE ? OR params LIKE ?)"
        args += [f"%{query}%"] * 6
    if project:
        sql += " AND project=?"
        args.append(project)
    return [{**dict(r), "params": json.loads(r["params"] or "{}")} for r in rt.db.all(sql + " ORDER BY ts DESC LIMIT 100", tuple(args))]
