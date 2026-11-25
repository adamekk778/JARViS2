"""3.14 Simulace „co když“ (návrh 55): money, time and projects, computed exactly (not guessed by the AI) with a chart.

- spoření / investice: "co když budu měsíčně dávat 5 000 Kč na 7 % po 15 let" (+ inflation → today's money)
- úvěr / hypotéka: "co když si půjčím 4 miliony na 5,2 % na 30 let" – the monthly payment, all the interest
- čas: "co když budu denně hodinu méně na mobilu" – hours and days in a year / over years
- projekt: tasks with optimistic / likely / pessimistic days → when it will really be done (P50, P80, P95 – Monte Carlo)
Two scenarios can be compared on one chart (e.g. 5 % vs. 8 %).
"""
from __future__ import annotations

import math
import random
from typing import Any
from xml.sax.saxutils import escape

COLORS = ["#7fe3ff", "#f5b942", "#c084fc", "#3ddc97", "#ff6b6b"]


def fmt(v: float, unit: str = "Kč") -> str:
    s = f"{v:,.0f}".replace(",", " ")
    return f"{s} {unit}".strip()


def savings(monthly: float, years: float, rate_pct: float = 0.0, start: float = 0.0, inflation_pct: float = 0.0) -> dict:
    """Monthly deposits with monthly compounding; the balance at the end of each year."""
    months = max(1, int(round(years * 12)))
    r = rate_pct / 100 / 12
    bal, paid, points = float(start), float(start), [(0.0, float(start))]
    for m in range(1, months + 1):
        bal = bal * (1 + r) + monthly
        paid += monthly
        if m % 12 == 0 or m == months:
            points.append((m / 12, bal))
    real = bal / ((1 + inflation_pct / 100) ** (months / 12)) if inflation_pct else bal
    return {"final": bal, "paid": paid, "interest": bal - paid, "real": real, "points": points}


def loan(amount: float, rate_pct: float, years: float) -> dict:
    """An annuity loan: the monthly payment, all the interest and the remaining debt by year."""
    n = max(1, int(round(years * 12)))
    r = rate_pct / 100 / 12
    pay = amount / n if r == 0 else amount * r / (1 - (1 + r) ** -n)
    bal, points = float(amount), [(0.0, float(amount))]
    for m in range(1, n + 1):
        bal = bal * (1 + r) - pay
        if m % 12 == 0 or m == n:
            points.append((m / 12, max(0.0, bal)))
    return {"payment": pay, "total": pay * n, "interest": pay * n - amount, "points": points}


def time_budget(minutes_per_day: float, years: float = 1.0) -> dict:
    per_year_h = minutes_per_day * 365 / 60
    return {"per_year_h": per_year_h, "per_year_days": per_year_h / 24, "work_days": per_year_h / 8,
            "total_h": per_year_h * years, "points": [(y, per_year_h * y) for y in range(0, int(math.ceil(years)) + 1)]}


def project(tasks: list[dict], runs: int = 4000, seed: int = 7) -> dict:
    """Tasks one after another, each {name, best, likely, worst} in days → the finish's spread (triangular)."""
    rnd = random.Random(seed)
    clean = []
    for t in tasks:
        b, lk, w = (float(t.get(k) or 0) for k in ("best", "likely", "worst"))
        lk = lk or b or w
        b, w = b or lk, w or lk
        lo, hi = min(b, lk, w), max(b, lk, w)
        clean.append((str(t.get("name") or "úkol"), lo, min(max(lk, lo), hi), hi))
    sums = sorted(sum(rnd.triangular(lo, hi, mode) for _, lo, mode, hi in clean) for _ in range(runs))

    def pct(p: float) -> float:
        return sums[min(len(sums) - 1, int(p * len(sums)))]

    naive = sum(mode for _, _, mode, _ in clean)
    lo, hi = sums[0], sums[-1]
    bins = 12
    width = (hi - lo) / bins or 1
    hist = [0] * bins
    for s in sums:
        hist[min(bins - 1, int((s - lo) / width))] += 1
    cum, points = 0, []
    for i, c in enumerate(hist):
        cum += c
        points.append((lo + (i + 1) * width, 100 * cum / len(sums)))
    return {"p50": pct(0.5), "p80": pct(0.8), "p95": pct(0.95), "naive": naive, "chance_naive": 100 * sum(1 for s in sums if s <= naive) / len(sums),
            "points": [(lo, 0.0)] + points, "tasks": [c[0] for c in clean]}


def chart_svg(series: list[tuple[str, list[tuple[float, float]]]], title: str, x_label: str, y_label: str, w: int = 720, h: int = 380) -> str:
    """A small line chart (dark, readable in the chat), no scripts."""
    pad_l, pad_r, pad_t, pad_b = 88, 20, 46, 46
    xs = [x for _, pts in series for x, _ in pts] or [0, 1]
    ys = [y for _, pts in series for _, y in pts] or [0, 1]
    x0, x1 = min(xs), max(xs) if max(xs) > min(xs) else min(xs) + 1
    y0, y1 = min(0.0, min(ys)), max(ys) if max(ys) > 0 else 1.0
    mag = 10 ** math.floor(math.log10(y1 - y0 or 1))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if (y1 - y0) / (s * mag) <= 6)
    y1 = math.ceil(y1 / step) * step

    def X(v: float) -> float:
        return pad_l + (v - x0) / (x1 - x0) * (w - pad_l - pad_r)

    def Y(v: float) -> float:
        return h - pad_b - (v - y0) / (y1 - y0 or 1) * (h - pad_t - pad_b)

    def short(v: float) -> str:
        a = abs(v)
        return (f"{v / 1e6:.1f} mil." if a >= 1e6 else f"{v / 1e3:.0f} tis." if a >= 1e4 else f"{v:.0f}").replace(".", ",").replace(",0 ", " ")

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="Segoe UI, sans-serif">',
           '<style>.l{stroke-dasharray:1;stroke-dashoffset:1;animation:d 1.4s cubic-bezier(.3,.8,.2,1) forwards}'
           '@keyframes d{to{stroke-dashoffset:0}}@media (prefers-reduced-motion:reduce){.l{animation:none;stroke-dashoffset:0}}</style>',
           f'<rect width="{w}" height="{h}" rx="14" fill="#0d1117"/>',
           f'<text x="{pad_l}" y="28" fill="#e6edf3" font-size="16" font-weight="600">{escape(title)}</text>']
    v = y0
    while v <= y1 + 1e-9:
        out.append(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#30363d"/>'
                   f'<text x="{pad_l - 8}" y="{Y(v) + 4:.1f}" fill="#8b949e" font-size="12" text-anchor="end">{escape(short(v))}</text>')
        v += step
    for i in range(6):
        xv = x0 + (x1 - x0) * i / 5
        out.append(f'<text x="{X(xv):.1f}" y="{h - pad_b + 18}" fill="#8b949e" font-size="12" text-anchor="middle">'
                   f'{escape(f"{xv:.0f}" if x1 - x0 >= 5 else f"{xv:.1f}".replace(".", ","))}</text>')
    out.append(f'<text x="{(pad_l + w - pad_r) / 2:.0f}" y="{h - 8}" fill="#8b949e" font-size="12" text-anchor="middle">{escape(x_label)}</text>')
    out.append(f'<text x="16" y="{(pad_t + h - pad_b) / 2:.0f}" fill="#8b949e" font-size="12" transform="rotate(-90 16 {(pad_t + h - pad_b) / 2:.0f})" '
               f'text-anchor="middle">{escape(y_label)}</text>')
    for i, (label, pts) in enumerate(series):
        col = COLORS[i % len(COLORS)]
        d = " ".join(f"{'M' if j == 0 else 'L'}{X(x):.1f},{Y(y):.1f}" for j, (x, y) in enumerate(pts))
        out.append(f'<path class="l" pathLength="1" d="{d}" fill="none" stroke="{col}" stroke-width="2.5" stroke-linejoin="round"/>')   # draws itself in
        out.append(f'<rect x="{w - pad_r - 220}" y="{40 + i * 20}" width="12" height="12" rx="3" fill="{col}"/>'
                   f'<text x="{w - pad_r - 202}" y="{50 + i * 20}" fill="#e6edf3" font-size="12">{escape(label)}</text>')
    out.append("</svg>")
    return "".join(out)


def run(kind: str, a: dict, b: dict | None = None) -> dict:
    """One scenario (or two to compare): {text, svg, data}."""
    kind = (kind or "").lower()
    if kind in ("savings", "sporeni", "investice", "spoření"):
        s1 = savings(**a)
        text = (f"Za {a['years']:g} let naspoříš {fmt(s1['final'])} (vloženo {fmt(s1['paid'])}, výnos {fmt(s1['interest'])})"
                + (f", v dnešních penězích {fmt(s1['real'])}" if a.get("inflation_pct") else "") + ".")
        series = [(f"{a.get('rate_pct', 0):g} % ročně", s1["points"])]
        data: dict[str, Any] = {"a": s1}
        if b:
            s2 = savings(**{**a, **b})
            text += f" Ve druhé variantě {fmt(s2['final'])} – rozdíl {fmt(s2['final'] - s1['final'])}."
            series.append((f"{b.get('rate_pct', a.get('rate_pct', 0)):g} % ročně" if "rate_pct" in b else "varianta B", s2["points"]))
            data["b"] = s2
        return {"text": text, "svg": chart_svg(series, "Co když: spoření", "roky", "Kč"), "data": data}
    if kind in ("loan", "uver", "úvěr", "hypoteka", "hypotéka"):
        l1 = loan(**a)
        text = (f"Splátka {fmt(l1['payment'])} měsíčně, celkem zaplatíš {fmt(l1['total'])}, z toho úroky {fmt(l1['interest'])}.")
        series = [(f"{a['rate_pct']:g} % na {a['years']:g} let", l1["points"])]
        data = {"a": l1}
        if b:
            l2 = loan(**{**a, **b})
            text += (f" Ve druhé variantě splátka {fmt(l2['payment'])}, úroky {fmt(l2['interest'])} "
                     f"({'o ' + fmt(abs(l2['interest'] - l1['interest'])) + (' méně' if l2['interest'] < l1['interest'] else ' víc')}).")
            series.append((f"{b.get('rate_pct', a['rate_pct']):g} % na {b.get('years', a['years']):g} let", l2["points"]))
            data["b"] = l2
        return {"text": text, "svg": chart_svg(series, "Co když: úvěr – zbývající dluh", "roky", "Kč"), "data": data}
    if kind in ("time", "cas", "čas"):
        t1 = time_budget(**a)
        text = (f"{a['minutes_per_day']:g} minut denně je {t1['per_year_h']:.0f} hodin ročně – {t1['per_year_days']:.1f} celých dní "
                f"nebo {t1['work_days']:.0f} pracovních dní; za {a.get('years', 1):g} let {t1['total_h']:.0f} hodin.").replace(".0 ", " ")
        return {"text": text, "svg": chart_svg([("hodiny celkem", t1["points"])], "Co když: čas", "roky", "hodin"), "data": {"a": t1}}
    if kind in ("project", "projekt"):
        p = project(a.get("tasks") or [])
        text = (f"Když všechno půjde podle odhadu, {p['naive']:.0f} dní – ale to vyjde jen s pravděpodobností {p['chance_naive']:.0f} %. "
                f"Realisticky: polovina šancí do {p['p50']:.0f} dní, 80 % do {p['p80']:.0f} dní, téměř jistě do {p['p95']:.0f} dní.")
        return {"text": text, "svg": chart_svg([("šance, že bude hotovo", p["points"])], "Co když: kdy bude projekt hotový", "dní", "%"),
                "data": {"a": p}}
    raise ValueError("Umím spoření, úvěr, čas a projekt.")
