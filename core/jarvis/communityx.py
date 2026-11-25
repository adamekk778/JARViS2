"""3.20 Komunita+ (ideas 481–500): monthly challenges, ratings of extensions, shared personality templates, a demo mode
without accounts, an encrypted backup to your own cloud (WebDAV / Nextcloud), a portable install, and company
deployment (a policy file the IT department controls: settings, locked keys and a status report).

Store accounts, a code-signing certificate, a forum and videos are not something code can make – the docs say what is
needed for each."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import socket
import tempfile
import time
from pathlib import Path
from typing import Any

# ------------------------------------------------------------------ (481) community challenges
CHALLENGES = [
    ("Nejlepší ranní rutina", "Postav rutinu, která tě ráno připraví na den (počasí, kalendář, doprava, hudba). Sdílej ji jako balíček."),
    ("Reflex na jedno slovo", "Najdi povel, který řekneš denně, a udělej z něj reflex bez AI. Kdo ušetří nejvíc času?"),
    ("Úsporný domov", "Automatizace, která za měsíc ušetří nejvíc kWh. Pošli graf spotřeby před a po."),
    ("Dílna bez chyb", "Kontrolní seznam před tiskem, který chytí nejvíc chyb. Sdílej ho jako dovednost."),
    ("Přístupný JARVIS", "Nastavení nebo rutina, která pomůže člověku se zrakovým, sluchovým nebo pohybovým omezením."),
    ("Rodinný kalendář", "Nejšikovnější rozdělení úkolů a vyzvedávání dětí v rodině."),
    ("Klidný večer", "Rutina, která večer ztlumí světla, telefon a obrazovky a připraví spánek."),
    ("Rychlá firma", "Automatizace, která malé firmě ušetří nejvíc administrativy za týden."),
    ("Výlet jedním povelem", "Jeden povel, který naplánuje celý výlet: trasu, počasí, jídlo a návrat."),
    ("Bezpečný domov", "Nejlepší kombinace hlídání: zámky, okna, kamery – bez falešných poplachů."),
    ("Učení s JARVISem", "Rutina, se kterou se nejlíp učí slovíčka nebo do školy."),
    ("Hlasový kouzelník", "Nejpraktičtější hlasový povel, na který by nikdo nepřišel."),
]


def challenge_of(day: dt.date) -> dict:
    title, text = CHALLENGES[(day.year * 12 + day.month) % len(CHALLENGES)]
    end = (day.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return {"title": title, "text": text, "month": f"{day.month:02d}/{day.year}", "ends": end.isoformat(), "days_left": (end - day).days}


# ------------------------------------------------------------------ (483) ratings of extensions
def rate(rt: Any, skill: str, stars: int, note: str = "") -> dict:
    if not 1 <= int(stars) <= 5:
        raise ValueError("Hodnocení je 1 až 5 hvězdiček.")
    row = rt.db.one("SELECT v FROM kv WHERE k='cx_ratings'")
    data = json.loads(row["v"]) if row else {}
    data[skill.strip().lower()] = {"stars": int(stars), "note": note[:300], "ts": time.time()}
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('cx_ratings', ?)", (json.dumps(data, ensure_ascii=False),))
    return data[skill.strip().lower()]


def ratings(rt: Any) -> dict[str, dict]:
    row = rt.db.one("SELECT v FROM kv WHERE k='cx_ratings'")
    return json.loads(row["v"]) if row else {}


def catalog_view(items: list[dict], mine: dict[str, dict]) -> list[dict]:
    """A catalog's items with their community score (from the catalog JSON: rating, votes), your own stars and whether the
    package is signed – the best first."""
    out = []
    for it in items:
        name = str(it.get("name", ""))
        votes = int(it.get("votes", 0) or 0)
        score = float(it.get("rating", 0) or 0)
        bayes = (score * votes + 3.5 * 5) / (votes + 5)              # a few votes do not beat many good ones
        out.append({**it, "community": round(score, 1) if votes else None, "votes": votes, "mine": (mine.get(name.lower()) or {}).get("stars"),
                    "signed": bool(it.get("signature") or it.get("signed")), "rank": round(bayes, 3)})
    return sorted(out, key=lambda x: (-x["signed"], -x["rank"]))


# ------------------------------------------------------------------ (492) personality templates
PERSONA_KEYS = ("name", "prompt", "voice", "rate", "pitch", "greeting", "author", "license")


def persona_export(rt: Any, name: str, author: str = "") -> dict:
    g = rt.cfg.general
    v = rt.cfg.voice
    if g.personality != "custom" or not g.custom_prompt.strip():
        raise ValueError("Sdílet jde vlastní osobnost (Nastavení → Obecné → Osobnost → Vlastní).")
    return {"format": "jarvis-persona/1", "name": name.strip()[:60], "prompt": g.custom_prompt.strip()[:4000], "voice": v.tts_voice,
            "rate": v.tts_rate, "pitch": v.tts_pitch, "author": author[:60], "license": "CC BY 4.0"}


def persona_check(data: Any) -> dict:
    """A shared personality is only text and a voice name – nothing that runs. Long or odd content is refused."""
    if not isinstance(data, dict) or data.get("format") != "jarvis-persona/1":
        raise ValueError("Tohle není šablona osobnosti JARVISe.")
    clean = {k: data[k] for k in PERSONA_KEYS if k in data}
    if not isinstance(clean.get("prompt"), str) or not clean["prompt"].strip() or len(clean["prompt"]) > 4000:
        raise ValueError("Šablona nemá platný popis osobnosti.")
    low = clean["prompt"].lower()
    if any(w in low for w in ("ignore previous", "ignoruj předchozí", "system prompt", "api key", "heslo", "password", "tool_call", "<script")):
        raise ValueError("Šablona obsahuje pokyny, které by měnily pravidla JARVISe – nenačtu ji.")
    if clean.get("voice") and not re.match(r"^[a-z]{2}-[A-Z]{2}-[A-Za-z]+Neural$", str(clean["voice"])):
        clean.pop("voice")
    return clean


def persona_import(rt: Any, data: Any) -> str:
    p = persona_check(data)
    patch: dict[str, Any] = {"general": {"personality": "custom", "custom_prompt": p["prompt"]}}
    if p.get("voice"):
        patch["voice"] = {"tts_voice": p["voice"]}
    rt.update_config(patch)
    return str(p.get("name") or "osobnost")


# ------------------------------------------------------------------ (490) portable, (497) demo
def portable_base(executable: str, frozen: bool, env: Any = os.environ) -> Path | None:
    """A copy on a USB stick: a file portable.txt next to JARVIS.exe → everything is kept in the 'data' folder beside it."""
    if env.get("JARVIS_PORTABLE") == "1":
        return Path(executable).resolve().parent / "data"
    if frozen and (Path(executable).resolve().parent / "portable.txt").exists():
        return Path(executable).resolve().parent / "data"
    return None


def demo_on(env: Any = os.environ) -> bool:
    return env.get("JARVIS_DEMO") == "1"


def demo_base() -> Path:
    return Path(tempfile.gettempdir()) / f"jarvis-demo-{os.getpid()}"


DEMO_LISTS = {"nákup": ["mléko", "chleba", "jablka", "káva"], "filmy": ["Interstellar", "Pelíšky"]}


def seed_demo(rt: Any, now: dt.datetime | None = None) -> int:
    """Made-up data so a friend can try JARVIS: a few events, two lists and a note. Nothing real is touched."""
    from .tools.list_tools import add_items

    now = now or dt.datetime.now()
    n = 0
    for title, delta_h in (("Porada s týmem", 2), ("Zubař", 26), ("Kino s přáteli", 50)):
        rt.calendar.add(title, (now + dt.timedelta(hours=delta_h)).replace(minute=0, second=0, microsecond=0), 60)
        n += 1
    for name, items in DEMO_LISTS.items():
        add_items(rt, name, items)
        n += len(items)
    return n


DEMO_REFUSAL = "Tohle je ukázkový režim – nic se doopravdy neodesílá, nekupuje ani nemaže. Vyzkoušej to v plném JARVISovi."


# ------------------------------------------------------------------ (498) encrypted backup to your own cloud
async def cloud_backup(rt: Any, client=None) -> dict:
    """The encrypted backup (AES-256-GCM, your password) uploaded to your WebDAV – Nextcloud, ownCloud, a NAS, Koofr…
    The storage only ever sees the encrypted file."""
    import httpx

    from . import privacy, secrets

    c = rt.cfg.communityx
    pw = secrets.get("backup_password")
    if not c.cloud_url or not pw:
        raise ValueError("Nastav adresu úložiště (WebDAV) a heslo zálohy (Nastavení → Záloha → Do vlastního cloudu).")
    folder = Path(tempfile.mkdtemp(prefix="jarvis-cloud-"))
    try:
        f = privacy.backup_encrypted(pw, folder)
        url = c.cloud_url.rstrip("/") + f"/JARVIS-{dt.date.today().isoformat()}{f.suffix}"
        own = client is None
        cl = client or httpx.AsyncClient(timeout=300)
        try:
            r = await cl.put(url, content=f.read_bytes(), auth=(secrets.get("cloud_user") or "", secrets.get("cloud_password") or ""))
            if r.status_code not in (200, 201, 204):
                raise ValueError(f"Úložiště odpovědělo {r.status_code}.")
        finally:
            if own:
                await cl.aclose()
        size = f.stat().st_size
    finally:
        for p in folder.glob("*"):
            p.unlink()
        folder.rmdir()
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('cx_cloud_last', ?)", (dt.date.today().isoformat(),))
    return {"url": url, "bytes": size}


# ------------------------------------------------------------------ (500) company deployment
def load_policy(source: str, read=None) -> dict:
    """The company's policy: a JSON file on a share (\\\\server\\jarvis\\policy.json) or a URL the IT department manages.
    {"settings": {...}, "locked": ["brain.chain", ...], "report_url": "...", "message": "..."}"""
    if source.startswith(("http://", "https://")):
        import httpx

        r = (read or httpx.get)(source, timeout=15)
        r.raise_for_status()
        data = r.json()
    else:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Zásady nejsou JSON objekt.")
    locked = [k for k in data.get("locked", []) if isinstance(k, str) and re.match(r"^[a-z_]+(\.[a-z_]+)+$", k)]
    return {"settings": data.get("settings") or {}, "locked": locked, "report_url": str(data.get("report_url") or ""),
            "message": str(data.get("message") or "")[:300]}


def strip_locked(patch: dict, locked: list[str], prefix: str = "") -> tuple[dict, list[str]]:
    """The patch without the keys the company locked (they stay as the policy says)."""
    out: dict = {}
    dropped: list[str] = []
    for k, v in patch.items():
        path = f"{prefix}{k}"
        if path in locked:
            dropped.append(path)
            continue
        if isinstance(v, dict) and any(lk.startswith(path + ".") for lk in locked):
            sub, d = strip_locked(v, locked, path + ".")
            dropped += d
            if sub:
                out[k] = sub
        else:
            out[k] = v
    return out, dropped


def apply_policy(rt: Any, policy: dict) -> dict:
    rt._policy_locked = list(policy["locked"])
    rt._applying_policy = True
    try:
        if policy["settings"]:
            rt.update_config(policy["settings"])
    finally:
        rt._applying_policy = False
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('cx_policy', ?)", (json.dumps({"locked": policy["locked"], "at": time.time()}),))
    return {"locked": len(policy["locked"]), "settings": len(policy["settings"])}


def status_report(rt: Any) -> dict:
    from . import __version__, reliax

    sc = reliax.score(rt)
    return {"host": socket.gethostname(), "version": __version__, "score": sc["score"], "problems": [p["what"] for p in sc["problems"][:5]],
            "ts": int(time.time())}


async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    from .proactiveplus import due_today

    now = now or dt.datetime.now()
    c = getattr(rt.cfg, "communityx", None)
    said: list[str] = []
    if c is None:
        return said
    if c.policy_source and due_today(rt, "cx_policy_day", "06:40", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('cx_policy_day', ?)", (now.date().isoformat(),))
        try:
            import asyncio

            pol = await asyncio.to_thread(load_policy, c.policy_source)
            apply_policy(rt, pol)
            if pol["report_url"]:
                import httpx

                async with httpx.AsyncClient(timeout=15) as cl:
                    await cl.post(pol["report_url"], json=status_report(rt))
            said.append("policy")
        except Exception as e:  # noqa: BLE001 – the share is offline; the last policy stays
            rt.notify("Firemní zásady", f"Zásady se nepodařilo načíst ({str(e)[:120]}). Platí poslední známé.", speak=False)
    if c.cloud_backup_day >= 0 and now.weekday() == c.cloud_backup_day and due_today(rt, "cx_cloud_day", "02:30", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('cx_cloud_day', ?)", (now.date().isoformat(),))
        try:
            r = await cloud_backup(rt)
            said.append(f"cloud {r['bytes']}")
        except Exception as e:  # noqa: BLE001
            rt.notify("Záloha do cloudu", f"Nepovedla se: {str(e)[:160]}", speak=False)
    return said
