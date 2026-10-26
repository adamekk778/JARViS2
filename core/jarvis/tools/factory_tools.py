"""OMEGA wave 15 by voice: the software factory – requirements and acceptance criteria from a description, a mock
server and a client SDK from an OpenAPI contract, a rollback plan, background jobs (Task Scheduler + JARVIS) and the
App Links / Universal Links of a domain."""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .dev import resolve_project
from .files import resolve

MOCKS: dict[int, dict] = {}


def _spec(path: str):
    from .. import devlab

    p = resolve(path)
    if not p.is_file():
        raise ValueError(f"Specifikace neexistuje: {p}")
    return devlab.load_spec(p)


@tool("requirements_from_idea", "Z popisu záměru („chci aplikaci, která…“) udělá požadavky: funkční, nefunkční (měřitelně), "
      "akceptační kritéria Given/When/Then, otevřené otázky a co je mimo rozsah – a zkontroluje vágní slova a mezery. "
      "Uloží Markdown a .feature soubor.", category="programování", perm="files_read")
async def requirements_from_idea(ctx, idea: Annotated[str, "popis záměru (nebo cesta k souboru s ním)"]) -> ToolResult:
    from .. import factory, thinking

    text = idea
    p = resolve(idea.strip()) if "\n" not in idea and len(idea) < 300 else None
    if p is not None and p.is_file():
        text = p.read_text(encoding="utf-8", errors="replace")
    if len(text.strip()) < 20:
        return ToolResult(False, "Popis je moc krátký – napiš aspoň pár vět, co to má umět a pro koho.")
    try:
        req = await thinking.ask_json(ctx, factory.REQ_SYSTEM, f"<popis>\n{text[:12000]}\n</popis>")
    except ValueError as e:
        return ToolResult(False, str(e))
    if not isinstance(req, dict) or not req.get("functional"):
        return ToolResult(False, "AI nevrátila žádné funkční požadavky – zkus popis rozvést.")
    chk = factory.check_requirements(req)
    md = factory.requirements_markdown(req, chk)
    out = paths.data_dir() / "pozadavky"
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w-]+", "-", (req.get("title") or "pozadavky").lower()).strip("-")[:40] or "pozadavky"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    mdf, feat = out / f"{stem}-{stamp}.md", out / f"{stem}-{stamp}.feature"
    mdf.write_text(md, encoding="utf-8")
    feat.write_text(factory.gherkin(req), encoding="utf-8")
    c = chk["counts"]
    msg = f"{c['functional']} funkčních, {c['nonfunctional']} nefunkčních požadavků, {c['acceptance']} akceptačních kritérií"
    if req.get("questions"):
        msg += f", {len(req['questions'])} otevřených otázek"
    msg += f". {'Kontrola v pořádku' if chk['ok'] else 'K upřesnění: ' + '; '.join(chk['issues'][:5])}. Uloženo: {mdf}"
    tasks = getattr(ctx, "tasks", None)
    if tasks is not None and tasks.current:
        tasks.add_artifact(mdf, "Požadavky")
        tasks.add_artifact(feat, "Akceptační scénáře")
    return ToolResult(True, msg, data={"requirements": req, "check": chk, "markdown": str(mdf), "feature": str(feat)})


@tool("mock_server_start", "Spustí na tomto počítači testovací (mock) server podle kontraktu OpenAPI: každý endpoint vrací "
      "ukázkovou odpověď, špatný požadavek dostane 400 s důvodem. Frontend jde vyvíjet bez hotového backendu.",
      category="programování", perm="network")
async def mock_server_start(ctx, spec: str, port: int = 0, delay_ms: int = 0, minutes: int = 60) -> ToolResult:
    from .. import factory

    try:
        sp = await asyncio.to_thread(_spec, spec)
        m = factory.MockServer(sp, max(0, port), max(0, min(delay_ms, 10000)))
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001 – broken YAML
        return ToolResult(False, f"Specifikaci nejde přečíst: {e}")
    url = m.start()
    minutes = max(1, min(minutes, 480))

    async def expire():
        await asyncio.sleep(minutes * 60)
        await asyncio.to_thread(m.stop)
        MOCKS.pop(m.port, None)
    MOCKS[m.port] = {"mock": m, "task": asyncio.create_task(expire()), "url": url}
    n = len(factory.operations(sp))
    return ToolResult(True, f"Mock server běží na {url} ({n} endpointů), sám skončí za {minutes} min.", data={"url": url, "port": m.port, "operations": n})


@tool("mock_server_stop", "Zastaví testovací (mock) server a řekne, jaké požadavky na něj přišly.", category="programování", perm="network")
async def mock_server_stop(ctx, port: int = 0) -> ToolResult:
    ports = [port] if port else list(MOCKS)
    if not ports or (port and port not in MOCKS):
        return ToolResult(False, "Žádný mock server neběží.")
    logs = {}
    for pt in ports:
        ent = MOCKS.pop(pt)
        ent["task"].cancel()
        await asyncio.to_thread(ent["mock"].stop)
        logs[pt] = ent["mock"].log
    total = sum(len(v) for v in logs.values())
    bad = sum(1 for v in logs.values() for e in v if e["status"] >= 400)
    return ToolResult(True, f"Zastaveno. Přišlo {total} požadavků, z toho {bad} mimo kontrakt.", data=logs)


@tool("generate_api_client", "Vygeneruje klientskou knihovnu (SDK) z kontraktu OpenAPI – Python (httpx) nebo TypeScript "
      "(fetch): jedna funkce na endpoint s parametry. Python verzi ověří překladem.", category="programování", perm="files_write")
async def generate_api_client(ctx, spec: str, language: Annotated[str, "python nebo typescript"] = "typescript",
                              target: Annotated[str, "soubor (prázdné = vedle specifikace)"] = "") -> ToolResult:
    from .. import factory

    lang = language.lower().strip()
    if lang in ("ts", "typescript", "javascript", "js"):
        lang, ext = "typescript", ".ts"
    elif lang in ("py", "python"):
        lang, ext = "python", ".py"
    else:
        return ToolResult(False, "Jazyk: python nebo typescript.")
    try:
        sp = await asyncio.to_thread(_spec, spec)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Specifikaci nejde přečíst: {e}")
    code = factory.sdk_python(sp) if lang == "python" else factory.sdk_typescript(sp)
    if lang == "python":
        try:
            compile(code, "api_client.py", "exec")
        except SyntaxError as e:
            return ToolResult(False, f"Vygenerovaný kód nejde přeložit ({e}) – to je chyba generátoru, nahlas ji.")
    out = resolve(target) if target else resolve(spec).with_name("api_client" + ext)
    if out.exists() and "vygenerovaný JARVISem" not in out.read_text(encoding="utf-8", errors="replace")[:300]:
        return ToolResult(False, f"{out.name} už existuje a není vygenerovaný JARVISem – nepřepíšu ho.")
    out.write_text(code, encoding="utf-8")
    ops = factory.operations(sp)
    return ToolResult(True, f"Klient ({lang}) s {len(ops)} funkcemi uložen: {out}. Funkce: " +
                      ", ".join(factory._ident(o["name"], lang == "typescript") for o in ops[:10]) + ".", data={"path": str(out), "operations": len(ops)})


@tool("rollback_plan", "Plán návratu na předchozí vydání (git tag): co se od té doby změnilo, co nejde jen tak vrátit "
      "(databázové migrace, konfigurace, závislosti), riziko a kroky. Nic nemění.", category="programování", perm="files_read")
async def rollback_plan(ctx, project: str, to: Annotated[str, "na který tag (prázdné = předchozí)"] = "") -> ToolResult:
    from .. import factory

    root = resolve_project(ctx, project)
    if isinstance(root, ToolResult):
        return root
    try:
        r = await asyncio.to_thread(factory.rollback_plan, root, to)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Návrat {r['current']} → {r['target']} ({r['commits']} commitů, {r['files']} souborů), riziko {r['risk']}. " +
                      " ".join(f"{i}. {s}" for i, s in enumerate(r["steps"], 1)), data=r)


@tool("background_jobs", "Úlohy na pozadí: Plánovač úloh Windows (mimo systémové) a naplánované rutiny JARVISe – které "
      "selhávají, zmeškaly běh nebo se vůbec nespouští.", category="systém", perm="system")
async def background_jobs(ctx) -> ToolResult:
    from .. import factory

    mine = factory.jarvis_jobs(ctx)
    try:
        win = await asyncio.to_thread(factory.scheduled_tasks)
        werr = ""
    except ValueError as e:
        win, werr = [], str(e)
    bad = [t for t in win if t["problem"]] + [j for j in mine if j["problem"]]
    head = f"Plánovač Windows: {len(win)} úloh" if not werr else f"Plánovač Windows: {werr}"
    head += f"; JARVIS: {len(mine)} rutin."
    if not bad:
        return ToolResult(True, head + " Nic neselhává.", data={"windows": win, "jarvis": mine, "problems": []})
    return ToolResult(True, head + " Problémy: " + "; ".join(f"{t['name']} – {t['problem']}" for t in bad[:8]) + ".",
                      data={"windows": win, "jarvis": mine, "problems": bad})


@tool("check_app_links", "Zkontroluje odkazy do mobilní aplikace na doméně: Android App Links (assetlinks.json) a iOS "
      "Universal Links (apple-app-site-association) – existence, formát, otisky, přesměrování a jestli se daná cesta otevře v aplikaci.",
      category="programování", perm="network")
async def check_app_links(ctx, domain: str, android_package: str = "", ios_app_id: Annotated[str, "TÝMID.bundle.id"] = "",
                          path: Annotated[str, "cesta k ověření, např. /produkt/123"] = "") -> ToolResult:
    from .. import factory

    try:
        async with ctx.http() as c:
            r = await factory.deep_links(c, domain, android_package, ios_app_id, path)
    except ValueError as e:
        return ToolResult(False, str(e))
    parts = []
    for side, label in (("android", "Android"), ("ios", "iOS")):
        d = r[side]
        parts.append(f"{label}: " + ("v pořádku" + (f" ({', '.join(map(str, d.get('apps', [])[:3]))})" if d.get("apps") else "")
                                     if not d["problems"] else "; ".join(d["problems"][:3])))
    return ToolResult(True, f"{r['domain']} – " + " | ".join(parts) + ".", data=r)
