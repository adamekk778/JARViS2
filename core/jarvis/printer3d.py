"""3.15 Dílna – 3D tiskárna (návrh C3): stav, pauza / pokračovat / zrušit, poslat soubor k tisku, fotka z kamery a hlídání
nepovedeného tisku.

Tiskárny: OctoPrint (REST, klíč X-Api-Key), Klipper přes Moonraker (Mainsail / Fluidd), Bambu Lab přes Home Assistant
(integrace ha-bambulab: senzory průběhu, tlačítka pauza / pokračovat / stop, kamera) a 3.17 Bambu Lab napřímo po síti
(bambu.py: MQTT + FTPS + kamera P1/A1, přístupový kód v klíčence). Klíč tiskárny je v klíčence
("printer"), nikdy v nastavení.

Hlídání: během tisku se JARVIS každých pár minut podívá kamerou (AI s obrazem) – špagety, odlepený výtisk, nalepená
koule plastu, posunuté vrstvy. Když to vidí dvakrát po sobě, tisk pozastaví (nebo jen dá vědět – podle nastavení) a pošle
fotku do telefonu. Hotový tisk a chyba tiskárny přijdou jako upozornění.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from . import secrets

log = logging.getLogger("jarvis.printer3d")

STATES = {"printing": "tiskne", "paused": "pozastaveno", "idle": "připravená", "done": "hotovo", "error": "chyba",
          "offline": "nedostupná"}
WATCH_PROMPT = (
    "Na fotce je probíhající 3D tisk (FDM). Posuď jen to, jestli se tisk nekazí: špagety (chuchvalce vláken ve vzduchu), "
    "výtisk odlepený od podložky nebo posunutý, koule plastu na trysce, výrazně posunuté vrstvy. Normální rozpracovaný "
    "tisk, prázdná podložka na začátku nebo tma NEJSOU chyba. Odpověz jen JSON: "
    '{"fail": true/false, "kind": "spaghetti|odlepení|koule|posun vrstev|nic", "confidence": 0.0-1.0, "why": "krátce česky"}')
KIND_CS = {"spaghetti": "špagety z vlákna", "odlepení": "výtisk se odlepil", "koule": "koule plastu na trysce",
           "posun vrstev": "posunuté vrstvy"}


def cfg(rt) -> Any:
    return rt.cfg.workshop


def configured(rt) -> bool:
    c = cfg(rt)
    return c.printer != "off" and (bool(c.printer_url) or c.printer == "bambu_ha")


def _base(rt) -> str:
    return cfg(rt).printer_url.rstrip("/")


def _headers(rt) -> dict:
    key = secrets.get("printer")
    return {"X-Api-Key": key} if key else {}


# ------------------------------------------------------------------------------------------ status (normalised)
def from_octoprint(job: dict, printer: dict | None) -> dict:
    st = str(job.get("state") or "").lower()
    flags = ((printer or {}).get("state") or {}).get("flags") or {}
    state = ("paused" if "paus" in st or flags.get("paused") else "printing" if "print" in st or flags.get("printing")
             else "error" if "error" in st or flags.get("error") else "offline" if "offline" in st or "closed" in st else "idle")
    prog = job.get("progress") or {}
    temps = (printer or {}).get("temperature") or {}
    t = lambda k: [round(float((temps.get(k) or {}).get("actual") or 0), 1), round(float((temps.get(k) or {}).get("target") or 0), 1)]  # noqa: E731
    return {"state": state, "file": ((job.get("job") or {}).get("file") or {}).get("name") or "",
            "progress": round(float(prog.get("completion") or 0), 1), "left_s": int(prog.get("printTimeLeft") or 0),
            "elapsed_s": int(prog.get("printTime") or 0), "nozzle": t("tool0"), "bed": t("bed")}


def from_moonraker(status: dict) -> dict:
    ps = status.get("print_stats") or {}
    st = str(ps.get("state") or "").lower()
    state = {"printing": "printing", "paused": "paused", "complete": "done", "error": "error", "cancelled": "idle",
             "standby": "idle"}.get(st, "idle")
    prog = float((status.get("virtual_sdcard") or {}).get("progress") or (status.get("display_status") or {}).get("progress") or 0)
    el = float(ps.get("print_duration") or 0)
    left = int(el / prog - el) if 0.01 < prog < 1 else 0
    t = lambda k: [round(float((status.get(k) or {}).get("temperature") or 0), 1), round(float((status.get(k) or {}).get("target") or 0), 1)]  # noqa: E731
    return {"state": state, "file": ps.get("filename") or "", "progress": round(prog * 100, 1), "left_s": left,
            "elapsed_s": int(el), "nozzle": t("extruder"), "bed": t("heater_bed")}


def _bambu_entities(states: list[dict], prefix: str) -> dict[str, dict]:
    """The printer's entities by their suffix (print_progress, print_status, …); prefix "" = the first Bambu printer found."""
    out: dict[str, dict] = {}
    if not prefix:
        for e in states:
            m = re.match(r"sensor\.(.+)_print_progress$", e.get("entity_id", ""))
            if m:
                prefix = m.group(1)
                break
    if not prefix:
        return out
    for e in states:
        eid = e.get("entity_id", "")
        dom, _, rest = eid.partition(".")
        if rest.startswith(prefix + "_"):
            out[f"{dom}.{rest[len(prefix) + 1:]}"] = e
    return out


def from_bambu(ent: dict[str, dict]) -> dict:
    if not ent:
        return {"state": "offline", "file": "", "progress": 0, "left_s": 0, "elapsed_s": 0, "nozzle": [0, 0], "bed": [0, 0]}
    v = lambda k: (ent.get(k) or {}).get("state")  # noqa: E731

    def num(k: str) -> float:
        try:
            return float(str(v(k)))
        except (TypeError, ValueError):
            return 0.0
    st = str(v("sensor.print_status") or v("sensor.current_stage") or "").lower()
    state = ("printing" if st in ("running", "printing", "prepare", "slicing") else "paused" if "pause" in st
             else "done" if st in ("finish", "finished") else "error" if st in ("failed", "error") else
             "offline" if st in ("unavailable", "offline", "") and not ent.get("sensor.print_progress") else "idle")
    return {"state": state, "file": str(v("sensor.task_name") or v("sensor.gcode_file") or ""), "progress": num("sensor.print_progress"),
            "left_s": int(num("sensor.remaining_time") * 60), "elapsed_s": 0,
            "nozzle": [num("sensor.nozzle_temperature"), num("sensor.nozzle_target_temperature")],
            "bed": [num("sensor.bed_temperature"), num("sensor.bed_target_temperature")]}


async def status(rt, client: httpx.AsyncClient | None = None) -> dict:
    c = cfg(rt)
    if not configured(rt):
        return {"state": "offline", "why": "není nastavená"}
    try:
        if c.printer == "bambu_lan":
            from . import bambu

            return await bambu.status(rt)
        if c.printer == "bambu_ha":
            return from_bambu(_bambu_entities(await rt.home.states(fresh=True), c.ha_prefix))
        own = client is None
        cl = client or httpx.AsyncClient(timeout=8)
        try:
            if c.printer == "octoprint":
                job = (await cl.get(_base(rt) + "/api/job", headers=_headers(rt))).json()
                pr = await cl.get(_base(rt) + "/api/printer", headers=_headers(rt))
                return from_octoprint(job, pr.json() if pr.status_code == 200 else None)
            q = "print_stats&virtual_sdcard&display_status&extruder&heater_bed"
            r = (await cl.get(_base(rt) + "/printer/objects/query?" + q, headers=_headers(rt))).json()
            return from_moonraker(((r.get("result") or {}).get("status")) or {})
        finally:
            if own:
                await cl.aclose()
    except Exception as e:  # noqa: BLE001
        return {"state": "offline", "why": str(e)[:120], "file": "", "progress": 0, "left_s": 0, "elapsed_s": 0,
                "nozzle": [0, 0], "bed": [0, 0]}


def say(s: dict, name: str = "Tiskárna") -> str:
    st = s.get("state", "offline")
    if st == "offline":
        return f"{name} je nedostupná{(' (' + s['why'] + ')') if s.get('why') else ''}."
    parts = [f"{name}: {STATES.get(st, st)}"]
    if st in ("printing", "paused"):
        parts.append(f"{s.get('file') or 'tisk'} na {s.get('progress', 0):.0f} %")
        if s.get("left_s"):
            m = int(s["left_s"]) // 60
            parts.append(f"zbývá {m // 60} h {m % 60} min" if m >= 60 else f"zbývá {m} min")
    noz, bed = s.get("nozzle") or [0, 0], s.get("bed") or [0, 0]
    if noz[0]:
        parts.append(f"tryska {noz[0]:.0f} °C, podložka {bed[0]:.0f} °C")
    return ", ".join(parts) + "."


# ------------------------------------------------------------------------------------------ control
async def command(rt, action: str, client: httpx.AsyncClient | None = None) -> str:
    """pause / resume / cancel → '' on success, else the reason."""
    c = cfg(rt)
    if action not in ("pause", "resume", "cancel"):
        return "neznámý příkaz"
    try:
        if c.printer == "bambu_lan":
            from . import bambu

            return await bambu.command(rt, action)
        if c.printer == "bambu_ha":
            ent = _bambu_entities(await rt.home.states(fresh=True), c.ha_prefix)
            btn = {"pause": "button.pause_printing", "resume": "button.resume_printing", "cancel": "button.stop_printing"}[action]
            if btn not in ent:
                return "tiskárna v Home Assistantu nemá tlačítko " + btn
            await rt.home.service("button", "press", {"entity_id": ent[btn]["entity_id"]})
            return ""
        own = client is None
        cl = client or httpx.AsyncClient(timeout=10)
        try:
            if c.printer == "octoprint":
                body = {"command": "cancel"} if action == "cancel" else {"command": "pause", "action": action}
                r = await cl.post(_base(rt) + "/api/job", json=body, headers=_headers(rt))
            else:
                r = await cl.post(_base(rt) + f"/printer/print/{action}", headers=_headers(rt))
            return "" if r.status_code < 300 else f"tiskárna odpověděla {r.status_code}"
        finally:
            if own:
                await cl.aclose()
    except Exception as e:  # noqa: BLE001
        return str(e)[:160]


async def upload_and_print(rt, path: Path, start: bool = True, client: httpx.AsyncClient | None = None) -> str:
    """A G-code file → the printer (and start it). '' on success."""
    c = cfg(rt)
    if c.printer == "bambu_lan":
        from . import bambu

        try:
            return await bambu.upload_and_print(rt, path, start)
        except Exception as e:  # noqa: BLE001
            return str(e)[:160]
    if c.printer == "bambu_ha":
        return "Bambu přes Home Assistant neumí přijmout soubor – pošli ho z Bambu Studia (otevřu ho tam), nebo přepni na Bambu napřímo"
    own = client is None
    cl = client or httpx.AsyncClient(timeout=120)
    try:
        files = {"file": (path.name, path.read_bytes(), "application/octet-stream")}
        if c.printer == "octoprint":
            data = {"select": "true", "print": "true" if start else "false"}
            r = await cl.post(_base(rt) + "/api/files/local", files=files, data=data, headers=_headers(rt))
        else:
            r = await cl.post(_base(rt) + "/server/files/upload", files=files, data={"print": "true" if start else "false"},
                              headers=_headers(rt))
        return "" if r.status_code < 300 else f"tiskárna odpověděla {r.status_code}: {r.text[:120]}"
    except Exception as e:  # noqa: BLE001
        return str(e)[:160]
    finally:
        if own:
            await cl.aclose()


def slicer() -> str | None:
    for name in ("prusa-slicer-console", "prusa-slicer", "PrusaSlicer", "superslicer"):
        found = shutil.which(name)
        if found:
            return found
    for p in (r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",):
        if Path(p).exists():
            return p
    return None


def orca() -> str | None:
    """3.18 OrcaSlicer or Bambu Studio (both slice for Bambu printers and save a sliced .gcode.3mf)."""
    for name in ("orca-slicer", "OrcaSlicer", "orcaslicer", "bambu-studio", "BambuStudio"):
        found = shutil.which(name)
        if found:
            return found
    for p in (r"C:\Program Files\OrcaSlicer\orca-slicer.exe", r"C:\Program Files\Bambu Studio\bambu-studio.exe"):
        if Path(p).exists():
            return p
    return None


def slice_for_bambu(model: Path, settings: str, filament: str, runner=subprocess.run) -> tuple[Path | None, str]:
    """STL or an unsliced 3MF → a sliced .gcode.3mf for Bambu (OrcaSlicer / Bambu Studio command line). A project 3MF
    carries its own settings; an STL needs your exported printer + process profile and the filament profile."""
    exe = orca()
    if not exe:
        return None, "není nainstalovaný OrcaSlicer ani Bambu Studio (oba zdarma)"
    profs = [x for x in (settings or "").split(";") if x.strip()]
    if model.suffix.lower() == ".stl" and (not profs or not all(Path(x).exists() for x in profs) or not Path(filament or "").exists()):
        return None, ("chybí profily pro OrcaSlicer (Nastavení → Integrace → Dílna: tiskárna + proces a filament, .json "
                      "vyexportované z OrcaSliceru)")
    outdir = model.parent / "jarvis-slice"
    outdir.mkdir(exist_ok=True)
    name = model.stem.removesuffix(".gcode") + ".gcode.3mf"
    cmd = [exe, "--slice", "0", "--outputdir", str(outdir), "--export-3mf", name]
    if profs:
        cmd += ["--load-settings", ";".join(profs)]
    if filament and Path(filament).exists():
        cmd += ["--load-filaments", filament]
    cmd.append(str(model))
    try:
        r = runner(cmd, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)[:160]
    out = outdir / name
    if r.returncode != 0 or not out.exists():
        return None, (r.stderr or r.stdout or "slicer selhal")[-300:]
    return out, ""


def slice_model(model: Path, profile: str, runner=subprocess.run) -> tuple[Path | None, str]:
    """STL / 3MF → G-code with PrusaSlicer and your printer's profile (.ini exported from PrusaSlicer)."""
    exe = slicer()
    if not exe:
        return None, "není nainstalovaný PrusaSlicer"
    if not profile or not Path(profile).exists():
        return None, "chybí profil tiskárny pro slicer (Nastavení → Dílna → Profil sliceru, .ini z PrusaSliceru)"
    out = model.with_suffix(".gcode")
    try:
        r = runner([exe, "--export-gcode", "--load", profile, "-o", str(out), str(model)], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)[:160]
    if r.returncode != 0 or not out.exists():
        return None, (r.stderr or r.stdout or "slicer selhal")[-300:]
    return out, ""


async def snapshot(rt, client: httpx.AsyncClient | None = None) -> bytes | None:
    """A JPEG from the printer's camera (or the camera URL in Settings)."""
    c = cfg(rt)
    if c.printer == "bambu_lan" and not c.camera_url:
        from . import bambu

        return await bambu.snapshot(rt)
    own = client is None
    cl = client or httpx.AsyncClient(timeout=10, follow_redirects=True)
    try:
        url, headers = c.camera_url, {}
        if not url and c.printer == "bambu_ha":
            ent = _bambu_entities(await rt.home.states(), c.ha_prefix)
            cam = ent.get("camera.camera") or next((e for k, e in ent.items() if k.startswith(("camera.", "image."))), None)
            if not cam:
                return None
            url, headers = rt.home._url(f"/api/camera_proxy/{cam['entity_id']}"), rt.home._headers()
        elif not url and c.printer == "octoprint":
            url = _base(rt) + "/webcam/?action=snapshot"
        elif not url and c.printer == "moonraker":
            r = await cl.get(_base(rt) + "/server/webcams/list", headers=_headers(rt))
            cams = ((r.json().get("result") or {}).get("webcams") or []) if r.status_code == 200 else []
            snap = (cams[0].get("snapshot_url") if cams else "") or "/webcam/?action=snapshot"
            host = re.sub(r":\d+$", "", _base(rt)) if snap.startswith("/") else ""
            url = host + snap
        if not url:
            return None
        r = await cl.get(url, headers=headers)
        ok = r.status_code == 200 and r.content[:2] in (b"\xff\xd8", b"\x89P")
        return r.content if ok else None
    except Exception as e:  # noqa: BLE001
        log.debug("snapshot: %s", e)
        return None
    finally:
        if own:
            await cl.aclose()


# ------------------------------------------------------------------------------------------ the failed-print watch
def parse_verdict(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    fail = bool(d.get("fail"))
    try:
        conf = max(0.0, min(1.0, float(d.get("confidence", 0.0))))
    except (TypeError, ValueError):
        conf = 0.0
    return {"fail": fail, "kind": str(d.get("kind") or ("nic" if not fail else "")), "confidence": conf, "why": str(d.get("why") or "")[:200]}


async def judge(rt, jpg: bytes) -> dict:
    mime = "image/png" if jpg[:2] == b"\x89P" else "image/jpeg"
    url = f"data:{mime};base64," + base64.b64encode(jpg).decode()
    out = await rt.router.complete([{"role": "user", "content": [{"type": "text", "text": WATCH_PROMPT},
                                                                  {"type": "image_url", "image_url": {"url": url}}]}], need_vision=True)
    return parse_verdict(str(out or ""))


class Watch:
    """Polls the printer: progress to the HUD / notch, "hotovo" / "chyba" to the phone, and the AI look at the print."""
    FAIL_CONF = 0.7

    def __init__(self, rt):
        self.rt = rt
        self.last: dict = {}
        self.last_look = 0.0
        self.strikes = 0
        self.alerted_file = ""

    async def step(self, now: float) -> dict:
        rt = self.rt
        s = await status(rt)
        prev = self.last.get("state")
        self.last = s
        rt.bus.publish("printer", **s, name=cfg(rt).printer_name)
        name = cfg(rt).printer_name or "Tiskárna"
        if prev == "printing" and s["state"] == "done":
            await self.finished(s, name)
        if prev in ("printing", "paused") and s["state"] == "error":
            rt.notify(name, "Tiskárna hlásí chybu – podívej se na ni.", target="all", urgent=True)
        if s["state"] != "printing":
            self.strikes = 0
            return s
        if cfg(rt).watch and now - self.last_look >= max(1, cfg(rt).watch_every_min) * 60:
            self.last_look = now
            await self.look(s)
        elif getattr(cfg(rt), "timelapse", True) and now - getattr(self, "last_frame", 0.0) >= max(1, cfg(rt).timelapse_every_min) * 60:
            self.last_frame = now                      # 3.18 a picture for the time-lapse (no AI look)
            jpg = await snapshot(rt)
            if jpg:
                self._frame(s, jpg)
        return s

    def _frame(self, s: dict, jpg: bytes) -> None:
        if getattr(cfg(self.rt), "timelapse", True):
            from . import timelapse

            try:
                timelapse.add_frame(s.get("file") or "tisk", jpg)
            except OSError as e:
                log.debug("timelapse: %s", e)

    async def finished(self, s: dict, name: str) -> None:
        """3.18 a print is done: the last picture and the time-lapse into the journal, "hotovo" to the phone."""
        rt = self.rt
        job = s.get("file") or "tisk"
        video = photo = None
        try:
            jpg = await snapshot(rt)
            if jpg:
                self._frame(s, jpg)
                photo = self._save_photo(jpg)
            if getattr(cfg(rt), "timelapse", True):
                from . import timelapse

                video = await asyncio.to_thread(timelapse.build, job)
        except Exception as e:  # noqa: BLE001
            log.debug("print done: %s", e)
        extra = " Fotka" + (" a časosběrné video jsou" if video else " je") + " v deníku dílny." if photo or video else ""
        rt.notify(name, f"Tisk {job} je hotový.{extra}".replace("  ", " "), target="all")
        self._log("print", f"Vytištěno: {job}" + (f" (časosběr: {video.name})" if video else ""), photo)
        rt.bus.publish("printer_done", file=job, photo=str(photo or ""), video=str(video or ""))

    async def look(self, s: dict) -> dict | None:
        rt = self.rt
        jpg = await snapshot(rt)
        if not jpg:
            return None
        self._frame(s, jpg)                            # 3.18 the AI's picture goes into the time-lapse too
        try:
            v = await judge(rt, jpg)
        except Exception as e:  # noqa: BLE001
            log.debug("print watch: %s", e)
            return None
        self.strikes = self.strikes + 1 if v["fail"] and v["confidence"] >= self.FAIL_CONF else 0
        rt.bus.publish("printer_look", ok=not v["fail"], kind=v["kind"], why=v["why"])
        if self.strikes >= 2 and self.alerted_file != (s.get("file") or "?"):
            self.alerted_file = s.get("file") or "?"
            what = KIND_CS.get(v["kind"], v["kind"] or "něco je špatně")
            paused = False
            if cfg(rt).on_failure == "pause":
                paused = not await command(rt, "pause")
            photo = self._save_photo(jpg)
            body = f"Tisk {s.get('file') or ''} se asi kazí: {what}. {v['why']} " + ("Pozastavil jsem ho." if paused else "Podívej se na něj.")
            acts = ([{"label": "Pokračovat", "action": "printer", "args": {"action": "resume"}}] if paused else
                    [{"label": "Pozastavit", "action": "printer", "args": {"action": "pause"}}])
            acts.append({"label": "Zrušit tisk", "action": "printer", "args": {"action": "cancel"}})
            rt.notify(cfg(rt).printer_name or "Tiskárna", body.replace("  ", " ").strip(), target="all", urgent=True, actions=acts)
            self._log("print", f"Selhání tisku ({what}){' – pozastaveno' if paused else ''}", photo)
        return v

    def _save_photo(self, jpg: bytes) -> Path | None:
        try:
            from . import paths

            p = paths.sub("workshop") / "photos" / f"tisk-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(jpg)
            return p
        except OSError:
            return None

    def _log(self, kind: str, text: str, photo: Path | None = None) -> None:
        try:
            from . import workbench

            workbench.log_active(self.rt, kind, text, photo)
        except Exception as e:  # noqa: BLE001
            log.debug("journal: %s", e)

    async def run(self) -> None:
        while True:
            try:
                if configured(self.rt):
                    await self.step(time.time())
            except Exception as e:  # noqa: BLE001
                log.debug("printer watch: %s", e)
            busy = self.last.get("state") in ("printing", "paused")
            await asyncio.sleep(30 if busy else 120)


def start(rt) -> asyncio.Task:
    rt.printer_watch = Watch(rt)
    return asyncio.get_running_loop().create_task(rt.printer_watch.run())
