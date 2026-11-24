"""3.14 Oči a uši: who is here, the screen buddy, the sounds of the house, what flies over us."""
from __future__ import annotations

import asyncio
from typing import Annotated

from .base import ToolResult, tool


@tool("faces_setup", "Nastaví rozpoznávání obličejů domácnosti: jednou stáhne dva malé otevřené modely (asi 38 MB) z OpenCV. "
      "Vše pak běží jen v tomto PC.", category="kamera", perm="network", danger=True,
      details=lambda a: ["Stáhne se: YuNet (hledání obličejů, 0,3 MB) a SFace (otisk obličeje, 37 MB) z github.com/opencv/opencv_zoo.",
                         "Fotky ani otisky nikam neodcházejí."])
async def faces_setup(ctx) -> ToolResult:
    from .. import faces

    try:
        r = await faces.download(ctx)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Stažení se nepovedlo: {e}")
    return ToolResult(True, "Rozpoznávání obličejů je připravené. Řekni „nauč se můj obličej“.", data=r)


@tool("face_enroll", "Naučí se obličej člověka z domácnosti (5 pohledů do kamery PC) – „nauč se můj obličej“, „nauč se Janu“. "
      "Uloží jen číselný otisk, ne fotku.", category="kamera", perm="screen", danger=True,
      details=lambda a: [f"Kamera PC se na pár vteřin zapne a naučí se obličej: {a.get('name', '')}.",
                         "Ať se dotyčný dívá do kamery a souhlasí s tím."])
async def face_enroll(ctx, name: Annotated[str, "jméno člověka"]) -> ToolResult:
    from .. import faces

    try:
        r = await asyncio.to_thread(faces.enroll, ctx, name.strip()[:40])
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, str(e))
    return ToolResult(True, f"Obličej {r['name']} si pamatuju ({r['samples']} pohledů).", data=r)


@tool("face_forget", "Smaže naučený obličej („zapomeň obličej Jany“).", category="kamera", perm="files_write")
async def face_forget(ctx, name: str) -> ToolResult:
    from .. import faces

    ok = faces.People().forget(name)
    return ToolResult(ok, f"Obličej {name} jsem zapomněl." if ok else f"Obličej {name} neznám.")


@tool("who_is_here", "Kdo sedí u počítače / je před kamerou PC – jména lidí z domácnosti, ostatní jako host.", category="kamera",
      perm="screen")
async def who_is_here(ctx) -> ToolResult:
    from .. import faces

    try:
        r = await asyncio.to_thread(faces.who_is_here, ctx)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, str(e))
    if not r["count"]:
        return ToolResult(True, "Před kamerou nikoho nevidím.", data=r)
    return ToolResult(True, "Vidím: " + ", ".join(p["name"] for p in r["people"]) + ".", data=r)


@tool("screen_buddy", "Pomocník na obrazovce: každých pár vteřin se podívá na obrazovku a ozve se jen, když vidí chybu nebo "
      "problém, se kterým umí pomoct. Na „sleduj se mnou obrazovku“, „pomáhej mi u toho“, „přestaň sledovat“.",
      category="kamera", perm="screen")
async def screen_buddy(ctx, on: bool = True, goal: Annotated[str, "na čem pracuješ (nepovinné)"] = "") -> ToolResult:
    from .. import eyes

    b = eyes.buddy(ctx)
    if not on:
        b.stop()
        return ToolResult(True, "Přestal jsem sledovat obrazovku.")
    b.start(goal)
    return ToolResult(True, "Sleduju s tebou obrazovku – ozvu se, jen když uvidím problém. Řekni „přestaň sledovat“.")


@tool("sound_watch", "Hlídání zvuků doma mikrofonem PC: kouřový hlásič, hlasitá rána (rozbité sklo, pád) → zpráva na telefon. "
      "mode: always (pořád), away (jen když nejsi doma), off.", category="domácnost", perm="screen")
async def sound_watch(ctx, mode: Annotated[str, "always | away | off"] = "away") -> ToolResult:
    from .. import eyes

    mode = mode if mode in ("always", "away", "off") else "away"
    ctx.update_config({"home": {"sound_watch": mode}})
    w = eyes.sounds(ctx)
    if mode == "off":
        w.stop()
    elif w.wanted():
        w.start()
    return ToolResult(True, {"always": "Hlídám zvuky doma.", "away": "Zvuky budu hlídat, když nebudeš doma.",
                             "off": "Hlídání zvuků je vypnuté."}[mode])


@tool("sky_overhead", "Co teď letí nad námi: letadla kolem tvého města (volací znak, výška, směr, vzdálenost) a kde je ISS.",
      category="info", perm="network")
async def sky_overhead(ctx, radius_km: Annotated[int, "okruh v km"] = 40) -> ToolResult:
    from .. import eyes

    try:
        r = await eyes.sky(ctx, max(5, min(int(radius_km), 200)))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Letový provoz teď nejde zjistit: {e}")
    ps = r["planes"]
    if ps:
        top = ", ".join(f"{p['callsign']} ({p['km']} km na {p['dir']}, {p['alt_m']} m)" for p in ps[:3])
        text = f"Nad {r['city']} je teď {len(ps)} letadel. Nejblíž: {top}."
    else:
        text = f"V okruhu {r['radius_km']} km kolem {r['city']} teď nic neletí (podle OpenSky)."
    if r["iss"]:
        text += f" ISS je {r['iss']['km']} km na {r['iss']['dir']}."
    return ToolResult(True, text, data=r)
