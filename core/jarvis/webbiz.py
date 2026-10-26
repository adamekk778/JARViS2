"""OMEGA §05 / §31 / §35 the business on the web and with customers: an SEO audit that crawls the site (titles,
descriptions, headings, alt texts, thin pages, broken links, duplicates, robots / sitemap), keyword gaps against a
competitor, watching a competitor's page (headings and prices since last time) and a feature matrix, products bought
together (lift) with cross-sell targets, follow-ups from quotes and requests, and one dashboard of the numbers."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from html.parser import HTMLParser
from itertools import combinations
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

from .comms import fold

STOP = set("""a aby aj ale ani ano asi az bez bude budem budes by byl byla byli bylo byt ci co coz da do ho i jak jake jako je jeho jej jeji jejich jen
jeste ji jine jiz jsem jses jsme jsou jste k kam kde kdo kdyz ke ktera ktere kteri ktery kvuli ma maji mate me mezi mi mit mne mnou muj muze my na nad
nam nas nasi ne nebo nejsou neni nez nic nove novy o od ode on ona oni ono ony po pod podle pokud pro proc proto protoze pred pri se si sice
sve svych svym svymi ta tak take takze tato te tedy tema ten tento teto tim timto tipy to tohle toho tohoto tom tomto tomuto tu tuto ty tyto u uz v vam
vas vase ve vice vsak vy z za zde ze the and for with you your our are this that from have has not but all can will more about""".split())


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.links, self.imgs, self.heads = "", {}, [], [], []
        self.lang, self.canonical = None, None
        self.text: list[str] = []
        self._in, self._skip = None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "meta" and (a.get("name") or a.get("property")):
            self.meta[(a.get("name") or a.get("property")).lower()] = a.get("content") or ""
        elif tag == "link" and (a.get("rel") or "").lower() == "canonical":
            self.canonical = a.get("href")
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "img":
            self.imgs.append(a)
        elif tag in ("title", "h1", "h2", "h3"):
            self._in = tag
            if tag != "title":
                self.heads.append([tag, ""])
        elif tag in ("script", "style", "noscript", "svg"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        if tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._in == "title":
            self.title += data
        elif self._in in ("h1", "h2", "h3") and self.heads:
            self.heads[-1][1] += data
        self.text.append(data)


def parse(html_text: str) -> _Page:
    p = _Page()
    p.feed(html_text)
    p.title = " ".join(p.title.split())
    p.heads = [[t, " ".join(x.split())] for t, x in p.heads if x.strip()]
    return p


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]{3,}", fold(text)) if w not in STOP and not w.isdigit()]


# ============================================================================================== 55 / 447 SEO audit
async def _get(c, url: str):
    t0 = time.monotonic()
    r = await c.get(url, follow_redirects=True, timeout=20, headers={"User-Agent": "JARVIS-SEO-audit"})
    return r, round((time.monotonic() - t0) * 1000)


def _norm(u: str) -> str:
    """https://web.cz and https://web.cz/ are one page; the #fragment is not a page."""
    p = urlparse(urldefrag(u)[0])
    return p._replace(path=p.path or "/", netloc=p.netloc.lower()).geturl()


def _disallowed(robots: str) -> list[str]:
    out, mine = [], False
    for line in robots.splitlines():
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            mine = v == "*"
        elif k == "disallow" and mine and v:
            out.append(v)
    return out


async def seo_audit(rt, url: str, max_pages: int = 15) -> dict:
    url = url if re.match(r"https?://", url) else "https://" + url
    host = urlparse(url).netloc
    pages, issues = [], []
    async with rt.http() as c:
        try:
            rb = await c.get(urljoin(url, "/robots.txt"), timeout=10)
            robots = rb.text if rb.status_code == 200 else ""
        except Exception:  # noqa: BLE001
            robots = ""
        try:
            sm = await c.get(urljoin(url, "/sitemap.xml"), timeout=10)
            sitemap = sm.status_code == 200 and ("<urlset" in sm.text or "<sitemapindex" in sm.text)
        except Exception:  # noqa: BLE001
            sitemap = False
        blocked = _disallowed(robots)
        queue, seen, broken = [_norm(url)], set(), []
        while queue and len(pages) < max_pages:
            u = queue.pop(0)
            if u in seen:
                continue
            seen.add(u)
            if any(urlparse(u).path.startswith(b) for b in blocked):
                continue
            try:
                r, ms = await _get(c, u)
            except Exception as e:  # noqa: BLE001
                broken.append({"url": u, "status": type(e).__name__})
                continue
            if r.status_code >= 400:
                broken.append({"url": u, "status": r.status_code})
                continue
            if "html" not in r.headers.get("content-type", "html"):
                continue
            p = parse(r.text)
            internal = []
            for href in p.links:
                full = _norm(urljoin(str(r.url), href))
                if urlparse(full).netloc == host and urlparse(full).scheme in ("http", "https"):
                    internal.append(full)
                    if full not in seen and full not in queue:
                        queue.append(full)
            wc = len(words(" ".join(p.text)))
            pg = {"url": str(r.url), "ms": ms, "kb": round(len(r.content) / 1024, 1), "title": p.title, "description": p.meta.get("description", ""),
                  "h1": [x for t, x in p.heads if t == "h1"], "words": wc, "img_no_alt": sum(1 for i in p.imgs if not (i.get("alt") or "").strip()),
                  "images": len(p.imgs), "internal_links": len(set(internal)), "lang": p.lang, "canonical": p.canonical,
                  "noindex": "noindex" in p.meta.get("robots", "").lower(), "og": bool(p.meta.get("og:title")), "problems": []}
            pr = pg["problems"]
            if not p.title:
                pr.append("chybí <title>")
            elif not 10 <= len(p.title) <= 60:
                pr.append(f"titulek má {len(p.title)} znaků (ideál 10–60)")
            if not pg["description"]:
                pr.append("chybí meta description")
            elif not 50 <= len(pg["description"]) <= 160:
                pr.append(f"description má {len(pg['description'])} znaků (ideál 50–160)")
            if len(pg["h1"]) != 1:
                pr.append(f"{len(pg['h1'])}× H1 (má být právě jeden)")
            if pg["img_no_alt"]:
                pr.append(f"{pg['img_no_alt']} obrázků bez alt textu")
            if wc < 250:
                pr.append(f"málo textu ({wc} slov)")
            if not p.lang:
                pr.append("chybí jazyk stránky (lang)")
            if pg["noindex"]:
                pr.append("stránka je noindex – Google ji nezobrazí")
            if ms > 1500:
                pr.append(f"načítání {ms} ms")
            if not pg["og"]:
                pr.append("chybí náhled pro sociální sítě (og:title)")
            pages.append(pg)
    dup_t = [t for t, n in Counter(p["title"] for p in pages if p["title"]).items() if n > 1]
    dup_d = [d for d, n in Counter(p["description"] for p in pages if p["description"]).items() if n > 1]
    if not sitemap:
        issues.append("chybí sitemap.xml")
    if not robots:
        issues.append("chybí robots.txt")
    if dup_t:
        issues.append(f"stejný titulek na více stránkách: {', '.join(dup_t[:3])}")
    if dup_d:
        issues.append("stejný popis (description) na více stránkách")
    if broken:
        issues.append(f"{len(broken)} nefunkčních odkazů")
    count = Counter(re.sub(r"\d+", "N", pr.split(" (")[0]) for p in pages for pr in p["problems"])     # the kind of problem, not its numbers
    total = sum(len(p["problems"]) for p in pages) + len(issues) * 2
    score = max(0, round(100 - 100 * total / max(1, len(pages) * 9 + 10)))
    return {"pages": pages, "site_issues": issues, "broken": broken, "sitemap": sitemap, "robots": bool(robots),
            "top_problems": count.most_common(8), "score": score, "crawled": len(pages)}


async def keyword_gap(rt, mine: str, competitor: str, top: int = 20) -> dict:
    """Words and two-word phrases the competitor's page uses a lot (and in its headings) that yours does not."""
    async with rt.http() as c:
        a = parse((await _get(c, mine if mine.startswith("http") else "https://" + mine))[0].text)
        b = parse((await _get(c, competitor if competitor.startswith("http") else "https://" + competitor))[0].text)

    def bag(p):
        w = words(" ".join(p.text))
        heads = words(" ".join([p.title] + [x for _, x in p.heads]))
        return Counter(w) + Counter(" ".join(x) for x in zip(w, w[1:])), set(heads)
    ma, _ = bag(a)
    mb, hb = bag(b)
    gaps = []
    for term, n in mb.most_common(400):
        if ma.get(term, 0) == 0 and n >= 2:
            gaps.append({"term": term, "competitor": n, "in_headings": any(t in hb for t in term.split())})
    gaps.sort(key=lambda g: (not g["in_headings"], -g["competitor"]))
    shared = [t for t, _ in (ma & mb).most_common(10)]
    return {"gaps": gaps[:top], "shared": shared, "mine_words": sum(1 for _ in words(" ".join(a.text))), "competitor_words": sum(1 for _ in words(" ".join(b.text)))}


# ============================================================================================== 445 / 384 competitors
SNAP_SQL = "CREATE TABLE IF NOT EXISTS competitor_snapshots (url TEXT, ts REAL, data TEXT);"
PRICE = re.compile(r"(\d{1,3}(?:[  .]\d{3})+|\d+)(?:[,.](\d{1,2}))?\s*(?:Kč|,-|CZK|€|EUR)", re.I)


def _price(s: str) -> float:
    m = PRICE.search(s)
    whole = re.sub(r"[  .]", "", m.group(1))
    return float(whole + ("." + m.group(2) if m.group(2) else ""))


def snapshot(html_text: str) -> dict:
    p = parse(html_text)
    items, last = {}, ""
    for chunk in [" ".join(t.split()) for t in p.text if t.strip()]:
        m = PRICE.search(chunk)
        if m and len(chunk) - len(m.group(0)) <= 12:          # a price on its own (not "zdarma nad 500 Kč" in a sentence)
            if last:
                items.setdefault(last, _price(chunk))
            last = ""
        elif not m and 2 < len(chunk) <= 80:
            last = chunk
    body = " ".join(" ".join(p.text).split())
    return {"title": p.title, "heads": [x for _, x in p.heads][:80], "prices": items, "hash": hashlib.sha256(body.encode()).hexdigest()[:16],
            "words": len(body.split())}


async def watch_competitor(rt, url: str) -> dict:
    rt.db.conn.executescript(SNAP_SQL)
    url = url if url.startswith("http") else "https://" + url
    async with rt.http() as c:
        r, _ = await _get(c, url)
    r.raise_for_status()
    now = snapshot(r.text)
    prev_row = rt.db.one("SELECT * FROM competitor_snapshots WHERE url=? ORDER BY ts DESC LIMIT 1", (url,))
    rt.db.exec("INSERT INTO competitor_snapshots VALUES (?,?,?)", (url, time.time(), json.dumps(now, ensure_ascii=False)))
    if not prev_row:
        return {"first": True, "now": now}
    prev = json.loads(prev_row["data"])
    price_changes = [{"item": k, "before": prev["prices"][k], "after": v, "pct": round(100 * (v - prev["prices"][k]) / prev["prices"][k], 1)}
                     for k, v in now["prices"].items() if k in prev["prices"] and prev["prices"][k] and v != prev["prices"][k]]
    return {"first": False, "since": time.strftime("%d. %m. %Y %H:%M", time.localtime(prev_row["ts"])),
            "new_headings": [h for h in now["heads"] if h not in prev["heads"]], "removed_headings": [h for h in prev["heads"] if h not in now["heads"]],
            "price_changes": price_changes, "new_items": [k for k in now["prices"] if k not in prev["prices"]],
            "removed_items": [k for k in prev["prices"] if k not in now["prices"]], "changed": now["hash"] != prev["hash"],
            "words_delta": now["words"] - prev["words"], "now": now}


async def feature_matrix(rt, urls: list[str], features: list[str]) -> dict:
    """Which of the listed features (words / phrases, with alternatives split by „/“) each site mentions."""
    texts = {}
    async with rt.http() as c:
        for u in urls:
            full = u if u.startswith("http") else "https://" + u
            try:
                r, _ = await _get(c, full)
                texts[u] = " " + " ".join(words(" ".join(parse(r.text).text))) + " "
            except Exception as e:  # noqa: BLE001
                texts[u] = None
                texts[u + "#chyba"] = type(e).__name__
    matrix = {}
    for f in features:
        alts = [" ".join(words(a)) for a in f.split("/") if words(a)]
        matrix[f] = {u: (None if texts.get(u) is None else any(f" {a} " in texts[u] for a in alts)) for u in urls}
    only = {u: [f for f in features if matrix[f][u] and sum(1 for x in matrix[f].values() if x) == 1] for u in urls}
    missing = {u: [f for f in features if matrix[f][u] is False] for u in urls}
    return {"matrix": matrix, "unique": only, "missing": missing}


# ============================================================================================== 436 bought together
def basket(header: list[str], rows: list[list[str]], min_support: int = 2, min_lift: float = 1.2) -> dict:
    """Orders (order, customer?, product) → pairs bought together with support, confidence and lift, and who bought
    one but not yet the other (cross-sell targets)."""
    from .business import _col

    oi, pi, ci = _col(header, "objednávka", "objednavka", "order", "doklad", "číslo", "cislo"), _col(header, "produkt", "product", "zboží", "zbozi", "položka", "polozka", "item"), \
        _col(header, "zákazník", "zakaznik", "customer", "klient", "email")
    if oi is None or pi is None:
        raise ValueError("Potřebuju sloupce objednávka a produkt (a ideálně zákazník).")
    orders: dict[str, set] = defaultdict(set)
    cust_of: dict[str, str] = {}
    for r in rows:
        if max(oi, pi) < len(r) and r[oi].strip() and r[pi].strip():
            orders[r[oi].strip()].add(r[pi].strip())
            if ci is not None and ci < len(r):
                cust_of[r[oi].strip()] = r[ci].strip()
    n = len(orders)
    if n < 3:
        raise ValueError("Na rozbor košíků je potřeba aspoň pár objednávek.")
    item_n = Counter(p for o in orders.values() for p in o)
    pair_n = Counter(pr for o in orders.values() for pr in combinations(sorted(o), 2))
    rules = []
    for (a, b), k in pair_n.items():
        if k < min_support:
            continue
        lift = k * n / (item_n[a] * item_n[b])
        if lift < min_lift:
            continue
        for x, y in ((a, b), (b, a)):
            rules.append({"if": x, "then": y, "together": k, "confidence_pct": round(100 * k / item_n[x], 1), "lift": round(lift, 2)})
    rules.sort(key=lambda r: (-r["lift"], -r["confidence_pct"]))
    targets = []
    if cust_of:
        bought: dict[str, set] = defaultdict(set)
        for o, items in orders.items():
            if cust_of.get(o):
                bought[cust_of[o]] |= items
        for r in rules[:10]:
            who = sorted(c for c, items in bought.items() if r["if"] in items and r["then"] not in items)
            if who:
                targets.append({"offer": r["then"], "to_buyers_of": r["if"], "customers": who[:20], "count": len(who)})
    return {"orders": n, "products": len(item_n), "rules": rules[:20], "cross_sell": targets,
            "top_products": [{"product": p, "orders": k} for p, k in item_n.most_common(5)]}


# ============================================================================================== 440 follow-ups
def follow_ups(rt, today: str | dt.date | None = None) -> list[dict]:
    from . import bizops

    d = bizops._today(today)
    rt.db.conn.executescript(bizops.QUOTES_SQL)
    rt.db.conn.executescript(bizops.REQ_SQL)
    out = []
    for q in rt.db.all("SELECT * FROM quotes WHERE status='otevřená'"):
        age = (d - dt.date.fromtimestamp(q["created"])).days
        left = (dt.date.fromisoformat(q["valid_until"]) - d).days
        if 0 <= left <= 3:
            out.append({"who": q["client"], "why": f"nabídka {q['number']} propadne za {left} d", "priority": 1,
                        "draft": f"Dobrý den, připomínám nabídku {q['number']} – platí do {q['valid_until']}. Máte k ní nějaké dotazy?"})
        elif age >= 7:
            out.append({"who": q["client"], "why": f"nabídka {q['number']} bez odpovědi {age} dní", "priority": 2,
                        "draft": f"Dobrý den, chtěl jsem se zeptat, jak jste se rozhodli ohledně nabídky {q['number']}. Rád cokoli upravím."})
    for r in bizops.requests(rt, today=d)["requests"]:
        if r["overdue_days"]:
            out.append({"who": r["client"], "why": f"požadavek č. {r['id']} je {r['overdue_days']} d po termínu", "priority": 0,
                        "draft": f"Dobrý den, omlouvám se za zdržení u „{r['text'][:60]}“ – ozvu se s řešením do …"})
    for q in rt.db.all("SELECT * FROM quotes WHERE status='přijatá' AND decided IS NOT NULL"):
        since = (d - dt.date.fromtimestamp(q["decided"])).days
        if 30 <= since <= 45:
            out.append({"who": q["client"], "why": f"zakázka {q['number']} běží měsíc – čas zeptat se na spokojenost", "priority": 3,
                        "draft": "Dobrý den, jak jste spokojeni? Pokud ano, moc by mi pomohla krátká reference."})
    last_won: dict[str, float] = {}
    for q in rt.db.all("SELECT client, max(decided) AS t FROM quotes WHERE status='přijatá' GROUP BY client"):
        last_won[q["client"]] = q["t"] or 0
    for client, t in last_won.items():
        if t and (d - dt.date.fromtimestamp(t)).days >= 90 and not any(x["who"] == client for x in out):
            out.append({"who": client, "why": f"{(d - dt.date.fromtimestamp(t)).days} dní bez nové zakázky", "priority": 4,
                        "draft": "Dobrý den, dlouho jsme se neslyšeli – nepotřebujete s něčím pomoct?"})
    return sorted(out, key=lambda x: x["priority"])


# ============================================================================================== 450 dashboard
def dashboard(rt, cash: dict | None = None, camp: dict | None = None) -> dict:
    from . import bizops

    q = bizops.quotes_overview(rt)
    req = bizops.requests(rt)
    k = {"otevřené nabídky": q["open"], "hodnota otevřených nabídek": q["open_value"], "úspěšnost nabídek %": q["win_rate"],
         "průměrná zakázka": q["avg_won"], "otevřené požadavky": req["open"], "požadavky po termínu": req["overdue"]}
    alerts = []
    if req["overdue"]:
        alerts.append(f"{req['overdue']} požadavků zákazníků je po termínu")
    if q["expiring"]:
        alerts.append(f"{len(q['expiring'])} nabídek brzy propadne")
    if cash:
        last = cash["months"][-1]
        k |= {"příjmy (poslední měsíc)": last["income"], "výdaje (poslední měsíc)": last["expenses"], "čistý výsledek": last["net"]}
        if last["net"] < 0:
            alerts.append(f"{last['month']} skončil ve ztrátě {last['net']:.0f} Kč")
        nets = [m["net"] for m in cash["months"]]
        if len(nets) >= 3 and all(a > b for a, b in zip(nets[-3:], nets[-2:])):
            alerts.append("čistý výsledek tři měsíce po sobě klesá")
    if camp:
        k |= {"ROAS kampaní": camp["total"]["roas"], "cena konverze": camp["total"]["cpa"]}
        if camp["move_budget"]:
            alerts.append(f"kampaně {', '.join(camp['move_budget']['from'])} prodělávají")
    fu = follow_ups(rt)
    k["lidé k oslovení"] = len(fu)
    return {"kpi": k, "alerts": alerts, "follow_ups": fu[:5]}


def load_csv(path: Path):
    from .science import read_csv

    header, rows, _, _ = read_csv(path)
    return header, rows
