"""OMEGA §29 design studio: colour contrast with the nearest passing colour, a colour theme (light + dark) and a design
system (tokens: colours, type scale, spacing, radii, shadows → CSS / JSON), visual regression between two images,
and in a real page: typography and UI consistency (how many different sizes, colours, spacings are really used)."""
from __future__ import annotations

import colorsys
import json
import re
from collections import Counter
from pathlib import Path

from .devcheck import contrast


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ValueError(f"„{h}“ není barva ve tvaru #RRGGBB.")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#" + "".join(f"{max(0, min(255, round(x))):02x}" for x in (r, g, b))


def css_color(s: str) -> str | None:
    """'rgb(1, 2, 3)' / 'rgba(…)' / '#abc' → '#rrggbb' (fully transparent → None)."""
    s = s.strip()
    m = re.match(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?", s)
    if m:
        if m.group(4) is not None and float(m.group(4)) == 0:
            return None
        return rgb_to_hex(float(m.group(1)), float(m.group(2)), float(m.group(3)))
    if s.startswith("#"):
        return rgb_to_hex(*hex_to_rgb(s))
    return None


def _hls(h: str) -> tuple[float, float, float]:
    r, g, b = hex_to_rgb(h)
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)


def _from_hls(h: float, l_: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l_)), max(0.0, min(1.0, s)))
    return rgb_to_hex(r * 255, g * 255, b * 255)


# ============================================================================================== 348 contrast
def contrast_report(fg: str, bg: str) -> dict:
    """WCAG ratio, which levels pass, and – when it fails – the nearest text colour (same hue) that passes AA."""
    fg, bg = rgb_to_hex(*hex_to_rgb(fg)), rgb_to_hex(*hex_to_rgb(bg))
    ratio = contrast(fg, bg) or 0
    res = {"fg": fg, "bg": bg, "ratio": ratio, "aa": ratio >= 4.5, "aa_large": ratio >= 3, "aaa": ratio >= 7, "aaa_large": ratio >= 4.5}
    if not res["aa"]:
        h, l_, s = _hls(fg)
        bg_l = _hls(bg)[1]
        best = None
        for step in range(1, 101):
            for direction in ((-1, 1) if bg_l > 0.5 else (1, -1)):
                cand = _from_hls(h, l_ + direction * step / 100, s)
                if (contrast(cand, bg) or 0) >= 4.5:
                    best = cand
                    break
            if best:
                break
        res["suggestion"] = best
        res["suggestion_ratio"] = contrast(best, bg) if best else None
    return res


# ============================================================================================== 356 theme / 346 design system
def scale(base: str) -> dict[str, str]:
    """50–950 tints and shades of one colour (like Tailwind), keeping its hue."""
    h, _, s = _hls(base)
    stops = {"50": 0.97, "100": 0.93, "200": 0.86, "300": 0.76, "400": 0.64, "500": 0.52, "600": 0.44, "700": 0.36, "800": 0.28, "900": 0.2, "950": 0.13}
    return {k: _from_hls(h, v, s if v < 0.95 else s * 0.6) for k, v in stops.items()}


def _readable_on(bg: str) -> str:
    return "#ffffff" if (contrast("#ffffff", bg) or 0) >= (contrast("#111111", bg) or 0) else "#111111"


def theme(primary: str, accent: str = "", neutral_tint: float = 0.08) -> dict:
    """Light and dark theme from one brand colour: every text/background pair is checked for WCAG AA."""
    primary = rgb_to_hex(*hex_to_rgb(primary))
    h, _, s = _hls(primary)
    accent = rgb_to_hex(*hex_to_rgb(accent)) if accent else _from_hls((h + 0.5) % 1, 0.5, min(1.0, s))
    pal = {"primary": scale(primary), "accent": scale(accent), "neutral": scale(_from_hls(h, 0.5, neutral_tint))}
    ok_red, ok_green, ok_amber = scale("#dc2626"), scale("#16a34a"), scale("#d97706")
    light = {"bg": "#ffffff", "surface": pal["neutral"]["50"], "border": pal["neutral"]["200"], "text": pal["neutral"]["900"],
             "muted": pal["neutral"]["600"], "primary": pal["primary"]["600"], "on-primary": _readable_on(pal["primary"]["600"]),
             "accent": pal["accent"]["600"], "danger": ok_red["600"], "success": ok_green["700"], "warning": ok_amber["700"]}
    dark = {"bg": pal["neutral"]["950"], "surface": pal["neutral"]["900"], "border": pal["neutral"]["700"], "text": pal["neutral"]["50"],
            "muted": pal["neutral"]["300"], "primary": pal["primary"]["400"], "on-primary": _readable_on(pal["primary"]["400"]),
            "accent": pal["accent"]["400"], "danger": ok_red["400"], "success": ok_green["400"], "warning": ok_amber["400"]}
    checks = []
    for name, t in (("světlé", light), ("tmavé", dark)):
        for fg, bg in (("text", "bg"), ("muted", "bg"), ("text", "surface"), ("primary", "bg"), ("on-primary", "primary"),
                       ("danger", "bg"), ("success", "bg"), ("warning", "bg")):
            r = contrast(t[fg], t[bg]) or 0
            if r < 4.5:                                                  # fix it in place: move the foreground until AA
                fix = contrast_report(t[fg], t[bg]).get("suggestion")
                if fix:
                    t[fg] = fix
                    r = contrast(fix, t[bg]) or 0
            checks.append({"theme": name, "pair": f"{fg} na {bg}", "ratio": r, "aa": r >= 4.5})
    return {"palette": pal, "light": light, "dark": dark, "checks": checks, "all_aa": all(c["aa"] for c in checks)}


def design_tokens(primary: str, base_font: float = 16, type_ratio: float = 1.25, spacing_unit: int = 4, radius: int = 8,
                  font: str = "Inter, system-ui, sans-serif") -> dict:
    t = theme(primary)
    type_scale = {name: round(base_font * type_ratio ** k, 2) for name, k in
                  (("xs", -2), ("sm", -1), ("base", 0), ("lg", 1), ("xl", 2), ("2xl", 3), ("3xl", 4), ("4xl", 5))}
    spacing = {str(k): k * spacing_unit for k in (0, 1, 2, 3, 4, 6, 8, 12, 16, 24)}
    radii = {"none": 0, "sm": max(2, radius // 2), "md": radius, "lg": radius * 2, "full": 9999}
    shadows = {"sm": "0 1px 2px rgb(0 0 0 / 0.06)", "md": "0 4px 12px rgb(0 0 0 / 0.10)", "lg": "0 12px 32px rgb(0 0 0 / 0.14)"}
    return {"color": t, "font": {"family": font, "size": type_scale, "line_height": {"tight": 1.2, "normal": 1.5}},
            "spacing": spacing, "radius": radii, "shadow": shadows}


def tokens_css(tok: dict) -> str:
    out = [":root {"]
    for name, sc in tok["color"]["palette"].items():
        out += [f"  --{name}-{k}: {v};" for k, v in sc.items()]
    out += [f"  --color-{k}: {v};" for k, v in tok["color"]["light"].items()]
    out += [f"  --font-family: {tok['font']['family']};"] + [f"  --text-{k}: {v / 16:g}rem;" for k, v in tok["font"]["size"].items()]
    out += [f"  --space-{k}: {v}px;" for k, v in tok["spacing"].items()]
    out += [f"  --radius-{k}: {v}px;" for k, v in tok["radius"].items()]
    out += [f"  --shadow-{k}: {v};" for k, v in tok["shadow"].items()]
    out += ["}", "", "@media (prefers-color-scheme: dark) {", "  :root {"]
    out += [f"    --color-{k}: {v};" for k, v in tok["color"]["dark"].items()]
    out += ["  }", "}", ""]
    return "\n".join(out)


def save_design_system(tok: dict, folder: Path) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    css, js = folder / "tokens.css", folder / "tokens.json"
    if css.exists() or js.exists():
        raise ValueError(f"Ve složce {folder} už tokens.css / tokens.json jsou.")
    css.write_text(tokens_css(tok), encoding="utf-8")
    js.write_text(json.dumps({k: v for k, v in tok.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return [str(css), str(js)]


# ============================================================================================== 360 visual regression
def visual_diff(before: Path, after: Path, out: Path, tolerance: int = 24) -> dict:
    """Pixel comparison (sizes aligned): % of changed pixels, boxes around changed areas, and a picture with them
    marked in red."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    with Image.open(before) as a0, Image.open(after) as b0:
        a, b = a0.convert("RGB"), b0.convert("RGB")
    size_changed = a.size != b.size
    w, h = max(a.width, b.width), max(a.height, b.height)
    ca, cb = Image.new("RGB", (w, h), "white"), Image.new("RGB", (w, h), "white")
    ca.paste(a)
    cb.paste(b)
    diff = ImageChops.difference(ca, cb).convert("L").point(lambda v: 255 if v > tolerance else 0)
    changed = sum(1 for v in diff.getdata() if v)
    grown = diff.filter(ImageFilter.MaxFilter(15))
    boxes = _boxes(grown)
    marked = cb.copy()
    dr = ImageDraw.Draw(marked)
    for x0, y0, x1, y1 in boxes:
        dr.rectangle([x0, y0, x1, y1], outline=(230, 0, 0), width=3)
    out.parent.mkdir(parents=True, exist_ok=True)
    marked.save(out)
    return {"changed_pct": round(100 * changed / (w * h), 3), "changed_px": changed, "regions": [list(b) for b in boxes[:30]],
            "size_changed": size_changed, "before_size": list(a.size), "after_size": list(b.size), "diff_image": str(out), "same": changed == 0 and not size_changed}


def _boxes(mask, max_boxes: int = 60) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of connected changed areas on a coarse grid (fast, good enough to point at the change)."""
    w, h = mask.size
    cell = 8
    gw, gh = (w + cell - 1) // cell, (h + cell - 1) // cell
    small = mask.resize((gw, gh))
    px = small.load()
    seen = set()
    out = []
    for y in range(gh):
        for x in range(gw):
            if px[x, y] and (x, y) not in seen:
                stack, x0, y0, x1, y1 = [(x, y)], x, y, x, y
                seen.add((x, y))
                while stack:
                    cx, cy = stack.pop()
                    x0, y0, x1, y1 = min(x0, cx), min(y0, cy), max(x1, cx), max(y1, cy)
                    for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                        if 0 <= nx < gw and 0 <= ny < gh and px[nx, ny] and (nx, ny) not in seen:
                            seen.add((nx, ny))
                            stack.append((nx, ny))
                out.append((x0 * cell, y0 * cell, min(w, (x1 + 1) * cell), min(h, (y1 + 1) * cell)))
                if len(out) >= max_boxes:
                    return out
    return sorted(out, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))


# ============================================================================================== 359 / 351 page styles
STYLES_JS = """() => {
  const out = [];
  const els = [...document.querySelectorAll('body *')].slice(0, 4000);
  for (const e of els) {
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const cs = getComputedStyle(e);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
    out.push({tag: e.tagName.toLowerCase(), text: own.slice(0, 80), len: own.length, width: Math.round(r.width),
      font: cs.fontFamily.split(',')[0].replace(/["']/g, '').trim(), size: parseFloat(cs.fontSize), weight: cs.fontWeight,
      line: cs.lineHeight === 'normal' ? 0 : parseFloat(cs.lineHeight), color: cs.color, bg: cs.backgroundColor,
      radius: cs.borderTopLeftRadius, mt: cs.marginTop, mb: cs.marginBottom, pt: cs.paddingTop, pl: cs.paddingLeft});
  }
  return out;
}"""


def typography(els: list[dict]) -> dict:
    text = [e for e in els if e["len"] >= 1]
    sizes = Counter(round(e["size"]) for e in text)
    fonts = Counter(e["font"] for e in text)
    issues = []
    body = [e for e in text if e["len"] >= 60]
    for e in body:
        cpl = e["width"] / (e["size"] * 0.5) if e["size"] else 0
        if cpl > 90:
            issues.append(f"příliš dlouhé řádky (~{int(cpl)} znaků) u „{e['text'][:30]}…“ – ideál 45–80")
            break
    tight = [e for e in body if e["line"] and e["line"] / e["size"] < 1.3]
    if tight:
        issues.append(f"těsné řádkování ({tight[0]['line'] / tight[0]['size']:.2f}×) v odstavcích – doporučeno 1,4–1,6")
    small = [e for e in text if e["size"] < 12]
    if small:
        issues.append(f"{len(small)} textů menších než 12 px")
    if len(fonts) > 3:
        issues.append(f"{len(fonts)} různých písem – stačí 1–2")
    if len(sizes) > 8:
        issues.append(f"{len(sizes)} různých velikostí písma – typografická škála má mít 5–8")
    return {"fonts": dict(fonts.most_common()), "sizes": dict(sorted(sizes.items())), "issues": issues}


def consistency(els: list[dict]) -> dict:
    colors = Counter(c for c in (css_color(e["color"]) for e in els if e["len"]) if c)
    bgs = Counter(c for c in (css_color(e["bg"]) for e in els) if c)
    spaces = Counter(v for e in els for v in (e["mt"], e["mb"], e["pt"], e["pl"]) if v not in ("0px", "auto"))
    radii = Counter(e["radius"] for e in els if e["radius"] not in ("0px", ""))

    def near(cnt: Counter) -> list[list[str]]:
        groups = []
        keys = list(cnt)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if a != b and _close(a, b):
                    groups.append([a, b])
        return groups[:10]
    issues = []
    nc = near(colors)
    if nc:
        issues.append(f"{len(nc)} dvojic skoro stejných barev textu (např. {nc[0][0]} a {nc[0][1]}) – sjednotit")
    if len(spaces) > 12:
        issues.append(f"{len(spaces)} různých odsazení – použij škálu (např. 4/8/12/16/24/32 px)")
    odd = [s for s in spaces if s.endswith("px") and float(s[:-2]) % 4]
    if odd:
        issues.append(f"odsazení mimo mřížku 4 px: {', '.join(sorted(odd)[:6])}")
    if len(radii) > 4:
        issues.append(f"{len(radii)} různých zaoblení rohů")
    return {"text_colors": dict(colors.most_common(12)), "backgrounds": dict(bgs.most_common(8)), "spacing": dict(spaces.most_common(15)),
            "radii": dict(radii.most_common()), "near_duplicates": nc, "issues": issues}


def _close(a: str, b: str, limit: float = 12) -> bool:
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return sum((x - y) ** 2 for x, y in zip(ra, rb)) ** 0.5 < limit


async def page_styles(url: str) -> list[dict]:
    from .testlab import headless, page_url

    pw, b = await headless()
    try:
        page = await b.new_page(viewport={"width": 1366, "height": 900})
        await page.goto(page_url(url), wait_until="load", timeout=30000)
        return await page.evaluate(STYLES_JS)
    finally:
        await b.close()
        await pw.stop()
