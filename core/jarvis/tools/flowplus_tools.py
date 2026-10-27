"""Wave 43 by voice: record a workflow and share it, animated scene proposals, move the sound to another device and a
rigging assistant for 3D characters."""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import REGISTRY, ToolResult, is_dangerous, tool
from .files import resolve

_REC: dict = {}


async def _watch(ctx, watch) -> None:
    while _REC.get("watch") is watch:
        watch.sample()
        await asyncio.sleep(2)


def _recorded_steps(ctx) -> list[dict]:
    from .. import flowplus

    start = _REC.get("start", time.time())
    have = ctx.db.one("SELECT name FROM sqlite_master WHERE name='task_actions'")
    acts = ctx.db.all("SELECT ts, tool, args, ok FROM task_actions WHERE ts >= ? ORDER BY ts", (start,)) if have else []
    return flowplus.steps_from_recording(acts, _REC["watch"].log if _REC.get("watch") else [])


def _rec_danger(a: dict, ctx=None) -> bool:
    return a.get("action") == "stop"


def _rec_details(a: dict, ctx=None) -> list[str]:
    from ..agent import describe_call

    if a.get("action") != "stop" or ctx is None:
        return []
    steps = _recorded_steps(ctx)
    if not steps:
        return ["Nenahrál se žádný krok – nic se neuloží."]
    return [f"Uloží postup „{a.get('name') or _REC.get('name', 'Můj postup')}“ jako dovednost:"] + \
        [f"{i + 1}. {describe_call(s['tool'], s['args'])}" for i, s in enumerate(steps)]


@tool("workflow_record", "Nahraje postup: od „začni nahrávat“ si zapisuje, co JARVIS dělá, a které aplikace přepínáš (jen jejich "
      "názvy – žádné klávesy ani obrazovka). Po „stop“ z toho uloží dovednost, kterou spustíš jedním příkazem.",
      category="systém", perm="apps", danger_if=_rec_danger, details=_rec_details)
async def workflow_record(ctx, action: Annotated[str, "start / stop / cancel"], name: str = "") -> ToolResult:
    from .. import flowplus, skillforge

    action = action.lower().strip()
    if action == "start":
        if _REC.get("watch"):
            return ToolResult(False, "Už nahrávám – řekni „stop“.")
        watch = flowplus.AppWatch(ctx.platform.foreground_app)
        _REC.update(start=time.time(), name=name or "Můj postup", watch=watch)
        _REC["task"] = asyncio.get_running_loop().create_task(_watch(ctx, watch))
        ctx.notify("Nahrávám postup", "Zapisuji kroky a přepnuté aplikace (jen názvy). Ukonči „stop nahrávání“.", speak=False)
        return ToolResult(True, f"Nahrávám postup „{_REC['name']}“. Dělej, co potřebuješ, pak řekni „stop nahrávání“.")
    if not _REC.get("watch"):
        return ToolResult(False, "Teď nic nenahrávám.")
    if action == "cancel":
        _REC.clear()
        return ToolResult(True, "Nahrávání zrušeno, nic se neuložilo.")
    steps = _recorded_steps(ctx)
    nm = name or _REC.get("name", "Můj postup")
    _REC.clear()
    if not steps:
        return ToolResult(False, "Nenahrál jsem žádný krok, který by šlo zopakovat.")
    pid = re.sub(r"[^a-z0-9]+", "-", skillforge._ascii(nm.lower())).strip("-") or f"postup-{int(time.time())}"
    proto = {"id": pid, "name": nm[:40], "icon": "record", "steps": steps}
    m = skillforge.manifest(ctx, proto)
    if m["problems"]:
        return ToolResult(False, "Postup nejde uložit: " + " ".join(m["problems"]), data=m)
    items = [x.model_dump(mode="json") for x in ctx.cfg.stark.protocols if x.id != pid] + [proto]
    ctx.skill_note = "nahraný postup"
    ctx.update_config({"stark": {"protocols": items}})
    return ToolResult(True, f"Postup „{nm}“ uložen ({len(steps)} kroků). Spustíš ho „spusť protokol {nm.lower()}“.", data={"id": pid, "steps": steps})


@tool("workflow_export", "Připraví dovednost / postup ke sdílení: soubor bez hesel a klíčů (nahradí je ***), s domovskou "
      "složkou jako ~ a kontrolním součtem.", category="systém")
async def workflow_export(ctx, name: str) -> ToolResult:
    from .. import flowplus
    from ..comms import fold

    p = next((x for x in ctx.cfg.stark.protocols if fold(name) in fold(x.name) or x.id == name), None)
    if not p:
        return ToolResult(False, f"Dovednost „{name}“ nemám.")
    r = flowplus.export_flow(p.model_dump(mode="json"), str(Path.home()))
    out = paths.sub("postupy") / f"{p.id}.jarvisflow.json"
    out.write_text(json.dumps(r["flow"], ensure_ascii=False, indent=1), encoding="utf-8")
    return ToolResult(True, f"„{p.name}“ připraveno ke sdílení ({len(r['flow']['steps'])} kroků"
                            + (f", skryl jsem {r['removed_secrets']} citlivých údajů" if r["removed_secrets"] else "") + ").",
                      data={"removed": r["removed_secrets"]}, attachments=[str(out)])


def _import_check(a: dict, ctx=None) -> dict:
    from .. import flowplus

    p = resolve(a.get("file", ""))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "problems": ["Soubor nejde přečíst."], "steps": [], "warnings": []}

    def danger(t, args):
        return is_dangerous(REGISTRY[t], args, ctx=ctx)
    return flowplus.check_flow(data, set(REGISTRY), danger)


def _import_details(a: dict, ctx=None) -> list[str]:
    c = _import_check(a, ctx)
    lines = [f"Přidá sdílený postup „{c.get('name', '')}“ – kroky:"]
    for s in c["steps"]:
        lines.append(f"{s['n']}. {s['tool'] or ('AI: ' + s['ask'][:80] if s['ask'] else 'řekne: ' + s['say'][:60])}"
                     + (" (MĚNÍ věci – při spuštění se zeptám)" if s["changes"] else ""))
    return lines + c["problems"] + c.get("warnings", [])


@tool("workflow_import", "Přidá postup, který ti někdo poslal (.jarvisflow.json): ověří, že nebyl změněn, a že zná všechny "
      "nástroje, a ukáže kroky ke schválení. Kroky, které něco mění, se i potom potvrzují.", category="systém", perm="files_read",
      danger=True, details=_import_details)
async def workflow_import(ctx, file: str) -> ToolResult:
    import hashlib

    c = _import_check({"file": file}, ctx)
    if not c["ok"]:
        return ToolResult(False, "Postup nejde přidat: " + " ".join(c["problems"] or ["je prázdný"]), data=c)
    data = json.loads(resolve(file).read_text(encoding="utf-8"))
    pid = "sdileny-" + hashlib.sha256(data["sha256"].encode()).hexdigest()[:8]
    allowed = {"say", "tool", "args", "ask", "when", "needs"}
    steps = [{k: v for k, v in st.items() if k in allowed} for st in data["steps"][:30]]
    items = [x.model_dump(mode="json") for x in ctx.cfg.stark.protocols if x.id != pid] + \
        [{"id": pid, "name": f"Sdílený: {c['name']}"[:40], "icon": "share-network", "steps": steps}]
    ctx.skill_note = "sdílený postup"
    ctx.update_config({"stark": {"protocols": items}})
    return ToolResult(True, f"Postup „{c['name']}“ přidán jako „Sdílený: {c['name']}“." + (" " + " ".join(c["warnings"]) if c["warnings"] else ""),
                      data=c)


@tool("scene_animation", "Navrhne animovanou scénu podle zadání: sled záběrů s časy, pohybem kamery a animací – s živým náhledem "
      "v prohlížeči a skriptem pro Blender.", category="design")
async def scene_animation(ctx, brief: str, seconds: float = 12, style: Annotated[str, "klidná / energická / hravá / technická"] = "") -> ToolResult:
    from .. import flowplus

    plan = flowplus.scene_plan(brief, max(3.0, min(seconds, 120.0)), style)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    d = paths.sub("animace")
    html_p, py_p = d / f"scena-{stamp}.html", d / f"scena-{stamp}.py"
    html_p.write_text(flowplus.scene_preview_html(plan), encoding="utf-8")
    py_p.write_text(flowplus.scene_blender_script(plan), encoding="utf-8")
    shots = "; ".join(f"{s['start']:g}–{s['start'] + s['duration']:g} s {s['shot']} ({s['camera']})" for s in plan["shots"])
    return ToolResult(True, f"Scéna ({plan['style']}, {plan['seconds']:g} s): {shots}. Náhled a skript pro Blender jsou v přílohách.",
                      data=plan, attachments=[str(html_p), str(py_p)])


@tool("audio_device", "Přepne zvuk na jiné zařízení – sluchátka, reproduktory, headset, televizi (výstup i mikrofon, i během hovoru) "
      "– nebo vypíše dostupná zařízení.", category="média", perm="system")
async def audio_device(ctx, device: Annotated[str, "sluchátka / reproduktory / část názvu (prázdné = seznam)"] = "",
                       kind: Annotated[str, "output / input / both"] = "output") -> ToolResult:
    from .. import flowplus

    if sys.platform != "win32":
        return ToolResult(False, "Přepínání zvukových zařízení umím jen ve Windows.")
    try:
        devs = await asyncio.to_thread(flowplus.list_devices)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Zvuková zařízení nejde načíst: {type(e).__name__}")
    if not device:
        act = [d for d in devs if d["state"] == "active"]
        return ToolResult(True, "Výstupy: " + ", ".join(d["name"] for d in act if d["flow"] == "output") + ". Mikrofony: "
                          + ", ".join(d["name"] for d in act if d["flow"] == "input") + ".", data=act)
    done = []
    for flow in (("output", "input") if kind == "both" else (kind,)):
        d = flowplus.pick_device([x for x in devs if x["flow"] == flow], device)
        if d:
            await asyncio.to_thread(flowplus.set_default_device, d["id"])
            done.append(f"{'zvuk' if flow == 'output' else 'mikrofon'} → {d['name']}")
    if not done:
        return ToolResult(False, f"Zařízení „{device}“ nevidím (je zapnuté a připojené?).")
    return ToolResult(True, "Přepnuto: " + ", ".join(done) + ".", data={"switched": done})


@tool("rig_assistant", "Kostra (rig) pro 3D postavu: lidská nebo čtyřnohá, přizpůsobená výšce, jako skript pro Blender (i s "
      "automatickými váhami k modelu) – nebo kontrola kostry v hotovém modelu .gltf / .glb (chybějící strany, smyčky, nulové kosti).",
      category="design", perm="files_read")
async def rig_assistant(ctx, kind: Annotated[str, "humanoid / quadruped"] = "humanoid", height: float = 1.8, mesh: str = "",
                        check_file: Annotated[str, "model .gltf/.glb ke kontrole (prázdné = vytvořit kostru)"] = "") -> ToolResult:
    from .. import flowplus

    if check_file:
        p = resolve(check_file)
        if not p.is_file():
            return ToolResult(False, f"Soubor neexistuje: {p}")
        try:
            bones = await asyncio.to_thread(flowplus.gltf_bones, p)
        except (ValueError, KeyError, IndexError) as e:
            return ToolResult(False, f"Kostru nejde přečíst: {e}")
        r = flowplus.check_rig(bones)
        msg = f"{p.name}: {r['bones']} kostí, " + ("v pořádku" if r["ok"] and not r["warnings"] else "; ".join((r["problems"] + r["warnings"])[:5]))
        return ToolResult(True, msg + ".", data=r)
    bones = flowplus.quadruped_rig(height) if kind.startswith("q") or "čtyř" in kind else flowplus.humanoid_rig(height)
    r = flowplus.check_rig(bones)
    out = paths.sub("animace") / f"rig-{kind[:10]}-{time.strftime('%Y%m%d-%H%M%S')}.py"
    out.write_text(flowplus.blender_rig_script(bones, mesh), encoding="utf-8")
    return ToolResult(True, f"Kostra ({len(bones)} kostí, {'v pořádku' if r['ok'] else 'problémy: ' + '; '.join(r['problems'])}). "
                            f"Spusť skript v Blenderu (Scripting → Run){' – model ' + mesh + ' se napojí s automatickými vahami' if mesh else ''}.",
                      data={"bones": [b["name"] for b in bones], "check": r}, attachments=[str(out)])
