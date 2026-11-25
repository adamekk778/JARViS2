"""Šablona dovednosti JARVISe – zkopíruj, přejmenuj a uprav. Zabalíš ji: „zabal dovednost pocasi_vtip“."""
from jarvis.tools.base import ToolResult, tool

SKILL = {
    "name": "pocasi_vtip",
    "description": "Řekne vtip podle počasí venku.",
    "version": "1.0",
    "permissions": ["network"],        # apps, input, screen, files_read, files_write, shell, network, system
    "timeout": 20,                      # sekund, pak se dovednost ukončí
}

VTIPY = {
    "déšť": "Prší? Aspoň nemusíš zalévat kytky.",
    "sníh": "Sněží – ideální den na kakao a programování.",
    "jasno": "Jasno! I tvoje obrazovka by chtěla ven.",
}


@tool("weather_joke", "Řekne krátký vtip podle aktuálního počasí ve městě.")
async def weather_joke(ctx, city: str = "Praha") -> ToolResult:
    async with ctx.http() as c:          # ctx.http() = httpx klient se správnými certifikáty
        r = await c.get("https://wttr.in/" + city, params={"format": "%C"}, timeout=10)
    what = r.text.strip().lower()
    joke = next((v for k, v in VTIPY.items() if k in what), "Počasí je… zajímavé. Jako vždycky.")
    return ToolResult(True, joke, data={"weather": what})
