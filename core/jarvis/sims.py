"""3.15 Dílna – simulace (návrh C6), počítané tady v numpy, s obrázkem SVG:

- nosník: průhyb a ohybový moment po délce (konzola / prostý nosník, síla v libovolném místě nebo rovnoměrné zatížení),
  největší napětí a bezpečnost proti mezi kluzu,
- teplo: deska (hliník / měď / ocel / FR4) se zdrojem tepla (třeba regulátor nebo LED), okraje drží teplotu okolí a obě
  plochy chladí vzduch → teplotní mapa a nejteplejší místo,
- obvod: stejnosměrný obvod ze seznamu součástek („V1 vcc 0 5; R1 vcc out 10k; R2 out 0 4k7“) → napětí v uzlech,
  proudy a výkon na rezistorech (a které se přehřejí),
- RC / RL: nabíjení kondenzátoru / náběh proudu cívky v čase.
"""
from __future__ import annotations

import math
import re
from html import escape

import numpy as np

from .hwlab import MATERIALS, _section

SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}
THERMAL = {  # W/(m·K)
    "hliník": 205.0, "měď": 385.0, "ocel": 50.0, "nerez": 16.0, "fr4": 0.3, "fr4 s mědí": 20.0, "pla": 0.13, "sklo": 1.0,
}


def value(s: str | float) -> float:
    """"4k7" → 4700, "10m" → 0.01, "2.2u" → 2.2e-6, "100" → 100."""
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip().replace(",", ".").replace("Ω", "").replace("ohm", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([pnuµmkKMG]?)(\d*)[a-zA-Z]*", t)
    if not m:
        raise ValueError(f"Nerozumím hodnotě „{s}“.")
    whole, pre, frac = m.groups()
    num = float(whole + ("." + frac if frac and pre else frac))
    return num * SI.get(pre, 1.0)


# ------------------------------------------------------------------------------------------ SVG charts (own, small)
def _palette() -> list[str]:
    return ["#4fc3ff", "#ffb547", "#3ddc97", "#ff6b8b"]


def line_svg(x: list[float], series: dict[str, list[float]], title: str = "", xlabel: str = "", w: int = 640, h: int = 300,
             invert: bool = False) -> str:
    """A line chart: one or more series over x, axes with a few ticks, the legend."""
    pad_l, pad_r, pad_t, pad_b = 56, 16, 30, 38
    xs = np.asarray(x, dtype=float)
    allv = np.concatenate([np.asarray(v, dtype=float) for v in series.values()]) if series else np.zeros(1)
    lo, hi = float(np.nanmin(allv)), float(np.nanmax(allv))
    if hi - lo < 1e-12:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    lo, hi = lo - span * 0.06, hi + span * 0.06
    x0, x1 = float(xs.min()), float(xs.max()) if xs.max() > xs.min() else float(xs.min()) + 1

    def px(v: float) -> float:
        return pad_l + (v - x0) / (x1 - x0) * (w - pad_l - pad_r)

    def py(v: float) -> float:
        k = (v - lo) / (hi - lo)
        return pad_t + (k if invert else 1 - k) * (h - pad_t - pad_b)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="system-ui,sans-serif" font-size="11">',
           f'<rect width="{w}" height="{h}" rx="10" fill="#07121d"/>']
    if title:
        out.append(f'<text x="{pad_l}" y="19" fill="#cdefff" font-size="13" font-weight="600">{escape(title)}</text>')
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        y = py(v)
        out.append(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{y:.1f}" y2="{y:.1f}" stroke="#1d3347" stroke-width="1"/>')
        out.append(f'<text x="{pad_l - 6}" y="{y + 4:.1f}" fill="#7fa6bf" text-anchor="end">{_short(v)}</text>')
    for i in range(6):
        v = x0 + (x1 - x0) * i / 5
        out.append(f'<text x="{px(v):.1f}" y="{h - pad_b + 16}" fill="#7fa6bf" text-anchor="middle">{_short(v)}</text>')
    if xlabel:
        out.append(f'<text x="{w - pad_r}" y="{h - 6}" fill="#7fa6bf" text-anchor="end">{escape(xlabel)}</text>')
    for (name, vals), col in zip(series.items(), _palette()):
        pts = " ".join(f"{px(a):.1f},{py(b):.1f}" for a, b in zip(xs, vals) if not math.isnan(b))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.2" stroke-linejoin="round">'
                   f'<animate attributeName="stroke-dasharray" from="0,4000" to="4000,0" dur="1.2s" fill="freeze"/></polyline>')
    lx = pad_l + 8
    for (name, _), col in zip(series.items(), _palette()):
        out.append(f'<rect x="{lx}" y="{pad_t + 4}" width="10" height="3" fill="{col}"/><text x="{lx + 14}" y="{pad_t + 9}" fill="#cdefff">{escape(name)}</text>')
        lx += 22 + 7 * len(name)
    out.append("</svg>")
    return "".join(out)


def _short(v: float) -> str:
    a = abs(v)
    if a >= 1e4 or (0 < a < 1e-2):
        return f"{v:.2g}"
    return f"{v:.3g}".replace(".", ",")


def heat_svg(T: np.ndarray, w_mm: float, h_mm: float, title: str = "", hot: tuple[float, float] | None = None, size: int = 520) -> str:
    """A temperature map: cells coloured blue → yellow → red, the scale on the right, the hottest point marked."""
    ny, nx = T.shape
    W = size
    H = int(size * h_mm / w_mm) if w_mm else size
    H = max(160, min(H, 720))
    cw, ch = (W - 90) / nx, (H - 40) / ny
    lo, hi = float(T.min()), float(T.max())

    def col(v: float) -> str:
        k = 0.0 if hi - lo < 1e-9 else (v - lo) / (hi - lo)
        stops = [(0, (40, 90, 200)), (0.35, (40, 200, 220)), (0.65, (250, 210, 60)), (1, (240, 60, 50))]
        for (a, ca), (b, cb) in zip(stops, stops[1:]):
            if k <= b:
                f = (k - a) / (b - a)
                return "#%02x%02x%02x" % tuple(int(ca[i] + (cb[i] - ca[i]) * f) for i in range(3))
        return "#f03c32"

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="system-ui,sans-serif" font-size="11">',
           f'<rect width="{W}" height="{H}" rx="10" fill="#07121d"/>',
           f'<text x="10" y="18" fill="#cdefff" font-size="13" font-weight="600">{escape(title)}</text><g transform="translate(10,28)">']
    for j in range(ny):
        for i in range(nx):
            out.append(f'<rect x="{i * cw:.1f}" y="{j * ch:.1f}" width="{cw + 0.6:.1f}" height="{ch + 0.6:.1f}" fill="{col(float(T[j, i]))}"/>')
    if hot:
        hx, hy = hot[0] / w_mm * nx * cw, hot[1] / h_mm * ny * ch
        out.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="7" fill="none" stroke="#fff" stroke-width="2"/>')
    out.append("</g>")
    bx = W - 66
    for k in range(20):
        v = hi - (hi - lo) * k / 19
        out.append(f'<rect x="{bx}" y="{30 + k * (H - 50) / 20:.1f}" width="14" height="{(H - 50) / 20 + 0.5:.1f}" fill="{col(v)}"/>')
    out.append(f'<text x="{bx + 18}" y="38" fill="#cdefff">{hi:.0f} °C</text><text x="{bx + 18}" y="{H - 14}" fill="#cdefff">{lo:.0f} °C</text>')
    out.append("</svg>")
    return "".join(out)


# ------------------------------------------------------------------------------------------ beam
def beam(length_mm: float, load_n: float, support: str = "konzola", at_mm: float | None = None, distributed: bool = False,
         material: str = "ocel S235", profile: str = "plný čtverec", size_mm: float = 20, n: int = 120) -> dict:
    """Deflection and bending moment along the beam (Euler–Bernoulli, small deflections)."""
    if length_mm <= 0 or size_mm <= 0:
        raise ValueError("Délka i velikost průřezu musí být kladné.")
    mat = next((m for m in MATERIALS if material.lower().split()[0] in m.lower()), "ocel S235")
    fy, e_gpa, rho = MATERIALS[mat]
    E = e_gpa * 1000                                    # N/mm²
    A, I, label = _section(profile, size_mm)
    L, F = float(length_mm), float(load_n)
    cant = not support.lower().startswith("prost")
    a = L if at_mm is None else max(0.0, min(L, float(at_mm)))
    if not cant and at_mm is None:
        a = L / 2
    x = np.linspace(0, L, n)
    if distributed:                                     # q in N/mm over the whole length (F is the total)
        q = F / L
        if cant:
            M = -q * (L - x) ** 2 / 2
            v = q * x ** 2 * (6 * L ** 2 - 4 * L * x + x ** 2) / (24 * E * I)
        else:
            M = q * x * (L - x) / 2
            v = q * x * (L ** 3 - 2 * L * x ** 2 + x ** 3) / (24 * E * I)
    elif cant:                                          # fixed at x = 0, the force at a
        M = np.where(x < a, -F * (a - x), 0.0)
        v = np.where(x <= a, F * x ** 2 * (3 * a - x) / (6 * E * I), F * a ** 2 * (3 * x - a) / (6 * E * I))
    else:                                               # simply supported, the force at a
        b = L - a
        M = np.where(x <= a, F * b * x / L, F * a * (L - x) / L)
        v = np.where(x <= a, F * b * x * (L ** 2 - b ** 2 - x ** 2) / (6 * L * E * I),
                     F * a * (L - x) * (L ** 2 - a ** 2 - (L - x) ** 2) / (6 * L * E * I))
    c = size_mm / 2
    m_max = float(np.abs(M).max())
    stress = m_max * c / I
    i = int(np.abs(v).argmax())
    svg = line_svg(list(x), {"průhyb [mm]": list(v)}, f"Průhyb – {mat}, {profile} {label}", "x [mm]", invert=True)
    svg_m = line_svg(list(x), {"moment [N·m]": list(M / 1000)}, "Ohybový moment", "x [mm]")
    return {"material": mat, "section": f"{profile} {label}", "support": "konzola" if cant else "prostý nosník",
            "max_deflection_mm": round(float(np.abs(v).max()), 3), "where_mm": round(float(x[i]), 1),
            "max_moment_nm": round(m_max / 1000, 2), "max_stress_mpa": round(stress, 1),
            "safety": round(fy / stress, 2) if stress > 0 else None, "mass_kg": round(A * L * rho / 1e9, 3),
            "svg": svg, "svg_moment": svg_m}


# ------------------------------------------------------------------------------------------ heat in a plate
def heat_plate(w_mm: float, h_mm: float, power_w: float, at: tuple[float, float] | None = None, src_mm: float = 10,
               material: str = "hliník", thickness_mm: float = 2, ambient_c: float = 25, h_air: float = 10,
               edges_fixed: bool = True, n: int = 48) -> dict:
    """Steady state: k·t·∇²T − 2·h·(T − T₀) + q = 0 on a grid (Gauss–Seidel, red–black), edges at T₀ when fixed."""
    if w_mm <= 0 or h_mm <= 0 or thickness_mm <= 0:
        raise ValueError("Rozměry desky musí být kladné.")
    k = next((v for m, v in THERMAL.items() if m in material.lower()), None)
    if k is None:
        k = THERMAL["hliník"]
    nx = n
    ny = max(8, int(round(n * h_mm / w_mm)))
    dx, dy = w_mm / 1000 / nx, h_mm / 1000 / ny         # m
    t = thickness_mm / 1000
    cx, cy = (at if at else (w_mm / 2, h_mm / 2))
    X, Y = np.meshgrid((np.arange(nx) + 0.5) * w_mm / nx, (np.arange(ny) + 0.5) * h_mm / ny)
    src = (np.abs(X - cx) <= src_mm / 2) & (np.abs(Y - cy) <= src_mm / 2)
    if not src.any():
        src[int(cy / h_mm * ny) % ny, int(cx / w_mm * nx) % nx] = True
    q = np.where(src, power_w / (src.sum() * dx * dy), 0.0)                    # W/m² into the plate
    T = np.full((ny, nx), ambient_c, dtype=float)
    kt = k * t
    denom = 2 * kt / dx ** 2 + 2 * kt / dy ** 2 + 2 * h_air
    red = (np.add.outer(np.arange(ny), np.arange(nx)) % 2) == 0
    for it in range(20000):
        old = T.copy()
        for mask in (red, ~red):
            P = np.pad(T, 1, mode="constant", constant_values=ambient_c) if edges_fixed else np.pad(T, 1, mode="edge")
            nb = kt * (P[1:-1, :-2] + P[1:-1, 2:]) / dx ** 2 + kt * (P[:-2, 1:-1] + P[2:, 1:-1]) / dy ** 2
            new = (nb + 2 * h_air * ambient_c + q) / denom
            T = np.where(mask, T + 1.6 * (new - T), T)                       # over-relaxed
        if np.abs(T - old).max() < 1e-4:
            break
    j, i = np.unravel_index(int(T.argmax()), T.shape)
    hot = ((i + 0.5) * w_mm / nx, (j + 0.5) * h_mm / ny)
    title = f"{material} {w_mm:g}×{h_mm:g}×{thickness_mm:g} mm, {power_w:g} W"
    return {"max_c": round(float(T.max()), 1), "mean_c": round(float(T.mean()), 1), "hot_mm": [round(hot[0]), round(hot[1])],
            "rise_c": round(float(T.max()) - ambient_c, 1), "iterations": it + 1, "k": k,
            "svg": heat_svg(T, w_mm, h_mm, title, hot)}


# ------------------------------------------------------------------------------------------ DC circuit (nodal analysis)
def parse_netlist(text: str) -> list[dict]:
    out = []
    for line in re.split(r"[;\n]", text):
        parts = line.split()
        if not parts:
            continue
        if len(parts) < 4:
            raise ValueError(f"Řádek „{line.strip()}“: čekám „název uzel uzel hodnota“, např. „R1 vcc out 10k“.")
        name, a, b, val = parts[0], parts[1].lower(), parts[2].lower(), parts[3]
        kind = name[0].upper()
        if kind not in "RVI":
            raise ValueError(f"{name}: umím R (rezistor), V (zdroj napětí) a I (zdroj proudu).")
        g = lambda n: "0" if n in ("0", "gnd", "zem", "-") else n  # noqa: E731
        out.append({"name": name, "kind": kind, "a": g(a), "b": g(b), "value": value(val),
                    "watts": value(parts[4]) if kind == "R" and len(parts) > 4 else 0.25})
    return out


def dc(netlist: str | list[dict]) -> dict:
    """Modified nodal analysis → node voltages, the current through every part, the power in the resistors."""
    parts = parse_netlist(netlist) if isinstance(netlist, str) else netlist
    nodes = sorted({p[k] for p in parts for k in ("a", "b")} - {"0"})
    if not nodes:
        raise ValueError("Obvod nemá žádný uzel kromě země.")
    ni = {n: i for i, n in enumerate(nodes)}
    vs = [p for p in parts if p["kind"] == "V"]
    N, Mv = len(nodes), len(vs)
    A = np.zeros((N + Mv, N + Mv))
    z = np.zeros(N + Mv)
    for p in parts:
        a, b = ni.get(p["a"]), ni.get(p["b"])
        if p["kind"] == "R":
            if p["value"] <= 0:
                raise ValueError(f"{p['name']}: odpor musí být kladný.")
            g = 1 / p["value"]
            for i, j, s in ((a, a, g), (b, b, g), (a, b, -g), (b, a, -g)):
                if i is not None and j is not None:
                    A[i, j] += s
        elif p["kind"] == "I":                          # current from a to b through the source (into b)
            if a is not None:
                z[a] -= p["value"]
            if b is not None:
                z[b] += p["value"]
    for k, p in enumerate(vs):                          # V(a) − V(b) = value
        a, b = ni.get(p["a"]), ni.get(p["b"])
        if a is not None:
            A[a, N + k] += 1
            A[N + k, a] += 1
        if b is not None:
            A[b, N + k] -= 1
            A[N + k, b] -= 1
        z[N + k] = p["value"]
    try:
        x = np.linalg.solve(A, z)
    except np.linalg.LinAlgError:
        raise ValueError("Obvod nejde spočítat – nějaký uzel visí ve vzduchu (chybí spojení se zemí) nebo jsou dva zdroje napětí proti sobě.") from None
    V = {n: float(x[ni[n]]) for n in nodes} | {"0": 0.0}
    rows, hot = [], []
    for k, p in enumerate(parts):
        va, vb = V[p["a"]], V[p["b"]]
        if p["kind"] == "R":
            cur = (va - vb) / p["value"]
            pw = cur * cur * p["value"]
            rows.append({"name": p["name"], "current_ma": round(cur * 1000, 3), "voltage_v": round(va - vb, 3), "power_w": round(pw, 4)})
            if pw > p["watts"] * 0.7:
                hot.append(f"{p['name']} {pw:.2f} W (snese {p['watts']:g} W)")
        elif p["kind"] == "V":
            cur = -float(x[N + vs.index(p)])
            rows.append({"name": p["name"], "current_ma": round(cur * 1000, 3), "voltage_v": round(p["value"], 3), "power_w": round(cur * p["value"], 4)})
        else:
            rows.append({"name": p["name"], "current_ma": round(p["value"] * 1000, 3), "voltage_v": round(va - vb, 3), "power_w": round(p["value"] * (vb - va), 4)})
    return {"nodes": {n: round(v, 4) for n, v in V.items() if n != "0"}, "parts": rows, "too_hot": hot}


# ------------------------------------------------------------------------------------------ RC / RL transients
def transient(kind: str, r: float, cl: float, supply_v: float = 5.0, t_end: float = 0.0) -> dict:
    """RC: the capacitor charging to the supply; RL: the coil's current rising to V/R."""
    if r <= 0 or cl <= 0:
        raise ValueError("Odpor i kapacita / indukčnost musí být kladné.")
    tau = r * cl if kind.lower() == "rc" else cl / r
    T = t_end or 5 * tau
    t = np.linspace(0, T, 200)
    if kind.lower() == "rc":
        y = supply_v * (1 - np.exp(-t / tau))
        series, ylab = {"napětí na C [V]": list(y)}, "V"
    else:
        y = supply_v / r * (1 - np.exp(-t / tau)) * 1000
        series, ylab = {"proud [mA]": list(y)}, "mA"
    scale, unit = (1e3, "ms") if T < 1 else (1, "s")
    svg = line_svg(list(t * scale), series, f"{kind.upper()} – τ = {_short(tau * scale)} {unit}", f"t [{unit}]")
    return {"tau_s": tau, "t63_s": tau, "t99_s": 4.6 * tau, "final": round(float(y[-1]), 4), "unit": ylab, "svg": svg}
