"""OMEGA wave 21 by voice: the super browser – tabs, sessions, recorded workflows, page structure over time, the click route
to a page, refusing cookies, a privacy report, logins about to expire, verifying a download, and subscriptions."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Annotated

from .base import ToolResult, tool


async def _session_pages():
    from .browser import SESSION

    if SESSION.ctx is None:
        return None, []
    return SESSION, [p for p in SESSION.ctx.pages if not p.is_closed()]


async def _tabs() -> list[dict]:
    _, pages = await _session_pages()
    out = []
    for p in pages:
        try:
            title = await p.title()
        except Exception:  # noqa: BLE001 – a page in the middle of navigating
            title = ""
        out.append({"url": p.url, "title": title})
    return out


@tool("sort_tabs", "Roztřídí otevřené karty prohlížeče JARVISe (práce, nákupy, video, zprávy, sítě, banka…) a najde duplicity; "
      "volitelně duplicitní karty zavře.", category="prohlížeč")
async def sort_tabs(ctx, close_duplicates: bool = False) -> ToolResult:
    from .. import browserplus as bp

    sess, pages = await _session_pages()
    if not pages:
        return ToolResult(False, "Prohlížeč JARVISe není otevřený.")
    tabs = await _tabs()
    r = bp.sort_tabs(tabs)
    closed = 0
    if close_duplicates and r["duplicates"]:
        seen = set()
        for p in pages:
            key = p.url.split("#")[0].rstrip("/")
            if key in seen:
                await p.close()
                closed += 1
            seen.add(key)
    msg = "; ".join(f"{g} {len(v)}" for g, v in sorted(r["groups"].items(), key=lambda kv: -len(kv[1])))
    msg += f". Duplicit {len(r['duplicates'])}" + (f", zavřeno {closed}" if closed else "") + "."
    return ToolResult(True, f"{r['count']} karet: " + msg, data={**r, "closed": closed})


@tool("save_browser_session", "Uloží otevřené karty prohlížeče JARVISe pod názvem (např. „rozdělaná práce“) – i s poznámkou, kde jsi skončil.",
      category="prohlížeč")
async def save_browser_session(ctx, name: str, note: str = "") -> ToolResult:
    from .. import browserplus as bp

    tabs = await _tabs()
    if not tabs:
        return ToolResult(False, "Prohlížeč JARVISe není otevřený – není co uložit.")
    f = bp.save_session(name, tabs, note)
    return ToolResult(True, f"Relace „{name}“ uložena ({len(tabs)} karet).", data={"path": str(f), "tabs": tabs})


@tool("restore_browser_session", "Znovu otevře uloženou relaci karet v prohlížeči JARVISe (bez názvu = seznam uložených).",
      category="prohlížeč")
async def restore_browser_session(ctx, name: str = "") -> ToolResult:
    from .. import browserplus as bp
    from .browser import SESSION

    if not name:
        ss = bp.list_sessions()
        return ToolResult(True, "; ".join(f"{s['name']} ({s['tabs']} karet)" for s in ss) or "Žádná uložená relace.", data=ss)
    try:
        s = bp.load_session(name)
    except ValueError as e:
        return ToolResult(False, str(e))
    async with SESSION._lock:
        first = await SESSION.ensure()
        opened, failed = 0, []
        for i, t in enumerate(s["tabs"]):
            try:
                page = first if i == 0 else await SESSION.ctx.new_page()
                await page.goto(t["url"], wait_until="domcontentloaded", timeout=30000)
                opened += 1
            except Exception as e:  # noqa: BLE001
                failed.append(f"{t['url']}: {str(e).splitlines()[0][:80]}")
    return ToolResult(opened > 0, f"Otevřeno {opened} z {len(s['tabs'])} karet" + (f"; poznámka: {s['note']}" if s.get("note") else "") +
                      (f". Nešlo: {'; '.join(failed[:3])}" if failed else "") + ".", data={"opened": opened, "failed": failed})


# ---------------------------------------------------------------------------------------------- workflows
@tool("record_workflow_start", "Začne nahrávat, co v prohlížeči JARVISe děláš (kliknutí, vyplnění polí, stránky) – pak z toho "
      "udělá opakovatelný postup. Hesla se nikdy nezaznamenávají.", category="prohlížeč")
async def record_workflow_start(ctx, url: str = "") -> ToolResult:
    from .. import browserplus as bp
    from .browser import SESSION

    async with SESSION._lock:
        page = await SESSION.ensure()
        if not getattr(SESSION, "_recorder", False):
            await SESSION.ctx.add_init_script(bp.RECORDER_JS)
            SESSION._recorder = True
        if url:
            await page.goto(url if url.startswith(("http", "file:")) else "https://" + url, wait_until="domcontentloaded", timeout=45000)
        await page.evaluate("() => sessionStorage.removeItem('__jarvisRec')")   # listeners stay (installed once per page)
        await page.evaluate(bp.RECORDER_JS)
        SESSION._rec_start = page.url
    return ToolResult(True, f"Nahrávám od {page.url}. Až budeš hotový, řekni „ulož postup jako …“.", data={"url": page.url})


@tool("record_workflow_stop", "Ukončí nahrávání a uloží postup pod názvem (kroky jako „vyplň … = …“, „klikni na …“).",
      category="prohlížeč", perm="files_write")
async def record_workflow_stop(ctx, name: str) -> ToolResult:
    from .. import browserplus as bp
    from .browser import SESSION

    if SESSION.page is None or not getattr(SESSION, "_rec_start", ""):
        return ToolResult(False, "Nahrávání neběží.")
    events = []
    for p in SESSION.ctx.pages:
        try:
            events += await p.evaluate("() => window.__jarvisRec ? window.__jarvisRec.events() : []")
        except Exception:  # noqa: BLE001
            continue
    steps = bp.events_to_steps(events, SESSION._rec_start)
    if not steps:
        return ToolResult(False, "Nic jsem nezaznamenal – klikni nebo vyplň něco na stránce.")
    f = bp.save_workflow(name, SESSION._rec_start, steps)
    SESSION._rec_start = ""
    return ToolResult(True, f"Postup „{name}“ uložen ({len(steps)} kroků): " + "; ".join(steps[:8]) + ".", data={"path": str(f), "steps": steps})


@tool("replay_workflow", "Přehraje uložený postup v čistém prohlížeči a po každém kroku uloží snímek (heslo se zeptá, nikde se neukládá).",
      category="prohlížeč", perm="network")
async def replay_workflow(ctx, name: str, secrets: Annotated[dict[str, str] | None, "hodnoty za {heslo} a jiné {zástupce}"] = None) -> ToolResult:
    from .. import browserplus as bp, paths, testlab
    from .. import redact

    try:
        wf = bp.load_workflow(name)
    except ValueError as e:
        return ToolResult(False, str(e))
    steps = []
    for s in wf["steps"]:
        for k, v in (secrets or {}).items():
            redact.add_literal(v)
            s = s.replace("{" + k + "}", v)
        if "{heslo}" in s:
            return ToolResult(False, "Postup potřebuje heslo – zadej ho do secrets jako {\"heslo\": …} (neuloží se).")
        steps.append(s)
    out = paths.data_dir() / "testlab" / f"postup-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        r = await testlab.user_flow(wf["url"], steps, out)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Přehrání selhalo: {str(e).splitlines()[0][:200]}")
    if r["ok"]:
        return ToolResult(True, f"Postup „{name}“ proběhl: {r['total']} kroků. Snímky: {out}", data=r)
    bad = next(s for s in r["steps"] if not s["ok"])
    return ToolResult(True, f"Postup „{name}“ se zasekl v kroku „{bad['step'].split('=')[0]}“: {bad['error']}. Snímky: {out}", data=r)


# ---------------------------------------------------------------------------------------------- pages
async def _headless_page(url: str):
    from .. import testlab

    pw, b = await testlab.headless()
    ctx_ = await b.new_context()
    page = await ctx_.new_page()
    return pw, b, ctx_, page, testlab.page_url(url)


@tool("page_structure_check", "Zapamatuje si strukturu stránky (nadpisy, menu, formuláře, tlačítka) a příště řekne, co se změnilo.",
      category="web", perm="network")
async def page_structure_check(ctx, url: str) -> ToolResult:
    from .. import browserplus as bp

    try:
        pw, b, _, page, u = await _headless_page(url)
    except ValueError as e:
        return ToolResult(False, str(e))
    try:
        await page.goto(u, wait_until="load", timeout=30000)
        now = await page.evaluate(bp.STRUCTURE_JS)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Stránku nejde načíst: {str(e).splitlines()[0][:200]}")
    finally:
        await b.close()
        await pw.stop()
    f = bp._struct_file(u)
    old = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    f.write_text(json.dumps(now, ensure_ascii=False), encoding="utf-8")
    if old is None:
        return ToolResult(True, f"Struktura zapamatována: {len(now['headings'])} nadpisů, {len(now['forms'])} formulářů, {len(now['buttons'])} tlačítek, "
                                f"{now['links']} odkazů.", data={"first": True, "structure": now})
    d = bp.structure_diff(old, now)
    if d["same"]:
        return ToolResult(True, "Struktura stránky se nezměnila.", data=d)
    parts = []
    for k, label in (("headings", "nadpisy"), ("forms", "formuláře"), ("buttons", "tlačítka"), ("landmarks", "oblasti")):
        if d[k]["added"] or d[k]["removed"]:
            parts.append(f"{label}: " + ", ".join([*("+" + x for x in d[k]["added"][:4]), *("−" + x for x in d[k]["removed"][:4])]))
    if d["links"]:
        parts.append(f"odkazů {d['links'][0]} → {d['links'][1]}")
    if d["title"]:
        parts.append(f"titulek „{d['title'][0]}“ → „{d['title'][1]}“")
    return ToolResult(True, "Změny: " + " | ".join(parts) + ".", data=d)


@tool("find_page_route", "Najde na webu cestu k stránce s hledaným obsahem (např. „reklamační formulář“): na které odkazy "
      "postupně kliknout.", category="web", perm="network")
async def find_page_route(ctx, site: str, target: str, max_pages: int = 60) -> ToolResult:
    from .. import browserplus as bp

    async with ctx.http() as c:
        r = await bp.find_route(c, site, target, max(5, min(max_pages, 200)))
    if not r["found"]:
        return ToolResult(True, f"„{target}“ jsem na {r['visited']} prohledaných stránkách nenašel.", data=r)
    return ToolResult(True, ("Klikni: " + " → ".join(r["clicks"]) if r["clicks"] else "Je to přímo na úvodní stránce") + f". Adresa: {r['url']}", data=r)


@tool("reject_cookies", "Na stránce v prohlížeči JARVISe odmítne nepovinné cookies (najde lištu se souhlasem a klikne na "
      "„Odmítnout vše“ / „Pouze nezbytné“).", category="prohlížeč")
async def reject_cookies(ctx, url: str = "") -> ToolResult:
    from .. import browserplus as bp
    from .browser import SESSION

    async with SESSION._lock:
        page = await SESSION.ensure()
        if url:
            await page.goto(url if url.startswith(("http", "file:")) else "https://" + url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(1200)                          # consent banners load a moment later
        r = await bp.reject_cookies(page)
    if r["clicked"]:
        return ToolResult(True, f"Nepovinné cookies odmítnuty (tlačítko „{r['how']}“).", data=r)
    return ToolResult(True, "Lištu se souhlasem s cookies jsem tu nenašel (nebo už je vyřízená).", data=r)


@tool("privacy_report", "Soukromí webu: které sledovací služby načítá (Google Analytics, Facebook pixel, Hotjar…), cookies třetích "
      "stran ještě před souhlasem, kolik cizích domén volá. Stránku otevře v čistém prohlížeči.", category="web", perm="network")
async def privacy_report(ctx, url: str) -> ToolResult:
    from .. import browserplus as bp

    try:
        pw, b, c, page, u = await _headless_page(url)
    except ValueError as e:
        return ToolResult(False, str(e))
    reqs: list[str] = []
    page.on("request", lambda r: reqs.append(r.url))
    try:
        await page.goto(u, wait_until="load", timeout=30000)
        await page.wait_for_timeout(2500)
        cookies = await c.cookies()
        kb = await page.evaluate("() => { let n = 0; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); "
                                 "n += k.length + (localStorage.getItem(k) || '').length; } return n / 1024; }")
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Stránku nejde načíst: {str(e).splitlines()[0][:200]}")
    finally:
        await b.close()
        await pw.stop()
    r = bp.privacy_summary(u, reqs, cookies, kb)
    msg = f"Hodnocení {r['grade']} ({r['score']}/100). Sledování: {', '.join(r['trackers']) or 'žádné známé'}; cizích domén {len(r['third_parties'])}"
    msg += f"; cookies bez souhlasu: {len(r['cookies_first'])} vlastních, {len(r['cookies_third'])} cizích"
    if r["long_lived"]:
        msg += f"; {len(r['long_lived'])} cookies na déle než rok"
    return ToolResult(True, msg + ".", data=r)


@tool("expiring_logins", "Které přihlášení v prohlížeči JARVISe brzy vyprší (podle přihlašovacích cookies) – ať tě web "
      "neodhlásí uprostřed práce.", category="prohlížeč")
async def expiring_logins(ctx, hours: int = 48) -> ToolResult:
    from .. import browserplus as bp
    from .browser import SESSION

    if SESSION.ctx is None:
        return ToolResult(False, "Prohlížeč JARVISe není otevřený.")
    r = bp.expiring_logins(await SESSION.ctx.cookies(), hours)
    if not r["sites"]:
        return ToolResult(True, "V prohlížeči JARVISe nejsi nikde přihlášený.", data=r)
    return ToolResult(True, "; ".join(f"{s['site']}: {s['state']}" for s in r["sites"][:10]) + ".", data=r)


@tool("verify_download", "Ověří soubor ke stažení dřív, než ho otevřeš: přesměrování, šifrování, stáří domény, jestli obsah odpovídá "
      "příponě, a kontrolní součet SHA-256 (porovná se zveřejněným).", category="bezpečnost", perm="network")
async def verify_download(ctx, url: str, expected_sha256: str = "") -> ToolResult:
    from urllib.parse import urlparse

    from .. import browserplus as bp

    try:
        async with ctx.http() as c:
            r = await bp.verify_download(c, url, expected_sha256)
            age = await bp.domain_age(c, urlparse(r["final_url"]).netloc)
    except ValueError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Soubor nejde ověřit: {type(e).__name__}: {str(e)[:150]}")
    r["domain_age"] = age
    if age.get("known") and age["days"] < 90:
        r["issues"].append(f"doména {age['domain']} je stará jen {age['days']} dní – typické pro podvodné weby")
        r["ok"] = False
    msg = f"{r['file']} ({r['type']}, {r['bytes'] / 2 ** 20:.1f} MB), SHA-256 {r['sha256'][:16]}…"
    if r["checksum_ok"]:
        msg += " – součet SEDÍ se zveřejněným"
    if r["issues"]:
        return ToolResult(True, "POZOR: " + "; ".join(r["issues"]) + f". {msg}.", data=r)
    return ToolResult(True, f"Vypadá v pořádku: {msg}" + (f", doména existuje {age['days'] // 365} let" if age.get("known") and age["days"] >= 365 else "") + ".", data=r)


@tool("subscriptions_overview", "Přehled předplatných z e-mailů s účtenkami (Netflix, Spotify, aplikace…): kolik měsíčně a ročně "
      "platíš, kdy přijde další platba a co zdražilo.", category="finance", perm="network")
async def subscriptions_overview(ctx, months: int = 14) -> ToolResult:
    from .. import browserplus as bp

    mail = getattr(ctx, "mail", None)
    if mail is None or not getattr(mail, "accounts", None):
        return ToolResult(False, "Nemám připojený e-mail (Nastavení → E-mail).")

    def fetch():
        mail.sync()
        msgs, seen = [], set()
        for acc in list(mail.accounts.values()):
            for q in ("předplatné", "subscription", "faktura", "receipt", "invoice", "účtenka", "renewal", "platba"):
                for h in acc.list(limit=60, query=q):
                    if h["id"] in seen or float(h["date"]) < time.time() - months * 31 * 86400:
                        continue
                    seen.add(h["id"])
                    try:
                        full = acc.read(int(str(h["id"]).split(":")[-1]), mark_seen=False)
                    except Exception:  # noqa: BLE001
                        full = {}
                    msgs.append({**h, "body": (full.get("body") or "")[:4000]})
                    if len(msgs) >= 200:
                        return msgs
        return msgs
    try:
        msgs = await asyncio.to_thread(fetch)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"E-mail nejde přečíst: {str(e)[:150]}")
    r = bp.subscriptions(msgs)
    if not r["subscriptions"]:
        return ToolResult(True, f"V {len(msgs)} e-mailech s platbami jsem žádné pravidelné předplatné nenašel.", data=r)
    msg = f"Asi {r['monthly_czk']} Kč měsíčně ({r['yearly_czk']} Kč ročně): " + "; ".join(
        f"{s['service']} {s['amount']:g} {s['currency']} {s['period']}, další {s['next']}" + (" (ZDRAŽILO)" if s["price_up"] else "") +
        (" (možná zrušené)" if s["stale"] else "") for s in r["subscriptions"][:10])
    return ToolResult(True, msg + ".", data=r)
