"""3.5 smart home through Home Assistant's REST API: "rozsviť v obýváku", "zhasni všechno", "kolik je v ložnici stupňů".

The user connects it once in Settings → Domov (address + a long-lived access token; the token stays in the keyring).
"""
from __future__ import annotations

import difflib
import logging
import time

from . import secrets
from .stark import _fold

log = logging.getLogger(__name__)

TOKEN_KEY = "ha_token"
CACHE_S = 4
CONTROLLABLE = ("light", "switch", "fan", "cover", "climate", "lock", "media_player", "scene", "script", "vacuum",
                "input_boolean", "humidifier", "water_heater", "alarm_control_panel", "button")
DOMAIN_CS = {"light": "světlo", "switch": "zásuvka/vypínač", "fan": "ventilátor", "cover": "žaluzie/brána", "climate": "topení/klima",
             "lock": "zámek", "media_player": "přehrávač", "scene": "scéna", "script": "skript", "vacuum": "vysavač",
             "sensor": "senzor", "binary_sensor": "čidlo", "input_boolean": "přepínač", "humidifier": "zvlhčovač",
             "water_heater": "bojler", "alarm_control_panel": "alarm", "button": "tlačítko", "person": "osoba", "weather": "počasí"}
STATE_CS = {"on": "zapnuto", "off": "vypnuto", "open": "otevřeno", "closed": "zavřeno", "opening": "otevírá se",
            "closing": "zavírá se", "locked": "zamčeno", "unlocked": "odemčeno", "home": "doma", "not_home": "pryč",
            "playing": "hraje", "paused": "pozastaveno", "idle": "nečinný", "unavailable": "nedostupné", "heat": "topí",
            "cool": "chladí", "docked": "v nabíječce", "cleaning": "uklízí", "armed_away": "zapnutý", "disarmed": "vypnutý"}
ALL_WORDS = {"vse", "vsechno", "vsechna", "vsechny", "all", "cely dum", "celem dome", "everything"}
# opening these from a voice command or an automation always asks first
RISKY_WORDS = ("garaz", "brana", "vrata", "branka", "dvere", "gate", "garage", "door")


def configured(rt) -> bool:
    return bool(rt.cfg.home.url and secrets.get(TOKEN_KEY))


def short(e: dict) -> dict:
    a = e.get("attributes") or {}
    d = e["entity_id"].split(".", 1)[0]
    out = {"id": e["entity_id"], "name": a.get("friendly_name") or e["entity_id"], "domain": d, "state": e.get("state", "")}
    if a.get("unit_of_measurement"):
        out["unit"] = a["unit_of_measurement"]
    if d == "light" and a.get("brightness") is not None:
        out["brightness"] = round(a["brightness"] / 255 * 100)
    if d == "climate":
        out["target"] = a.get("temperature")
        out["current"] = a.get("current_temperature")
    if d == "cover" and a.get("current_position") is not None:
        out["position"] = a["current_position"]
    return out


def say_state(e: dict) -> str:
    st = e["state"]
    if e["domain"] in ("sensor",) and e.get("unit"):
        return f"{e['name']}: {st} {e['unit']}"
    txt = STATE_CS.get(st, st)
    if e.get("brightness") and st == "on":
        txt += f" ({e['brightness']} %)"
    if e["domain"] == "climate" and e.get("current") is not None:
        txt += f", {e['current']} °C" + (f" → {e['target']} °C" if e.get("target") else "")
    return f"{e['name']}: {txt}"


def risky(action: str, target: str, domain: str = "") -> bool:
    a, t = (action or "").lower(), _fold(target)
    if domain == "lock" or a in ("unlock", "disarm"):
        return a != "lock"
    if domain == "alarm_control_panel":
        return True
    return a in ("open", "on", "toggle") and any(w in t for w in RISKY_WORDS)


def match(items: list[dict], name: str, domains: tuple[str, ...] = CONTROLLABLE) -> list[dict]:
    """Entities matching a spoken name: exact > contains > fuzzy. "obývák" finds "Světlo obývák"."""
    want = _fold(name)
    pool = [e for e in items if e["domain"] in domains]
    if not want:
        return []
    exact = [e for e in pool if want in (_fold(e["name"]), _fold(e["id"]), _fold(e["id"].split(".", 1)[1]))]
    if exact:
        return exact
    words = want.split()
    contains = [e for e in pool if all(w in _fold(e["name"]) + " " + _fold(e["id"]) for w in words)]
    if contains:
        return contains
    names = {_fold(e["name"]): e for e in pool}
    return [names[n] for n in difflib.get_close_matches(want, list(names), n=1, cutoff=0.6)]


class Home:
    def __init__(self, rt):
        self.rt = rt
        self._cache: tuple[float, list[dict]] = (0.0, [])

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {secrets.get(TOKEN_KEY)}", "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return self.rt.cfg.home.url.rstrip("/") + path

    async def states(self, fresh: bool = False) -> list[dict]:
        if not fresh and time.monotonic() - self._cache[0] < CACHE_S:
            return self._cache[1]
        async with self.rt.http() as c:
            r = await c.get(self._url("/api/states"), headers=self._headers(), timeout=8)
        if r.status_code == 401:
            raise PermissionError("Home Assistant odmítl token (Nastavení → Domov).")
        r.raise_for_status()
        items = [short(e) for e in r.json() if isinstance(e, dict) and "entity_id" in e]
        self._cache = (time.monotonic(), items)
        return items

    async def service(self, domain: str, service: str, data: dict) -> None:
        async with self.rt.http() as c:
            r = await c.post(self._url(f"/api/services/{domain}/{service}"), headers=self._headers(), json=data, timeout=10)
        r.raise_for_status()
        self._cache = (0.0, [])

    async def find(self, name: str, domains: tuple[str, ...] = CONTROLLABLE) -> list[dict]:
        return match(await self.states(), name, domains)

    def find_cached(self, name: str) -> dict | None:
        """For the confirmation check (sync): the device a name means, from the last list we saw."""
        hits = match(self._cache[1], name, CONTROLLABLE)
        return hits[0] if hits else None

    async def control(self, target: str, action: str, value: float | None = None, domain: str = "") -> str:
        """One spoken command → Home Assistant services. Returns what happened, in Czech."""
        a = (action or "toggle").lower()
        doms = (domain,) if domain else CONTROLLABLE
        if _fold(target) in ALL_WORDS or _fold(target).startswith(("vsechna ", "vsechny ")):
            d = domain or ("light" if "svetl" in _fold(target) or a in ("off", "on") else "")
            if d not in ("light", "switch", "fan", "media_player", "cover"):
                return "Řekněte, co všechno: třeba „zhasni všechna světla“."
            svc = {"on": "turn_on", "off": "turn_off", "open": "open_cover", "close": "close_cover"}.get(a, "turn_off")
            if d == "cover" and svc.startswith("turn"):
                svc = "close_cover" if svc == "turn_off" else "open_cover"
            await self.service(d, svc, {"entity_id": "all"})
            return f"Hotovo, {DOMAIN_CS.get(d, d)} – vše {'zapnuto' if svc in ('turn_on', 'open_cover') else 'vypnuto'}."
        hits = await self.find(target, doms)
        if not hits:
            return f"Zařízení „{target}“ v Home Assistantu nevidím."
        e = hits[0]
        d, eid = e["domain"], e["id"]
        data: dict = {"entity_id": eid}
        if d in ("scene", "script"):
            await self.service(d, "turn_on", data)
            return f"Spouštím {e['name']}."
        if d == "button":
            await self.service(d, "press", data)
            return f"Zmáčknuto: {e['name']}."
        if d == "lock":
            if a in ("open", "off", "toggle"):
                return f"{e['name']} je zámek – řekněte výslovně „odemkni“ nebo „zamkni“."
            svc = "unlock" if a == "unlock" else "lock"
            await self.service(d, svc, data)
            return f"{e['name']}: {'odemykám' if svc == 'unlock' else 'zamykám'}."
        if d == "cover":
            if a == "set" and value is not None:
                await self.service(d, "set_cover_position", {**data, "position": int(max(0, min(100, value)))})
                return f"{e['name']}: nastavuji na {int(value)} %."
            svc = {"open": "open_cover", "on": "open_cover", "close": "close_cover", "off": "close_cover", "stop": "stop_cover"}.get(a, "toggle")
            await self.service(d, svc, data)
            return f"{e['name']}: {'otevírám' if svc == 'open_cover' else 'zavírám' if svc == 'close_cover' else 'hotovo'}."
        if d == "climate":
            if value is None:
                return say_state(e)
            await self.service(d, "set_temperature", {**data, "temperature": float(value)})
            return f"{e['name']}: nastavuji {value:g} °C."
        if d == "vacuum":
            svc = "return_to_base" if a in ("off", "stop", "close") else "start"
            await self.service(d, svc, data)
            return f"{e['name']}: {'jede domů' if svc == 'return_to_base' else 'začíná uklízet'}."
        if d == "alarm_control_panel":
            if a in ("off", "disarm", "unlock"):
                return "Alarm vypínejte v aplikaci Home Assistant (potřebuje kód)."
            await self.service(d, "alarm_arm_away", data)
            return f"{e['name']}: zapínám."
        if d == "light" and a == "set" and value is not None:
            await self.service(d, "turn_on", {**data, "brightness_pct": int(max(1, min(100, value)))})
            return f"{e['name']}: jas {int(value)} %."
        if d == "media_player" and a == "set" and value is not None:          # OMEGA 429: the room's player volume
            await self.service(d, "volume_set", {**data, "volume_level": round(max(0, min(100, value)) / 100, 2)})
            return f"{e['name']}: hlasitost {int(value)} %."
        if d == "media_player" and a in ("next", "previous"):
            await self.service(d, "media_next_track" if a == "next" else "media_previous_track", data)
            return f"{e['name']}: {'další' if a == 'next' else 'předchozí'} skladba."
        svc = {"on": "turn_on", "open": "turn_on", "off": "turn_off", "close": "turn_off", "set": "turn_on"}.get(a, "toggle")
        if d == "media_player" and a in ("pause", "play"):
            svc = "media_pause" if a == "pause" else "media_play"
        await self.service(d, svc, data)
        word = {"turn_on": "zapínám", "turn_off": "vypínám", "toggle": "přepínám", "media_pause": "pozastavuji", "media_play": "pouštím"}[svc]
        return f"{e['name']}: {word}."

    async def test(self, url: str, token: str) -> int:
        """→ how many entities Home Assistant has (raises when the address or token is wrong)."""
        async with self.rt.http() as c:
            r = await c.get(url.rstrip("/") + "/api/states", headers={"Authorization": f"Bearer {token}"}, timeout=8)
        if r.status_code == 401:
            raise PermissionError("Token nesedí. Vytvoř nový v Home Assistantu: Profil → Zabezpečení → Dlouhodobé přístupové tokeny.")
        r.raise_for_status()
        return len(r.json())
