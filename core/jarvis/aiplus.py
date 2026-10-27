"""Wave 40 – local AI and the integration gateway.

* CPU/GPU split (OMEGA 574): how many layers of a local model fit the graphics card; the rest runs on the processor
* inference queue (577): the local model serves one request at a time – your chat first, background jobs wait
* response cache (584): repeated background questions (summaries of the same text…) answered from a local cache
* adaptive resources (P15.10): while a game runs full-screen or the laptop is low on battery, local models step aside
* offline knowledge packs (579): your own folders / zips of documents installed as named, searchable packs
* webhooks (590): other services call JARVIS at a secret URL – a notification, an automation, or a message for review
* event replay (599): recorded events replayed as a dry run – which automations would fire
* integration sandbox (593): an OpenAPI connector called against a mock built from its own spec – no live data
* connector SDK (600): a curl command turned into a connector you can call by voice
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hashlib
import hmac
import json
import re
import secrets
import shlex
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

from . import paths

# ---------------------------------------------------------------- 574 CPU / GPU split
def gpu_layers(params_b: float, vram_gb: float, layers: int = 0, quant_bits: float = 4.5, ctx: int = 4096, reserve_gb: float = 0.8) -> dict:
    """Layers to offload to the GPU (Ollama num_gpu). The KV cache and runtime overhead stay reserved."""
    from .localai import kv_cache_gb

    layers = layers or max(16, round(16 + params_b * 1.6))          # ~32 for 7–8 B, ~40 for 14 B, ~64 for 32 B
    model_gb = params_b * quant_bits / 8 * 1.07
    free = vram_gb - reserve_gb - kv_cache_gb(params_b, ctx)
    per = model_gb / layers
    n = max(0, min(layers, int(free / per))) if per > 0 else 0
    share = n / layers if layers else 0
    mode = "celý model na grafice" if n >= layers else "jen procesor" if n == 0 else "napůl grafika / procesor"
    # throughput: GPU part ~8× faster than CPU part; the slow part dominates
    speed = 1 / ((1 - share) * 1.0 + share * 0.125) if share < 1 else 8.0
    return {"layers": layers, "gpu_layers": n, "share": round(share, 2), "mode": mode, "model_gb": round(model_gb, 1),
            "relative_speed": round(speed, 1)}


# ---------------------------------------------------------------- 577 inference queue
PRIORITY: contextvars.ContextVar[str] = contextvars.ContextVar("ai_priority", default="interactive")


class InferenceQueue:
    """One local inference at a time; interactive requests always go before background ones."""

    def __init__(self):
        self._busy = False
        self._waiting: list[tuple[int, int, asyncio.Future]] = []
        self._seq = 0
        self.served = {"interactive": 0, "background": 0}
        self.wait_ms: list[float] = []

    @contextlib.asynccontextmanager
    async def slot(self, priority: str | None = None):
        prio = priority or PRIORITY.get()
        t0 = time.monotonic()
        if self._busy:
            fut = asyncio.get_running_loop().create_future()
            self._seq += 1
            entry = (0 if prio == "interactive" else 1, self._seq, fut)
            self._waiting.append(entry)
            self._waiting.sort(key=lambda w: w[:2])
            try:
                await fut
            except asyncio.CancelledError:
                if entry in self._waiting:
                    self._waiting.remove(entry)
                elif fut.done() and not fut.cancelled():
                    self._release()                         # the slot was already handed to us – pass it on
                raise
        self._busy = True
        self.wait_ms = (self.wait_ms + [(time.monotonic() - t0) * 1000])[-50:]
        self.served[prio if prio in self.served else "background"] += 1
        try:
            yield
        finally:
            self._release()

    def _release(self) -> None:
        while self._waiting:
            _, _, nxt = self._waiting.pop(0)
            if not nxt.done():
                nxt.set_result(True)
                return
        self._busy = False

    def status(self) -> dict:
        return {"busy": self._busy, "waiting": len(self._waiting), "served": dict(self.served),
                "avg_wait_ms": round(sum(self.wait_ms) / len(self.wait_ms), 1) if self.wait_ms else 0}


@contextlib.contextmanager
def background():
    """Mark the AI calls inside as background work (they wait for the user's own requests)."""
    tok = PRIORITY.set("background")
    try:
        yield
    finally:
        PRIORITY.reset(tok)


# ---------------------------------------------------------------- 584 response cache
CACHE_SQL = "CREATE TABLE IF NOT EXISTS ai_cache (k TEXT PRIMARY KEY, text TEXT, ts REAL, hits INTEGER DEFAULT 0)"


class AICache:
    def __init__(self, db, ttl_s: float = 7 * 86400, max_rows: int = 2000):
        self.db, self.ttl, self.max = db, ttl_s, max_rows
        db.exec(CACHE_SQL)

    @staticmethod
    def key(messages: list[dict], **kw) -> str:
        return hashlib.sha256(json.dumps([messages, kw], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    def get(self, k: str) -> str | None:
        r = self.db.one("SELECT text, ts FROM ai_cache WHERE k=?", (k,))
        if not r or time.time() - r["ts"] > self.ttl:
            return None
        self.db.exec("UPDATE ai_cache SET hits=hits+1 WHERE k=?", (k,))
        return r["text"]

    def put(self, k: str, text: str) -> None:
        if not text.strip():
            return
        self.db.exec("INSERT OR REPLACE INTO ai_cache (k, text, ts, hits) VALUES (?,?,?,0)", (k, text, time.time()))
        n = self.db.one("SELECT COUNT(*) AS n FROM ai_cache")["n"]
        if n > self.max:
            self.db.exec("DELETE FROM ai_cache WHERE k IN (SELECT k FROM ai_cache ORDER BY ts LIMIT ?)", (n - self.max,))

    def stats(self) -> dict:
        r = self.db.one("SELECT COUNT(*) AS n, COALESCE(SUM(hits), 0) AS hits FROM ai_cache")
        return {"entries": r["n"], "hits": r["hits"]}

    def clear(self) -> int:
        return self.db.exec("DELETE FROM ai_cache").rowcount


# ---------------------------------------------------------------- P15.10 adaptive resources
def local_should_yield(snapshot: dict) -> str:
    """Reason to keep local models out of the way right now ('' = no reason)."""
    if snapshot.get("fullscreen"):
        return "běží hra nebo video přes celou obrazovku"
    bat = snapshot.get("battery")
    if bat is not None and bat < 30 and not snapshot.get("plugged", True):
        return f"notebook má jen {bat:.0f} % baterie"
    if snapshot.get("ram_percent", 0) > 92:
        return "dochází paměť RAM"
    return ""


def install(rt) -> None:
    """Hook the queue, the cache and the adaptive gate into the AI router."""
    router = rt.router
    if getattr(router, "_aiplus", False):
        return
    router._aiplus = True
    router.local_queue = InferenceQueue()
    router.cache = AICache(rt.db)
    prev_gate = router.gate
    state = {"why": "", "t": 0.0}

    def snapshot() -> dict:
        import psutil

        b = psutil.sensors_battery()
        snap = {"battery": b.percent if b else None, "plugged": b.power_plugged if b else True, "ram_percent": psutil.virtual_memory().percent}
        try:
            from .desktop.winutil import foreground_is_fullscreen

            snap["fullscreen"] = foreground_is_fullscreen()
        except Exception:  # noqa: BLE001
            snap["fullscreen"] = False
        return snap

    def gate(p) -> str:
        why = prev_gate(p) if prev_gate else ""
        if why:
            return why
        from .llm.presets import PRESETS

        if not getattr(rt.cfg.brain, "adaptive_local", True) or not PRESETS.get(p.preset, {}).get("local"):
            return ""
        others = [x for x in router.providers() if not PRESETS.get(x.preset, {}).get("local")]
        if not others or rt.cfg.brain.offline_only:
            return ""                                           # nothing else to use: keep the local model
        if time.monotonic() - state["t"] > 20:
            try:
                state["why"] = local_should_yield(snapshot())
            except Exception:  # noqa: BLE001
                state["why"] = ""
            state["t"] = time.monotonic()
        return f"místní model teď ustupuje – {state['why']}" if state["why"] else ""
    router.gate = gate


# ---------------------------------------------------------------- 579 offline knowledge packs
def packs_dir() -> Path:
    return paths.sub("packs")


def list_packs() -> list[dict]:
    out = []
    for d in sorted(p for p in packs_dir().iterdir() if p.is_dir()):
        meta = json.loads((d / "pack.json").read_text(encoding="utf-8")) if (d / "pack.json").is_file() else {}
        files = [f for f in d.rglob("*") if f.is_file() and f.name != "pack.json"]
        out.append({"name": d.name, "files": len(files), "mb": round(sum(f.stat().st_size for f in files) / 2**20, 1),
                    "source": meta.get("source", ""), "added": meta.get("added"), "enabled": meta.get("enabled", True)})
    return out


TEXTY = {".txt", ".md", ".pdf", ".docx", ".html", ".htm", ".csv", ".json", ".odt", ".rtf", ".epub", ".xlsx", ".pptx"}


def install_pack(source: Path, name: str, max_mb: float = 2048) -> dict:
    """Copy a folder or unpack a zip of documents into a named pack (only document types, size-capped, no traversal)."""
    import shutil

    name = re.sub(r"[^\w -]", "", name).strip()[:40] or source.stem
    dest = packs_dir() / name
    if dest.exists():
        raise ValueError(f"Balíček „{name}“ už existuje.")
    total, copied = 0, 0
    dest.mkdir(parents=True)
    try:
        if source.is_file() and source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as z:
                for info in z.infolist():
                    p = Path(info.filename)
                    if info.is_dir() or p.is_absolute() or ".." in p.parts or p.suffix.lower() not in TEXTY:
                        continue
                    total += info.file_size
                    if total > max_mb * 2**20:
                        raise ValueError(f"Balíček je větší než {max_mb:g} MB.")
                    out = dest / p
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, out.open("wb") as fh:
                        shutil.copyfileobj(src, fh)
                    copied += 1
        elif source.is_dir():
            for f in source.rglob("*"):
                if f.is_file() and f.suffix.lower() in TEXTY and not f.is_symlink():
                    total += f.stat().st_size
                    if total > max_mb * 2**20:
                        raise ValueError(f"Balíček je větší než {max_mb:g} MB.")
                    out = dest / f.relative_to(source)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, out)
                    copied += 1
        else:
            raise ValueError("Balíček musí být složka nebo .zip s dokumenty.")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    (dest / "pack.json").write_text(json.dumps({"source": str(source), "added": time.time(), "enabled": True}, ensure_ascii=False), encoding="utf-8")
    return {"name": name, "files": copied, "mb": round(total / 2**20, 1), "path": str(dest)}


def remove_pack(name: str) -> bool:
    import shutil

    d = packs_dir() / name
    if not d.is_dir() or d.parent != packs_dir():
        return False
    shutil.rmtree(d)
    return True


# ---------------------------------------------------------------- 590 webhooks
def new_webhook(name: str, action: str = "notify") -> dict:
    if action not in ("notify", "automation"):
        raise ValueError("Akce: notify (upozornění) / automation (jen spustí automatizace).")
    return {"id": secrets.token_hex(6), "name": name.strip()[:60] or "Webhook", "secret": secrets.token_urlsafe(24), "action": action}


def verify_webhook(hook: dict, body: bytes, token: str = "", signature: str = "") -> bool:
    """A shared secret as ?token= / X-Jarvis-Token, or an HMAC-SHA256 signature of the body (X-Hub-Signature-256 style)."""
    secret = hook.get("secret", "")
    if token and hmac.compare_digest(token, secret):
        return True
    if signature:
        sig = signature.split("=", 1)[-1].strip()
        mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, mac)
    return False


def summarize_payload(body: bytes, limit: int = 600) -> dict:
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        return {"text": body.decode("utf-8", "replace")[:limit], "data": None}
    flat = []

    def walk(x, pre=""):
        if len(flat) > 40:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{pre}{k}.")
        elif isinstance(x, list):
            for i, v in enumerate(x[:5]):
                walk(v, f"{pre}{i}.")
        else:
            flat.append(f"{pre[:-1]}: {str(x)[:120]}")
    walk(data)
    return {"text": "; ".join(flat)[:limit], "data": data}


_HOOK_HITS: dict[str, list[float]] = {}


def secret_key(hook_id: str) -> str:
    return f"webhook:{hook_id}"


def handle_webhook(rt, hook_id: str, body: bytes, token: str = "", signature: str = "") -> tuple[int, str]:
    """An incoming webhook: check the secret, rate-limit, then an event for automations (+ a notice). The payload is DATA –
    it never becomes an instruction for the AI."""
    from . import secrets as vault

    hook = next((h for h in rt.cfg.integrations.webhooks if h.id == hook_id and h.enabled), None)
    if hook is None:
        return 404, "neznámý webhook"
    if len(body) > 256 * 1024:
        return 413, "příliš velké"
    secret = vault.get(secret_key(hook.id)) or ""
    if not secret or not verify_webhook({"secret": secret}, body, token, signature):
        return 401, "špatný klíč"
    now = time.monotonic()
    hits = [t for t in _HOOK_HITS.get(hook.id, []) if now - t < 60] + [now]
    _HOOK_HITS[hook.id] = hits
    if len(hits) > 30:
        return 429, "příliš mnoho požadavků"
    info = summarize_payload(body)
    rt.bus.publish("webhook", name=hook.name, hook=hook.id, text=info["text"])
    if hook.action == "notify":
        rt.notify(f"Webhook {hook.name}", info["text"][:200] or "(prázdný)", speak=False)
    return 200, "ok"


EVENTS_SQL = "CREATE TABLE IF NOT EXISTS event_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, type TEXT, data TEXT)"


def record_event(rt, ev: dict) -> None:
    rt.db.exec(EVENTS_SQL)
    keep = {k: (v[:500] if isinstance(v, str) else v) for k, v in ev.items() if k not in ("body", "html", "raw", "data")}
    rt.db.exec("INSERT INTO event_log (ts, type, data) VALUES (?,?,?)", (time.time(), ev.get("type", ""), json.dumps(keep, ensure_ascii=False, default=str)[:8000]))
    rt.db.exec("DELETE FROM event_log WHERE id NOT IN (SELECT id FROM event_log ORDER BY id DESC LIMIT 500)")


def recent_events(rt, kind: str = "", limit: int = 30) -> list[dict]:
    rt.db.exec(EVENTS_SQL)
    rows = rt.db.all("SELECT * FROM event_log " + ("WHERE type=? " if kind else "") + "ORDER BY id DESC LIMIT ?", ((kind, limit) if kind else (limit,)))
    return [{**r, "data": json.loads(r["data"])} for r in rows]


def replay(rt, event_id: int) -> dict:
    """599: which automations this recorded event would start – a dry run, nothing is executed."""
    from .automations import describe_trigger, match_event

    rt.db.exec(EVENTS_SQL)
    row = rt.db.one("SELECT * FROM event_log WHERE id=?", (event_id,))
    if not row:
        raise KeyError(f"Událost č. {event_id} neznám.")
    ev = json.loads(row["data"])
    hits = []
    for a in rt.cfg.automations.items:
        if not getattr(a, "enabled", True):
            continue
        vars_ = match_event(a, ev)
        if vars_ is not None:
            hits.append({"automation": a.name, "trigger": describe_trigger(a.trigger), "vars": vars_})
    return {"event": ev, "would_fire": hits}


# ---------------------------------------------------------------- 593 sandbox for connectors
def example_for(spec: dict, schema: Any, depth: int = 0) -> Any:
    from .devlab import _ref

    s = _ref(spec, schema) if isinstance(schema, dict) else {}
    if not isinstance(s, dict) or depth > 6:
        return None
    if "example" in s:
        return s["example"]
    if s.get("enum"):
        return s["enum"][0]
    t = s.get("type") or ("object" if "properties" in s else "array" if "items" in s else "string")
    if t == "object":
        return {k: example_for(spec, v, depth + 1) for k, v in (s.get("properties") or {}).items()}
    if t == "array":
        return [example_for(spec, s.get("items") or {}, depth + 1)]
    return {"integer": 1, "number": 1.5, "boolean": True}.get(t, "text")


def mock_transport(spec: dict, calls: list, base_path: str = ""):
    """An httpx transport that answers every operation of the spec with an example built from its response schema."""
    import httpx

    from .devlab import _match_path, response_schema

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"method": request.method, "url": str(request.url), "headers": dict(request.headers),
                      "body": request.content.decode("utf-8", "replace")[:2000]})
        path = request.url.path
        if base_path and path.startswith(base_path.rstrip("/")):
            path = path[len(base_path.rstrip("/")):] or "/"
        if not _match_path(spec, path):
            return httpx.Response(404, json={"error": "operace ve specifikaci není"})
        for code in (200, 201, 204):
            try:
                _, schema = response_schema(spec, path, request.method, code)
            except ValueError:
                continue
            return httpx.Response(code, json=example_for(spec, schema) if schema else {"ok": True})
        return httpx.Response(405, json={"error": "metoda ve specifikaci není"})
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------- 600 connector from curl
def curl_to_spec(curl: str) -> dict:
    """`curl -X POST https://api.x.com/v1/items?q=1 -H 'Authorization: Bearer …' -d '{"a":1}'` → OpenAPI with one operation.
    Header values that look like secrets are never kept – the connector asks for its key separately."""
    args = shlex.split(curl.replace("\\\n", " "))
    if not args or args[0] != "curl":
        raise ValueError("Čekám příkaz začínající „curl“.")
    method, url, headers, body = "", "", {}, None
    i = 1
    while i < len(args):
        a = args[i]
        if a in ("-X", "--request"):
            method, i = args[i + 1].upper(), i + 1
        elif a in ("-H", "--header"):
            k, _, v = args[i + 1].partition(":")
            headers[k.strip()] = v.strip()
            i += 1
        elif a in ("-d", "--data", "--data-raw", "--json"):
            body, i = args[i + 1], i + 1
            if a == "--json":
                headers.setdefault("Content-Type", "application/json")
        elif not a.startswith("-") and not url:
            url = a
        i += 1
    if not url.startswith(("http://", "https://")):
        raise ValueError("V příkazu nevidím adresu http(s).")
    method = method or ("POST" if body is not None else "GET")
    u = urllib.parse.urlsplit(url)
    params = [{"name": k, "in": "query", "schema": {"type": "string"}, "example": v} for k, v in urllib.parse.parse_qsl(u.query)]
    auth = "none"
    header_name = ""
    dropped: list[str] = []
    for k, v in list(headers.items()):
        if k.lower() == "authorization":
            auth = "bearer" if v.lower().startswith("bearer") else "header"
            header_name = "Authorization"
            dropped.append(v.split(" ", 1)[-1])
            headers.pop(k)
        elif re.search(r"key|token|secret|auth", k, re.I):
            auth, header_name = "header", k
            dropped.append(v)
            headers.pop(k)
    for p in list(params):
        if re.search(r"key|token|secret|signature", p["name"], re.I):
            auth, header_name = "query", p["name"]
            dropped.append(str(p.pop("example", "")))
            params.remove(p)
    op = {"operationId": re.sub(r"\W+", "_", f"{method.lower()}_{u.path.strip('/')}").strip("_")[:60] or "call",
          "summary": f"{method} {u.path}", "parameters": params, "responses": {"200": {"description": "OK"}}}
    if body is not None:
        try:
            ex = json.loads(body)
        except ValueError:
            ex = body
        op["requestBody"] = {"content": {"application/json": {"schema": {"type": "object"}, "example": ex}}}
    spec = {"openapi": "3.0.0", "info": {"title": u.netloc, "version": "1"}, "servers": [{"url": f"{u.scheme}://{u.netloc}"}],
            "paths": {u.path or "/": {method.lower(): op}}}
    return {"spec": spec, "base_url": f"{u.scheme}://{u.netloc}", "auth": auth, "header": header_name, "operation": op["operationId"],
            "dropped_secret": auth != "none", "secret_values": [v for v in dropped if v]}
