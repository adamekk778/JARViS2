"""OMEGA wave 44: how a page behaves on different displays (347), an editor for animation curves (349), a glass material
(350), an icon system from loose SVGs (355), a motion design timeline (357) and a heatmap of how the space in a UI is
used (358)."""
from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------- 347 responsive layout
WIDTHS = [(360, 760, "telefon"), (768, 1024, "tablet"), (1024, 768, "malý notebook"), (1440, 900, "monitor")]

LAYOUT_JS = """() => {
  const vw = document.documentElement.clientWidth;
  const out = {vw, scroll: document.documentElement.scrollWidth, overflow: [], small_text: [], small_targets: [], overlaps: []};
  const sel = (e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
  const vis = (e, r) => r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden';
  const targets = [];
  for (const e of document.body.querySelectorAll('*')) {
    const r = e.getBoundingClientRect();
    if (!vis(e, r)) continue;
    if (r.right > vw + 1 && getComputedStyle(e).position !== 'fixed') out.overflow.push({sel: sel(e), right: Math.round(r.right)});
    const t = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 2);
    if (t && parseFloat(getComputedStyle(e).fontSize) < 12) out.small_text.push({sel: sel(e), size: parseFloat(getComputedStyle(e).fontSize)});
    if (e.matches('a,button,input,select,textarea,[role=button]')) {
      targets.push({sel: sel(e), x: r.left, y: r.top, w: r.width, h: r.height});
      if (r.width < 44 || r.height < 44) out.small_targets.push({sel: sel(e), w: Math.round(r.width), h: Math.round(r.height)});
    }
  }
  for (let i = 0; i < targets.length; i++) for (let j = i + 1; j < targets.length; j++) {
    const a = targets[i], b = targets[j];
    const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x), oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
    if (ox > 2 && oy > 2) out.overlaps.push([a.sel, b.sel]);
  }
  return out;
}"""


def layout_issues(samples: list[dict]) -> dict:
    """samples: [{width, label, vw, scroll, overflow, small_text, small_targets, overlaps}] → problems per display."""
    rows, score = [], 100
    for s in samples:
        issues = []
        if s["scroll"] > s["vw"] + 1:
            worst = sorted(s["overflow"], key=lambda o: -o["right"])[:3]
            issues.append(f"vodorovné posouvání (obsah {s['scroll']} px na {s['vw']} px), přečnívá: " + ", ".join(o["sel"] for o in worst))
            score -= 20
        if s["small_text"]:
            issues.append(f"{len(s['small_text'])}× písmo menší než 12 px")
            score -= 5
        if s["width"] <= 768 and s["small_targets"]:
            issues.append(f"{len(s['small_targets'])} tlačítek / odkazů menších než 44 px (na dotyk těžko trefit)")
            score -= 10
        if s["overlaps"]:
            issues.append(f"{len(s['overlaps'])}× se ovládací prvky překrývají (" + " × ".join(s["overlaps"][0]) + ")")
            score -= 10
        rows.append({"width": s["width"], "label": s["label"], "issues": issues})
    return {"score": max(0, score), "displays": rows, "ok": all(not r["issues"] for r in rows)}


async def analyze_layout(url: str, out_dir: Path) -> dict:
    from PIL import Image

    from .testlab import headless, page_url

    pw, b = await headless()
    samples, shots = [], []
    try:
        for w, h, label in WIDTHS:
            page = await b.new_page(viewport={"width": w, "height": h})
            await page.goto(page_url(url), wait_until="load", timeout=30000)
            s = await page.evaluate(LAYOUT_JS)
            samples.append({**s, "width": w, "label": label})
            p = out_dir / f"{w}.png"
            await page.screenshot(path=str(p))
            shots.append(p)
            await page.close()
    finally:
        await b.close()
        await pw.stop()
    r = layout_issues(samples)
    ims = [Image.open(p) for p in shots]
    hh = 420
    scaled = [im.resize((max(1, round(im.width * hh / im.height)), hh)) for im in ims]
    sheet = Image.new("RGB", (sum(i.width for i in scaled) + 20 * (len(scaled) + 1), hh + 40), (24, 26, 32))
    x = 20
    for im in scaled:
        sheet.paste(im, (x, 20))
        x += im.width + 20
    sheet.save(out_dir / "prehled.png")
    return {**r, "sheet": str(out_dir / "prehled.png")}


# ---------------------------------------------------------------- 349 animation curves
NAMED = {"linear": (0, 0, 1, 1), "ease": (0.25, 0.1, 0.25, 1), "ease-in": (0.42, 0, 1, 1), "ease-out": (0, 0, 0.58, 1),
         "ease-in-out": (0.42, 0, 0.58, 1), "easeOutBack": (0.34, 1.56, 0.64, 1), "easeInBack": (0.36, 0, 0.66, -0.56),
         "easeOutExpo": (0.16, 1, 0.3, 1), "easeInOutCubic": (0.65, 0, 0.35, 1), "easeOutQuart": (0.25, 1, 0.5, 1)}


def parse_easing(s: str) -> tuple[float, float, float, float]:
    s = s.strip()
    if s in NAMED:
        return NAMED[s]
    m = re.fullmatch(r"cubic-bezier\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)", s)
    if not m:
        raise ValueError("Čekám název (ease-in-out…) nebo cubic-bezier(x1, y1, x2, y2).")
    x1, y1, x2, y2 = (float(v) for v in m.groups())
    if not (0 <= x1 <= 1 and 0 <= x2 <= 1):
        raise ValueError("x1 a x2 musí být mezi 0 a 1.")
    return x1, y1, x2, y2


def _bez(t: float, a: float, b: float) -> float:
    return 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t * t * b + t ** 3


def ease_at(c: tuple, x: float) -> float:
    """y for a given progress x (solve x(t) = x by bisection, robust for any valid curve)."""
    x1, y1, x2, y2 = c
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if _bez(mid, x1, x2) < x:
            lo = mid
        else:
            hi = mid
    return _bez((lo + hi) / 2, y1, y2)


def describe_curve(c: tuple) -> dict:
    ys = [ease_at(c, i / 100) for i in range(101)]
    over = max(ys) > 1.001
    under = min(ys) < -0.001
    first, last = ys[10] - ys[0], ys[100] - ys[90]
    kind = "lineární" if max(abs(y - i / 100) for i, y in enumerate(ys)) < 0.02 else \
        "zrychluje (ease-in)" if first < last * 0.6 else "zpomaluje (ease-out)" if last < first * 0.6 else "plynulý rozjezd i dojezd"
    close = min(NAMED, key=lambda k: sum((a - b) ** 2 for a, b in zip(NAMED[k], c)))
    return {"kind": kind, "overshoot": over, "anticipation": under, "max": round(max(ys), 3), "min": round(min(ys), 3),
            "closest": close, "css": f"cubic-bezier({', '.join(f'{v:g}' for v in c)})"}


def fit_bezier(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Control points that best follow measured (x, y) motion samples – coarse grid then local refinement."""
    pts = [(float(x), float(y)) for x, y in points]

    def err(c):
        return sum((ease_at(c, x) - y) ** 2 for x, y in pts)
    best = min(((x1, y1, x2, y2) for x1 in np.linspace(0, 1, 6) for x2 in np.linspace(0, 1, 6) for y1 in np.linspace(-0.5, 1.5, 9)
                for y2 in np.linspace(-0.5, 1.5, 9)), key=err)
    step = 0.1
    while step > 0.004:
        improved = False
        for i in range(4):
            for d in (-step, step):
                c = list(best)
                c[i] += d
                if i in (0, 2) and not 0 <= c[i] <= 1:
                    continue
                if err(tuple(c)) < err(best):
                    best, improved = tuple(c), True
        if not improved:
            step /= 2
    return tuple(round(v, 3) for v in best)


def curve_svg(c: tuple, size: int = 240) -> str:
    pad = size * 0.2
    s = size - 2 * pad

    def P(x, y):
        return f"{pad + x * s:.1f},{pad + (1 - y) * s:.1f}"
    path = " ".join(("M" if i == 0 else "L") + P(i / 60, ease_at(c, i / 60)) for i in range(61))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
            f'<rect width="{size}" height="{size}" fill="#111827"/><rect x="{pad}" y="{pad}" width="{s}" height="{s}" fill="none" stroke="#374151"/>'
            f'<line x1="{P(0, 0).split(",")[0]}" y1="{P(0, 0).split(",")[1]}" x2="{P(c[0], c[1]).split(",")[0]}" y2="{P(c[0], c[1]).split(",")[1]}" stroke="#60a5fa"/>'
            f'<line x1="{P(1, 1).split(",")[0]}" y1="{P(1, 1).split(",")[1]}" x2="{P(c[2], c[3]).split(",")[0]}" y2="{P(c[2], c[3]).split(",")[1]}" stroke="#f472b6"/>'
            f'<path d="{path}" fill="none" stroke="#f9fafb" stroke-width="2.5"/></svg>')


def curve_editor_html(c: tuple) -> str:
    """A standalone editor: drag the two handles, watch the ball, copy the CSS."""
    return """<!doctype html><html lang="cs"><head><meta charset="utf-8"><title>Animační křivka</title><style>
body{margin:0;background:#0b0d12;color:#e5e7eb;font:15px system-ui;display:grid;place-items:center;min-height:100vh;gap:16px}
svg{background:#111827;border-radius:12px;touch-action:none}.h{cursor:grab}#ball{width:36px;height:36px;border-radius:50%;background:#60a5fa;position:relative}
.track{width:420px;max-width:90vw;background:#1f2937;border-radius:20px;padding:6px}code{background:#1f2937;padding:6px 10px;border-radius:8px;cursor:pointer}
</style></head><body><svg id="s" viewBox="-0.25 -0.75 1.5 2.5" width="300" height="500"><g transform="scale(1,-1) translate(0,-1)">
<rect x="0" y="0" width="1" height="1" fill="none" stroke="#374151" stroke-width=".005"/><line id="l1" stroke="#60a5fa" stroke-width=".01"/>
<line id="l2" stroke="#f472b6" stroke-width=".01"/><path id="p" fill="none" stroke="#f9fafb" stroke-width=".015"/>
<circle id="h1" class="h" r=".04" fill="#60a5fa"/><circle id="h2" class="h" r=".04" fill="#f472b6"/></g></svg>
<div class="track"><div id="ball"></div></div><code id="css" title="Kliknutím zkopírovat"></code>
<script>
let c = CURVE;
const $ = (id) => document.getElementById(id), svg = $("s");
function bez(t, a, b) { return 3*(1-t)*(1-t)*t*a + 3*(1-t)*t*t*b + t*t*t; }
function draw() {
  let d = "M0,0"; for (let i = 1; i <= 60; i++) { const t = i / 60; d += ` L${bez(t, c[0], c[2])},${bez(t, c[1], c[3])}`; }
  $("p").setAttribute("d", d);
  $("h1").setAttribute("cx", c[0]); $("h1").setAttribute("cy", c[1]); $("h2").setAttribute("cx", c[2]); $("h2").setAttribute("cy", c[3]);
  for (const [l, x, y, a, b] of [["l1", 0, 0, c[0], c[1]], ["l2", 1, 1, c[2], c[3]]]) { $(l).setAttribute("x1", x); $(l).setAttribute("y1", y); $(l).setAttribute("x2", a); $(l).setAttribute("y2", b); }
  const css = `cubic-bezier(${c.map((v) => +v.toFixed(2)).join(", ")})`;
  $("css").textContent = css;
  const ball = $("ball"); ball.animate([{ left: "0px" }, { left: "calc(100% - 36px)" }], { duration: 1200, easing: css, iterations: Infinity, direction: "alternate" });
}
let drag = null;
for (const [id, i] of [["h1", 0], ["h2", 2]]) $(id).addEventListener("pointerdown", (e) => { drag = i; e.target.setPointerCapture(e.pointerId); });
svg.addEventListener("pointermove", (e) => {
  if (drag === null) return;
  const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
  const p = pt.matrixTransform(svg.getScreenCTM().inverse());
  c[drag] = Math.min(1, Math.max(0, p.x)); c[drag + 1] = Math.min(2, Math.max(-1, 1 - (p.y + 0)));
  document.getAnimations().forEach((a) => a.cancel()); draw();
});
svg.addEventListener("pointerup", () => { drag = null; });
$("css").onclick = () => navigator.clipboard && navigator.clipboard.writeText($("css").textContent);
draw();
</script></body></html>""".replace("CURVE", json.dumps(list(c)))


# ---------------------------------------------------------------- 350 glass material
def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def glass(tint: str = "#ffffff", opacity: float = 0.18, blur: int = 18, backgrounds: list[str] | None = None, text: str = "") -> dict:
    """Glass (frosted, 'liquid glass') CSS: tint + transparency + blur + light edge. Checks the text contrast over the darkest
    and lightest background it may sit on, and raises the opacity until the text is readable (WCAG AA 4.5:1)."""
    from .design import contrast_report

    bgs = backgrounds or ["#0b0d12", "#f5f5f5"]
    tr, tg, tb = _hex(tint)
    light_tint = (tr * 299 + tg * 587 + tb * 114) / 1000 > 128
    text = text or ("#111827" if light_tint else "#f9fafb")
    op = max(0.05, min(0.95, opacity))
    worst = None
    while True:
        ratios = []
        for bg in bgs:
            br, bgg, bb = _hex(bg)
            mix = "#%02x%02x%02x" % tuple(round(t * op + b * (1 - op)) for t, b in zip((tr, tg, tb), (br, bgg, bb)))
            ratios.append(contrast_report(text, mix)["ratio"])
        worst = min(ratios)
        if worst >= 4.5 or op >= 0.95:
            break
        op = round(op + 0.05, 2)
    rgba = f"rgba({tr}, {tg}, {tb}, {op})"
    edge = "rgba(255, 255, 255, 0.45)" if not light_tint else "rgba(255, 255, 255, 0.7)"
    css = (f".glass {{\n  background: {rgba};\n  backdrop-filter: blur({blur}px) saturate(160%);\n  -webkit-backdrop-filter: blur({blur}px) saturate(160%);\n"
           f"  border: 1px solid {edge};\n  border-radius: 20px;\n  box-shadow: inset 0 1px 0 {edge}, 0 10px 40px rgba(0, 0, 0, 0.25);\n  color: {text};\n}}\n"
           f"@supports not (backdrop-filter: blur(1px)) {{\n  .glass {{ background: rgba({tr}, {tg}, {tb}, {min(0.95, op + 0.35):.2f}); }}\n}}\n")
    return {"css": css, "opacity": op, "raised": op > opacity, "worst_contrast": round(worst, 2), "text": text, "ok": worst >= 4.5}


def glass_preview(g: dict, title: str = "Skleněný panel") -> str:
    return ("<!doctype html><html lang='cs'><head><meta charset='utf-8'><title>Sklo</title><style>"
            "body{margin:0;min-height:100vh;display:grid;place-items:center;font:16px system-ui;"
            "background:radial-gradient(circle at 20% 30%,#f43f5e,transparent 40%),radial-gradient(circle at 80% 60%,#22d3ee,transparent 40%),"
            "linear-gradient(135deg,#0b0d12,#4338ca 50%,#f5f5f5)}" + g["css"] + ".glass{padding:28px 36px;max-width:360px}</style></head>"
            f"<body><div class='glass'><h2>{html.escape(title)}</h2><p>Text musí zůstat čitelný na tmavém i světlém pozadí.</p></div></body></html>")


# ---------------------------------------------------------------- 355 icon system
SVG_NS = "http://www.w3.org/2000/svg"


def _strip(tag: str) -> str:
    return tag.split("}")[-1]


def inspect_icon(text: str) -> dict:
    root = ET.fromstring(text)
    vb = root.get("viewBox") or (f"0 0 {root.get('width', '24').rstrip('px')} {root.get('height', '24').rstrip('px')}")
    strokes, fills, colors = set(), set(), set()
    for el in root.iter():
        for attr in ("stroke", "fill"):
            v = el.get(attr)
            if v and v not in ("none", "currentColor", "inherit"):
                colors.add(v.lower())
        if el.get("stroke") not in (None, "none"):
            strokes.add(el.get("stroke-width", "1"))
        if _strip(el.tag) in ("path", "circle", "rect", "polygon", "ellipse") and el.get("fill") not in ("none",) and el.get("stroke") in (None, "none"):
            fills.add(_strip(el.tag))
    return {"viewBox": " ".join(vb.split()), "stroke_widths": sorted(strokes), "hard_colors": sorted(colors),
            "style": "obrys" if strokes and not fills else "výplň" if fills and not strokes else "smíšený"}


def build_icon_set(files: list[Path]) -> dict:
    """Loose SVG icons → one sprite (<symbol> per icon, colours → currentColor), CSS classes, a preview grid and a report."""
    symbols, report, names = [], [], set()
    infos = []
    for f in sorted(files, key=lambda p: p.name.lower()):
        try:
            text = f.read_text(encoding="utf-8")
            info = inspect_icon(text)
        except (ET.ParseError, OSError, UnicodeDecodeError) as e:
            report.append(f"{f.name}: nejde přečíst ({type(e).__name__})")
            continue
        name = re.sub(r"[^a-z0-9-]+", "-", f.stem.lower()).strip("-") or "icon"
        while name in names:
            name += "-2"
        names.add(name)
        root = ET.fromstring(text)
        for el in root.iter():
            for attr in ("stroke", "fill"):
                v = el.get(attr)
                if v and v not in ("none", "currentColor", "inherit"):
                    el.set(attr, "currentColor")
        inner = "".join(ET.tostring(ch, encoding="unicode").replace("ns0:", "").replace(f' xmlns:ns0="{SVG_NS}"', "") for ch in root)
        inner = re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", inner)
        symbols.append(f'<symbol id="i-{name}" viewBox="{info["viewBox"]}">{inner}</symbol>')
        infos.append((name, info))
    if not infos:
        raise ValueError("Ve složce nejsou čitelné ikony SVG.")
    vbs = {i["viewBox"] for _, i in infos}
    if len(vbs) > 1:
        common = max(vbs, key=lambda v: sum(1 for _, i in infos if i["viewBox"] == v))
        report += [f"{n}: jiná velikost plátna ({i['viewBox']} místo {common})" for n, i in infos if i["viewBox"] != common]
    sws = {w for _, i in infos for w in i["stroke_widths"]}
    if len(sws) > 1:
        report.append(f"různé tloušťky čar: {', '.join(sorted(sws))}")
    styles = {i["style"] for _, i in infos}
    if len(styles) > 1:
        report.append("míchají se obrysové a vyplněné ikony: " + ", ".join(f"{n} ({i['style']})" for n, i in infos if i["style"] != "obrys")[:300])
    recolored = [n for n, i in infos if i["hard_colors"]]
    sprite = f'<svg xmlns="{SVG_NS}" style="display:none">' + "".join(symbols) + "</svg>"
    css = ".icon{width:1em;height:1em;display:inline-block;vertical-align:-0.125em;fill:none;stroke:currentColor}\n"
    grid = "".join(f'<figure><svg class="icon"><use href="#i-{n}"/></svg><figcaption>{n}</figcaption></figure>' for n, _ in infos)
    preview = ("<!doctype html><html lang='cs'><head><meta charset='utf-8'><title>Sada ikon</title><style>" + css +
               "body{font:14px system-ui;background:#0b0d12;color:#e5e7eb;padding:24px}main{display:grid;grid-template-columns:repeat(auto-fill,110px);gap:12px}"
               "figure{margin:0;padding:16px;border:1px solid #1f2937;border-radius:12px;text-align:center}.icon{font-size:32px}"
               "figcaption{margin-top:8px;font-size:12px;opacity:.7}</style></head><body>" + sprite + f"<main>{grid}</main></body></html>")
    return {"count": len(infos), "names": [n for n, _ in infos], "sprite": sprite, "css": css, "preview": preview,
            "report": report, "recolored": recolored}


# ---------------------------------------------------------------- 357 motion design timeline
PROPS = {"opacity": ("opacity", ""), "scale": ("transform", "scale({})"), "x": ("transform", "translateX({}px)"),
         "y": ("transform", "translateY({}px)"), "rotate": ("transform", "rotate({}deg)"), "blur": ("filter", "blur({}px)")}


def parse_timeline(text: str) -> list[dict]:
    """'logo: opacity 0→1 0–0.5s ease-out' per line (also '->', '-', 's' optional) → tracks."""
    out = []
    for i, line in enumerate(l for l in text.splitlines() if l.strip()):
        m = re.match(r"^\s*([\w .-]+?)\s*:\s*(\w+)\s+(-?\d+(?:\.\d+)?)\s*(?:→|->|>)\s*(-?\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*(?:–|-|—|až)\s*(\d+(?:\.\d+)?)\s*s?\s*([\w-]*(?:\([^)]*\))?)?\s*$", line)
        if not m:
            raise ValueError(f"Řádek {i + 1} nerozumím: „{line.strip()}“ (např. „logo: opacity 0→1 0–0.5s ease-out“).")
        layer, prop, a, b, t0, t1, ease = m.groups()
        if prop not in PROPS:
            raise ValueError(f"Vlastnost {prop} neznám (umím {', '.join(PROPS)}).")
        if float(t1) <= float(t0):
            raise ValueError(f"Řádek {i + 1}: konec musí být po začátku.")
        out.append({"layer": layer.strip(), "prop": prop, "from": float(a), "to": float(b), "start": float(t0), "end": float(t1), "ease": ease or "ease-in-out"})
    return out


def timeline_check(tracks: list[dict]) -> list[str]:
    issues = []
    by: dict[tuple, list] = {}
    for t in tracks:
        by.setdefault((t["layer"], t["prop"]), []).append(t)
    for (layer, prop), ts in by.items():
        ts.sort(key=lambda t: t["start"])
        for a, b in zip(ts, ts[1:]):
            if b["start"] < a["end"]:
                issues.append(f"{layer}: dvě animace {prop} se překrývají ({a['start']:g}–{a['end']:g} s a {b['start']:g}–{b['end']:g} s)")
            elif abs(b["from"] - a["to"]) > 1e-9:
                issues.append(f"{layer}: {prop} skočí z {a['to']:g} na {b['from']:g} v {b['start']:g} s")
    return issues


def timeline_css(tracks: list[dict]) -> dict:
    """CSS @keyframes per layer (all its tracks merged on one time axis) + an HTML preview + a Gantt-style SVG."""
    total = max(t["end"] for t in tracks)
    layers: dict[str, list] = {}
    for t in tracks:
        layers.setdefault(t["layer"], []).append(t)
    css, divs = [], []
    for li, (layer, ts) in enumerate(layers.items()):
        times = sorted({0.0, total, *[t["start"] for t in ts], *[t["end"] for t in ts]})
        frames = []
        for tm in times:
            vals: dict[str, list[str]] = {}
            for prop in {t["prop"] for t in ts}:
                seg = sorted([t for t in ts if t["prop"] == prop], key=lambda t: t["start"])
                v = seg[0]["from"]
                for t in seg:
                    if tm >= t["end"]:
                        v = t["to"]
                    elif tm > t["start"]:
                        v = t["from"] + (t["to"] - t["from"]) * (tm - t["start"]) / (t["end"] - t["start"])
                css_prop, fmt = PROPS[prop]
                vals.setdefault(css_prop, []).append(fmt.format(round(v, 3)) if fmt else f"{round(v, 3)}")
            body = "; ".join(f"{k}: {' '.join(v)}" for k, v in vals.items())
            ease = next((t["ease"] for t in ts if abs(t["start"] - tm) < 1e-9), "linear")
            frames.append(f"  {tm / total * 100:.2f}% {{ {body}; animation-timing-function: {ease} }}")
        cls = re.sub(r"\W+", "-", layer.lower()).strip("-") or f"l{li}"
        css.append(f"@keyframes {cls} {{\n" + "\n".join(frames) + "\n}\n" + f".{cls} {{ animation: {cls} {total:g}s both; }}")
        divs.append(f'<div class="layer {cls}" style="top:{20 + li * 70}px">{html.escape(layer)}</div>')
    gantt_h = 30 + 28 * len(tracks)
    bars = "".join(f'<rect x="{120 + t["start"] / total * 460:.1f}" y="{20 + i * 28}" width="{(t["end"] - t["start"]) / total * 460:.1f}" height="20" rx="4" fill="#60a5fa"/>'
                   f'<text x="8" y="{35 + i * 28}" fill="#e5e7eb" font-size="12">{html.escape(t["layer"])} · {t["prop"]}</text>' for i, t in enumerate(tracks))
    gantt = f'<svg xmlns="{SVG_NS}" viewBox="0 0 600 {gantt_h}" width="600" height="{gantt_h}"><rect width="600" height="{gantt_h}" fill="#111827"/>{bars}</svg>'
    preview = ("<!doctype html><html lang='cs'><head><meta charset='utf-8'><title>Časová osa animace</title><style>"
               "body{margin:0;background:#0b0d12;color:#fff;font:16px system-ui;padding:20px}.stage{position:relative;height:" + str(40 + 70 * len(layers)) + "px;"
               "border:1px solid #1f2937;border-radius:12px;overflow:hidden;margin-bottom:16px}.layer{position:absolute;left:40px;padding:12px 18px;"
               "background:#4f46e5;border-radius:10px}" + "\n".join(css) + "</style></head><body><div class='stage'>" + "".join(divs) +
               "</div>" + gantt + "<p><button onclick=\"document.querySelectorAll('.layer').forEach(e=>{e.style.animation='none';e.offsetWidth;e.style.animation=''})\">Přehrát znovu</button></p></body></html>")
    return {"css": "\n\n".join(css), "preview": preview, "gantt": gantt, "duration": total, "layers": list(layers)}


# ---------------------------------------------------------------- 358 layout heatmap
def layout_heatmap(img, cell: int = 24) -> dict:
    """Where the UI is busy and where it breathes: edge density per cell (a proxy for visual weight), empty share, the
    busiest regions, and whether the visual weight is balanced (centre of mass vs the middle)."""
    from PIL import Image

    g = np.asarray(img.convert("L"), dtype=np.float32)
    gx = np.abs(np.diff(g, axis=1, prepend=g[:, :1]))
    gy = np.abs(np.diff(g, axis=0, prepend=g[:1, :]))
    edges = (gx + gy) > 40
    h, w = edges.shape
    rows, cols = max(1, h // cell), max(1, w // cell)
    dens = edges[:rows * cell, :cols * cell].reshape(rows, cell, cols, cell).mean(axis=(1, 3))
    empty = float((dens < 0.01).mean())
    ys, xs = np.mgrid[0:rows, 0:cols]
    tot = dens.sum() or 1
    cy, cx = float((ys * dens).sum() / tot / max(1, rows - 1)), float((xs * dens).sum() / tot / max(1, cols - 1))
    # busiest 3×3-cell regions
    k = 3
    pad = np.pad(dens, 1)
    win = sum(pad[i:i + rows, j:j + cols] for i in range(k) for j in range(k)) / (k * k)
    hot = []
    flat = np.argsort(win, axis=None)[::-1]
    for idx in flat:
        r, c = divmod(int(idx), cols)
        if all(abs(r - a) > 2 or abs(c - b) > 2 for a, b, _ in hot):
            hot.append((r, c, float(win[r, c])))
        if len(hot) == 3:
            break
    norm = dens / (dens.max() or 1)
    heat = np.zeros((rows, cols, 4), dtype=np.uint8)
    heat[..., 0] = (255 * np.clip(norm * 2, 0, 1)).astype(np.uint8)
    heat[..., 1] = (255 * np.clip(2 - norm * 2, 0, 1) * np.clip(norm * 2, 0, 1)).astype(np.uint8)
    heat[..., 3] = (170 * norm).astype(np.uint8)
    overlay = Image.fromarray(heat, "RGBA").resize((cols * cell, rows * cell), Image.NEAREST)
    base = img.convert("RGBA").crop((0, 0, cols * cell, rows * cell))
    out = Image.alpha_composite(base, overlay)
    balance = "vyvážené" if abs(cx - 0.5) < 0.12 and abs(cy - 0.5) < 0.15 else \
        ("těžiště vlevo" if cx < 0.38 else "těžiště vpravo" if cx > 0.62 else "") + (" " if abs(cx - 0.5) >= 0.12 and abs(cy - 0.5) >= 0.15 else "") + \
        ("nahoře" if cy < 0.35 else "dole" if cy > 0.65 else "")
    advice = []
    if empty < 0.25:
        advice.append("málo volného místa – přidej mezery nebo uber prvky")
    elif empty > 0.75:
        advice.append("hodně prázdného místa – obsah může být větší nebo hustší")
    if hot and hot[0][2] > 3 * float(dens.mean() or 1e-9):
        r, c, _ = hot[0]
        advice.append(f"nejvíc přeplněná oblast kolem {round((c + 0.5) * cell)}×{round((r + 0.5) * cell)} px")
    return {"empty_share": round(empty, 2), "center": (round(cx, 2), round(cy, 2)), "balance": balance.strip() or "vyvážené",
            "hotspots": [{"x": round((c + 0.5) * cell), "y": round((r + 0.5) * cell), "density": round(d, 3)} for r, c, d in hot],
            "advice": advice, "image": out}
