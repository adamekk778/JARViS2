"""3.5 smart home by voice (Home Assistant): "rozsviť v obýváku", "zhasni všechna světla", "nastav topení na 22"."""
from __future__ import annotations

from typing import Annotated, Literal

from .base import ToolResult, tool

NOT_SET = ("Chytrá domácnost není připojená. V Nastavení → Domov zadej adresu Home Assistantu a přístupový token "
           "(Home Assistant → Profil → Zabezpečení → Dlouhodobé přístupové tokeny).")


def _risky(args: dict, ctx=None) -> bool:
    from ..home import risky

    action, target, domain = str(args.get("action", "")), str(args.get("target", "")), str(args.get("domain", ""))
    if risky(action, target, domain):
        return True
    home = getattr(ctx, "home", None)
    hit = home.find_cached(target) if home else None
    if hit is None:      # not seen yet → opening something unknown asks first
        return action in ("open", "unlock")
    return risky(action, hit["name"], hit["domain"])


@tool("home_devices", "Zařízení chytré domácnosti (Home Assistant) a jejich stav: světla, zásuvky, topení, teploty, "
      "žaluzie, zámky, senzory. Na „co svítí“, „kolik je v obýváku stupňů“, „je zamčeno?“.", category="domácnost", perm="home")
async def home_devices(ctx, query: Annotated[str, "část názvu, např. obývák (prázdné = vše)"] = "",
                       domain: Annotated[str, "light, switch, climate, sensor, cover, lock… (prázdné = vše)"] = "") -> ToolResult:
    from ..home import configured, say_state
    from ..stark import _fold

    if not configured(ctx):
        return ToolResult(False, NOT_SET)
    items = await ctx.home.states(fresh=True)
    if domain:
        items = [e for e in items if e["domain"] == domain]
    else:
        items = [e for e in items if e["domain"] not in ("automation", "update", "zone", "sun", "device_tracker", "event", "tts",
                                                         "conversation", "stt", "number", "select", "input_number", "input_text")]
    if query:
        words = _fold(query).split()
        items = [e for e in items if all(w in _fold(e["name"]) + " " + _fold(e["id"]) for w in words)]
    if not items:
        return ToolResult(True, "Nic takového v Home Assistantu nevidím.")
    items = items[:60]
    return ToolResult(True, "\n".join(say_state(e) for e in items), data=items)


@tool("home_control", "Ovládá chytrou domácnost (Home Assistant). action: on, off, toggle, set (value = jas % u světla, "
      "teplota °C u topení, poloha % u žaluzií), open, close, stop, lock, unlock, play, pause. target = název zařízení, "
      "místnosti nebo scény („obývák“, „lampa“, „scéna kino“); „všechna světla“ = všechna. Zámky, alarm a otevírání "
      "garáže/brány se vždy nejdřív zeptá.", category="domácnost", perm="home", danger_if=_risky,
      details=lambda a: [f"Zařízení: {a.get('target', '')}", f"Akce: {a.get('action', '')}" + (f" {a.get('value')}" if a.get("value") is not None else "")])
async def home_control(ctx, target: str,
                       action: Literal["on", "off", "toggle", "set", "open", "close", "stop", "lock", "unlock", "play", "pause"] = "toggle",
                       value: float | None = None, domain: str = "") -> ToolResult:
    from ..home import configured

    if not configured(ctx):
        return ToolResult(False, NOT_SET)
    return ToolResult(True, await ctx.home.control(target, action, value, domain))


@tool("home_scene", "Spustí scénu nebo skript v Home Assistantu („scéna kino“, „dobrou noc“).", category="domácnost", perm="home")
async def home_scene(ctx, name: str) -> ToolResult:
    from ..home import configured

    if not configured(ctx):
        return ToolResult(False, NOT_SET)
    hits = await ctx.home.find(name, ("scene", "script"))
    if not hits:
        scenes = [e["name"] for e in await ctx.home.states() if e["domain"] in ("scene", "script")]
        return ToolResult(False, f"Scénu „{name}“ nevidím. Mám: {', '.join(scenes[:15]) or 'žádné'}.")
    await ctx.home.service(hits[0]["domain"], "turn_on", {"entity_id": hits[0]["id"]})
    return ToolResult(True, f"Spouštím {hits[0]['name']}.")
