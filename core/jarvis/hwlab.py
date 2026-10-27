"""Wave 35 – the hardware lab.

* boards (OMEGA 156 / 157): which Arduino / ESP32 sits on which port (USB VID:PID), compile and upload through arduino-cli,
  flash an ESP32 .bin through esptool – both only if installed, both behind a confirmation; JARVIS never downloads them itself
* Raspberry Pi (158): found on the network by its MAC prefix; a fixed read-only status over SSH (your own key, no password)
* schematics (159): a wiring list → nets, an SVG diagram and a KiCad netlist; PCB help (162): trace width (IPC-2221), size
* firmware projects (164 / 475): board, port, version, build history with flash / RAM use, compiler errors explained
* enclosures (466): a parametric box with a lid → OpenSCAD source + a printable STL
* camera calibration (478): chessboard photos → focal length, centre, lens distortion (Zhang's method, numpy only)
* engineering alternatives (774): a beam / bracket – sizes for several materials and profiles, ranked by mass
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------- 156 / 157 boards on USB
BOARDS = {
    ("2341", "0043"): ("Arduino Uno", "arduino:avr:uno"), ("2341", "0001"): ("Arduino Uno", "arduino:avr:uno"),
    ("2341", "0042"): ("Arduino Mega 2560", "arduino:avr:mega"), ("2341", "0010"): ("Arduino Mega 2560", "arduino:avr:mega"),
    ("2341", "8036"): ("Arduino Leonardo", "arduino:avr:leonardo"), ("2341", "8037"): ("Arduino Micro", "arduino:avr:micro"),
    ("2341", "0058"): ("Arduino Nano Every", "arduino:megaavr:nona4809"), ("2341", "1002"): ("Arduino Uno R4 WiFi", "arduino:renesas_uno:unor4wifi"),
    ("2341", "0069"): ("Arduino Uno R4 Minima", "arduino:renesas_uno:minima"),
    ("303a", "1001"): ("ESP32-S3 / C3 (USB)", "esp32:esp32:esp32s3"), ("303a", "0002"): ("ESP32-S2", "esp32:esp32:esp32s2"),
    ("2e8a", "0005"): ("Raspberry Pi Pico", "rp2040:rp2040:rpipico"), ("2e8a", "000a"): ("Raspberry Pi Pico", "rp2040:rp2040:rpipico"),
}
BRIDGES = {("1a86", "7523"): "CH340", ("1a86", "55d4"): "CH9102", ("10c4", "ea60"): "CP2102", ("0403", "6001"): "FTDI",
           ("0403", "6015"): "FTDI"}


def identify(port: dict) -> dict:
    """What is probably plugged into this serial port."""
    vid, pid = (port.get("vid") or "").lower().zfill(4), (port.get("pid") or "").lower().zfill(4)
    if (vid, pid) in BOARDS:
        name, fqbn = BOARDS[(vid, pid)]
        return {**port, "board": name, "fqbn": fqbn, "sure": True}
    if (vid, pid) in BRIDGES:
        chip = BRIDGES[(vid, pid)]
        guess = "ESP32 / ESP8266 nebo klon Arduina" if chip in ("CP2102", "CH9102") else "klon Arduina (Nano/Uno) nebo ESP"
        return {**port, "board": f"{guess} – převodník {chip}", "fqbn": "", "sure": False}
    return {**port, "board": "", "fqbn": "", "sure": False}


def list_boards() -> list[dict]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        out.append(identify({"port": p.device, "desc": p.description or "", "vid": f"{p.vid:04x}" if p.vid else "",
                             "pid": f"{p.pid:04x}" if p.pid else ""}))
    return out


def arduino_cli() -> str | None:
    found = shutil.which("arduino-cli")
    if found:
        return found
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")):
        for sub in ("Programs/arduino-cli/arduino-cli.exe", "Arduino CLI/arduino-cli.exe", "arduino-cli/arduino-cli.exe"):
            p = Path(base) / sub
            if base and p.is_file():
                return str(p)
    return None


MISSING_CLI = ("Na sestavení a nahrání potřebuji Arduino CLI. Stáhni ho z arduino.cc (Software → Arduino CLI) a nainstaluj – "
               "JARVIS si nic sám nestahuje. Pak řekni „nahraj sketch“ znovu.")

# ---------------------------------------------------------------- 475 compiler output explained
ERRORS = [
    (re.compile(r"fatal error: ([\w./-]+)\.h: No such file", re.I),
     lambda m: f"Chybí knihovna pro {m.group(1)}.h – nainstaluj ji (Arduino IDE → Knihovny, nebo arduino-cli lib install …)."),
    (re.compile(r"'(\w+)' was not declared in this scope", re.I),
     lambda m: f"„{m.group(1)}“ není nikde deklarované – překlep, chybějící #include nebo proměnná definovaná až pod místem použití."),
    (re.compile(r"expected '([;)}\]])' before", re.I), lambda m: f"Chybí „{m.group(1)}“ – nejčastěji středník na konci předchozího řádku."),
    (re.compile(r"Sketch too big|text section exceeds available space", re.I),
     lambda m: "Program se nevejde do paměti desky – zmenši ho (méně knihoven, texty do F(\"…\")) nebo zvol větší desku."),
    (re.compile(r"(global variables use .* exceeds|not enough memory)", re.I),
     lambda m: "Došla RAM – velká pole, Stringy; texty dej do flash přes F(\"…\")."),
    (re.compile(r"(avrdude: .*not in sync|Failed to connect to ESP32|A fatal error occurred: Failed to connect)", re.I),
     lambda m: "Deska neodpovídá při nahrávání – zkontroluj port a typ desky, kabel s daty; u ESP32 drž při startu nahrávání tlačítko BOOT."),
    (re.compile(r"(could not open port|Access is denied|Permission denied).*(COM\d+|/dev/\w+)?", re.I),
     lambda m: "Port je obsazený – zavři sériový monitor nebo jiný program, který s deskou mluví."),
    (re.compile(r"Platform '([\w:]+)' not found|platform not installed", re.I),
     lambda m: "Chybí jádro pro tuhle desku (např. esp32:esp32) – doinstaluj ho v Arduino IDE (Správce desek)."),
]


def explain_build(output: str) -> dict:
    hints, seen = [], set()
    for rx, msg in ERRORS:
        for m in rx.finditer(output or ""):
            text = msg(m)
            if text not in seen:
                seen.add(text)
                hints.append(text)
    loc = re.findall(r"([\w./\\-]+\.(?:ino|cpp|c|h)):(\d+):(?:\d+:)? error: (.+)", output or "")
    flash = re.search(r"Sketch uses (\d+) bytes \((\d+)%\) of program storage space\. Maximum is (\d+)", output or "")
    ram = re.search(r"Global variables use (\d+) bytes \((\d+)%\) of dynamic memory", output or "")
    return {"hints": hints, "errors": [{"file": Path(f).name, "line": int(n), "message": e.strip()} for f, n, e in loc[:10]],
            "flash": {"bytes": int(flash.group(1)), "percent": int(flash.group(2)), "max": int(flash.group(3))} if flash else None,
            "ram": {"bytes": int(ram.group(1)), "percent": int(ram.group(2))} if ram else None}


def run_cli(args: list[str], timeout: int = 600, runner=subprocess.run) -> tuple[int, str]:
    cli = arduino_cli()
    if not cli:
        raise FileNotFoundError(MISSING_CLI)
    r = runner([cli, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ---------------------------------------------------------------- 164 firmware projects
SCHEMA = ("CREATE TABLE IF NOT EXISTS fw_projects (name TEXT PRIMARY KEY, path TEXT, fqbn TEXT, port TEXT, version TEXT, "
          "notes TEXT DEFAULT '', created REAL); "
          "CREATE TABLE IF NOT EXISTS fw_builds (id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, ts REAL, action TEXT, ok INTEGER, "
          "version TEXT, flash INTEGER, flash_pct INTEGER, ram_pct INTEGER, summary TEXT)")


def _db(rt):
    rt.db.conn.executescript(SCHEMA)
    return rt.db


def add_project(rt, name: str, path: str, fqbn: str = "", port: str = "", version: str = "0.1.0") -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Složka nebo sketch {p} neexistuje.")
    _db(rt).exec("INSERT INTO fw_projects VALUES (?,?,?,?,?, '', ?) ON CONFLICT(name) DO UPDATE SET path=excluded.path, "
                 "fqbn=excluded.fqbn, port=excluded.port", (name.strip()[:60], str(p), fqbn, port, version, time.time()))
    return get_project(rt, name)


def get_project(rt, name: str) -> dict | None:
    r = _db(rt).one("SELECT * FROM fw_projects WHERE lower(name)=lower(?)", (name.strip(),))
    if not r:
        return None
    builds = _db(rt).all("SELECT * FROM fw_builds WHERE project=? ORDER BY ts DESC LIMIT 10", (r["name"],))
    return {**r, "builds": builds}


def list_projects(rt) -> list[dict]:
    return _db(rt).all("SELECT * FROM fw_projects ORDER BY created DESC")


def bump(version: str, part: str = "patch") -> str:
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", version or "0.0.0")
    a, b, c = (int(x) for x in m.groups()) if m else (0, 0, 0)
    return f"{a + 1}.0.0" if part == "major" else f"{a}.{b + 1}.0" if part == "minor" else f"{a}.{b}.{c + 1}"


def record_build(rt, project: str, action: str, ok: bool, version: str, info: dict, summary: str) -> None:
    f, r = info.get("flash") or {}, info.get("ram") or {}
    _db(rt).exec("INSERT INTO fw_builds (project, ts, action, ok, version, flash, flash_pct, ram_pct, summary) VALUES (?,?,?,?,?,?,?,?,?)",
                 (project, time.time(), action, int(ok), version, f.get("bytes"), f.get("percent"), r.get("percent"), summary[:400]))


def build_project(rt, name: str, upload: bool = False, runner=subprocess.run) -> dict:
    p = get_project(rt, name)
    if not p:
        raise KeyError(f"Projekt „{name}“ neznám – přidej ho (název, složka, deska).")
    fqbn = p["fqbn"] or next((b["fqbn"] for b in list_boards() if b["fqbn"]), "")
    if not fqbn:
        raise ValueError("Nevím, jaká je to deska – zadej ji (např. arduino:avr:uno nebo esp32:esp32:esp32).")
    args = ["compile", "--fqbn", fqbn, p["path"]]
    port = p["port"] or next((b["port"] for b in list_boards() if b["fqbn"] == fqbn), "")
    if upload:
        if not port:
            raise ValueError("Nevidím připojenou desku – připoj ji USB kabelem s daty nebo zadej port.")
        args += ["--upload", "-p", port]
    code, out = run_cli(args, runner=runner)
    info = explain_build(out)
    ok = code == 0
    summary = ("Nahráno" if upload else "Sestaveno") if ok else ("; ".join(info["hints"]) or (info["errors"][0]["message"] if info["errors"] else out.strip()[-300:]))
    record_build(rt, p["name"], "upload" if upload else "build", ok, p["version"], info, summary)
    return {"ok": ok, "project": p["name"], "fqbn": fqbn, "port": port, "summary": summary, **info, "log": out[-4000:]}


def flash_esp(port: str, firmware: Path, address: str = "0x0", runner=subprocess.run) -> dict:
    """OMEGA 157: an ESP32 / ESP8266 .bin through esptool (installed as a Python package)."""
    import importlib.util
    import sys

    if not importlib.util.find_spec("esptool"):
        raise FileNotFoundError("Na nahrání .bin do ESP potřebuji esptool (pip install esptool) – sám ho nestahuji.")
    if not firmware.is_file() or firmware.suffix.lower() != ".bin":
        raise ValueError("Čekám soubor firmwaru .bin.")
    if not re.fullmatch(r"0x[0-9a-fA-F]{1,8}", address):
        raise ValueError("Adresa musí být šestnáctkově, např. 0x0 nebo 0x10000.")
    r = runner([sys.executable, "-m", "esptool", "--port", port, "write_flash", address, str(firmware)],
               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (r.stdout or "") + (r.stderr or "")
    return {"ok": r.returncode == 0, "log": out[-3000:], **explain_build(out)}


# ---------------------------------------------------------------- 158 Raspberry Pi
PI_OUIS = ("b8:27:eb", "dc:a6:32", "e4:5f:01", "28:cd:c1", "2c:cf:67", "d8:3a:dd")
PI_STATUS = "uptime -p; vcgencmd measure_temp 2>/dev/null || cat /sys/class/thermal/thermal_zone0/temp; df -h / | tail -1; free -m | sed -n 2p"


def find_pis(devices: list[dict]) -> list[dict]:
    return [d for d in devices if str(d.get("mac", "")).lower().replace("-", ":")[:8] in PI_OUIS]


def parse_pi_status(text: str) -> dict:
    out: dict = {}
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    for ln in lines:
        if ln.startswith("up "):
            out["uptime"] = ln[3:]
        elif m := re.match(r"temp=([\d.]+)", ln):
            out["temp_c"] = float(m.group(1))
        elif re.fullmatch(r"\d{4,6}", ln):
            out["temp_c"] = round(int(ln) / 1000, 1)
        elif ln.startswith("/dev/"):
            parts = ln.split()
            if len(parts) >= 5:
                out["disk"] = {"size": parts[1], "used": parts[2], "percent": int(parts[4].rstrip("%"))}
        elif ln.startswith("Mem:"):
            parts = ln.split()
            out["ram_mb"] = {"total": int(parts[1]), "used": int(parts[2])}
    warn = []
    if out.get("temp_c", 0) >= 80:
        warn.append("Je hodně horký – přidej chladič nebo větrák, jinak se zpomalí.")
    if out.get("disk", {}).get("percent", 0) >= 90:
        warn.append("Karta je skoro plná.")
    out["warnings"] = warn
    return out


def pi_status(host: str, user: str = "pi", runner=subprocess.run) -> dict:
    """Read-only, fixed commands over SSH with your key (BatchMode: never asks for or stores a password)."""
    if not re.fullmatch(r"[\w.-]+", host) or not re.fullmatch(r"[\w.-]+", user):
        raise ValueError("Neplatná adresa nebo uživatel.")
    ssh = shutil.which("ssh")
    if not ssh:
        raise FileNotFoundError("Chybí program ssh (ve Windows: Nastavení → Aplikace → Volitelné funkce → Klient OpenSSH).")
    r = runner([ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new", f"{user}@{host}", PI_STATUS],
               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        hint = "Nastav přihlášení klíčem (ssh-copy-id) – heslo JARVIS nezadává ani neukládá." if "Permission denied" in err else err[-200:]
        return {"ok": False, "error": hint}
    return {"ok": True, **parse_pi_status(r.stdout)}


# ---------------------------------------------------------------- 159 schematics
def parse_wiring(text: str) -> dict:
    """'Arduino.D9 -> R1.1; R1.2 -> LED1.A; LED1.K -> GND' (also '–', '→', new lines) → components and nets."""
    nets: list[set[str]] = []
    comps: dict[str, set[str]] = {}
    for line in re.split(r"[;\n]+", text or ""):
        pins = [p.strip() for p in re.split(r"\s*(?:->|→|–|—|-|=|,)\s*", line) if p.strip()]
        pins = [p for p in pins if re.fullmatch(r"[\w+]+(?:\.[\w+]+)?", p)]
        if len(pins) < 2:
            continue
        for p in pins:
            comp, _, pin = p.partition(".")
            if pin or comp.upper() not in ("GND", "VCC", "5V", "3V3", "3.3V", "VIN"):
                comps.setdefault(comp, set()).add(pin or "1")
        group = {p if "." in p else (p.upper() if p.upper() in ("GND", "VCC", "5V", "3V3", "VIN") else f"{p}.1") for p in pins}
        hit = [n for n in nets if n & group]
        merged = set(group).union(*hit) if hit else set(group)
        nets = [n for n in nets if n not in hit] + [merged]
    named = []
    for i, n in enumerate(nets):
        power = sorted(x for x in n if "." not in x)
        named.append({"name": power[0] if power else f"N{i + 1}", "pins": sorted(x for x in n if "." in x)})
    return {"components": {k: sorted(v) for k, v in comps.items()}, "nets": named}


def schematic_svg(w: dict) -> str:
    comps = list(w["components"].items())
    cols = max(1, min(4, math.ceil(math.sqrt(len(comps)))))
    bw, gap = 150, 90
    pos: dict[str, tuple[float, float]] = {}
    boxes = []
    for i, (name, pins) in enumerate(comps):
        x, y = 40 + (i % cols) * (bw + gap), 40 + (i // cols) * 200
        h = 30 + 18 * len(pins)
        boxes.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{h}" rx="6" fill="#f6f8fb" stroke="#334"/>'
                     f'<text x="{x + bw / 2}" y="{y + 18}" text-anchor="middle" font-weight="700">{_esc(name)}</text>')
        for j, pin in enumerate(pins):
            py = y + 34 + 18 * j
            pos[f"{name}.{pin}"] = (x + bw, py)
            boxes.append(f'<circle cx="{x + bw}" cy="{py}" r="3" fill="#334"/><text x="{x + bw - 8}" y="{py + 4}" text-anchor="end" font-size="12">{_esc(pin)}</text>')
    colors = ["#e4572e", "#2e86ab", "#76b041", "#a23b72", "#f18f01", "#3b1f2b", "#17bebb"]
    wires = []
    for k, net in enumerate(w["nets"]):
        pts = [pos[p] for p in net["pins"] if p in pos]
        if not pts:
            continue
        c = "#111" if net["name"] in ("GND",) else "#d00" if net["name"] in ("VCC", "5V", "3V3", "VIN") else colors[k % len(colors)]
        bus_x = max(x for x, _ in pts) + 20 + 8 * k
        ys = [y for _, y in pts]
        wires.append(f'<line x1="{bus_x}" y1="{min(ys)}" x2="{bus_x}" y2="{max(ys)}" stroke="{c}" stroke-width="2"/>')
        for x, y in pts:
            wires.append(f'<polyline points="{x},{y} {bus_x},{y}" fill="none" stroke="{c}" stroke-width="2"/>')
        wires.append(f'<text x="{bus_x + 4}" y="{min(ys) - 4}" font-size="11" fill="{c}">{_esc(net["name"])}</text>')
    width = 80 + cols * (bw + gap) + 8 * len(w["nets"])
    height = 80 + math.ceil(len(comps) / cols) * 200
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="Segoe UI, sans-serif">'
            f'<rect width="100%" height="100%" fill="#fff"/>{"".join(boxes)}{"".join(wires)}</svg>')


def kicad_netlist(w: dict) -> str:
    comps = "".join(f'\n    (comp (ref "{_esc(c)}") (value "{_esc(c)}"))' for c in w["components"])
    nets = "".join(f'\n    (net (code "{i + 1}") (name "{_esc(n["name"])}")' + "".join(
        f' (node (ref "{_esc(p.split(".")[0])}") (pin "{_esc(p.split(".")[1])}"))' for p in n["pins"]) + ")" for i, n in enumerate(w["nets"]))
    return f'(export (version "E")\n  (components{comps})\n  (nets{nets}))\n'


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------- 162 PCB help
def trace_width(current_a: float, rise_c: float = 10, copper_oz: float = 1, external: bool = True) -> dict:
    """IPC-2221: the narrowest trace for a current with an allowed temperature rise."""
    if current_a <= 0:
        raise ValueError("Proud musí být kladný.")
    k = 0.048 if external else 0.024
    area_mils2 = (current_a / (k * rise_c ** 0.44)) ** (1 / 0.725)
    thick_mils = 1.378 * copper_oz
    width_mils = area_mils2 / thick_mils
    return {"width_mm": round(width_mils * 0.0254, 3), "width_mils": round(width_mils, 1),
            "recommended_mm": round(max(0.2, width_mils * 0.0254 * 1.2), 2), "layer": "vnější" if external else "vnitřní"}


def board_size(parts: list[dict], density: float = 0.55, margin_mm: float = 3) -> dict:
    """Board area from footprints (w × h mm each); density = how much of the board the parts may cover."""
    area = sum(float(p["w"]) * float(p["h"]) * int(p.get("qty", 1)) for p in parts)
    side = math.sqrt(area / max(0.1, min(0.9, density)))
    widest = max((float(p["w"]) for p in parts), default=0)
    w = max(side, widest) + 2 * margin_mm
    h = max(area / max(0.1, density) / max(1, w - 2 * margin_mm), max((float(p["h"]) for p in parts), default=0)) + 2 * margin_mm
    return {"parts_area_mm2": round(area, 1), "board_mm": [math.ceil(w), math.ceil(h)], "density": density}


# ---------------------------------------------------------------- 466 enclosure
def enclosure(inner_w: float, inner_d: float, inner_h: float, wall: float = 2.0, lid: float = 2.0, clearance: float = 0.3,
              holes: list[dict] | None = None) -> dict:
    """A box (open at the top) and a lid that sits on it: OpenSCAD source + an STL of the box and the lid side by side."""
    if min(inner_w, inner_d, inner_h) <= 0 or wall < 0.8:
        raise ValueError("Rozměry musí být kladné a stěna aspoň 0,8 mm (tisk).")
    W, D, H = inner_w + 2 * wall, inner_d + 2 * wall, inner_h + wall
    holes = holes or []
    hole_scad = "".join(
        f"\n    translate([{h.get('x', W / 2)}, {-1 if h.get('side', 'front') == 'front' else D - wall - 1}, {h.get('z', H / 2)}]) "
        f"rotate([-90,0,0]) cylinder(d={h.get('d', 6)}, h={wall + 2}, $fn=40);" for h in holes)
    scad = (f"// JARVIS – krabička {inner_w}×{inner_d}×{inner_h} mm (vnitřek), stěna {wall} mm\n"
            f"difference() {{\n    cube([{W}, {D}, {H}]);\n    translate([{wall}, {wall}, {wall}]) cube([{inner_w}, {inner_d}, {inner_h + 1}]);{hole_scad}\n}}\n"
            f"// víko vedle krabičky, s okrajem dovnitř\ntranslate([{W + 10}, 0, 0]) union() {{\n    cube([{W}, {D}, {lid}]);\n"
            f"    translate([{wall + clearance}, {wall + clearance}, {lid}]) difference() {{\n"
            f"        cube([{inner_w - 2 * clearance}, {inner_d - 2 * clearance}, 3]);\n"
            f"        translate([1.2, 1.2, -1]) cube([{inner_w - 2 * clearance - 2.4}, {inner_d - 2 * clearance - 2.4}, 5]);\n    }}\n}}\n")
    cuboids = [  # non-overlapping solids: floor, 4 walls, lid plate, lid rim (holes only in the .scad)
        (0, 0, 0, W, D, wall), (0, 0, wall, W, wall, inner_h), (0, D - wall, wall, W, wall, inner_h),
        (0, wall, wall, wall, inner_d, inner_h), (W - wall, wall, wall, wall, inner_d, inner_h),
        (W + 10, 0, 0, W, D, lid)]
    rx, ry, rw, rd = W + 10 + wall + clearance, wall + clearance, inner_w - 2 * clearance, inner_d - 2 * clearance
    cuboids += [(rx, ry, lid, rw, 1.2, 3), (rx, ry + rd - 1.2, lid, rw, 1.2, 3), (rx, ry + 1.2, lid, 1.2, rd - 2.4, 3),
                (rx + rw - 1.2, ry + 1.2, lid, 1.2, rd - 2.4, 3)]
    return {"scad": scad, "stl": _stl(cuboids), "outer_mm": [W, D, H], "lid_mm": [W, D, lid + 3], "holes": len(holes),
            "volume_cm3": round(sum(c[3] * c[4] * c[5] for c in cuboids) / 1000, 1)}


def _stl(cuboids) -> str:
    out = ["solid jarvis"]
    for x, y, z, w, d, h in cuboids:
        v = [(x + a * w, y + b * d, z + c * h) for a in (0, 1) for b in (0, 1) for c in (0, 1)]
        faces = [(0, 2, 3, 1, (-1, 0, 0)), (4, 5, 7, 6, (1, 0, 0)), (0, 1, 5, 4, (0, -1, 0)), (2, 6, 7, 3, (0, 1, 0)),
                 (0, 4, 6, 2, (0, 0, -1)), (1, 3, 7, 5, (0, 0, 1))]
        for a, b, c, d2, n in faces:
            for tri in ((a, b, c), (a, c, d2)):
                out.append(f"facet normal {n[0]} {n[1]} {n[2]}\n outer loop")
                out += [f"  vertex {v[i][0]:.3f} {v[i][1]:.3f} {v[i][2]:.3f}" for i in tri]
                out.append(" endloop\nendfacet")
    out.append("endsolid jarvis")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- 774 engineering alternatives
MATERIALS = {  # name: (yield MPa, E GPa, density kg/m3)
    "ocel S235": (235, 210, 7850), "hliník 6061-T6": (240, 69, 2700), "smrkové dřevo": (40, 11, 450),
    "PETG (tisk)": (45, 2.1, 1270), "PLA (tisk)": (50, 3.5, 1240),
}


def _section(profile: str, s: float) -> tuple[float, float, str]:
    """(area mm², second moment mm⁴) for size s (mm): full square, round tube (t = s/10), square tube (t = s/10)."""
    if profile == "plný čtverec":
        return s * s, s ** 4 / 12, f"{s:.0f}×{s:.0f} mm"
    t = max(1.0, s / 10)
    if profile == "kruhová trubka":
        di = s - 2 * t
        return math.pi / 4 * (s * s - di * di), math.pi / 64 * (s ** 4 - di ** 4), f"Ø{s:.0f}×{t:.1f} mm"
    di = s - 2 * t
    return s * s - di * di, (s ** 4 - di ** 4) / 12, f"{s:.0f}×{s:.0f}×{t:.1f} mm"


def beam_alternatives(load_n: float, length_mm: float, support: str = "konzola", safety: float = 2.0, max_defl: float = 0) -> dict:
    """The smallest section of each material × profile that carries the load (stress × safety) within the deflection limit."""
    if load_n <= 0 or length_mm <= 0:
        raise ValueError("Zatížení i délka musí být kladné.")
    cant = support != "prostý nosník"
    m_max = load_n * length_mm if cant else load_n * length_mm / 4                     # N·mm, point load at the tip / middle
    limit = max_defl or length_mm / (180 if cant else 250)
    out = []
    for mat, (fy, e_gpa, rho) in MATERIALS.items():
        e = e_gpa * 1000
        for prof in ("plný čtverec", "kruhová trubka", "čtvercová trubka"):
            for s in np.arange(4, 400, 1.0):
                a, i, label = _section(prof, float(s))
                stress = m_max * (s / 2) / i
                defl = load_n * length_mm ** 3 / (3 * e * i) if cant else load_n * length_mm ** 3 / (48 * e * i)
                if stress * safety <= fy and defl <= limit:
                    mass = a * length_mm * rho / 1e9
                    out.append({"material": mat, "profile": prof, "size": label, "mass_kg": round(mass, 3),
                                "stress_mpa": round(stress, 1), "deflection_mm": round(defl, 2), "governs": "průhyb" if defl > limit * 0.95 else "pevnost"})
                    break
    out.sort(key=lambda x: x["mass_kg"])
    return {"load_n": load_n, "length_mm": length_mm, "support": "konzola" if cant else "prostý nosník", "safety": safety,
            "deflection_limit_mm": round(limit, 2), "options": out}


# ---------------------------------------------------------------- 478 camera calibration (Zhang, numpy only)
def _gray(path: Path, max_side: int = 900) -> tuple[np.ndarray, float]:
    from PIL import Image, ImageOps

    im = ImageOps.exif_transpose(Image.open(path)).convert("L")
    scale = min(1.0, max_side / max(im.size))
    if scale < 1:
        im = im.resize((round(im.width * scale), round(im.height * scale)))
    return np.asarray(im, dtype=np.float64) / 255.0, scale


def _blur(a: np.ndarray, sigma: float) -> np.ndarray:
    r = max(1, int(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    a = np.apply_along_axis(lambda m: np.convolve(np.pad(m, r, mode="edge"), k, mode="valid"), 1, a)
    return np.apply_along_axis(lambda m: np.convolve(np.pad(m, r, mode="edge"), k, mode="valid"), 0, a)


def find_corners(img: np.ndarray, cols: int, rows: int) -> np.ndarray | None:
    """Inner corners of a chessboard (cols × rows inner corners), ordered row by row; None if not found."""
    n = cols * rows
    g = _blur(img, 1.6)
    gy, gx = np.gradient(g)
    gxy, gxx = np.gradient(gx)
    gyy, _ = np.gradient(gy)
    s = -(gxx * gyy - gxy * gxy)                       # saddle points of the intensity = chessboard corners
    s[s < 0] = 0
    r = 4
    pad = np.pad(s, r, mode="constant")
    win = np.lib.stride_tricks.sliding_window_view(pad, (2 * r + 1, 2 * r + 1)).max(axis=(2, 3))
    peaks = np.argwhere((s == win) & (s > s.max() * 0.08))
    if len(peaks) < n:
        return None
    strength = s[peaks[:, 0], peaks[:, 1]]
    keep = peaks[np.argsort(-strength)[: n]]
    pts = []
    for y, x in keep:                                  # sub-pixel: centre of the response around the peak
        y0, y1, x0, x1 = max(0, y - 2), min(s.shape[0], y + 3), max(0, x - 2), min(s.shape[1], x + 3)
        w = s[y0:y1, x0:x1]
        yy, xx = np.mgrid[y0:y1, x0:x1]
        pts.append((float((xx * w).sum() / w.sum()), float((yy * w).sum() / w.sum())))
    p = np.array(pts)
    return _order_grid(p, cols, rows)


def _hull(p: np.ndarray) -> np.ndarray:
    pts = sorted(map(tuple, p))
    def half(seq):
        out = []
        for q in seq:
            while len(out) >= 2 and (out[-1][0] - out[-2][0]) * (q[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (q[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(q)
        return out
    lo, up = half(pts), half(pts[::-1])
    return np.array(lo[:-1] + up[:-1])


def _order_grid(p: np.ndarray, cols: int, rows: int) -> np.ndarray | None:
    """Order by the four outer corners: they define a homography that predicts every inner corner of the grid."""
    hull = _hull(p)
    if len(hull) < 4:
        return None
    area = lambda a, b, c: abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2   # noqa: E731
    cen = p.mean(0)
    a = hull[np.argmax(np.linalg.norm(hull - cen, axis=1))]
    b = hull[np.argmax(np.linalg.norm(hull - a, axis=1))]
    side = np.sign((b[0] - a[0]) * (hull[:, 1] - a[1]) - (b[1] - a[1]) * (hull[:, 0] - a[0]))
    quad = [a, b]
    for sgn in (1, -1):
        cand = hull[side == sgn]
        if not len(cand):
            return None
        quad.append(cand[np.argmax([area(a, b, q) for q in cand])])
    quad = np.array(quad)
    ang = np.arctan2(quad[:, 1] - cen[1], quad[:, 0] - cen[0])
    quad = quad[np.argsort(ang)]                       # clockwise on screen (y grows down)
    start = int(np.argmin(quad.sum(1)))                # the top-left one first
    quad = np.roll(quad, -start, axis=0)
    best = None
    for nc, nr, transpose in ((cols, rows, False), (rows, cols, True)):
        corners = np.array([(0, 0), (nc - 1, 0), (nc - 1, nr - 1), (0, nr - 1)], dtype=float)
        h = _homography(corners, quad)
        ideal = np.array([(i, j) for j in range(nr) for i in range(nc)], dtype=float)
        proj = np.c_[ideal, np.ones(len(ideal))] @ h.T
        proj = proj[:, :2] / proj[:, 2:]
        d = np.linalg.norm(proj[:, None] - p[None], axis=2)
        idx = d.argmin(1)
        err = d[np.arange(len(idx)), idx].max()
        if len(set(idx)) == len(idx) and (best is None or err < best[0]):
            order = p[idx].reshape(nr, nc, 2)
            if transpose:                              # the board lies the other way: rows ↔ columns
                order = order.transpose(1, 0, 2)[:, ::-1]
            best = (err, order.reshape(-1, 2))
    if best is None:
        return None
    step = np.median(np.linalg.norm(np.diff(best[1].reshape(rows, cols, 2), axis=1), axis=2))
    return best[1] if best[0] < 0.4 * step else None


def _homography(obj: np.ndarray, img: np.ndarray) -> np.ndarray:
    def norm(x):
        m, s = x.mean(0), x.std(0).mean() / math.sqrt(2) or 1
        t = np.array([[1 / s, 0, -m[0] / s], [0, 1 / s, -m[1] / s], [0, 0, 1]])
        return t, (np.c_[x, np.ones(len(x))] @ t.T)[:, :2]
    to, on = norm(obj)
    ti, imn = norm(img)
    a = []
    for (x, y), (u, v) in zip(on, imn):
        a.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        a.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    h = np.linalg.svd(np.array(a))[2][-1].reshape(3, 3)
    h = np.linalg.inv(ti) @ h @ to
    return h / h[2, 2]


def calibrate(views: list[np.ndarray], cols: int, rows: int, square_mm: float, size: tuple[int, int]) -> dict:
    """Zhang's closed form: intrinsics from ≥ 3 homographies, then radial distortion k1, k2 by least squares."""
    obj = np.array([(i * square_mm, j * square_mm) for j in range(rows) for i in range(cols)], dtype=float)
    hs = [_homography(obj, v) for v in views]

    def vij(h, i, j):
        return np.array([h[0, i] * h[0, j], h[0, i] * h[1, j] + h[1, i] * h[0, j], h[1, i] * h[1, j],
                         h[2, i] * h[0, j] + h[0, i] * h[2, j], h[2, i] * h[1, j] + h[1, i] * h[2, j], h[2, i] * h[2, j]])
    vmat = []
    for h in hs:
        vmat.append(vij(h, 0, 1))
        vmat.append(vij(h, 0, 0) - vij(h, 1, 1))
    vmat.append([0, 1, 0, 0, 0, 0])                    # no skew
    b = np.linalg.svd(np.array(vmat))[2][-1]
    b11, b12, b22, b13, b23, b33 = b
    v0 = (b12 * b13 - b11 * b23) / (b11 * b22 - b12 * b12)
    lam = b33 - (b13 * b13 + v0 * (b12 * b13 - b11 * b23)) / b11
    fx = math.sqrt(abs(lam / b11))
    fy = math.sqrt(abs(lam * b11 / (b11 * b22 - b12 * b12)))
    u0 = -b13 * fx * fx / lam
    k = np.array([[fx, 0, u0], [0, fy, v0], [0, 0, 1]])
    kinv = np.linalg.inv(k)
    ideal, real, radius = [], [], []
    for h, img in zip(hs, views):
        r1, r2, t = kinv @ h[:, 0], kinv @ h[:, 1], kinv @ h[:, 2]
        s = 1 / np.linalg.norm(r1)
        r1, r2, t = r1 * s, r2 * s, t * s
        for (x, y), (u, v) in zip(obj, img):
            pc = r1 * x + r2 * y + t
            xn, yn = pc[0] / pc[2], pc[1] / pc[2]
            ideal.append((fx * xn + u0, fy * yn + v0))
            real.append((u, v))
            radius.append(xn * xn + yn * yn)
    ideal, real, radius = np.array(ideal), np.array(real), np.array(radius)
    du = ideal - [u0, v0]
    a = np.r_[np.c_[du[:, 0] * radius, du[:, 0] * radius ** 2], np.c_[du[:, 1] * radius, du[:, 1] * radius ** 2]]
    rhs = np.r_[real[:, 0] - ideal[:, 0], real[:, 1] - ideal[:, 1]]
    k1, k2 = np.linalg.lstsq(a, rhs, rcond=None)[0]
    pred = ideal + du * (k1 * radius + k2 * radius ** 2)[:, None]
    err = float(np.sqrt(((pred - real) ** 2).sum(1).mean()))
    w, hgt = size
    return {"fx": round(fx, 1), "fy": round(fy, 1), "cx": round(float(u0), 1), "cy": round(float(v0), 1), "k1": round(float(k1), 4),
            "k2": round(float(k2), 4), "rms_px": round(err, 2), "views": len(views),
            "fov_deg": [round(math.degrees(2 * math.atan(w / (2 * fx))), 1), round(math.degrees(2 * math.atan(hgt / (2 * fy))), 1)]}


def calibrate_photos(paths: list[Path], cols: int = 9, rows: int = 6, square_mm: float = 25) -> dict:
    views, used, skipped, size = [], [], [], None
    for p in paths:
        img, scale = _gray(p)
        c = find_corners(img, cols, rows)
        if c is None:
            skipped.append(p.name)
            continue
        views.append(c / scale)
        used.append(p.name)
        size = (round(img.shape[1] / scale), round(img.shape[0] / scale))
    if len(views) < 3:
        raise ValueError(f"Šachovnici ({cols}×{rows} vnitřních rohů) jsem našel jen na {len(views)} fotkách – potřebuji aspoň 3, "
                         "focené z různých úhlů, celá šachovnice v záběru.")
    out = calibrate(views, cols, rows, square_mm, size)
    out.update(used=used, skipped=skipped, quality="výborná" if out["rms_px"] < 1 else "dobrá" if out["rms_px"] < 2.5 else "slabá – přidej fotky z víc úhlů")
    return out


def save_json(obj: dict, path: Path) -> Path:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
