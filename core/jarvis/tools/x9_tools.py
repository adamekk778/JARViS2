"""3.20 Programování+ (301–320), Dílna+ (321–340) a Zábava+ (341–360) tools."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Literal

from .. import devx, funx, paths, shopx
from .base import ToolResult, tool

CODE_CHANGES = {"run", "kill", "docker_action", "rename_apply", "git"}
FUN_CHANGES = {"albums_apply", "eq", "discord"}


async def _ai(ctx, prompt: str, fast: bool = True) -> str:
    return await ctx.router.complete([{"role": "user", "content": prompt}], fast=fast)


def _project(ctx, path: str) -> Path | ToolResult:
    from .dev import resolve_project

    return resolve_project(ctx, path or ".")


async def _diff(root: Path, staged: bool = False) -> str:
    code, out = await asyncio.to_thread(devx.git, root, "diff", *(["--staged"] if staged else []), "--no-color")
    if code == 0 and not out.strip() and not staged:
        code, out = await asyncio.to_thread(devx.git, root, "diff", "--staged", "--no-color")
    return out if code == 0 else ""


@tool("code_kit", "Programování: licence knihoven (licenses path), kontrola změn před commitem (review), zpráva commitu (commit_msg), "
      "hlídání CI (ci), README z kódu (readme), spuštění projektu hlasem (run text=backend/frontend/test, stop, projects), regex z "
      "popisu (regex text, sample), SQL z češtiny (sql path=.db, text), kód do editoru (code text), jdi na funkci (goto name), kdo ji "
      "volá (callers name), snippety (snippet_add name+text, snippets text), české testovací údaje (testdata n), změna pro netechniky "
      "(explain_change), porty (ports, port n, kill pid), Docker (docker, docker_logs name, docker_action name+text=start/stop/"
      "restart), přejmenování s náhledem (rename name+target, rename_apply), stará TODO (todos), úhledný JSON/YAML (pretty text, "
      "lang=yaml), git pomocník (git text=„vrať poslední commit“), převod kódu do jiného jazyka (translate path/text, lang).",
      category="programování", perm="files_read", danger_if=lambda a: a.get("action") in CODE_CHANGES)
async def code_kit(ctx, action: Literal["licenses", "review", "commit_msg", "ci", "readme", "run", "stop", "projects", "regex", "sql", "code",
                                        "goto", "callers", "snippet_add", "snippets", "testdata", "explain_change", "ports", "port", "kill",
                                        "docker", "docker_logs", "docker_action", "rename", "rename_apply", "todos", "pretty", "git", "translate"],
                   text: str = "", path: str = "", name: str = "", target: str = "", sample: str = "", lang: str = "", n: int = 0,
                   pid: int = 0) -> ToolResult:
    root = Path(".")
    if action in ("licenses", "review", "commit_msg", "readme", "run", "goto", "callers", "explain_change", "rename", "rename_apply",
                  "todos", "git") or (action == "projects" and path):
        found = _project(ctx, path)
        if isinstance(found, ToolResult):
            return found
        root = found
    if action == "licenses":
        deps = await asyncio.to_thread(devx.scan_licenses, root)
        if not deps:
            return ToolResult(False, "Nenašel jsem závislosti (package.json s node_modules, requirements.txt nebo pyproject.toml).")
        lic = text or ctx.cfg.devx.project_license
        bad = devx.license_conflicts(lic, deps)
        if not bad:
            return ToolResult(True, f"{len(deps)} knihoven, s licencí {lic} se nic nebije.", data={"deps": deps})
        return ToolResult(True, f"{len(bad)} z {len(deps)} knihoven hlídej (projekt {lic}):\n" + "\n".join(
            f"• {b['name']} ({b['license']}): {b['why']}" for b in bad[:15]) + "\n(Není to právní rada.)", data={"deps": deps, "bad": bad})
    if action == "review":
        diff = await _diff(root)
        if not diff:
            return ToolResult(True, "Žádné změny ke kontrole.")
        quick = devx.quick_review(diff)
        lines = [f"• {q['file']}:{q['line']} – {q['issue']}" for q in quick[:12]]
        try:
            ai = await _ai(ctx, devx.REVIEW_PROMPT + devx.clip_diff(diff), fast=False)
        except Exception:  # noqa: BLE001 – no AI: the quick checks still help
            ai = ""
        return ToolResult(True, ("Rychlá kontrola:\n" + "\n".join(lines) if lines else "Rychlá kontrola: nic podezřelého.") +
                          (f"\n\nAI review:\n{ai.strip()}" if ai.strip() else ""), data={"quick": quick})
    if action == "commit_msg":
        diff = await _diff(root, staged=True) or await _diff(root)
        if not diff:
            return ToolResult(False, "Nic k commitu.")
        _, log = await asyncio.to_thread(devx.git, root, "log", "-15", "--pretty=%s")
        try:
            msg = (await _ai(ctx, devx.COMMIT_PROMPT.format(lang=devx.commit_lang(log)) + devx.clip_diff(diff, 16000))).strip().strip("`")
        except Exception:  # noqa: BLE001
            msg = devx.commit_fallback(diff)
        ctx.platform.clipboard_set(msg)
        return ToolResult(True, f"{msg}\n\n(Zkopírováno do schránky – commitni přes git_commit nebo ve svém editoru.)", data={"message": msg})
    if action == "ci":
        repos = [text] if "/" in text else ctx.cfg.devx.ci_repos
        if not repos:
            return ToolResult(False, "Řekni repozitář (vlastník/název) nebo ho přidej do Nastavení → Programování → Hlídat CI.")
        import httpx

        out = []
        async with httpx.AsyncClient(timeout=15) as c:
            from ..connectors import value

            tok = value("github", "token") or ""
            for repo in repos[:5]:
                r = await c.get(f"https://api.github.com/repos/{repo}/actions/runs?per_page=5",
                                headers={"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {tok}"} if tok else {})})
                if r.status_code != 200:
                    out.append(f"{repo}: nedostupné ({r.status_code})")
                    continue
                runs = devx.parse_runs(r.json())
                last = runs[0] if runs else None
                out.append(f"{repo}: " + (f"{last['name']} – {last['conclusion'] or last['status']} ({last['branch']}, {last['sha']})" if last else "žádné běhy"))
        return ToolResult(True, "\n".join(out) + ("\nHlídám je a ozvu se, když něco spadne." if ctx.cfg.devx.ci_repos else ""))
    if action == "readme":
        o = await asyncio.to_thread(devx.project_outline, root)
        text_md = devx.readme_from_outline(o)
        dst = root / ("README.md" if not (root / "README.md").exists() else "README.navrh.md")
        dst.write_text(text_md, encoding="utf-8")
        return ToolResult(True, f"Návrh README: {dst} ({len(o['modules'])} modulů). Doplň popis „co a pro koho“.", data={"path": str(dst)})
    if action == "projects":
        if path:
            cmds = devx.detect_commands(root)
            devx.project_set(ctx, name or root.name, str(root), "")
            return ToolResult(True, f"{root.name}: " + (", ".join(f"{k} = {v}" for k, v in cmds.items()) or "nic ke spuštění nenašel"), data=cmds)
        rows = ctx.db.all("SELECT * FROM dx_projects") if devx.db(ctx) else []
        return ToolResult(True, "\n".join(f"{r['name']}: {r['path']}" for r in rows) or "Žádné uložené projekty – řekni „projekt X je ve složce Y“.")
    if action == "run":
        cmds = devx.detect_commands(root)
        pick = devx.pick_command(cmds, text or "start")
        if not pick:
            return ToolResult(False, f"V {root.name} nevím, co spustit pro „{text}“. Mám: {', '.join(cmds) or 'nic'}.")
        key = f"{root.name}:{pick[0]}"
        logf = await asyncio.to_thread(devx.start_command, key, pick[1], root, paths.sub("logs"))
        return ToolResult(True, f"Spuštěno: {pick[1]} v {root.name} (výpis: {logf}). Zastavíš „zastav {pick[0]}“.", data={"key": key, "log": str(logf)})
    if action == "stop":
        keys = [k for k in devx.RUNNING if not text or devx.fold(text) in devx.fold(k)]
        for k in keys:
            await asyncio.to_thread(devx.stop_command, k)
        return ToolResult(bool(keys), f"Zastaveno: {', '.join(keys)}." if keys else "Nic takového neběží.")
    if action == "regex":
        pat = devx.regex_offline(text)
        why = "z knihovny běžných vzorů"
        if not pat:
            ans = await _ai(ctx, devx.REGEX_PROMPT.format(desc=text))
            lines = [x for x in ans.strip().strip("`").splitlines() if x.strip()]
            pat, why = (lines[0].strip().strip("/"), " ".join(lines[1:])) if lines else ("", "")
        test = devx.regex_test(pat, sample) if sample else {"ok": devx.regex_test(pat, "")["ok"]}
        if not test["ok"]:
            return ToolResult(False, f"Výraz nejde použít: {test.get('error')}")
        return ToolResult(True, f"{pat}\n{why}" + (f"\nShody v ukázce: {', '.join(test['matches'][:10]) or 'žádné'}" if sample else ""),
                          data={"pattern": pat, **test})
    if action == "sql":
        from .files import resolve

        dbp = resolve(path)
        if dbp.suffix.lower() not in (".db", ".sqlite", ".sqlite3") or not dbp.is_file():
            return ToolResult(False, "Pošli cestu k databázi SQLite (.db / .sqlite).")
        schema = await asyncio.to_thread(devx.sqlite_schema, dbp)
        sql = devx.extract_code(await _ai(ctx, devx.SQL_PROMPT.format(schema=schema[:12000], ask=text)))
        if not devx.read_only_sql(sql):
            return ToolResult(False, f"Navržený dotaz by databázi měnil, nespustím ho:\n{sql}")
        import sqlite3

        def run():
            con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
            try:
                cur = con.execute(sql)
                cols = [c[0] for c in cur.description or []]
                return cols, cur.fetchmany(30)
            finally:
                con.close()

        try:
            cols, rows = await asyncio.to_thread(run)
        except sqlite3.Error as e:
            return ToolResult(False, f"{sql}\nChyba: {e}")
        table = " | ".join(cols) + "\n" + "\n".join(" | ".join(str(x) for x in r) for r in rows)
        return ToolResult(True, f"{sql}\n\n{table}", data={"sql": sql, "columns": cols, "rows": [list(r) for r in rows]})
    if action == "code":
        title = ctx.platform.foreground_info().get("title", "") if hasattr(ctx.platform, "foreground_info") else ""
        code = devx.extract_code(await _ai(ctx, devx.CODE_PROMPT.format(lang=lang or devx.lang_of(title), ask=text), fast=False))
        ctx.platform.clipboard_set(code)
        ctx.platform.hotkey(["ctrl", "v"])
        return ToolResult(True, f"Vloženo do editoru ({len(code.splitlines())} řádků). Ctrl+Z to vrátí.", data={"code": code})
    if action in ("goto", "callers"):
        hits = await asyncio.to_thread(devx.find_symbol if action == "goto" else devx.find_callers, root, name or text)
        if not hits:
            return ToolResult(False, f"„{name or text}“ jsem v {root.name} nenašel.")
        if action == "goto":
            h = hits[0]
            try:
                subprocess.Popen(devx.editor_command(h["file"], h["line"]))  # noqa: S603
            except OSError:
                ctx.platform.open_path(h["file"])
            return ToolResult(True, f"{Path(h['file']).name}:{h['line']} – {h['code']}" + (f" (a {len(hits) - 1} dalších)" if len(hits) > 1 else ""),
                              data={"hits": hits[:20]})
        return ToolResult(True, f"{name or text} volá {len(hits)} míst:\n" + "\n".join(
            f"• {Path(h['file']).name}:{h['line']} v {h['in'] or '?'}" for h in hits[:15]), data={"hits": hits[:50]})
    if action == "snippet_add":
        sid = devx.snippet_add(ctx, name or text.splitlines()[0][:60], text, lang)
        return ToolResult(True, f"Snippet #{sid} uložen.")
    if action == "snippets":
        snips = devx.snippet_find(ctx, text)
        if not snips:
            return ToolResult(False, "Žádný takový snippet.")
        ctx.platform.clipboard_set(snips[0]["code"])
        return ToolResult(True, f"„{snips[0]['title']}“ je ve schránce." + (" Další: " + ", ".join(f["title"] for f in snips[1:]) if len(snips) > 1 else ""),
                          data={"snippets": snips})
    if action == "testdata":
        rows = devx.test_people(n or 10)
        csvf = paths.sub("dev") / f"testovaci-osoby-{dt.datetime.now():%Y%m%d-%H%M}.csv"
        csvf.write_text(devx.to_csv(rows), encoding="utf-8")
        return ToolResult(True, f"{len(rows)} vymyšlených osob (jména, adresy, platná rodná čísla, IČO a účty jen pro testy): {csvf}",
                          data={"path": str(csvf), "sample": rows[:3]})
    if action == "explain_change":
        diff = await _diff(root, staged=False)
        if not diff:
            _, diff = await asyncio.to_thread(devx.git, root, "show", "--no-color", "HEAD")
        return ToolResult(True, (await _ai(ctx, devx.PEOPLE_PROMPT + devx.clip_diff(diff, 20000))).strip())
    if action == "ports":
        ps = await asyncio.to_thread(devx.listening_ports)
        return ToolResult(True, "\n".join(f"{p['port']}: {p['name']} (PID {p['pid']})" for p in ps) or "Nic neposlouchá.", data={"ports": ps})
    if action == "port":
        who = await asyncio.to_thread(devx.who_uses_port, n)
        return ToolResult(True, "\n".join(f"{w['name']} (PID {w['pid']}): {w['cmd']}" for w in who) or f"Na portu {n} nic neběží.", data={"who": who})
    if action == "kill":
        try:
            nm = await asyncio.to_thread(devx.kill_pid, pid)
        except (ValueError, Exception) as e:  # noqa: BLE001
            return ToolResult(False, str(e))
        return ToolResult(True, f"{nm} (PID {pid}) ukončen.")
    if action == "docker":
        rc, dout = await asyncio.to_thread(devx.docker, "ps", "-a", "--format", "{{json .}}")
        if rc != 0:
            return ToolResult(False, dout.strip()[:300])
        rows = devx.parse_docker_ps(dout)
        return ToolResult(True, devx.docker_summary(rows), data={"containers": rows})
    if action == "docker_logs":
        rc, dout = await asyncio.to_thread(devx.docker, "logs", "--tail", "40", name or text)
        return ToolResult(rc == 0, dout.strip()[-3000:] or "Prázdný log.")
    if action == "docker_action":
        verb = devx.fold(text)
        if verb not in ("start", "stop", "restart"):
            return ToolResult(False, "Umím start, stop a restart.")
        rc, dout = await asyncio.to_thread(devx.docker, verb, name)
        return ToolResult(rc == 0, f"{name}: {verb} {'hotovo' if rc == 0 else dout.strip()[:200]}")
    if action == "rename":
        prev = await asyncio.to_thread(devx.rename_preview, root, name, target)
        if not prev:
            return ToolResult(False, f"„{name}“ jsem nenašel.")
        total = sum(p["count"] for p in prev)
        sample = "\n".join(p["diff"] for p in prev[:3])[:2500]
        return ToolResult(True, f"{total}× v {len(prev)} souborech. Ukázka:\n{sample}\nPotvrď „proveď přejmenování“ a pustím i testy.",
                          data={"files": [p["file"] for p in prev]})
    if action == "rename_apply":
        cnt = await asyncio.to_thread(devx.rename_apply, root, name, target)
        cmds = devx.detect_commands(root)
        test_cmd = cmds.get("test")
        res = ""
        if test_cmd:
            proc = await asyncio.to_thread(subprocess.run, test_cmd, cwd=str(root), shell=True, capture_output=True, text=True, timeout=600)
            res = "Testy prošly." if proc.returncode == 0 else f"Testy SELHALY – vrať to přes git („zahoď změny“):\n{(proc.stdout + proc.stderr)[-800:]}"
        return ToolResult(True, f"Přejmenováno {cnt}×. {res}".strip())
    if action == "todos":
        items = await asyncio.to_thread(devx.old_todos, root, max(1, n or 30))
        return ToolResult(True, "\n".join(f"• {t['file']}:{t['line']} ({t['age_days']} dní, {t['author']}): {t['text']}" for t in items[:20])
                          or "Žádná TODO starší než měsíc.", data={"todos": items})
    if action == "pretty":
        try:
            nice, kind = devx.pretty(text or ctx.platform.clipboard_get(), "yaml" if devx.fold(lang) == "yaml" else "json" if lang else "")
        except ValueError as e:
            return ToolResult(False, str(e))
        ctx.platform.clipboard_set(nice)
        return ToolResult(True, f"Úhledný {kind.upper()} je ve schránce:\n{nice[:3000]}")
    if action == "git":
        pushed = await asyncio.to_thread(devx.is_pushed, root)
        plan = devx.git_plan(text, pushed, target, name or ".")
        if not plan:
            return ToolResult(False, "Nevím, co tím myslíš v gitu – řekni třeba „vrať poslední commit“, „odlož práci“, „nová větev X“.")
        rc, gout = await asyncio.to_thread(devx.git, root, *plan["args"])
        return ToolResult(rc == 0, f"{plan['why']}\n$ git {' '.join(plan['args'])}\n{gout.strip()[:1500]}", data=plan)
    # translate
    src_code = text
    src_lang = ""
    if path:
        from .files import resolve

        p = resolve(path)
        if p.is_file():
            src_code = p.read_text(encoding="utf-8", errors="ignore")[:20000]
            src_lang = devx.EXT_LANG.get(p.suffix.lower(), "")
    if not src_code:
        return ToolResult(False, "Pošli kód nebo cestu k souboru.")
    translated = await _ai(ctx, devx.TRANSLATE_PROMPT.format(src=src_lang or "(pozná sám)", dst=lang or "TypeScript", code=src_code), fast=False)
    return ToolResult(True, translated.strip())


@tool("shop_kit", "Dílna: sušení filamentu (dry text=materiál, n=vlhkost %), cena tisku (cost amount=g, hours), cívky (spool_add text="
      "„PETG černá 1000 g 549 Kč“, spools, spool_use text+amount), knihovna modelů (library_index, library text), úprava STL (stl "
      "path, text=„zvětši o 10 %“ / „otoč o 90°“ / „díra 5 mm“), tiskárny a fronta (queue_add path+text=materiál+hours, queue), "
      "kalibrace (calibrate text=esteps/flow/pa/temp/retraction/first_layer, values), laser a CNC (laser / cnc text=rect/circle, w, h, "
      "depth), nářadí (tool_add name+text=místo, where text), převody (units text=„3/8 palce“ / „M6“ / „20 Nm na lb ft“), půjčené věci "
      "(lend name+text=komu, returned name, lent), nářezový plán (cut text=„2440: 800, 800, 600“ nebo „2800x2070: 600x400, …“), barva "
      "(paint amount=m², text=druh), hmoždinky (anchor text=zeď, amount=kg), údržba (maint_add name+text+n, maint, maint_done n), "
      "rozdělení velkého modelu (split path), bezpečnost (safety text), balíček pro Printables (printables path, name).", category="dílna",
      perm="files_read")
async def shop_kit(ctx, action: Literal["dry", "cost", "spool_add", "spools", "spool_use", "library_index", "library", "stl", "queue_add", "queue",
                                        "calibrate", "laser", "cnc", "tool_add", "where", "units", "lend", "returned", "lent", "cut", "paint",
                                        "anchor", "maint_add", "maint", "maint_done", "split", "safety", "printables"],
                   text: str = "", path: str = "", name: str = "", amount: float = 0, hours: float = 0, n: int = 0, w: float = 0,
                   h: float = 0, depth: float = 0, values: str = "") -> ToolResult:
    c = ctx.cfg.shopx
    if action == "dry":
        r = shopx.dry_advice(text, n or None)
        return ToolResult(r["ok"], r["text"], data=r)
    if action == "cost":
        sp = shopx.spool_find(ctx, text) if text else None
        price = (sp["price"] / sp["total_g"] * 1000) if sp and sp["price"] and sp["total_g"] else c.filament_price
        r = shopx.print_cost(amount, hours, price, c.printer_watts, c.kwh_price, c.wear_per_hour)
        return ToolResult(True, r["text"], data=r)
    if action == "spool_add":
        m = re.search(r"(\d+)\s*g", text)
        pm = re.search(r"(\d+)\s*(kč|kc|,-)", text.lower())
        words = re.sub(r"\d+\s*(g|kč|kc|,-)", "", text, flags=re.I).split()
        mat = shopx.material(words[0]) if words else "PLA"
        sid = shopx.spool_add(ctx, mat, " ".join(words[1:3]), "", float(m.group(1)) if m else 1000, float(pm.group(1)) if pm else 0)
        return ToolResult(True, f"Cívka #{sid}: {mat} {' '.join(words[1:3])}.")
    if action == "spools":
        all_sp = shopx.spools(ctx)
        return ToolResult(True, "\n".join(f"#{s['id']} {s['material']} {s['color']}: {s['left_g']:.0f} g" for s in all_sp) or "Žádné cívky.", data={"spools": all_sp})
    if action == "spool_use":
        sp = shopx.spool_find(ctx, text)
        if not sp:
            return ToolResult(False, "Kterou cívku? Řekni materiál a barvu.")
        r = shopx.spool_use(ctx, sp["id"], amount, c.spool_low_g)
        return ToolResult(True, f"{r['name']}: zbývá {r['left']} g" + (" – objednej novou." if r["low"] else "."), data=r)
    if action == "library_index":
        if not c.parts_dirs:
            return ToolResult(False, "Přidej složky s modely (Nastavení → Dílna → Knihovna dílů).")
        k = await asyncio.to_thread(shopx.library_index, ctx, c.parts_dirs)
        return ToolResult(True, f"Zaindexováno {k} nových nebo změněných modelů.")
    if action == "library":
        hits = shopx.library_find(ctx, text)
        return ToolResult(bool(hits), "\n".join(f"• {x['name']} ({x['dims'] or '?'} mm): {x['path']}" for x in hits) or "Nic takového v knihovně.",
                          data={"parts": hits})
    model = Path(".")
    if action in ("stl", "split", "printables"):
        from .files import resolve

        model = resolve(path)
        if not model.is_file():
            return ToolResult(False, "Pošli cestu k modelu.")
    if action == "stl":
        edit = shopx.parse_edit(text)
        if not edit["op"]:
            return ToolResult(False, "Umím: zvětši/zmenši o X %, otoč o X° (kolem X/Y/Z), zrcadli podle X, díra X mm.")
        tris = await asyncio.to_thread(shopx.stl_read, model)
        out = model.with_name(f"{model.stem}-upraveno.stl")
        if edit["op"] == "hole":
            ok, err = await asyncio.to_thread(shopx.run_openscad, shopx.hole_scad(model, edit["d"], shopx.dims(tris)), out)
            return ToolResult(ok, f"Díra ⌀{edit['d']:g} mm uprostřed: {out}" if ok else err)
        new = shopx.stl_edit(tris, edit)
        await asyncio.to_thread(shopx.stl_write, out, new)
        d = shopx.dims(new)
        return ToolResult(True, f"Hotovo: {out} ({d[0]:g} × {d[1]:g} × {d[2]:g} mm). Originál zůstal.", data={"path": str(out), "dims": d})
    if action == "queue_add":
        mats = [m for m in shopx.MATERIALS if m in text.upper()]
        qid = shopx.queue_add(ctx, path or name, mats[0] if mats else "PLA", hours or 1, text)
        return ToolResult(True, f"Ve frontě jako #{qid}.")
    if action == "queue":
        jobs = [dict(r) for r in shopx.db(ctx).all("SELECT * FROM sx_queue WHERE state='waiting'")]
        printers = c.printers or [{"name": "Tiskárna"}]
        plan = shopx.plan_queue(jobs, printers)
        return ToolResult(True, "\n".join(f"• {Path(j['file']).name} ({j['material']}, {j['hours']:g} h) → {j['printer'] or '—'}"
                                          + (f" za {j['start_h']:g} h" if j.get("start_h") else (" teď" if j["printer"] else f": {j.get('why')}"))
                                          for j in plan) or "Fronta je prázdná.", data={"plan": plan})
    if action == "calibrate":
        kind = devx_fold(text) or "esteps"
        steps = shopx.CALIBRATION.get(kind)
        if not steps:
            return ToolResult(False, "Kalibrace: " + ", ".join(shopx.CALIBRATION))
        nums = [float(x.replace(",", ".")) for x in re.findall(r"[\d.,]+", values)]
        extra = ""
        try:
            if kind == "esteps" and len(nums) >= 2:
                extra = f"\nNové E-steps: {shopx.esteps(nums[0], nums[2] if len(nums) > 2 else 100, nums[1])}"
            elif kind == "flow" and len(nums) >= 2:
                extra = f"\nNový průtok: {shopx.flow(nums[0], nums[2] if len(nums) > 2 else 0.45, nums[1])}"
        except ValueError as e:
            extra = f"\n{e}"
        return ToolResult(True, "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)) + extra)
    if action in ("laser", "cnc"):
        shape = "circle" if "kru" in devx_fold(text) or "circle" in text else "rect"
        if w <= 0:
            return ToolResult(False, "Řekni rozměr (w, u obdélníku i h, u CNC hloubku).")
        g = shopx.laser_gcode(shape, w, h or w) if action == "laser" else shopx.cnc_profile(shape, w, h or w, depth or 3)
        out = paths.sub("dilna") / f"{action}-{shape}-{w:g}x{(h or w):g}.nc"
        out.write_text("\n".join(g), encoding="utf-8")
        return ToolResult(True, f"G-code: {out} ({len(g)} řádků, asi {shopx.gcode_time(g):g} min). Pošli ho přes svůj program (LaserGRBL, "
                                "UGS, Candle) – nejdřív nasucho bez výkonu.", data={"path": str(out)})
    if action == "tool_add":
        tid = shopx.tool_add(ctx, name, text)
        return ToolResult(True, f"{name} – {text or 'bez místa'} (#{tid}).")
    if action == "where":
        hits = shopx.tool_where(ctx, text)
        return ToolResult(bool(hits), "; ".join(f"{x['name']}: {x['place'] or '?'}" for x in hits) or f"„{text}“ nemám zapsané.")
    if action == "units":
        t = text.strip()
        if re.match(r"(?i)^(m\d|#\d|\d/\d+-\d)", t):
            return ToolResult(True, shopx.thread_info(t))
        m = re.match(r"(?i)^([\d.,]+)\s*(nm|lb ?ft|ft ?lb|lb ?in|in ?lb|kg ?m|kg ?cm)\b", t)
        if m:
            r = shopx.torque(float(m.group(1).replace(",", ".")), m.group(2))
            return ToolResult(True, ", ".join(f"{v:g} {k}" for k, v in r.items()), data=r)
        m = re.match(r"(?i)^awg\s*(\d+)|^(\d+)\s*awg", t)
        if m:
            gauge = int(m.group(1) or m.group(2))
            return ToolResult(gauge in shopx.AWG, f"AWG {gauge} = {shopx.AWG.get(gauge, '?')} mm²")
        mm = shopx.parse_len(re.sub(r"(?i)\s*(na|v|do)\s+(mm|palc\w*|in\w*)$", "", t))
        if mm is None:
            return ToolResult(False, "Řekni třeba „3/8 palce“, „25 mm na palce“, „M8“ nebo „20 Nm“.")
        return ToolResult(True, f"{mm:.2f} mm = {mm / 25.4:.4f}\" ≈ {shopx.inch_fraction(mm)}")
    if action == "lend":
        shopx.lend(ctx, name, text)
        return ToolResult(True, f"Zapsáno: {name} má {text}. Připomenu se za {c.lend_days} dní.")
    if action == "returned":
        return ToolResult(shopx.returned(ctx, name or text), "Vráceno, smazal jsem to." if name or text else "Co se vrátilo?")
    if action == "lent":
        rows = [dict(r) for r in shopx.db(ctx).all("SELECT * FROM sx_lent ORDER BY since")]
        return ToolResult(True, "\n".join(f"• {r['item']} – {r['person']} (od {r['since']})" for r in rows) or "Nic není půjčené.")
    if action == "cut":
        try:
            m2 = re.match(r"\s*([\d.,]+)\s*[x×]\s*([\d.,]+)\s*:(.*)", text)
            if m2:
                parts = [tuple(float(v.replace(",", ".")) for v in re.split(r"[x×]", part.strip())) for part in m2.group(3).split(",") if part.strip()]
                r = shopx.sheet_plan((float(m2.group(1).replace(",", ".")), float(m2.group(2).replace(",", "."))),
                                     [(a, b) for a, b in parts], amount or 3)
                return ToolResult(True, f"{r['count']} desek, odpad {r['waste_pct']} %.\n" + "\n".join(
                    f"Deska {i + 1}: " + ", ".join(f"{x['w']:g}×{x['h']:g} @ ({x['x']:g},{x['y']:g})" for x in s) for i, s in enumerate(r["sheets"])), data=r)
            stock, rest = text.split(":", 1)
            cuts = []
            for part in rest.split(","):
                mm_ = re.match(r"\s*(\d+)\s*[x×]\s*([\d.,]+)\s*$", part)
                if mm_:
                    cuts += [float(mm_.group(2).replace(",", "."))] * int(mm_.group(1))
                elif part.strip():
                    cuts.append(float(part.strip().replace(",", ".")))
            r = shopx.cut_plan(float(stock.strip().replace(",", ".")), cuts, amount or 3)
        except ValueError as e:
            return ToolResult(False, str(e) if "Kus" in str(e) or "Díl" in str(e) else "Napiš „2440: 800, 800, 3x600“ nebo „2800x2070: 600x400, 600x400“.")
        return ToolResult(True, f"{r['count']} prken, odpad {r['waste_pct']} %.\n" + "\n".join(
            f"Prkno {i + 1}: {' + '.join(f'{x:g}' for x in b['pieces'])} (zbytek {b['rest']:g})" for i, b in enumerate(r["boards"])), data=r)
    if action == "paint":
        r = shopx.paint_need(amount, text)
        return ToolResult(True, r["text"], data=r)
    if action == "anchor":
        return ToolResult(True, shopx.anchor_advice(text, amount or 5))
    if action == "maint_add":
        mid = shopx.maint_add(ctx, name, text, n or 90)
        return ToolResult(True, f"Údržba #{mid}: {name} – {text}, každých {n or 90} dní.")
    if action == "maint":
        if not shopx.db(ctx).one("SELECT 1 FROM sx_maint"):
            for t, task, days in shopx.MAINT_DEFAULTS:
                shopx.maint_add(ctx, t, task, days)
        due = shopx.maint_due(ctx, dt.date.today())
        return ToolResult(True, "\n".join(f"#{d['id']} {d['tool']}: {d['task']}" + (f" ({d['late']} dní po termínu)" if d["late"] else "") for d in due)
                          or "Žádná údržba teď není na řadě.", data={"due": due})
    if action == "maint_done":
        return ToolResult(shopx.maint_done(ctx, n), "Zapsáno, příště za plánovaný interval.")
    if action == "split":
        if model.suffix.lower() != ".stl":
            return ToolResult(False, "Rozdělím STL.")
        tris = await asyncio.to_thread(shopx.stl_read, model)
        d = shopx.dims(tris)
        bed = (c.printers[0].get("bed") if c.printers else None) or [256, 256, 256]
        split = shopx.split_plan(d, bed)
        if split["pieces"] == 1:
            return ToolResult(True, f"Model {d[0]:g}×{d[1]:g}×{d[2]:g} mm se vejde na podložku {bed[0]}×{bed[1]} mm vcelku.")
        mn = [float(x) for x in tris.reshape(-1, 3).min(0)]
        outs: list[str] = []
        errs: list[str] = []
        for ix in range(split["counts"][0]):
            for iy in range(split["counts"][1]):
                for iz in range(split["counts"][2]):
                    o = model.with_name(f"{model.stem}-dil-{ix + 1}{iy + 1}{iz + 1}.stl")
                    ok, err = await asyncio.to_thread(shopx.run_openscad, shopx.split_scad(model, mn, d, split["counts"], ix, iy, iz), o)
                    (outs if ok else errs).append(str(o) if ok else err)
                    if errs and "OpenSCAD" in errs[0]:
                        return ToolResult(False, f"Potřebuju {split['pieces']} dílů ({' × '.join(map(str, split['counts']))}). {errs[0]}", data=split)
        return ToolResult(not errs, f"{len(outs)} dílů s otvory na kolíky ⌀4 mm (vytiskni kolíky nebo použij kousky filamentu 1,75 mm × 4).",
                          data={**split, "files": outs})
    if action == "safety":
        rules = shopx.safety_for(text)
        return ToolResult(True, "\n".join(f"• {r}" for r in rules) or "Obecně: brýle, upnutý materiál, uklizený stůl, hasicí přístroj na dosah.")
    files = [model] + [q for q in model.parent.glob(f"{model.stem}*") if q != model and q.suffix.lower() in (".stl", ".3mf", ".step")][:10]
    out = paths.sub("dilna") / f"printables-{re.sub(r'[^a-z0-9]+', '-', devx_fold(name or model.stem))}.zip"
    r = await asyncio.to_thread(shopx.printables_package, files, out, name or model.stem, text)
    return ToolResult(True, f"Balíček: {out} ({r['models']} modelů, {r['pictures']} obrázků, POPIS.md). Nahraj ho na printables.com → Upload model.",
                      data=r)


def devx_fold(s: str) -> str:
    from ..devx import fold

    return fold(s)


@tool("fun_kit", "Zábava: herní kouč (coach text=hra), playlist podle nálady (playlist text), skóre deskovek (score name=hráč+amount, "
      "text=hra; scores, score_reset), pravidla hry (rules text=hra, name=dotaz), film na večer (film text=nálada), knihovna her "
      "(games), náhodná hra (random_game), hlídání slev (wish text+amount=cena v $, wishes), kvíz na telefonech (quiz text=téma / "
      "„hudba“), podcast bez reklam (podcast path), textová hra (adventure text), časovač hraní dětí (play_start name, play_stop "
      "name), ekvalizér podle žánru (eq text), fotky do alb (albums path, albums_apply path), zkrácení videa (video path+amount=s, "
      "text=hudba), píseň z rádia do seznamu (radio), Discord společník (discord), seriály (show_add text, watched text+values="
      "„S2E5“, shows), koncerty (concerts), zvuky upozornění (sounds text=krystal/marimba/scifi/klid/původní).", category="zábava",
      danger_if=lambda a: a.get("action") in FUN_CHANGES)
async def fun_kit(ctx, action: Literal["coach", "playlist", "score", "scores", "score_reset", "rules", "film", "games", "random_game", "wish",
                                       "wishes", "quiz", "podcast", "adventure", "play_start", "play_stop", "eq", "albums", "albums_apply",
                                       "video", "radio", "discord", "show_add", "watched", "shows", "concerts", "sounds"],
                  text: str = "", name: str = "", path: str = "", amount: float = 0, values: str = "") -> ToolResult:
    c = ctx.cfg.funx
    port = ctx.cfg.phone.port
    if action == "coach":
        game = text or getattr(getattr(ctx, "gamecoach", None), "game", "") or ""
        line = funx.coach_for(ctx, game) if game else ""
        return ToolResult(bool(line), line or "Zatím nemám dost výsledků – zapisuj zápasy („vyhrál jsem 13:7“).")
    if action == "playlist":
        snap = dict(getattr(ctx, "media_state", {}) or {})
        hist = [{"artist": snap.get("artist", ""), "title": snap.get("title", "")}] if snap.get("artist") else []
        hist += [{"artist": a} for a in ctx.cfg.funx.favorite_artists]
        q = funx.mood_query(text, hist)
        from .youtube import youtube_play

        r = await youtube_play(ctx, q["query"] + " playlist")
        return ToolResult(r.ok, f"Nálada „{q['mood']}“: {q['query']} ({q['bpm'][0]}–{q['bpm'][1]} BPM). " + r.summary, data=q)
    if action == "score":
        funx.score_add(ctx, text or "hra", name, amount)
        tab = funx.score_table(ctx, text or "hra")
        return ToolResult(True, "Pořadí: " + ", ".join(f"{t['player']} {t['points']:g}" for t in tab), data={"table": tab})
    if action == "scores":
        tab = funx.score_table(ctx, text or "hra")
        return ToolResult(True, ", ".join(f"{t['player']} {t['points']:g}" for t in tab) or "Zatím žádné body.")
    if action == "score_reset":
        funx.score_reset(ctx, text or "hra")
        return ToolResult(True, "Nová hra, body vynulované.")
    if action == "rules":
        return ToolResult(True, (await _ai(ctx, funx.RULES_PROMPT.format(game=text, ask=name or "základní pravidla"), fast=False)).strip())
    if action == "film":
        try:
            films = await funx.film_tonight(ctx, text, c.services)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(bool(films), "\n".join(f"• {f['title']} ({f['year']}, {f['rating']}/10): {f['overview'][:140]}" for f in films)
                          or "Nic jsem nenašel – zkus jinou náladu.", data={"films": films})
    if action in ("games", "random_game"):
        games = await asyncio.to_thread(funx.game_library, c.steam_dir, c.epic_dir)
        if not games:
            return ToolResult(False, "Nenašel jsem nainstalované hry ze Steamu, Epicu ani GOG.")
        if action == "games":
            by: dict[str, list[str]] = {}
            for g in games:
                by.setdefault(g["store"], []).append(g["name"])
            return ToolResult(True, "; ".join(f"{k} ({len(v)}): {', '.join(v[:12])}" for k, v in by.items()), data={"games": games})
        recent = set()
        try:
            recent = {r["game"] for r in ctx.db.all("SELECT DISTINCT game FROM game_sessions WHERE start >= ?", (dt.datetime.now().timestamp() - 3 * 86400,))}
        except Exception:  # noqa: BLE001
            pass
        pick = funx.random_game(games, recent)
        if pick is None:
            return ToolResult(False, "Nemám z čeho vybírat.")
        if pick["launch"]:
            if "://" in pick["launch"]:
                ctx.platform.open_url(pick["launch"])
            else:
                ctx.platform.open_path(pick["launch"])
        return ToolResult(True, f"Dnes: {pick['name']} ({pick['store']}) – spouštím.", data=pick)
    if action == "wish":
        funx.wish_add(ctx, text, amount)
        return ToolResult(True, f"Hlídám {text}" + (f" pod ${amount:g}." if amount else " (ozvu se při velké slevě)."))
    if action == "wishes":
        rows = funx.wish_list(ctx)
        return ToolResult(True, "\n".join(f"• {w['title']}: " + (f"teď ${w['last']:.2f}" if w["last"] is not None else "zatím nezjištěno")
                                          + (f", hlídám ${w['target']:g}" if w["target"] else "") for w in rows) or "Seznam přání je prázdný.")
    if action == "quiz":
        if devx_fold(text).startswith("hud"):
            files = [f for d in c.music_dirs for f in Path(d).expanduser().rglob("*") if f.suffix.lower() in (".mp3", ".m4a", ".ogg", ".flac", ".wav")][:2000]
            qs = funx.music_round(files)
            if not qs:
                return ToolResult(False, "Na hudební kvíz potřebuju aspoň 4 písničky (Nastavení → Zábava → Složky s hudbou).")
        else:
            qs = []
            if text:
                try:
                    qs = funx.parse_quiz(await _ai(ctx, funx.QUIZ_PROMPT.format(n=10, topic=text), fast=False))
                except Exception:  # noqa: BLE001
                    qs = []
            qs = qs or funx.BUILTIN_QUIZ[:]
        tok = funx.quiz_create(ctx, qs, f"Kvíz: {text or 'všehochuť'}")
        base = str(getattr(ctx.cfg.phone_link, "public_url", "") or "").rstrip("/") or f"http://localhost:{port}"
        try:
            ctx.platform.open_url(f"http://localhost:{port}/quiz/{tok}/host")
        except Exception:  # noqa: BLE001
            pass
        return ToolResult(True, f"Kvíz připraven ({len(qs)} otázek). Hosté se připojí na {base}/quiz/{tok} (QR je na obrazovce kvízu).",
                          data={"token": tok, "join": f"{base}/quiz/{tok}"})
    if action == "podcast":
        from .files import resolve

        p = resolve(path)
        if not p.is_file():
            return ToolResult(False, "Pošli cestu ke stažené epizodě.")
        stt = getattr(ctx.voice, "transcriber", None) if getattr(ctx, "voice", None) else None
        if stt is None:
            return ToolResult(False, "Na hledání reklam potřebuju přepis s časy – zapni hlasový modul (místní Whisper nebo Groq).")
        try:
            raw = await asyncio.to_thread(stt.segments, str(p))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"Přepis se nepovedl: {e}")
        segs = [{"start": a, "end": b, "text": t} for a, b, t in raw]
        cut = funx.ad_segments(segs)
        if not cut:
            return ToolResult(True, "Sponzorské vstupy jsem v epizodě nenašel.")
        total = float(segs[-1]["end"]) if segs else 0
        keep = funx.keep_ranges(cut, total)
        out = p.with_name(f"{p.stem}-bez-reklam.mp3")
        r = await asyncio.to_thread(subprocess.run, ["ffmpeg", "-y", "-i", str(p), "-filter_complex", funx.ffmpeg_concat_filter(keep),
                                                     "-map", "[out]", str(out)], capture_output=True, text=True, timeout=1800)
        mins = sum(b - a for a, b in cut) / 60
        return ToolResult(r.returncode == 0, f"Vystřiženo {len(cut)} sponzorských vstupů ({mins:.1f} min): {out}" if r.returncode == 0
                          else "ffmpeg selhal: " + (r.stderr or "")[-300:], data={"cut": cut})
    if action == "adventure":
        st = funx.adventure_load(ctx)
        if devx_fold(text) in ("nova hra", "znovu", "restart", ""):
            st = {"state": {}, "log": []}
        msgs = [{"role": "user", "content": funx.ADVENTURE_RULES + (f"\nAktuální STAV: {json.dumps(st['state'], ensure_ascii=False)}" if st["state"] else
                                                                    "\nZačni novou hru: krátký úvod a první volba.")}]
        for m in st["log"][-12:]:
            msgs.append(m)
        msgs.append({"role": "user", "content": text or "Začni."})
        out = await ctx.router.complete(msgs, fast=False)
        story, state = funx.adventure_parse(out)
        log = st["log"] + [{"role": "user", "content": text or "Začni."}, {"role": "assistant", "content": story}]
        funx.adventure_save(ctx, state or st["state"], log)
        return ToolResult(True, story, data={"state": state})
    if action == "play_start":
        funx.play_start(ctx, name)
        lim = c.play_limits.get(name)
        return ToolResult(True, f"{name} hraje" + (f", dnes má {lim} min." if lim else " (limit nemá – nastav ho v Zábava → Hraní dětí)."))
    if action == "play_stop":
        return ToolResult(True, f"{name} dnes hrál(a) {funx.play_stop(ctx, name):g} min.")
    if action == "eq":
        genre = text
        if not genre:
            try:
                from .. import nowplaying

                genre = (await nowplaying.song_info(ctx)).get("genre", "")
            except Exception:  # noqa: BLE001
                genre = ""
        preset = funx.eq_for_genre(genre)
        try:
            f = await asyncio.to_thread(funx.eq_apply, preset)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Ekvalizér: {preset} ({genre or 'neznámý žánr'}) – {f}")
    if action in ("albums", "albums_apply"):
        from .files import resolve

        folder = resolve(path)
        if not folder.is_dir():
            return ToolResult(False, "Pošli složku s fotkami.")
        plan = await asyncio.to_thread(funx.album_plan, folder)
        if action == "albums":
            return ToolResult(True, f"{len(plan)} akcí: " + ", ".join(f"{e['name']} ({len(e['photos'])})" for e in plan[:15])
                              + ". Řekni „roztřiď je“ a přesunu je do složek.", data={"events": [{"name": e["name"], "n": len(e["photos"])} for e in plan]})
        n = await asyncio.to_thread(funx.album_apply, plan, folder / "Alba")
        return ToolResult(True, f"Přesunuto {n} fotek do {folder / 'Alba'}.")
    if action == "video":
        from .files import resolve

        p = resolve(path)
        if not p.is_file():
            return ToolResult(False, "Pošli cestu k videu.")
        try:
            dur = await asyncio.to_thread(funx.probe_duration, p)
        except ValueError as e:
            return ToolResult(False, str(e))
        music = resolve(text) if text and resolve(text).is_file() else None
        clips = funx.short_segments(dur, amount or 60)
        out = p.with_name(f"{p.stem}-kratke.mp4")
        r = await asyncio.to_thread(subprocess.run, funx.ffmpeg_short_cmd(p, out, clips, music), capture_output=True, text=True, timeout=3600)
        return ToolResult(r.returncode == 0, f"Hotovo: {out} ({sum(b - a for a, b in clips):.0f} s z {dur:.0f} s, {len(clips)} záběrů)" if r.returncode == 0
                          else "ffmpeg selhal: " + (r.stderr or "")[-300:])
    if action == "radio":
        from .. import nowplaying

        info = await nowplaying.song_info(ctx)
        if not info.get("ok") or not info.get("title"):
            return ToolResult(False, "Nepoznal jsem, co hraje (rádio v prohlížeči nebo Spotify musí ukazovat název). Z reproduktoru "
                                     "v místnosti to bez služby na rozpoznání hudby nejde.")
        from .list_tools import list_add

        item = f"{info.get('artist', '')} – {info['title']}".strip(" –")
        await list_add(ctx, [item], "písně z rádia")
        return ToolResult(True, f"Uloženo do seznamu „písně z rádia“: {item}")
    if action == "discord":
        ok, why = funx.discord_ready()
        if not ok:
            return ToolResult(False, why)
        if getattr(ctx, "_discord_task", None) and not ctx._discord_task.done():
            return ToolResult(True, "Společník už je v Discordu. Příkazy: !kviz, !a, !hraj <odkaz>, !stop, !skore.")
        ctx._discord_task = asyncio.create_task(funx.run_discord_bot(ctx))
        return ToolResult(True, "Společník se připojuje do Discordu. Na serveru napiš !pomoc.")
    if action == "show_add":
        funx.show_add(ctx, text)
        return ToolResult(True, f"Sleduju {text}. Řekni „dokoukal jsem {text} S1E3“ a budu vědět, kde jsi.")
    if action == "watched":
        m = re.search(r"s(\d+)\s*e(\d+)", (values or text).lower())
        if not m:
            return ToolResult(False, "Řekni díl jako S2E5.")
        ok = funx.show_watched(ctx, re.sub(r"(?i)s\d+\s*e\d+", "", text).strip() or name, int(m.group(1)), int(m.group(2)))
        return ToolResult(ok, "Zapsáno." if ok else "Ten seriál nesleduju – přidej ho.")
    if action == "shows":
        rows = funx.shows(ctx)
        return ToolResult(True, "\n".join(f"• {s['name']}: jsi na S{s['season']:02d}E{s['episode']:02d}" + (f", další díl {s['next_air']}" if s["next_air"] else "")
                                          for s in rows) or "Nesleduju žádné seriály.")
    if action == "concerts":
        artists = c.favorite_artists
        snap = dict(getattr(ctx, "media_state", {}) or {})
        if not artists and snap.get("artist"):
            artists = [snap["artist"]]
        if not artists:
            return ToolResult(False, "Řekni mi oblíbené kapely (Nastavení → Zábava → Oblíbení interpreti).")
        try:
            evs = await funx.concerts(ctx, artists)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, "\n".join(f"• {e['date']} {e['artist']} – {e['venue']}, {e['city']}" for e in evs[:12]) or "Teď nikdo z nich v ČR nehraje.",
                          data={"events": evs})
    # sounds
    pack = devx_fold(text)
    d = ctx.sounds_dir()
    if pack in ("puvodni", "vychozi", "default", ""):
        n = funx.remove_pack(d)
        ctx.bus.publish("sounds", files=ctx.custom_sounds())
        return ToolResult(True, f"Zpátky původní zvuky ({n} souborů odstraněno).")
    try:
        r = await asyncio.to_thread(funx.install_pack, pack, d)
    except ValueError as e:
        return ToolResult(False, str(e))
    ctx.bus.publish("sounds", files=ctx.custom_sounds())
    return ToolResult(True, f"Sada „{pack}“: {len(r['written'])} zvuků" + (f"; tvoje vlastní ({', '.join(r['kept'])}) jsem nechal." if r["kept"] else "."))

