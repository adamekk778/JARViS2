"""OMEGA wave 43: recording a workflow (146) and sharing it safely (153), animated scene proposals (127), moving audio
between devices (414) and a rigging assistant for 3D models (667)."""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import time
from pathlib import Path
from typing import Any, Callable

from .comms import fold

# ---------------------------------------------------------------- 146 workflow recorder
SKIP = {"update_plan", "remember", "recall", "workflow_record", "workflow_export", "workflow_import", "ui_tick"}


def steps_from_recording(actions: list[dict], apps: list[dict]) -> list[dict]:
    """task_actions rows (ts, tool, args, ok) + app switches (ts, app) → protocol steps in time order. A switch to an app
    becomes `open_app`; failed or bookkeeping actions are left out; the same step twice in a row is kept once."""
    events = [(a["ts"], "tool", a) for a in actions if a.get("ok") and a.get("tool") not in SKIP]
    events += [(a["ts"], "app", a) for a in apps]
    steps: list[dict] = []
    last_app = ""
    for _, kind, x in sorted(events, key=lambda e: e[0]):
        if kind == "app":
            if x["app"] and x["app"] != last_app:
                last_app = x["app"]
                st = {"tool": "open_app", "args": {"name": x["app"]}}
            else:
                continue
        else:
            try:
                args = json.loads(x.get("args") or "{}") if isinstance(x.get("args"), str) else (x.get("args") or {})
            except ValueError:
                continue
            st = {"tool": x["tool"], "args": args if isinstance(args, dict) else {}}
            if x["tool"] == "open_app":
                last_app = str(st["args"].get("name", ""))
        if not steps or steps[-1] != st:
            steps.append(st)
    return steps[:30]


class AppWatch:
    """While recording: which app is in front (every 2 s). Only app names – no keys, no screen, no clipboard."""

    def __init__(self, foreground: Callable[[], str]):
        self.fg = foreground
        self.log: list[dict] = []

    def sample(self, now: float | None = None) -> None:
        try:
            app = self.fg() or ""
        except Exception:  # noqa: BLE001
            app = ""
        if app and (not self.log or self.log[-1]["app"] != app):
            self.log.append({"ts": now or time.time(), "app": app})


# ---------------------------------------------------------------- 153 sharing
SECRET_KEY = re.compile(r"pass|heslo|token|secret|key|klic|klíč|auth|cookie|session|pin\b|iban|card|karta", re.I)
SECRET_VAL = re.compile(r"(?:sk|pk|ghp|xox[bap]|AKIA)[-_A-Za-z0-9]{12,}|eyJ[\w-]{10,}\.[\w-]{10,}|\b\d{13,19}\b")
FORMAT = "jarvis-flow/1"


def _scrub(v: Any, key: str = "", home: str = "") -> tuple[Any, int]:
    if isinstance(v, dict):
        out, n = {}, 0
        for k, x in v.items():
            out[k], m = _scrub(x, k, home)
            n += m
        return out, n
    if isinstance(v, list):
        res = [_scrub(x, key, home) for x in v]
        return [r[0] for r in res], sum(r[1] for r in res)
    if isinstance(v, str):
        if key and SECRET_KEY.search(key) and v:
            return "***", 1
        s, n = SECRET_VAL.subn("***", v)
        if home and home in s:
            s = s.replace(home, "~")
        s = re.sub(r"(?i)[A-Z]:\\Users\\[^\\]+", "~", s)
        return s, n
    return v, 0


def export_flow(proto: dict, home: str = "") -> dict:
    """A shareable copy: secrets replaced by ***, the user's home folder by ~, a checksum over the content."""
    steps, removed = _scrub([{k: v for k, v in st.items() if v not in ("", [], {}, None)} for st in proto.get("steps", [])], home=home)
    body = {"format": FORMAT, "name": proto.get("name", "Postup"), "icon": proto.get("icon", "lightning"), "steps": steps,
            "exported": int(time.time())}
    body["sha256"] = hashlib.sha256(json.dumps({k: body[k] for k in ("name", "steps")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"flow": body, "removed_secrets": removed}


def check_flow(data: dict, known_tools: set[str], dangerous: Callable[[str, dict], bool]) -> dict:
    """Before importing someone else's workflow: format, checksum, unknown tools, which steps change things, gaps to fill."""
    problems, warn = [], []
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return {"ok": False, "problems": ["Tohle není sdílený postup JARVISe."], "steps": []}
    steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    want = hashlib.sha256(json.dumps({"name": data.get("name"), "steps": steps}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if want != data.get("sha256"):
        problems.append("Kontrolní součet nesedí – soubor byl po exportu změněn.")
    out = []
    for i, st in enumerate(steps[:30]):
        if not isinstance(st, dict):
            problems.append(f"Krok {i + 1} je poškozený.")
            continue
        t = st.get("tool", "")
        if t and t not in known_tools:
            problems.append(f"Krok {i + 1}: nástroj {t} tady neexistuje.")
        d = bool(t) and t in known_tools and dangerous(t, st.get("args") or {})
        if "***" in json.dumps(st, ensure_ascii=False):
            warn.append(f"Krok {i + 1}: chybí skrytý údaj – doplň ho.")
        out.append({"n": i + 1, "tool": t, "say": st.get("say", ""), "ask": st.get("ask", ""), "changes": d})
    if any(s["ask"] for s in out):
        warn.append("Postup obsahuje úkoly pro AI – jejich text je od autora postupu, ne od tebe.")
    return {"ok": not problems and bool(out), "problems": problems, "warnings": warn, "steps": out, "name": str(data.get("name", ""))[:40]}


# ---------------------------------------------------------------- 127 animated scene proposals
STYLES = {
    "klidná": {"palette": ["#0f172a", "#334155", "#94a3b8", "#e2e8f0", "#38bdf8"], "ease": "ease-in-out", "pace": 1.3},
    "energická": {"palette": ["#111827", "#f43f5e", "#f59e0b", "#10b981", "#fafafa"], "ease": "cubic-bezier(.2,.9,.3,1.3)", "pace": 0.7},
    "hravá": {"palette": ["#fff7ed", "#fb923c", "#a78bfa", "#34d399", "#1f2937"], "ease": "cubic-bezier(.34,1.56,.64,1)", "pace": 0.9},
    "technická": {"palette": ["#020617", "#0ea5e9", "#22d3ee", "#64748b", "#f8fafc"], "ease": "linear", "pace": 1.0},
}
BEATS = [("Úvod", "pomalé přiblížení k hlavnímu motivu", "dolly-in", "zoom"), ("Představení", "motiv vjede do záběru a usadí se", "static", "slide"),
         ("Detail", "kamera obkrouží detail", "orbit", "rotate"), ("Akce", "rychlý pohyb a odraz", "pan", "bounce"),
         ("Vyvrcholení", "vše se seskupí a rozzáří", "crane-up", "pulse"), ("Závěr", "oddálení a text / logo", "dolly-out", "fade")]


def scene_plan(brief: str, seconds: float = 12, style: str = "", shots: int = 0) -> dict:
    """A shot list with timing, camera move and motion – sized to the length, in the chosen mood."""
    f = fold(brief)
    style = style if style in STYLES else ("energická" if re.search(r"sport|akc|rychl|hudb|tanec|reklam", f) else "hravá" if re.search(r"dět|hra|zábav|vtip", f)
                                           else "technická" if re.search(r"tech|aplik|softw|data|robot", f) else "klidná")
    st = STYLES[style]
    n = shots or max(3, min(6, round(seconds / (2.5 * st["pace"]))))
    beats = [BEATS[0]] + BEATS[1:-1][:n - 2] + [BEATS[-1]]
    weights = [1.2] + [1.0] * (len(beats) - 2) + [1.3]
    unit = seconds / sum(weights)
    t, out = 0.0, []
    for (name, what, cam, motion), w in zip(beats, weights):
        d = round(unit * w, 2)
        out.append({"shot": name, "start": round(t, 2), "duration": d, "action": what, "camera": cam, "motion": motion})
        t += d
    return {"brief": brief, "seconds": seconds, "style": style, "palette": st["palette"], "ease": st["ease"], "shots": out}


MOTION_CSS = {"zoom": "from{transform:scale(.4);opacity:0}to{transform:scale(1);opacity:1}",
              "slide": "from{transform:translateX(-120%)}to{transform:translateX(0)}",
              "rotate": "from{transform:rotate(0)}to{transform:rotate(360deg)}",
              "bounce": "0%{transform:translateY(0)}40%{transform:translateY(-60%)}70%{transform:translateY(0)}85%{transform:translateY(-15%)}100%{transform:translateY(0)}",
              "pulse": "0%,100%{transform:scale(1);filter:brightness(1)}50%{transform:scale(1.25);filter:brightness(1.6)}",
              "fade": "from{opacity:1}to{opacity:0}"}


def scene_preview_html(plan: dict) -> str:
    """A self-contained animated preview (CSS only) that plays the shot list in a loop."""
    p, total = plan["palette"], plan["seconds"]
    css, shots = [], []
    for i, s in enumerate(plan["shots"]):
        a, b = s["start"] / total * 100, (s["start"] + s["duration"]) / total * 100
        css.append(f"@keyframes m{i}{{{MOTION_CSS[s['motion']]}}}")
        css.append(f"@keyframes v{i}{{0%,{a:.2f}%{{visibility:hidden}}{a:.2f}%,{b:.2f}%{{visibility:visible}}{b + 0.01:.2f}%,100%{{visibility:hidden}}}}")
        shots.append(f'<div class="shot" style="animation:v{i} {total}s step-end infinite"><div class="obj" style="background:{p[(i % 3) + 1]};'
                     f'animation:m{i} {s["duration"]}s {plan["ease"]} {s["start"]}s infinite"></div><p>{i + 1}. {s["shot"]} – {s["action"]} '
                     f'<small>(kamera: {s["camera"]}, {s["duration"]:g} s)</small></p></div>')
    return ("<!doctype html><html lang='cs'><head><meta charset='utf-8'><title>Návrh animace</title><style>"
            f"body{{margin:0;background:{p[0]};color:{p[4]};font:15px system-ui;display:grid;place-items:center;min-height:100vh}}"
            ".stage{position:relative;width:min(90vw,720px);aspect-ratio:16/9;overflow:hidden;border-radius:14px;"
            f"background:{p[1]}}}.shot{{position:absolute;inset:0;display:grid;place-items:center}}"
            ".obj{width:28%;aspect-ratio:1;border-radius:22%;box-shadow:0 10px 40px rgba(0,0,0,.35)}"
            ".shot p{position:absolute;bottom:8px;left:12px;right:12px;margin:0}"
            + "".join(css) + "</style></head><body><div class='stage'>" + "".join(shots) + "</div></body></html>")


CAM_PATH = {"dolly-in": ((0, -12, 3), (0, -6, 2)), "dolly-out": ((0, -6, 2), (0, -14, 4)), "static": ((0, -9, 2.5), (0, -9, 2.5)),
            "orbit": ((9, 0, 3), (0, 9, 3)), "pan": ((-5, -9, 2.5), (5, -9, 2.5)), "crane-up": ((0, -9, 1), (0, -9, 7))}


def scene_blender_script(plan: dict, fps: int = 24) -> str:
    """Blender (bpy) script: a cube as the motif and a camera keyframed per shot, timeline set to the length."""
    keys = []
    for s in plan["shots"]:
        a, b = CAM_PATH[s["camera"]]
        f0, f1 = int(s["start"] * fps) + 1, int((s["start"] + s["duration"]) * fps)
        keys.append(f"    (({f0}, {a}), ({f1}, {b}), '{s['motion']}'),")
    return f'''import bpy
# Návrh animace: {plan["brief"]!r} ({plan["style"]}, {plan["seconds"]} s)
scn = bpy.context.scene
scn.render.fps = {fps}
scn.frame_start, scn.frame_end = 1, {int(plan["seconds"] * fps)}
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
obj = bpy.context.object
obj.name = "Motiv"
bpy.ops.object.camera_add(location=(0, -10, 3))
cam = bpy.context.object
scn.camera = cam
track = cam.constraints.new("TRACK_TO")
track.target = obj
track.track_axis, track.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
SHOTS = [
{chr(10).join(keys)}
]
for (f0, a), (f1, b), motion in SHOTS:
    cam.location = a
    cam.keyframe_insert("location", frame=f0)
    cam.location = b
    cam.keyframe_insert("location", frame=f1)
    if motion == "rotate":
        obj.rotation_euler[2] = 0
        obj.keyframe_insert("rotation_euler", frame=f0)
        obj.rotation_euler[2] = 6.2832
        obj.keyframe_insert("rotation_euler", frame=f1)
    elif motion in ("pulse", "zoom"):
        obj.scale = (0.4, 0.4, 0.4) if motion == "zoom" else (1, 1, 1)
        obj.keyframe_insert("scale", frame=f0)
        obj.scale = (1, 1, 1) if motion == "zoom" else (1.25, 1.25, 1.25)
        obj.keyframe_insert("scale", frame=f1)
    elif motion == "bounce":
        obj.location.z = 1
        obj.keyframe_insert("location", frame=f0)
        obj.location.z = 3
        obj.keyframe_insert("location", frame=(f0 + f1) // 2)
        obj.location.z = 1
        obj.keyframe_insert("location", frame=f1)
'''


# ---------------------------------------------------------------- 414 audio device handoff
def pick_device(devices: list[dict], query: str) -> dict | None:
    """'sluchátka', 'reproduktory', 'headset', 'bluetooth', part of the name → the best matching active device."""
    q = fold(query)
    syn = {"sluchatk": ["headphone", "headset", "sluchatk", "earbud", "airpods", "buds"], "reprak": ["speaker", "reproduktor", "realtek"],
           "reproduktor": ["speaker", "reproduktor", "realtek"], "monitor": ["display", "hdmi", "monitor"], "headset": ["headset", "hands-free"],
           "bluetooth": ["bluetooth", "bt", "hands-free", "airpods", "buds"], "televiz": ["tv", "hdmi", "display"]}
    words = [w for k, v in syn.items() if k in q for w in v] or [q]
    best, score = None, 0
    for d in devices:
        if d.get("state", "active") != "active":
            continue
        name = fold(d.get("name", ""))
        s = sum(2 if w == q else 1 for w in words if w and w in name)
        if s > score:
            best, score = d, s
    return best


def set_default_device(device_id: str) -> None:            # pragma: no cover – Windows audio policy (COM)
    """Default device for every role (console, multimedia, communications) through IPolicyConfig."""
    import comtypes
    from comtypes import GUID, HRESULT, COMMETHOD, IUnknown
    from ctypes import c_int, c_wchar_p

    class IPolicyConfig(IUnknown):
        _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
        _methods_ = [COMMETHOD([], HRESULT, f"Unused{i}") for i in range(10)] + [
            COMMETHOD([], HRESULT, "SetDefaultEndpoint", (["in"], c_wchar_p, "id"), (["in"], c_int, "role"))]
    comtypes.CoInitialize()
    try:
        pc = comtypes.CoCreateInstance(GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}"), IPolicyConfig, comtypes.CLSCTX_ALL)
        for role in (0, 1, 2):
            pc.SetDefaultEndpoint(device_id, role)
    finally:
        comtypes.CoUninitialize()


def list_devices() -> list[dict]:                          # pragma: no cover – Windows
    from pycaw.pycaw import AudioUtilities

    out = []
    for d in AudioUtilities.GetAllDevices():
        flow = "output" if "{0.0.0." in (d.id or "") else "input" if "{0.0.1." in (d.id or "") else "?"
        out.append({"id": d.id, "name": d.FriendlyName or "", "state": "active" if str(d.state).endswith("Active") else "off", "flow": flow})
    return out


# ---------------------------------------------------------------- 667 rigging
def humanoid_rig(height: float = 1.8) -> list[dict]:
    """A game-ready humanoid skeleton (Blender naming, .L / .R) scaled to the character's height (metres)."""
    h = height / 1.8
    S = lambda *v: tuple(round(x * h, 4) for x in v)  # noqa: E731
    bones = [("root", None, S(0, 0, 0), S(0, 0, 0.1)), ("hips", "root", S(0, 0, 0.95), S(0, 0, 1.05)),
             ("spine", "hips", S(0, 0, 1.05), S(0, 0, 1.25)), ("chest", "spine", S(0, 0, 1.25), S(0, 0, 1.45)),
             ("neck", "chest", S(0, 0, 1.45), S(0, 0, 1.55)), ("head", "neck", S(0, 0, 1.55), S(0, 0, 1.78))]
    for side, x in (("L", 1), ("R", -1)):
        bones += [(f"shoulder.{side}", "chest", S(0.03 * x, 0, 1.42), S(0.17 * x, 0, 1.42)),
                  (f"upper_arm.{side}", f"shoulder.{side}", S(0.17 * x, 0, 1.42), S(0.45 * x, 0, 1.42)),
                  (f"forearm.{side}", f"upper_arm.{side}", S(0.45 * x, 0, 1.42), S(0.7 * x, 0, 1.42)),
                  (f"hand.{side}", f"forearm.{side}", S(0.7 * x, 0, 1.42), S(0.8 * x, 0, 1.42)),
                  (f"thigh.{side}", "hips", S(0.1 * x, 0, 0.95), S(0.1 * x, 0, 0.52)),
                  (f"shin.{side}", f"thigh.{side}", S(0.1 * x, 0, 0.52), S(0.1 * x, 0, 0.09)),
                  (f"foot.{side}", f"shin.{side}", S(0.1 * x, 0, 0.09), S(0.1 * x, -0.15, 0.02))]
    return [{"name": n, "parent": p, "head": a, "tail": b} for n, p, a, b in bones]


def quadruped_rig(length: float = 1.0) -> list[dict]:
    h = length
    S = lambda *v: tuple(round(x * h, 4) for x in v)  # noqa: E731
    bones = [("root", None, S(0, 0, 0), S(0, 0, 0.1)), ("pelvis", "root", S(0, 0.4, 0.6), S(0, 0.2, 0.62)),
             ("spine", "pelvis", S(0, 0.2, 0.62), S(0, -0.2, 0.64)), ("chest", "spine", S(0, -0.2, 0.64), S(0, -0.4, 0.66)),
             ("neck", "chest", S(0, -0.4, 0.66), S(0, -0.55, 0.8)), ("head", "neck", S(0, -0.55, 0.8), S(0, -0.75, 0.82)),
             ("tail", "pelvis", S(0, 0.4, 0.6), S(0, 0.7, 0.55))]
    for side, x in (("L", 1), ("R", -1)):
        for part, y in (("front", -0.4), ("back", 0.4)):
            top = "chest" if part == "front" else "pelvis"
            bones += [(f"{part}_upper.{side}", top, S(0.12 * x, y, 0.6), S(0.12 * x, y, 0.32)),
                      (f"{part}_lower.{side}", f"{part}_upper.{side}", S(0.12 * x, y, 0.32), S(0.12 * x, y, 0.06)),
                      (f"{part}_paw.{side}", f"{part}_lower.{side}", S(0.12 * x, y, 0.06), S(0.12 * x, y - 0.08, 0.01))]
    return [{"name": n, "parent": p, "head": a, "tail": b} for n, p, a, b in bones]


def _side(name: str) -> tuple[str, str] | None:
    """'thigh.L' / 'hand_r' / 'mixamorig:LeftArm' → (base, 'L' | 'R')."""
    m = re.match(r"^(.+?)[._-](L|R|l|r|left|right|Left|Right)$", name)
    if m:
        return m.group(1), m.group(2)[0].upper()
    m = re.match(r"^(.*?)(Left|Right)(.+)$", name)
    if m:
        return m.group(1) + m.group(3), m.group(2)[0]
    return None


def check_rig(bones: list[dict]) -> dict:
    """Missing parents, loops, several roots, zero-length bones, left without right (and the other way), mirrored lengths."""
    names = {b["name"] for b in bones}
    problems, warnings = [], []
    roots = [b["name"] for b in bones if not b.get("parent")]
    if len(roots) > 1:
        warnings.append(f"Víc kořenových kostí ({', '.join(roots[:4])}) – export do her čeká jednu.")
    for b in bones:
        if b.get("parent") and b["parent"] not in names:
            problems.append(f"{b['name']}: rodič {b['parent']} neexistuje.")
        if "head" in b and "tail" in b and math.dist(b["head"], b["tail"]) < 1e-4:
            problems.append(f"{b['name']}: kost má nulovou délku.")
    parent = {b["name"]: b.get("parent") for b in bones}
    for n in names:
        seen, cur = set(), n
        while cur:
            if cur in seen:
                problems.append(f"Smyčka v hierarchii u {n}.")
                break
            seen.add(cur)
            cur = parent.get(cur)
    sides: dict[str, dict[str, dict]] = {}
    for b in bones:
        s = _side(b["name"])
        if s:
            sides.setdefault(s[0], {})[s[1]] = b
    for base, pair in sides.items():
        if len(pair) == 1:
            have = next(iter(pair))
            warnings.append(f"{base}: je jen {'levá' if have == 'L' else 'pravá'} strana.")
        elif "head" in pair["L"] and "head" in pair["R"]:
            la, ra = math.dist(pair["L"]["head"], pair["L"]["tail"]), math.dist(pair["R"]["head"], pair["R"]["tail"])
            if abs(la - ra) > 0.05 * max(la, ra):
                warnings.append(f"{base}: levá a pravá kost mají jinou délku ({la:.3f} vs {ra:.3f}).")
    return {"ok": not problems, "bones": len(bones), "roots": roots, "problems": sorted(set(problems)), "warnings": warnings}


def blender_rig_script(bones: list[dict], mesh: str = "") -> str:
    data = json.dumps([{"name": b["name"], "parent": b["parent"], "head": list(b["head"]), "tail": list(b["tail"])} for b in bones])
    return f'''import bpy, json
BONES = json.loads({data!r})
bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
arm = bpy.context.object
arm.name = "Rig"
eb = arm.data.edit_bones
eb.remove(eb[0])
for b in BONES:
    e = eb.new(b["name"])
    e.head, e.tail = b["head"], b["tail"]
for b in BONES:
    if b["parent"]:
        eb[b["name"]].parent = eb[b["parent"]]
        eb[b["name"]].use_connect = tuple(eb[b["parent"]].tail) == tuple(b["head"])
bpy.ops.object.mode_set(mode="OBJECT")
MESH = {mesh!r}
if MESH and MESH in bpy.data.objects:
    m = bpy.data.objects[MESH]
    bpy.ops.object.select_all(action="DESELECT")
    m.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")   # automatic weights
'''


def gltf_bones(path: Path) -> list[dict]:
    """Joints of the skins in a .gltf / .glb (names, parents, positions from node translations)."""
    raw = path.read_bytes()
    if raw[:4] == b"glTF":
        length = struct.unpack("<I", raw[12:16])[0]
        doc = json.loads(raw[20:20 + length])
    else:
        doc = json.loads(raw.decode("utf-8"))
    nodes = doc.get("nodes", [])
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    joints = sorted({j for s in doc.get("skins", []) for j in s.get("joints", [])})
    if not joints:
        raise ValueError("Model nemá kostru (skin).")

    def world(i):
        p = [0.0, 0.0, 0.0]
        while i is not None:
            t = nodes[i].get("translation", [0, 0, 0])
            p = [p[k] + t[k] for k in range(3)]
            i = parent.get(i)
        return tuple(round(x, 4) for x in p)
    js = set(joints)
    out = []
    for j in joints:
        kids = [c for c in nodes[j].get("children", []) if c in js]
        head = world(j)
        tail = world(kids[0]) if kids else tuple(round(h + d, 4) for h, d in zip(head, (0, 0, 0.05)))
        out.append({"name": nodes[j].get("name", f"joint{j}"), "parent": nodes[parent[j]].get("name") if parent.get(j) in js else None,
                    "head": head, "tail": tail})
    return out
