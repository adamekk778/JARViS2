"""OMEGA §48 software testing lab: load with many simulated users, unusual inputs (fuzzing), a network-fault proxy,
memory-leak watching, corrupted test data, translations that overflow (and pseudo-localisation), and browser tests in
a separate headless browser – keyboard accessibility, a device matrix, offline behaviour and scripted user flows with
screenshots as evidence.

Load and fuzzing only ever target the user's own machine or local network (loopback / private addresses) – never the
internet, so it cannot be used to flood someone else's server."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import random
import re
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ============================================================================================== safety
def local_only(url: str) -> str:
    """The host must be this computer or the local network."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("Adresa musí začínat http:// nebo https://")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"Adresu {u.hostname} nejde přeložit: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not (ip.is_loopback or ip.is_private or ip.is_link_local):
            raise ValueError(f"{u.hostname} není tvůj počítač ani místní síť – zátěžové testy a fuzzing pouštím jen na vlastní servery.")
    return url


# ============================================================================================== 642 load
def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))], 1)


async def load_test(client_factory, url: str, users: int = 10, seconds: float = 10, max_requests: int = 20000) -> dict:
    """N simulated users, each repeating requests for T seconds. Latency percentiles, throughput, errors over time."""
    local_only(url)
    users = max(1, min(users, 50))
    seconds = max(1.0, min(seconds, 120.0))
    lat: list[float] = []
    codes: dict[str, int] = {}
    errors: dict[str, int] = {}
    timeline: list[tuple[float, bool]] = []
    stop_at = time.monotonic() + seconds
    t_start = time.monotonic()
    count = 0

    async def user(client):
        nonlocal count
        while time.monotonic() < stop_at and count < max_requests:
            count += 1
            t0 = time.perf_counter()
            try:
                r = await client.get(url, timeout=10)
                ms = (time.perf_counter() - t0) * 1000
                lat.append(ms)
                codes[str(r.status_code)] = codes.get(str(r.status_code), 0) + 1
                timeline.append((time.monotonic() - t_start, r.status_code < 500))
            except Exception as e:  # noqa: BLE001 – every failure is a data point
                errors[type(e).__name__] = errors.get(type(e).__name__, 0) + 1
                timeline.append((time.monotonic() - t_start, False))
    async with client_factory() as client:
        await asyncio.gather(*(user(client) for _ in range(users)))
    took = time.monotonic() - t_start
    total = len(lat) + sum(errors.values())
    bad = sum(n for c, n in codes.items() if c.startswith("5")) + sum(errors.values())
    first_fail = next((round(t, 1) for t, ok in timeline if not ok), None)
    return {"users": users, "seconds": round(took, 1), "requests": total, "rps": round(total / took, 1) if took else 0,
            "p50_ms": _pct(lat, 50), "p95_ms": _pct(lat, 95), "p99_ms": _pct(lat, 99), "max_ms": round(max(lat), 1) if lat else 0,
            "status": codes, "errors": errors, "error_pct": round(100 * bad / total, 1) if total else 0, "first_failure_s": first_fail}


# ============================================================================================== 633 fuzzing
FUZZ_VALUES: list[tuple[str, Any]] = [
    ("prázdné", ""), ("mezera", " "), ("velmi dlouhé", "A" * 10000), ("unicode", "Příliš žluťoučký kůň 😀 ‮"), ("nulový znak", "a\x00b"),
    ("nula", 0), ("záporné", -1), ("obří číslo", 2 ** 63), ("desetinné", 1e308), ("NaN text", "NaN"), ("null", None), ("true", True),
    ("pole", [1, 2]), ("objekt", {"a": 1}), ("SQL", "' OR '1'='1"), ("HTML", "<script>alert(1)</script>"), ("cesta", "../../etc/passwd"),
    ("formát", "%s%s%n{0}"), ("JSON uvnitř", '{"x":'), ("nový řádek", "a\r\nX-Test: 1"),
]


def _fuzz_url(url: str, param: str, value: Any) -> str:
    u = urlparse(url)
    q = [kv for kv in u.query.split("&") if kv and not kv.startswith(param + "=")]
    v = value if isinstance(value, str) else json.dumps(value)
    q.append(urlencode({param: v}))
    return urlunparse(u._replace(query="&".join(q)))


async def fuzz(client_factory, url: str, params: list[str], method: str = "GET", json_body: dict | None = None) -> dict:
    """Sends unusual values into each query parameter (GET) or JSON field (POST) and records what breaks the server:
    5xx answers, timeouts, dropped connections, and inputs that come back unescaped in HTML."""
    local_only(url)
    findings, tried = [], 0
    async with client_factory() as client:
        try:
            base = await client.request(method, url, json=json_body, timeout=10)
            baseline = base.status_code
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Server neodpovídá ani na běžný požadavek: {e}") from e
        for p in params[:20]:
            for label, val in FUZZ_VALUES:
                tried += 1
                try:
                    if method.upper() == "GET":
                        r = await client.get(_fuzz_url(url, p, val), timeout=10)
                    else:
                        r = await client.request(method, url, json={**(json_body or {}), p: val}, timeout=10)
                    if r.status_code >= 500:
                        findings.append({"param": p, "input": label, "problem": f"server spadl ({r.status_code})"})
                    elif label == "HTML" and "<script>alert(1)</script>" in r.text and "html" in r.headers.get("content-type", ""):
                        findings.append({"param": p, "input": label, "problem": "vstup se vrací neošetřený do HTML (XSS)"})
                except Exception as e:  # noqa: BLE001
                    findings.append({"param": p, "input": label, "problem": f"bez odpovědi ({type(e).__name__})"})
    return {"baseline": baseline, "tried": tried, "findings": findings}


# ============================================================================================== 634 network faults
class FaultProxy:
    """A TCP proxy on 127.0.0.1 that forwards to a target and injects faults: delay, dropped connections, a slow line,
    or a full outage. Point the app at the proxy port to see how it copes."""

    def __init__(self, target_host: str, target_port: int, latency_ms: int = 0, drop_pct: int = 0, kbps: int = 0,
                 down: bool = False):
        self.target = (target_host, target_port)
        self.latency_ms, self.drop_pct, self.kbps, self.down = max(0, latency_ms), max(0, min(drop_pct, 100)), max(0, kbps), down
        self.server: asyncio.base_events.Server | None = None
        self.port = 0
        self.stats = {"connections": 0, "dropped": 0, "bytes": 0}
        self.rng = random.Random()

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    async def _pipe(self, reader, writer, delay: bool):
        try:
            while data := await reader.read(16384):
                if delay and self.latency_ms:
                    await asyncio.sleep(self.latency_ms / 1000)
                if self.kbps:
                    for i in range(0, len(data), 1024):
                        writer.write(data[i:i + 1024])
                        await writer.drain()
                        await asyncio.sleep(1024 / (self.kbps * 128))
                else:
                    writer.write(data)
                    await writer.drain()
                self.stats["bytes"] += len(data)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def _handle(self, reader, writer):
        self.stats["connections"] += 1
        if self.down or self.rng.randrange(100) < self.drop_pct:
            self.stats["dropped"] += 1
            writer.transport.abort()
            return
        try:
            tr, tw = await asyncio.wait_for(asyncio.open_connection(*self.target), 10)
        except (OSError, asyncio.TimeoutError):
            writer.transport.abort()
            return
        await asyncio.gather(self._pipe(reader, tw, False), self._pipe(tr, writer, True))


# ============================================================================================== 635 memory leaks
def find_processes(name_or_pid: str):
    import psutil

    if str(name_or_pid).isdigit():
        return [psutil.Process(int(name_or_pid))]
    n = name_or_pid.lower().removesuffix(".exe")
    out = [p for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower().removesuffix(".exe") == n]
    if not out:
        raise ValueError(f"Proces „{name_or_pid}“ neběží.")
    return out


def rss_mb(procs) -> float:
    import psutil

    total = 0
    seen = set()
    for p in procs:
        try:
            for q in [p, *p.children(recursive=True)]:
                if q.pid not in seen:
                    seen.add(q.pid)
                    total += q.memory_info().rss
        except psutil.Error:
            continue
    return total / 2 ** 20


def leak_verdict(samples: list[tuple[float, float]]) -> dict:
    """Linear trend of memory over time: MB per minute, how straight the line is (R²), total growth."""
    if len(samples) < 4:
        raise ValueError("Málo vzorků – sleduj aspoň 4 intervaly.")
    xs = [t / 60 for t, _ in samples]
    ys = [m for _, m in samples]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (my + slope * (x - mx))) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    growth = 100 * (ys[-1] - ys[0]) / ys[0] if ys[0] else 0.0
    leak = slope > 0.5 and r2 > 0.8 and growth > 5
    return {"start_mb": round(ys[0], 1), "end_mb": round(ys[-1], 1), "mb_per_min": round(slope, 2), "r2": round(r2, 2),
            "growth_pct": round(growth, 1), "verdict": "podezření na únik paměti" if leak else "paměť roste" if slope > 0.5 and growth > 5 else "stabilní"}


def watch_memory(name_or_pid: str, seconds: float = 60, interval: float = 5, sleep=time.sleep) -> dict:
    procs = find_processes(name_or_pid)
    samples = []
    t0 = time.monotonic()
    n = max(4, int(seconds / interval) + 1)
    for i in range(n):
        samples.append((time.monotonic() - t0, rss_mb(procs)))
        if i < n - 1:
            sleep(interval)
    return {**leak_verdict(samples), "samples": [(round(t, 1), round(m, 1)) for t, m in samples], "processes": len(procs)}


# ============================================================================================== 643 corrupted data
def corrupt_variants(src: Path, out_dir: Path, seed: int = 7) -> list[dict]:
    """Damaged copies of a test file: empty, cut in half, one byte short, flipped bits, a zeroed block, invalid UTF-8,
    duplicated content, random bytes of the same size. The original is only read."""
    data = src.read_bytes()
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    flipped = bytearray(data)
    for _ in range(max(1, len(data) // 200)):
        if flipped:
            i = rng.randrange(len(flipped))
            flipped[i] ^= 1 << rng.randrange(8)
    zeroed = bytearray(data)
    if zeroed:
        a = len(zeroed) // 3
        zeroed[a:a + max(1, len(zeroed) // 10)] = b"\x00" * len(zeroed[a:a + max(1, len(zeroed) // 10)])
    mid = len(data) // 2
    variants = {"prazdny": b"", "pulka": data[:mid], "bez-posledniho-bajtu": data[:-1], "prehozene-bity": bytes(flipped),
                "vynulovany-blok": bytes(zeroed), "neplatne-utf8": data[:mid] + b"\xff\xfe\xc3\x28" + data[mid:],
                "dvakrat": data + data, "nahodne-bajty": bytes(rng.randrange(256) for _ in range(len(data)))}
    out = []
    for name, content in variants.items():
        p = out_dir / f"{src.stem}.{name}{src.suffix}"
        p.write_bytes(content)
        out.append({"variant": name, "path": str(p), "bytes": len(content)})
    return out


def _crashed(code: int | None, output: str) -> bool:
    if code is None:
        return False
    if code < 0 or (os.name == "nt" and code >= 0xC0000000):
        return True
    return bool(re.search(r"Traceback \(most recent call last\)|Unhandled exception|panicked at|Segmentation fault|"
                          r"Exception in thread|UnhandledPromiseRejection|FATAL ERROR", output))


def corruption_test(src: Path, command: str, out_dir: Path, timeout: float = 30) -> dict:
    """Runs the user's program on every damaged variant ({file} in the command) and sorts the outcome: rejected with an
    error (good), crashed, hung, or silently accepted the damaged data."""
    if "{file}" not in command:
        raise ValueError("Příkaz musí obsahovat {file} – tam dosadím poškozený soubor.")
    variants = corrupt_variants(src, out_dir)
    results = []
    for v in variants:
        cmd = command.replace("{file}", f'"{v["path"]}"')
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                               stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
            code, out = r.returncode, (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            code, out = None, ""
        outcome = "visí" if code is None else "spadl" if _crashed(code, out) else "odmítl" if code != 0 else "přijal"
        results.append({**v, "outcome": outcome, "code": code, "tail": out.strip()[-300:]})
    return {"results": results, "bad": [r for r in results if r["outcome"] in ("spadl", "visí")],
            "accepted": [r["variant"] for r in results if r["outcome"] == "přijal"]}


# ============================================================================================== 639 translations
def overflow(src: dict[str, str], dst: dict[str, str], ratio: float = 1.3, min_extra: int = 6,
             limits: dict[str, int] | None = None) -> list[dict]:
    """Translated strings that will probably not fit where the original did (much longer, or over a known limit)."""
    out = []
    for k, s in src.items():
        d = dst.get(k)
        if not d or not s:
            continue
        lim = (limits or {}).get(k)
        if lim and len(d) > lim:
            out.append({"key": k, "source": s, "text": d, "len": len(d), "limit": lim, "why": f"delší než limit {lim}"})
        elif len(d) > len(s) * ratio and len(d) - len(s) >= min_extra:
            out.append({"key": k, "source": s, "text": d, "len": len(d), "limit": lim,
                        "why": f"o {round(100 * (len(d) / len(s) - 1))} % delší než originál"})
    return sorted(out, key=lambda x: -(x["len"] / max(1, len(x["source"]))))


ACCENT = str.maketrans("aceinorsuyzACEINORSUYZ", "áčéíňóřšůýžÁČÉÍŇÓŘŠŮÝŽ")


def pseudo(text: str, expand: float = 0.4) -> str:
    """[!! Ťéxť ~~~~ !!] – accents, ~40 % longer, brackets to spot cut-off text; placeholders stay intact."""
    parts = re.split(r"(\{[^}]*\}|%\w|%\(\w+\)s|<[^>]+>|\$\{[^}]*\})", text)
    body = "".join(p if re.fullmatch(r"\{[^}]*\}|%\w|%\(\w+\)s|<[^>]+>|\$\{[^}]*\}", p or "x") else p.translate(ACCENT) for p in parts)
    pad = "~" * max(1, round(len(text) * expand))
    return f"[!! {body} {pad} !!]"


def pseudo_localize(src_path: Path, dst_path: Path) -> dict:
    """Writes a pseudo-translated copy of a JSON strings file (nested keys kept) for testing layouts."""
    if dst_path.exists():
        raise ValueError(f"{dst_path.name} už existuje.")
    data = json.loads(src_path.read_text(encoding="utf-8"))
    n = 0

    def walk(x):
        nonlocal n
        if isinstance(x, str):
            n += 1
            return pseudo(x)
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x
    dst_path.write_text(json.dumps(walk(data), ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(dst_path), "strings": n}


# ============================================================================================== browser tests
async def headless():
    """A separate headless browser (not the user's profile): Edge / Chrome on Windows, else Playwright's Chromium."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    kw: dict = {"headless": True}
    if os.environ.get("JARVIS_CHROMIUM"):
        kw["executable_path"] = os.environ["JARVIS_CHROMIUM"]
    last = None
    for ch in (["msedge", "chrome", None] if sys.platform == "win32" and "executable_path" not in kw else [None]):
        try:
            b = await (pw.chromium.launch(channel=ch, **kw) if ch else pw.chromium.launch(**kw))
            return pw, b
        except Exception as e:  # noqa: BLE001
            last = e
    await pw.stop()
    raise RuntimeError(f"Prohlížeč se nepodařilo spustit: {last}")


def page_url(target: str) -> str:
    if re.match(r"https?://|file:", target):
        return target
    p = Path(target).expanduser()
    if p.is_file():
        return p.resolve().as_uri()
    raise ValueError(f"{target} není adresa ani soubor.")


FOCUS_JS = """() => {
  const e = document.activeElement;
  if (!e || e === document.body) return null;
  const cs = getComputedStyle(e), r = e.getBoundingClientRect();
  const label = (e.getAttribute('aria-label') || (e.labels && e.labels[0] ? e.labels[0].innerText : '') || e.innerText || e.value || e.placeholder || e.name || e.id || e.tagName).trim().slice(0, 60);
  const sel = e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\\s+/).join('.') : '');
  const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow && cs.boxShadow !== 'none');
  return {sel, label, ring, visible: r.width > 0 && r.height > 0, key: sel + '|' + label + '|' + Math.round(r.x) + ',' + Math.round(r.y)};
}"""

INTERACTIVE_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const out = [];
  document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, [tabindex], [onclick], [role=button], [role=link]').forEach(e => {
    if (!vis(e) || e.disabled) return;
    const ti = e.getAttribute('tabindex');
    const native = e.matches('a[href], button, input, select, textarea');
    const label = (e.getAttribute('aria-label') || (e.labels && e.labels[0] ? e.labels[0].innerText : '') || e.innerText || e.value || e.placeholder || e.name || e.id || e.tagName).trim().slice(0, 60);
    const r = e.getBoundingClientRect();
    out.push({label, tag: e.tagName.toLowerCase(), native, tabindex: ti === null ? null : parseInt(ti),
              key_hint: label + '|' + Math.round(r.x) + ',' + Math.round(r.y)});
  });
  return out;
}"""


async def keyboard_test(url: str, max_tabs: int = 80) -> dict:
    """OMEGA 644: Tab through the page – focus order, elements the keyboard never reaches (e.g. clickable <div>s),
    focus without a visible ring, a focus trap, positive tabindex."""
    pw, b = await headless()
    try:
        page = await b.new_page()
        await page.goto(page_url(url), wait_until="load", timeout=30000)
        interactive = await page.evaluate(INTERACTIVE_JS)
        order, keys, trap = [], [], None
        for _ in range(max_tabs):
            await page.keyboard.press("Tab")
            f = await page.evaluate(FOCUS_JS)
            if not f:
                if order:
                    break
                continue
            if keys and f["key"] == keys[0] and len(keys) > 1:
                break                                         # wrapped around to the first element: a full cycle
            if len(keys) >= 3 and f["key"] in keys[-2:] and f["key"] != keys[-1]:
                trap = f["label"]
            keys.append(f["key"])
            order.append({"label": f["label"], "element": f["sel"], "ring": f["ring"]})
        reached = {o["label"] for o in order}
        unreachable = [i for i in interactive if i["label"] not in reached and (not i["native"] and (i["tabindex"] is None or i["tabindex"] < 0))]
        missed_native = [i for i in interactive if i["native"] and i["label"] not in reached and (i["tabindex"] is None or i["tabindex"] >= 0)]
        positive = [i["label"] for i in interactive if (i["tabindex"] or 0) > 0]
        no_ring = [o["label"] for o in order if not o["ring"]]
        return {"order": order, "unreachable": unreachable + missed_native, "no_focus_ring": no_ring, "positive_tabindex": positive,
                "trap": trap, "ok": not (unreachable or missed_native or trap)}
    finally:
        await b.close()
        await pw.stop()


DEVICES = [("telefon", 375, 812, True), ("tablet", 768, 1024, True), ("notebook", 1366, 768, False), ("monitor", 1920, 1080, False)]

LAYOUT_JS = """(phone) => {
  const W = document.documentElement.clientWidth;
  const over = [], small = [], tiny = [];
  document.querySelectorAll('body *').forEach(e => {
    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    if (r.width === 0 || r.height === 0 || cs.visibility === 'hidden') return;
    if (r.right > W + 1 && cs.position !== 'fixed') over.push((e.tagName.toLowerCase() + (e.id ? '#' + e.id : '')) + ' (' + Math.round(r.right - W) + ' px)');
    if (e.matches('a[href], button, input, select, [role=button]') && phone && (r.width < 32 || r.height < 32))
      small.push((e.innerText || e.getAttribute('aria-label') || e.tagName).trim().slice(0, 30));
    if (e.childNodes.length && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) && parseFloat(cs.fontSize) < 12)
      tiny.push((e.innerText || '').trim().slice(0, 30));
  });
  return {scroll_x: document.documentElement.scrollWidth > W + 1, page_width: document.documentElement.scrollWidth, width: W,
          overflowing: over.slice(0, 10), small_targets: small.slice(0, 10), tiny_text: tiny.slice(0, 10)};
}"""


async def device_matrix(url: str, out_dir: Path) -> dict:
    """OMEGA 638: the page on a phone, tablet, laptop and monitor – a screenshot each, horizontal scrolling, elements
    sticking out, touch targets under 32 px, text under 12 px."""
    pw, b = await headless()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for name, w, h, mobile in DEVICES:
            ctx = await b.new_context(viewport={"width": w, "height": h}, is_mobile=mobile, has_touch=mobile, device_scale_factor=1)
            page = await ctx.new_page()
            await page.goto(page_url(url), wait_until="load", timeout=30000)
            lay = await page.evaluate(LAYOUT_JS, mobile)
            shot = out_dir / f"{name}-{w}x{h}.png"
            await page.screenshot(path=str(shot), full_page=False)
            rows.append({"device": name, "size": f"{w}×{h}", "screenshot": str(shot), **lay,
                         "ok": not (lay["scroll_x"] or lay["small_targets"])})
            await ctx.close()
    finally:
        await b.close()
        await pw.stop()
    return {"devices": rows, "ok": all(r["ok"] for r in rows)}


async def offline_test(url: str) -> dict:
    """OMEGA 641: load the page, cut the network, reload – does it still work (service worker / cache), what errors?"""
    pw, b = await headless()
    try:
        ctx = await b.new_context()
        page = await ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        await page.goto(page_url(url), wait_until="load", timeout=30000)
        online_text = (await page.evaluate("() => document.body ? document.body.innerText : ''"))[:2000]
        sw = await page.evaluate("async () => !!(navigator.serviceWorker && (await navigator.serviceWorker.getRegistrations()).length)")
        if sw:
            await page.wait_for_timeout(1500)
        await ctx.set_offline(True)
        reload_error = ""
        try:
            await page.reload(wait_until="load", timeout=15000)
        except Exception as e:  # noqa: BLE001 – the browser's own "no internet" is the expected failure
            reload_error = str(e).splitlines()[0][:200]
        off_text = ""
        try:
            off_text = (await page.evaluate("() => document.body ? document.body.innerText : ''"))[:2000]
        except Exception:  # noqa: BLE001
            pass
        works = not reload_error and bool(off_text.strip()) and off_text[:200] == online_text[:200]
        await ctx.set_offline(False)
        return {"works_offline": works, "service_worker": sw, "reload_error": reload_error, "console_errors": errors[:10],
                "offline_text": off_text[:300]}
    finally:
        await b.close()
        await pw.stop()


STEP_RX = [
    ("goto", r"(?i)^(?:jdi na|otevři|open|goto)\s+(.+)$"),
    ("fill", r"(?i)^(?:vyplň|napiš do|fill)\s+(.+?)\s*[=:]\s*(.*)$"),
    ("click", r"(?i)^(?:klikni(?: na)?|stiskni|click)\s+(.+)$"),
    ("press", r"(?i)^(?:klávesa|press)\s+(.+)$"),
    ("expect", r"(?i)^(?:očekávej|ověř|zkontroluj|expect)\s+(.+)$"),
    ("expect_not", r"(?i)^(?:nesmí být|expect not)\s+(.+)$"),
    ("wait", r"(?i)^(?:počkej|wait)\s+(\d+)"),
]


def parse_steps(steps: list[str]) -> list[tuple[str, list[str]]]:
    out = []
    for s in steps:
        s = s.strip().strip('"').strip()
        for kind, rx in STEP_RX:
            m = re.match(rx, s)
            if m:
                out.append((kind, [g.strip().strip('"„“') for g in m.groups()]))
                break
        else:
            raise ValueError(f"Krok „{s}“ nerozumím. Umím: jdi na …, vyplň X = Y, klikni na X, klávesa Enter, očekávej text, nesmí být text, počkej 500.")
    return out


async def user_flow(url: str, steps: list[str], out_dir: Path) -> dict:
    """OMEGA 631 / 645: a scripted user scenario in a clean browser, a screenshot after every step as evidence; stops
    at the first failing step and says why."""
    plan = parse_steps(steps)
    out_dir.mkdir(parents=True, exist_ok=True)
    pw, b = await headless()
    results = []
    try:
        page = await b.new_page()
        base = page_url(url)
        await page.goto(base, wait_until="load", timeout=30000)
        for i, (kind, args) in enumerate(plan, 1):
            t0 = time.perf_counter()
            ok, err = True, ""
            try:
                if kind == "goto":
                    target = args[0] if re.match(r"https?://|file:", args[0]) else base.rstrip("/") + "/" + args[0].lstrip("/")
                    await page.goto(target, wait_until="load", timeout=30000)
                elif kind == "fill":
                    loc = page.get_by_label(args[0]).or_(page.get_by_placeholder(args[0])).first
                    await loc.fill(args[1], timeout=5000)
                elif kind == "click":
                    loc = page.get_by_role("button", name=args[0]).or_(page.get_by_role("link", name=args[0])).or_(page.get_by_text(args[0], exact=False)).first
                    await loc.click(timeout=5000)
                elif kind == "press":
                    await page.keyboard.press(args[0])
                elif kind == "expect":
                    await page.get_by_text(args[0], exact=False).first.wait_for(state="visible", timeout=5000)
                elif kind == "expect_not":
                    await page.wait_for_timeout(300)
                    if await page.get_by_text(args[0], exact=False).count():
                        raise AssertionError(f"„{args[0]}“ na stránce je")
                elif kind == "wait":
                    await page.wait_for_timeout(min(int(args[0]), 10000))
            except Exception as e:  # noqa: BLE001 – a failing step is the result, not a crash
                ok, err = False, str(e).splitlines()[0][:200]
            shot = out_dir / f"krok-{i:02d}.png"
            await page.screenshot(path=str(shot))
            results.append({"step": steps[i - 1], "ok": ok, "error": err, "ms": round((time.perf_counter() - t0) * 1000), "screenshot": str(shot)})
            if not ok:
                break
    finally:
        await b.close()
        await pw.stop()
    return {"ok": all(r["ok"] for r in results) and len(results) == len(plan), "steps": results, "total": len(plan)}
