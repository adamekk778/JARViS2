"""Small deterministic helpers that complete partial features: a palette taken from a photo (133), a colour at a point
with its name and readability (282), a video thumbnail with a title (132), sensor data checks (163) and merging several
sensors into one estimate (486), equations solved step by step (766 / 106), a concept map from a text (464), two
articles compared (386) and the "what to do" sentences of research notes (390)."""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------- 133 / 282 colours
NAMED = {"černá": "#000000", "bílá": "#ffffff", "šedá": "#808080", "světle šedá": "#c8c8c8", "tmavě šedá": "#404040",
         "červená": "#e53935", "tmavě červená": "#8b0000", "růžová": "#f48fb1", "oranžová": "#fb8c00", "hnědá": "#795548",
         "béžová": "#e8d9b5", "žlutá": "#fdd835", "olivová": "#808000", "zelená": "#43a047", "tmavě zelená": "#1b5e20",
         "světle zelená": "#9ccc65", "tyrkysová": "#26a69a", "azurová": "#00bcd4", "světle modrá": "#64b5f6", "modrá": "#1e88e5",
         "tmavě modrá": "#0d47a1", "námořnická": "#1a237e", "fialová": "#8e24aa", "levandulová": "#b39ddb", "purpurová": "#c2185b"}


def _rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def color_name(hexcol: str) -> str:
    """Nearest Czech colour name (in a perceptual-ish weighted RGB distance)."""
    c = _rgb(hexcol)
    w = np.array([0.3, 0.59, 0.11]) * 3

    def d(x):
        return float(np.sqrt((((c - _rgb(x)) ** 2) * w).sum()))
    return min(NAMED, key=lambda k: d(NAMED[k]))


def describe_color(hexcol: str) -> dict:
    from .design import contrast_report

    hexcol = "#" + hexcol.lstrip("#").lower()
    r, g, b = (int(v) for v in _rgb(hexcol))
    on_white, on_black = contrast_report(hexcol, "#ffffff"), contrast_report(hexcol, "#000000")
    return {"hex": hexcol, "rgb": [r, g, b], "name": color_name(hexcol), "contrast_white": on_white["ratio"],
            "contrast_black": on_black["ratio"], "text_on_it": "#000000" if on_black["ratio"] >= on_white["ratio"] else "#ffffff"}


def palette_from_image(path: Path, k: int = 5, seed: int = 0) -> list[dict]:
    """The k dominant colours of a photo (k-means on a small copy), most common first, with share and name."""
    from PIL import Image

    with Image.open(path) as im:
        px = np.asarray(im.convert("RGB").resize((96, 96)), dtype=float).reshape(-1, 3)
    rng = np.random.default_rng(seed)
    cent = px[rng.choice(len(px), size=k, replace=False)]
    for _ in range(25):
        lab = np.argmin(((px[:, None, :] - cent[None, :, :]) ** 2).sum(-1), axis=1)
        new = np.array([px[lab == i].mean(0) if np.any(lab == i) else cent[i] for i in range(k)])
        if np.allclose(new, cent, atol=0.5):
            break
        cent = new
    counts = np.bincount(lab, minlength=k)
    out = []
    for i in np.argsort(-counts):
        hx = "#%02x%02x%02x" % tuple(int(round(v)) for v in cent[i])
        out.append({"hex": hx, "share": round(100 * counts[i] / len(px), 1), "name": color_name(hx)})
    return out


def pixel_color(path: Path, x: int, y: int) -> str:
    from PIL import Image

    with Image.open(path) as im:
        r, g, b = im.convert("RGB").getpixel((int(x), int(y)))
    return "#%02x%02x%02x" % (r, g, b)


# ---------------------------------------------------------------- 132 thumbnail
def thumbnail(title: str, out: Path, background: Path | None = None, accent: str = "#ffcc00", size=(1280, 720)) -> Path:
    """A YouTube-style thumbnail: the picture (or a gradient), a dark band for contrast and a big two-line title."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = size
    if background and Path(background).is_file():
        with Image.open(background) as src:
            im = src.convert("RGB")
            s = max(W / im.width, H / im.height)
            im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1))
            l, t = (im.width - W) // 2, (im.height - H) // 2
            im = im.crop((l, t, l + W, t + H))
    else:
        g = np.linspace(0, 1, H)[:, None]
        a, b = _rgb("#1a237e"), _rgb("#8e24aa")
        arr = (a * (1 - g)[..., None] + b * g[..., None]).repeat(W, axis=1).astype(np.uint8)
        im = Image.fromarray(arr, "RGB")
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shade).rectangle([0, int(H * 0.55), W, H], fill=(0, 0, 0, 150))
    im = Image.alpha_composite(im.convert("RGBA"), shade)
    d = ImageDraw.Draw(im)
    font = None
    for f in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(f, 92)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    words, lines, cur = title.upper().split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if d.textlength(test, font=font) > W * 0.88 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    lines.append(cur)
    lines = lines[:2]
    y = H - 40 - len(lines) * 100
    for i, ln in enumerate(lines):
        d.text((48, y + i * 100), ln, font=font, fill=accent if i == 0 else "#ffffff", stroke_width=6, stroke_fill="#000000")
    out.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(out, quality=92)
    return out


# ---------------------------------------------------------------- 163 / 486 sensors
def sensor_diagnose(values: list[float | None], lo: float | None = None, hi: float | None = None, rate_hz: float = 1.0) -> dict:
    """Signs of a faulty sensor: stuck (the same value for long), dropouts (missing readings), out of the physical range,
    spikes (a jump far beyond the usual step), noise (jitter larger than the trend) and drift (a steady slope)."""
    xs = np.array([np.nan if v is None else float(v) for v in values], dtype=float)
    n = len(xs)
    issues = []
    if n < 5:
        return {"ok": False, "issues": ["málo dat (aspoň 5 hodnot)"], "n": n}
    missing = int(np.isnan(xs).sum())
    if missing / n > 0.05:
        issues.append(f"výpadky: chybí {missing} z {n} hodnot ({100 * missing / n:.0f} %) – volný kontakt nebo rušení")
    v = xs[~np.isnan(xs)]
    run = best = 1
    for a, b in zip(v, v[1:]):
        run = run + 1 if a == b else 1
        best = max(best, run)
    if best >= max(10, 0.3 * len(v)) and np.std(v) > 0 or (best == len(v) and len(v) >= 10):
        issues.append(f"zamrzlá hodnota: {best}× za sebou {v[0] if best == len(v) else 'stejné číslo'} – čidlo neodpovídá nebo je odpojené")
    if lo is not None and (v < lo).any() or hi is not None and (v > hi).any():
        bad = int(((v < lo) if lo is not None else 0).sum() + ((v > hi) if hi is not None else 0).sum())
        issues.append(f"mimo rozsah: {bad} hodnot mimo {lo}…{hi} – vadné čidlo nebo špatný převod jednotek")
    d = np.diff(v)
    if len(d) >= 4:
        med = np.median(np.abs(d)) or 1e-9
        spikes = int((np.abs(d) > 8 * med + 1e-9).sum()) if med > 1e-9 else int((np.abs(d) > 0).sum() if np.std(v) > 0 and best < len(v) else 0)
        if med > 1e-9 and spikes:
            issues.append(f"špičky: {spikes}× skok přes osminásobek běžné změny – rušení, špatná zem nebo vadný kabel")
        t = np.arange(len(v)) / rate_hz
        slope = float(np.polyfit(t, v, 1)[0]) if np.std(t) > 0 else 0.0
        resid = v - np.polyval(np.polyfit(t, v, 1), t)
        if np.std(resid) > 0.25 * (np.ptp(v) or 1) and np.std(resid) > 3 * med:
            issues.append(f"šum: rozptyl {np.std(resid):.3g} kolem trendu – stínění, filtr nebo průměrování")
        if abs(slope) * (t[-1] - t[0] if len(t) > 1 else 0) > 0.5 * (np.ptp(v) or 1) and np.std(resid) < 0.1 * (np.ptp(v) or 1):
            issues.append(f"drift: hodnota stále roste/klesá ({slope:.3g} za s) – kalibrace nebo zahřívání čidla")
    return {"ok": not issues, "issues": issues, "n": n, "min": float(np.nanmin(xs)), "max": float(np.nanmax(xs)),
            "mean": float(np.nanmean(xs))}


def sensor_fusion(series: dict[str, list[float | None]], noise: dict[str, float] | None = None) -> dict:
    """Several sensors measuring the same thing → one estimate per moment, each weighted by 1 / its noise (variance).
    Noise is estimated from each sensor's step-to-step jitter when not given; a sensor that reads nothing is skipped."""
    names = list(series)
    n = max(len(v) for v in series.values())
    arr = {k: np.array([np.nan if x is None else float(x) for x in v] + [np.nan] * (n - len(v))) for k, v in series.items()}
    var = {}
    for k, a in arr.items():
        if noise and k in noise:
            var[k] = max(noise[k] ** 2, 1e-12)
        else:
            d = np.diff(a[~np.isnan(a)])
            var[k] = max(float(np.var(d) / 2) if len(d) > 2 else 1.0, 1e-12)
    fused, used = [], []
    for i in range(n):
        vals = [(arr[k][i], 1 / var[k]) for k in names if not np.isnan(arr[k][i])]
        if not vals:
            fused.append(None)
            continue
        w = sum(x[1] for x in vals)
        fused.append(round(sum(x[0] * x[1] for x in vals) / w, 4))
        used.append(len(vals))
    weights = {k: round((1 / var[k]) / sum(1 / v for v in var.values()), 3) for k in names}
    return {"fused": fused, "weights": weights, "noise": {k: round(math.sqrt(v), 4) for k, v in var.items()}}


# ---------------------------------------------------------------- 766 / 106 equations with steps
def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _fmt(x: float) -> str:
    return f"{x:g}".replace(".", ",") if abs(x - round(x)) > 1e-12 else str(int(round(x)))


def poly_coeffs(side: str, var: str = "x") -> dict[int, float]:
    """'3x^2 - 2x + 5' → {2: 3, 1: -2, 0: 5} (also x², 2*x, -x)."""
    s = side.replace(" ", "").replace("²", "^2").replace("*", "").replace("−", "-")
    if not s:
        return {0: 0.0}
    if s[0] not in "+-":
        s = "+" + s
    out: dict[int, float] = {}
    for sign, coef, has_x, power, const in re.findall(rf"([+-])(?:(\d+(?:[.,]\d+)?)?({var})(?:\^(\d+))?|(\d+(?:[.,]\d+)?))", s):
        k = -1.0 if sign == "-" else 1.0
        if has_x:
            p = int(power or 1)
            out[p] = out.get(p, 0.0) + k * (_num(coef) if coef else 1.0)
        elif const:
            out[0] = out.get(0, 0.0) + k * _num(const)
    rebuilt = "".join(re.findall(rf"[+-](?:\d+(?:[.,]\d+)?)?{var}(?:\^\d+)?|[+-]\d+(?:[.,]\d+)?", s))
    if rebuilt != s:
        raise ValueError(f"Výrazu „{side}“ nerozumím – umím mnohočleny (např. 2x^2 - 3x + 1).")
    return out


def solve_steps(equation: str, var: str = "x") -> dict:
    """Linear and quadratic equations, every step written out like at school."""
    if "=" not in equation:
        raise ValueError("Rovnice musí obsahovat =.")
    left, right = equation.split("=", 1)
    L, R = poly_coeffs(left, var), poly_coeffs(right, var)
    c = {p: L.get(p, 0.0) - R.get(p, 0.0) for p in set(L) | set(R)}
    deg = max((p for p, v in c.items() if abs(v) > 1e-12), default=0)
    a, b, k = c.get(2, 0.0), c.get(1, 0.0), c.get(0, 0.0)
    steps = [f"Zadání: {equation.strip()}"]

    def term(v, p):
        return ("" if abs(v) == 1 and p else _fmt(abs(v))) + (var if p == 1 else f"{var}²" if p == 2 else "")
    std = " ".join(("- " if v < 0 else "+ ") + term(v, p) for p, v in sorted(c.items(), reverse=True) if abs(v) > 1e-12).lstrip("+ ") or "0"
    if std.startswith("- "):
        std = "-" + std[2:]
    steps.append(f"Převedu vše na levou stranu: {std} = 0")
    if deg > 2:
        raise ValueError("Umím rovnice prvního a druhého stupně.")
    if deg == 0:
        steps.append("Neznámá zmizela: " + ("0 = 0 → platí pro každé " + var if abs(k) < 1e-12 else f"{_fmt(k)} = 0 → nemá řešení"))
        return {"steps": steps, "solutions": [] if abs(k) > 1e-12 else ["každé číslo"], "degree": 0}
    if deg == 1:
        steps.append(f"Odečtu {_fmt(k)}: {term(b, 1)} = {_fmt(-k)}" if k else f"{term(b, 1)} = 0")
        x = -k / b
        steps.append(f"Vydělím {_fmt(b)}: {var} = {_fmt(-k)} / {_fmt(b)} = {_fmt(x)}")
        steps.append(f"Zkouška: dosadím {var} = {_fmt(x)} → obě strany se rovnají ({_fmt(b * x + k)} = 0)")
        return {"steps": steps, "solutions": [round(x, 10)], "degree": 1}
    D = b * b - 4 * a * k
    steps.append(f"Kvadratická rovnice: a = {_fmt(a)}, b = {_fmt(b)}, c = {_fmt(k)}")
    steps.append(f"Diskriminant D = b² − 4ac = {_fmt(b)}² − 4·{_fmt(a)}·{_fmt(k)} = {_fmt(D)}")
    if D < -1e-12:
        re_, im_ = -b / (2 * a), math.sqrt(-D) / (2 * a)
        steps.append(f"D < 0 → v reálných číslech nemá řešení (komplexní: {_fmt(re_)} ± {_fmt(abs(im_))}i)")
        return {"steps": steps, "solutions": [], "degree": 2, "discriminant": D}
    if abs(D) <= 1e-12:
        x = -b / (2 * a)
        steps.append(f"D = 0 → jeden dvojnásobný kořen: {var} = −b / 2a = {_fmt(x)}")
        return {"steps": steps, "solutions": [round(x, 10)], "degree": 2, "discriminant": D}
    s = math.sqrt(D)
    x1, x2 = (-b + s) / (2 * a), (-b - s) / (2 * a)
    steps.append(f"√D = {_fmt(s)}")
    steps.append(f"{var}₁ = (−b + √D) / 2a = ({_fmt(-b)} + {_fmt(s)}) / {_fmt(2 * a)} = {_fmt(x1)}")
    steps.append(f"{var}₂ = (−b − √D) / 2a = ({_fmt(-b)} − {_fmt(s)}) / {_fmt(2 * a)} = {_fmt(x2)}")
    steps.append(f"Kontrola (Vieta): {var}₁ + {var}₂ = {_fmt(x1 + x2)} = −b/a, {var}₁·{var}₂ = {_fmt(x1 * x2)} = c/a")
    return {"steps": steps, "solutions": sorted([round(x1, 10), round(x2, 10)]), "degree": 2, "discriminant": D}


# ---------------------------------------------------------------- 464 concept map / 386 compare / 390 actions
STOP = set("a i o u v ve na se je to že ze z s k ke do po pro při jak jako by byl byla bylo jsou být má mají aby ale nebo ani už jen také "
           "tak tím této tento tyto který která které což kde kdy co jeho její jejich the and of to in is for on with as by".split())


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 3]


def _terms(sentence: str) -> list[str]:
    from .comms import fold

    return [w for w in re.findall(r"\w{4,}", fold(sentence)) if w not in STOP and not w.isdigit()]


SUFFIXES = sorted(["ami", "ach", "ech", "ich", "ovy", "ova", "ove", "eho", "emu", "ymi", "imi", "ou", "em", "um", "ty", "ta",
                   "a", "u", "y", "e", "i", "o"], key=len, reverse=True)


def stem(word: str) -> str:
    """A light Czech stemmer on folded words: endings off, at least 4 letters kept ("chloroplastech" → "chloroplas")."""
    w = word
    for suf in SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def concept_map(text: str, top: int = 14) -> dict:
    """Key terms (by frequency, stems cut to 6 letters so endings merge) and how strongly they occur together."""
    sents = [list(dict.fromkeys(stem(t) for t in _terms(s))) for s in _sentences(text)]
    freq: dict[str, int] = {}
    shown: dict[str, str] = {}
    from .comms import fold

    for s in _sentences(text):
        for w in re.findall(r"\w{4,}", s):
            k = stem(fold(w))
            if fold(w) in STOP:
                continue
            freq[k] = freq.get(k, 0) + 1
            if k not in shown or len(w) < len(shown[k]):      # the shortest form reads best ("chloroplast", not "chloroplastech")
                shown[k] = w.lower()
    keys = [k for k, _ in sorted(freq.items(), key=lambda kv: -kv[1]) if not k.isdigit()][:top]
    edges: dict[tuple[str, str], int] = {}
    for s in sents:
        ks = [k for k in s if k in keys]
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                a, b = sorted((ks[i], ks[j]))
                edges[(a, b)] = edges.get((a, b), 0) + 1
    return {"nodes": [{"id": shown[k], "weight": freq[k]} for k in keys],
            "edges": [{"a": shown[a], "b": shown[b], "weight": w} for (a, b), w in sorted(edges.items(), key=lambda kv: -kv[1]) if w >= 1][:40]}


def compare_texts(a: str, b: str) -> dict:
    """What two articles share and where they differ: common / only-in-one key terms, numbers that differ, and the
    sentences of B most similar to each of A's (to see the same claim told differently)."""
    from .fsplus import cosine, trigrams

    ta, tb = set(stem(t) for t in _terms(a)), set(stem(t) for t in _terms(b))
    nums = lambda s: set(re.findall(r"\d+(?:[.,]\d+)?\s?(?:%|kč|eur|usd|km|kg|let|lidí|mil\.?|mld\.?)?", s.lower()))  # noqa: E731
    sa, sb = _sentences(a), _sentences(b)
    pairs = []
    for s in sa[:40]:
        if not sb:
            break
        best = max(sb, key=lambda x: cosine(trigrams(s), trigrams(x)))
        sim = cosine(trigrams(s), trigrams(best))
        if sim > 0.45:
            pairs.append({"a": s[:200], "b": best[:200], "similarity": round(sim, 2)})
    common = ta & tb
    return {"overlap_pct": round(100 * len(common) / max(1, len(ta | tb))), "common": sorted(common)[:20],
            "only_a": sorted(ta - tb)[:15], "only_b": sorted(tb - ta)[:15],
            "numbers_only_a": sorted(nums(a) - nums(b))[:10], "numbers_only_b": sorted(nums(b) - nums(a))[:10], "same_claims": pairs[:8]}


ACTION_RX = re.compile(r"\b(je potřeba|je třeba|musíme|musím|měli bychom|mělo by se|doporuč\w*|navrhuj\w*|zkusit|ověřit|"
                       r"udělat|dokončit|zjistit|připravit|poslat|objednat|we should|need to|todo|to do)\b", re.I)


def research_actions(text: str, limit: int = 15) -> list[str]:
    """Sentences that say something should be done → short to-dos (without 'we should' etc.)."""
    out = []
    for s in _sentences(text):
        if ACTION_RX.search(s) or s.lstrip().startswith(("- [ ]", "TODO", "Úkol:")):
            t = re.sub(r"^(- \[ \]\s*|TODO:?\s*|Úkol:\s*)", "", s.strip())
            t = re.sub(r"\b(je potřeba|je třeba|musíme|měli bychom|mělo by se)\s+", "", t, flags=re.I)
            t = t[0].upper() + t[1:] if t else t
            if t and t not in out:
                out.append(t.rstrip(".")[:160])
        if len(out) >= limit:
            break
    return out
