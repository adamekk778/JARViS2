"""3.12 Kontrola funkcí: one button that tries every part on THIS PC and says in plain words what does not work and
what to do – music in the notch, the PC's sound (subtitles), the microphone, speech recognition, JARVIS's voice, the
brain and the phone connection (network profile, firewall). Started only by the user (the microphone is opened for
half a second and that is said on the button). The results also go into the log, so a diagnostics export carries them.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from typing import Any

log = logging.getLogger("jarvis.selfcheck")
WIN = sys.platform == "win32"


MISSING = "Chybí součást JARVISe ({}). Stáhni a nainstaluj nejnovější verzi – a pošli mi tenhle text."


def _r(key: str, name: str, ok: bool | None, detail: str, fix: str = "") -> dict:
    return {"key": key, "name": name, "ok": ok, "detail": detail[:300], "fix": fix[:400]}


def _ps_json(script: str, timeout: float = 20) -> Any:
    from .pcreport import run_quiet

    _, out, _ = run_quiet(["powershell", "-NoProfile", "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script], timeout)
    s = (out or "").strip()
    if not s:
        return None
    i = min([x for x in (s.find("["), s.find("{")) if x >= 0] or [0])
    return json.loads(s[i:])


# ---------- the parts ----------
async def media() -> dict:
    name = "Hudba v notchi"
    if not WIN:
        return _r("media", name, None, "Jen na Windows.")
    try:
        import winsdk  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return _r("media", name, False, f"Chybí součást Windows pro přehrávání (winsdk): {e}", "Přeinstaluj JARVIS nejnovějším instalátorem.")
    try:
        from .desktop.media import _snapshot

        snap = await asyncio.wait_for(_snapshot(), 8)
    except Exception as e:  # noqa: BLE001
        return _r("media", name, False, f"Windows nepustil JARVIS k přehrávání: {type(e).__name__}: {e}",
                  "Pusť písničku ve Spotify nebo v prohlížeči a zkus to znovu. Pokud chyba trvá, pošli tenhle text.")
    if not snap or not snap.get("title"):
        return _r("media", name, True, "Funguje, jen teď nic nehraje (nebo přehrávač Windows nic neohlásil).",
                  "Pusť písničku (Spotify, YouTube v Chrome/Edge) a zkontroluj znovu – měla by se ukázat tady.")
    return _r("media", name, True, f"Vidím: {snap.get('title')} – {snap.get('artist', '')} ({snap.get('app', '')})")


def loopback() -> dict:
    name = "Zvuk z PC (titulky, poslech)"
    if not WIN:
        return _r("loopback", name, None, "Jen na Windows.")
    try:
        import numpy as np
        import soundcard as sc

        spk = sc.default_speaker()
        with sc.get_microphone(str(spk.name), include_loopback=True).recorder(samplerate=48000, channels=1) as rec:
            data = rec.record(numframes=24000)                # half a second
        level = float(np.abs(data).max()) if data is not None and len(data) else 0.0
    except ImportError as e:
        return _r("loopback", name, False, f"Zvuk z PC nejde zachytit: {e}", MISSING.format(e.name or "soundcard"))
    except Exception as e:  # noqa: BLE001
        return _r("loopback", name, False, f"Zvuk z PC nejde zachytit: {type(e).__name__}: {e}",
                  "Zkontroluj, že máš ve Windows vybrané výchozí reproduktory/sluchátka (ikona reproduktoru vpravo dole).")
    if level < 1e-4:
        return _r("loopback", name, True, f"Zachytávání funguje ({spk.name}), ale teď je ticho.",
                  "Pusť video nebo písničku a zkontroluj znovu – úroveň by měla být nad nulou.")
    return _r("loopback", name, True, f"Funguje – slyším zvuk z {spk.name} (úroveň {level:.2f}).")


def microphone(rt: Any) -> dict:
    name = "Mikrofon (hlas)"
    try:
        import numpy as np
        import sounddevice as sd

        dev = rt.cfg.voice.input_device or None
        info = sd.query_devices(dev, "input")
        data = sd.rec(int(16000 * 0.5), samplerate=16000, channels=1, dtype="float32", device=dev)
        sd.wait()
        level = float(np.abs(data).max())
    except ImportError as e:
        return _r("mic", name, False, f"Mikrofon nejde otevřít: {e}", MISSING.format(e.name or "sounddevice"))
    except Exception as e:  # noqa: BLE001
        return _r("mic", name, False, f"Mikrofon nejde otevřít: {type(e).__name__}: {e}",
                  "Windows → Nastavení → Ochrana osobních údajů → Mikrofon: zapni přístup pro aplikace pro stolní počítače. "
                  "A vyber mikrofon v Nastavení JARVISe → Hlas.")
    if level < 1e-4:
        return _r("mic", name, False, f"Mikrofon „{info.get('name', '?')}“ je otevřený, ale nic neslyší (úplné ticho).",
                  "Je ztlumený nebo vybraný špatný? Windows → Nastavení → Systém → Zvuk → Vstup. Pak vyber ten správný v Nastavení JARVISe → Hlas.")
    return _r("mic", name, True, f"Funguje – „{info.get('name', '?')}“ (úroveň {level:.2f}).")


def speech(rt: Any) -> dict:
    name = "Rozpoznávání řeči"
    v = getattr(rt, "voice", None)
    st = v.status() if v is not None and hasattr(v, "status") else {}
    if not rt.cfg.voice.enabled:
        return _r("stt", name, False, "Hlasové ovládání je vypnuté.", "Zapni ho v Nastavení → Hlas → Hlasové ovládání.")
    if not st.get("available"):
        return _r("stt", name, False, f"Hlasový modul neběží: {st.get('error') or 'bez udání důvodu'}",
                  "Pošli tenhle text – podle něj to opravím.")
    return _r("stt", name, True, "Hlasový modul běží" + (" a poslouchá." if st.get("listening") else "."))


async def voice_out(rt: Any) -> dict:
    name = "Hlas JARVISe"
    if not getattr(rt, "speaker", None):
        return _r("tts", name, False, "Hlasový výstup není dostupný.", "Pošli tenhle text.")
    try:
        audio, mime = await asyncio.wait_for(rt.speaker.synth("Test."), 25)
    except Exception as e:  # noqa: BLE001
        return _r("tts", name, False, f"Hlas nejde vytvořit: {type(e).__name__}: {e}",
                  "Hlas Edge potřebuje internet. V Nastavení → Hlas zkus jiný hlas (Piper funguje i offline).")
    return _r("tts", name, bool(audio), f"Funguje ({len(audio) // 1024} kB {mime}).")


async def brain(rt: Any, tester) -> dict:
    name = "Mozek (AI)"
    chain = [c for c in rt.cfg.brain.chain if any(p.id == c and p.enabled for p in rt.cfg.brain.providers)]
    if not chain:
        return _r("brain", name, False, "Žádný mozek není zapnutý.", "Nastavení → Mozek → vlož API klíč.")
    from .brainkey import explain

    r = await tester(chain[0])
    if r.get("ok"):
        return _r("brain", name, True, f"{chain[0]} odpovídá ({r.get('ms', '?')} ms).")
    ok, msg = explain(str(r.get("message", "")))
    local = "localhost" in str(r.get("message", "")).lower() or chain[0] in ("omniroute", "ollama", "lmstudio")
    return _r("brain", name, ok, f"{chain[0]}: {msg}",
              "Nastavení → Mozek → nahoře vlož API klíč (Groq nebo Gemini zdarma). OmniRoute/Ollama běží jen když je máš nainstalované."
              if local else "Nastavení → Mozek → vlož klíč znovu (nahoře).")


def phone_net(rt: Any) -> list[dict]:
    """The phone reaches the PC at home: an address on the home network, a Private network profile, the firewall."""
    from .server.pairing import local_ips

    out = []
    lan, _ = local_ips()
    port = rt.cfg.phone.port
    if not lan:
        out.append(_r("lan", "Domácí síť", False, "PC nemá adresu v domácí síti (Wi-Fi / kabel).", "Připoj PC k Wi-Fi nebo kabelem k routeru."))
    else:
        out.append(_r("lan", "Domácí síť", True, f"Adresa PC: {', '.join(lan[:3])} (port {port}). Telefon musí být na stejné Wi-Fi."))
    if not WIN:
        return out
    try:
        prof = _ps_json("Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,NetworkCategory | ConvertTo-Json -Compress")
        profs = prof if isinstance(prof, list) else ([prof] if prof else [])
        public = [p for p in profs if str(p.get("NetworkCategory")) in ("0", "Public")]
        if public:
            out.append(_r("profile", "Typ sítě", False, f"Síť „{public[0].get('Name')}“ je nastavená jako Veřejná – Windows v ní blokuje telefon.",
                          "Windows → Nastavení → Síť a internet → Wi-Fi (nebo Ethernet) → tvoje síť → Typ profilu sítě: Soukromá."))
        elif profs:
            out.append(_r("profile", "Typ sítě", True, "Síť je Soukromá (domácí) – správně."))
    except Exception as e:  # noqa: BLE001
        log.info("selfcheck profile: %s", e)
    try:
        exe = sys.executable.replace("'", "''")
        rules = _ps_json(f"Get-NetFirewallApplicationFilter -Program '{exe}' -ErrorAction SilentlyContinue | Get-NetFirewallRule | "
                         "Where-Object Direction -eq 'Inbound' | Select-Object DisplayName,Enabled,Action,Profile | ConvertTo-Json -Compress")
        rl = rules if isinstance(rules, list) else ([rules] if rules else [])
        allow = [x for x in rl if str(x.get("Action")) in ("2", "Allow") and str(x.get("Enabled")) in ("1", "True")]
        block = [x for x in rl if str(x.get("Action")) in ("4", "Block") and str(x.get("Enabled")) in ("1", "True")]
        if block:
            out.append(_r("firewall", "Firewall Windows", False, "Firewall má pro JARVIS pravidlo Blokovat – telefon se nepřipojí.",
                          "Klikni na Povolit telefon ve firewallu (Windows se zeptá)."))
        elif not allow:
            out.append(_r("firewall", "Firewall Windows", False, "Firewall zatím JARVISu nepovolil příchozí spojení z telefonu.",
                          "Klikni na Povolit telefon ve firewallu (Windows se zeptá)."))
        else:
            out.append(_r("firewall", "Firewall Windows", True, "JARVIS má ve firewallu povolení."))
    except Exception as e:  # noqa: BLE001
        log.info("selfcheck firewall: %s", e)
    phone = getattr(rt, "phone", None)
    if phone is not None:
        last = float(getattr(phone, "last_poll", 0) or 0)
        out.append(_r("phone", "Telefon", phone.link_alive() if last else None,
                      "Telefon je teď spojený s PC." if phone.link_alive() else
                      (f"Telefon se naposledy ozval {time.strftime('%d.%m. %H:%M', time.localtime(last))}." if last else "Telefon se zatím nespojil."),
                      "" if phone.link_alive() else "V telefonu otevři JARVIS. Když píše „PC není dostupné“, oprav nejdřív položky výše."))
    return out


def allow_firewall() -> bool:
    """Ask Windows (UAC) to allow JARVIS's incoming connections on home (private) networks – the user confirms it."""
    if not WIN:
        return False
    exe = sys.executable
    args = (f'advfirewall firewall add rule name="JARVIS (telefon)" dir=in action=allow program="{exe}" '
            f'enable=yes profile=private')
    import subprocess

    ps = f"Start-Process netsh -Verb RunAs -WindowStyle Hidden -ArgumentList '{args.replace(chr(39), chr(39) * 2)}'"
    subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True


async def _limited(coro, secs: float, key: str, name: str, quiet: str) -> dict:
    """No check may hang the whole check (on real Windows the speaker loopback waits forever while nothing plays)."""
    try:
        return await asyncio.wait_for(coro, secs)
    except asyncio.TimeoutError:
        return _r(key, name, None, quiet)


async def run(rt: Any, tester) -> list[dict]:
    results: list[dict] = []
    results.append(await _limited(media(), 12, "media", "Hudba v notchi", "Windows neodpověděl včas, zkus to znovu."))
    results.append(await _limited(asyncio.to_thread(loopback), 6, "loopback", "Zvuk z PC (titulky, poslech)",
                                  "Teď nic nehraje, takže není co zachytit – pusť video nebo hudbu a zkontroluj znovu."))
    results.append(await _limited(asyncio.to_thread(microphone, rt), 8, "mic", "Mikrofon (hlas)",
                                  "Mikrofon se neozval včas – je připojený a vybraný ve Windows?"))
    results.append(speech(rt))
    results.append(await _limited(voice_out(rt), 30, "tts", "Hlas JARVISe", "Hlas se nestihl vytvořit (internet?)."))
    results.append(await _limited(brain(rt, tester), 70, "brain", "Mozek (AI)", "Mozek neodpověděl do minuty."))
    try:
        results += await asyncio.wait_for(asyncio.to_thread(phone_net, rt), 45)
    except asyncio.TimeoutError:
        results.append(_r("lan", "Domácí síť", None, "Kontrola sítě nestihla doběhnout."))
    for r in results:                                  # into the log, so a diagnostics export carries them
        (log.warning if r["ok"] is False else log.info)("kontrola %s: %s – %s", r["key"], "OK" if r["ok"] else "CHYBA", r["detail"])
    return results


async def warn_phone_blocked(rt: Any, delay: float = 40.0) -> None:
    """3.12 after start-up (Windows): if the phone cannot get through (a Public network, the firewall), say so once a
    day with what to do – nobody has to open Diagnostika to find out why the phone does not connect."""
    import datetime as dt

    await asyncio.sleep(delay)
    if not WIN:
        return
    try:
        row = rt.db.one("SELECT v FROM kv WHERE k='phone_net_warned'")
        today = dt.date.today().isoformat()
        if row and row["v"] == today:
            return
        bad = [i for i in await asyncio.to_thread(phone_net, rt) if i["ok"] is False and i["key"] in ("profile", "firewall", "lan")]
        if not bad:
            return
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('phone_net_warned', ?)", (today,))
        b = bad[0]
        rt.notify("Telefon se k PC nepřipojí", f"{b['detail']} {b['fix']} (Nastavení → Telefon)", speak=False)
    except Exception as e:  # noqa: BLE001
        log.info("phone net warning: %s", e)
