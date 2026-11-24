"""3.14 tools: memory (decisions with a reason, imports, clean-up, encrypted data folder)."""
from __future__ import annotations

import asyncio
from typing import Annotated

from .base import ToolResult, tool


@tool("remember_decision", "Zapamatuje si rozhodnutí i s DŮVODEM (proč) – aby šlo později dohledat, proč se něco "
      "rozhodlo („rozhodli jsme se pro nabídku B, protože je levnější o 20 %“). Pro obyčejné fakty použij remember.",
      category="paměť", perm="files_write")
async def remember_decision(ctx, decision: Annotated[str, "co se rozhodlo"], reason: Annotated[str, "proč"]) -> ToolResult:
    from .. import memplus

    text = memplus.decision_text(decision, reason)
    know = getattr(ctx, "knowledge", None)
    res = know.add_fact(text, source="rozhodnutí") if know else {"stored": False, "reason": "paměť není"}
    return ToolResult(bool(res.get("stored")), f"Zapamatováno: {text}" if res.get("stored") else f"Neuloženo: {res.get('reason')}")


@tool("import_memory", "Načte do JARVISe historii z exportu ChatGPT nebo Claude (conversations.json / ZIP) nebo poznámky "
      "Google Keep (Takeout). Bez confirm jen ukáže, co by se načetlo; s confirm=true to načte do složky Import "
      "(prohledávatelné, dá se smazat).", danger_if=lambda a: bool(a.get("confirm")), category="paměť", perm="files_write",
      details=lambda a: [f"Soubor: {a.get('path', '')}", "Konverzace/poznámky půjdou do historie (složka Import)."])
async def import_memory(ctx, path: str, confirm: bool = False) -> ToolResult:
    from .. import memplus

    try:
        prev = await asyncio.to_thread(memplus.preview_import, path)
    except (ValueError, OSError) as e:
        return ToolResult(False, f"Nejde přečíst: {e}")
    if not confirm:
        what = (f"{prev['conversations']} konverzací ({prev['messages']} zpráv)" if prev["kind"] == "chat"
                else f"{prev['notes']} poznámek z Google Keep")
        return ToolResult(True, f"Načetlo by se {what}. Ukázka: {', '.join(prev['titles'][:5])}.", data=prev)
    res = await asyncio.to_thread(memplus.run_import, ctx, path)
    return ToolResult(True, f"Načteno {res['imported']} zpráv/poznámek do {res['conversations']} konverzací (složka Import).", data=res)


@tool("memory_cleanup", "Úklid paměti: najde skoro stejné fakty a ty, které už neplatí (prošlý termín). Bez ids jen "
      "navrhne; s ids smaže vybrané fakty.", danger_if=lambda a: bool(a.get("ids")), category="paměť", perm="files_write")
async def memory_cleanup(ctx, ids: list[int] | None = None) -> ToolResult:
    from .. import memplus

    if ids:
        n = await asyncio.to_thread(memplus.apply_cleanup, ctx, ids)
        return ToolResult(True, f"Smazáno {n} faktů.")
    s = await asyncio.to_thread(memplus.cleanup_suggestions, ctx)
    return ToolResult(True, f"{len(s['duplicates'])} dvojic skoro stejných faktů, {len(s['expired'])} prošlých.", data=s)


@tool("encrypt_data", "Zašifruje složku s daty JARVISe (paměť, historie, nahrávky) pomocí EFS ve Windows – číst ji pak jde "
      "jen pod přihlášením uživatele. Na Windows Home EFS není (pak BitLocker).", danger=True, category="systém", perm="system",
      details=lambda a: ["Složka s daty JARVISe se zašifruje (EFS, klíč z tvého přihlášení do Windows).",
                         "Zálohuj si certifikát EFS, jinak data po přeinstalaci Windows neotevřeš."])
async def encrypt_data(ctx) -> ToolResult:
    from .. import memplus, paths

    r = await asyncio.to_thread(memplus.encrypt_data_folder, paths.data_dir())
    return ToolResult(r["ok"], r["message"])


@tool("remind_on", "Připomene něco v určitou CHVÍLI místo času: when = pc (až si sednu k PC), home (až přijdu domů), "
      "away_home (až odejdu z domu), call (až mi zavolá `who`), message (až mi napíše `who`), app (až otevřu aplikaci `who`), "
      "mail (až přijde e-mail od `who`). Připomínka se po jednom použití sama smaže.", category="připomínky", perm="apps")
async def remind_on(ctx, when: str, text: str, who: str = "") -> ToolResult:
    from .. import proactiveplus

    try:
        r = proactiveplus.remind_on(ctx, when, text, who)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Připomenu: „{text}“ ({proactiveplus.WHEN_LABEL.get(when, when)}{' – ' + who if who else ''}).", data=r)


@tool("proactive_stats", "Která upozornění, co JARVIS posílá sám od sebe (večerní přehled, brífink při odchodu, návrhy "
      "dovedností…), používáš a která ignoruješ – a které jsou kvůli tomu ztlumené.", category="připomínky")
async def proactive_stats(ctx) -> ToolResult:
    from .. import proactiveplus

    st = proactiveplus.stats(ctx)
    if not st:
        return ToolResult(True, "Zatím jsem sám od sebe nic neposílal.")
    return ToolResult(True, "; ".join(f"{s['label']}: {s['shown']}× ukázáno, {s['used']}× použito{' (ztlumeno)' if s['muted'] else ''}"
                                      for s in st), data=st)


@tool("live_activity", "Ukáže v zavřeném notchi malý průběh dlouhé věci (stahování, převod, build): id, název, průběh 0–1 "
      "nebo krátký text; done=true ho schová.", category="notch")
async def live_activity(ctx, id: str, title: str, progress: float | None = None, text: str = "",  # noqa: A002
                        done: bool = False, icon: str = "spinner-gap") -> ToolResult:
    from .. import notchplus

    notchplus.live(ctx, id, title, icon, progress, text, done)
    return ToolResult(True, "Skryto." if done else "Zobrazeno v notchi.")


@tool("notch_widget_add", "Přidá do notche (Více) vlastní widget: krátký text z nástroje, který nic nemění, každých N minut "
      "(např. počasí v Brně: tool=weather, args={city: Brno}; kurz bitcoinu: tool=price; odjezdy: tool=transit_departures).",
      category="notch", perm="apps")
async def notch_widget_add(ctx, name: str, tool_name: str, args: dict | None = None, every_min: int = 15,
                           icon: str = "squares-four") -> ToolResult:
    import uuid

    from .. import tools as T

    T.load_builtin()
    spec = T.REGISTRY.get(tool_name)
    if spec is None or spec.danger or (spec.danger_if and spec.danger_if(dict(args or {}))):
        return ToolResult(False, "Widget smí používat jen nástroj, který nic nemění.")
    w = {"id": uuid.uuid4().hex[:8], "name": name[:30], "icon": icon[:30], "tool": tool_name, "args": dict(args or {}),
         "every_min": max(1, min(int(every_min), 1440))}
    items = [x.model_dump() for x in ctx.cfg.notch.widgets] + [w]
    ctx.update_config({"notch": {"widgets": items}})
    wid = getattr(ctx, "widgets", None)
    if wid is not None:
        await wid.refresh(force=True)
    return ToolResult(True, f"Widget „{name}“ je v notchi (Více).", data=w)


@tool("mochi_level", "Jak Mochi (postavička JARVISe) roste: úroveň, body za společné dny, mise a návyky, a co se odemklo.",
      category="notch")
async def mochi_level(ctx) -> ToolResult:
    from .. import notchplus

    lv = notchplus.mochi_level(ctx)
    nxt = lv["locked"][0] if lv["locked"] else None
    return ToolResult(True, f"Mochi má úroveň {lv['level']} ({lv['points']} bodů)."
                      + (f" Na úrovni {nxt['level']} odemkne {nxt['name']}." if nxt else " Všechno odemčeno."), data=lv)


@tool("guest_mode", "Režim host: u PC sedí někdo jiný – JARVIS neukáže nic osobního (paměť, e-maily, zprávy, kalendář), "
      "upozornění jen s titulkem a nic soukromého nahlas. on=false ho vypne.", category="bezpečnost")
async def guest_mode(ctx, on: bool = True) -> ToolResult:
    ctx.update_config({"privacy": {"guest_mode": bool(on)}})
    return ToolResult(True, "Režim host je zapnutý – nic osobního neukážu." if on else "Režim host je vypnutý.")


@tool("access_log", "Co JARVIS dnes (nebo za posledních N dní) viděl a slyšel: obrazovka, schránka, myš a klávesnice, "
      "kamera, mikrofon a podezřelé texty – kdy a k čemu.", category="bezpečnost")
async def access_log(ctx, days: int = 1) -> ToolResult:
    from .. import shield

    r = shield.recent(ctx, max(1, min(days, 30)))
    mic = (r.get("mic") or {}).get("sessions") or []
    if not r["rows"] and not mic:
        return ToolResult(True, "Nic – na obrazovku, schránku, kameru, mikrofon ani ovládání jsem nesahal.", data=r)
    parts = [f"{shield.KIND_OF.get(k, k)}: {n}×" for k, n in r["counts"].items()]
    if mic:
        parts.append(f"mikrofon: {len(mic)}× ({r['mic'].get('seconds', 0)} s)")
    return ToolResult(True, "Za tu dobu: " + ", ".join(parts) + ".", data=r)


# ---------- 3.14 návrh 113: self-healing skills ----------
@tool("skill_fix", "Navrhne opravu naučené dovednosti (skillu), která padá nebo dělá chybu: AI přepíše soubor, JARVIS "
      "zkontroluje, že jde načíst, a ukáže změny řádek po řádku. Nic se nezapíše – použití opravy je skill_fix_apply. Na "
      "„oprav dovednost …“, „skill … nefunguje“.", category="dovednosti", perm="files_read")
async def skill_fix(ctx, name: Annotated[str, "název dovednosti (souboru) – viz list_skills"],
                    problem: Annotated[str, "co nefunguje, vlastními slovy (nepovinné, když dovednost spadla)"] = "") -> ToolResult:
    from .. import skillheal

    try:
        prop = await skillheal.propose(ctx, name.strip().lower(), problem)
    except ValueError as e:
        return ToolResult(False, str(e))
    if prop["problems"]:
        return ToolResult(False, f"Opravu se nepodařilo připravit: {'; '.join(prop['problems'])}.", data=prop)
    changed = sum(1 for x in prop["diff"] if x[:1] in "+-" and not x.startswith(("+++", "---")))
    return ToolResult(True, f"Oprava dovednosti {name} je připravená ({changed} změněných řádků). {prop['why']} Mám ji použít? "
                      "(ukážu ti změny ke schválení)", data={"diff": prop["diff"], "why": prop["why"]})


def _fix_details(a: dict) -> list[str]:
    from .. import skillheal

    return skillheal.details(str(a.get("name", "")).strip().lower())


@tool("skill_fix_apply", "Použije připravenou opravu dovednosti ze skill_fix (po schválení; stará verze se zálohuje).",
      danger=True, category="dovednosti", perm="files_write", details=_fix_details)
async def skill_fix_apply(ctx, name: Annotated[str, "název dovednosti"]) -> ToolResult:
    from .. import skillheal

    try:
        res = await asyncio.to_thread(skillheal.apply, ctx, name.strip().lower())
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Dovednost {name} je opravená a znovu načtená ({', '.join(res['tools'])}). Původní verze je v "
                      "záloze.", data=res)


# ---------- 3.14 the brain picked in one step (Claude, Ollama, …) ----------
@tool("brain_switch", "Přepne, která AI (mozek) JARVISovi odpovídá, a případně její model: Claude (Anthropic), Ollama v tomhle "
      "PC, Groq, Gemini, OpenAI, OpenRouter. Na „přepni na Ollamu“, „použij Claude Sonnet“, „přepni model na qwen3:8b“, "
      "„jaký teď používáš model“ (bez parametrů jen řekne, co odpovídá teď).", category="mozek")
async def brain_switch(ctx, brain: Annotated[str, "anthropic | ollama | groq | gemini | openai | openrouter | omniroute | lmstudio "
                                                  "(prázdné = jen změnit model té, co odpovídá teď)"] = "",
                       model: Annotated[str, "model, např. claude-sonnet-5-5 nebo qwen3:8b (prázdné = nechat)"] = "",
                       only: Annotated[bool | None, "true = jen tahle AI, žádné záložní; false = ostatní jako záloha"] = None) -> ToolResult:
    from .. import brainpick

    if not brain and not model and only is None:
        cur = brainpick.current(ctx)
        if not cur["id"]:
            return ToolResult(False, "Teď nemám žádnou AI – vlož API klíč v Nastavení → Mozek nebo spusť Ollamu.")
        return ToolResult(True, f"Teď odpovídá {cur['label']} (model {cur['model']}).", data=cur)
    key = (brain or "").strip().lower()
    key = brainpick.preset_from_words(key) or key or brainpick.current(ctx)["id"]
    if not key:
        return ToolResult(False, "Nevím, na kterou AI přepnout – řekni třeba „přepni na Ollamu“ nebo „použij Claude“.")
    if model and brainpick.find(ctx, key) and (brainpick.find(ctx, key).preset == "ollama" or key == "ollama"):
        try:
            have = await brainpick.models(ctx, key)
        except ValueError:
            have = {"models": []}
        names = [m["id"] for m in have.get("models", [])]
        if names and model not in names:
            near = next((n for n in names if n.split(":")[0] == model.split(":")[0] or n.startswith(model)), "")
            if not near:
                return ToolResult(False, f"Model {model} v Ollamě nemám. Mám: {', '.join(names[:8])}.", data={"models": names})
            model = near
    try:
        res = brainpick.use(ctx, key, model, only)
    except ValueError as e:
        return ToolResult(False, str(e))
    line = f"Hotovo, odpovídá {res['label']}" + (f" s modelem {res['model']}" if res["model"] else "") + "."
    return ToolResult(True, " ".join([line, *res["notes"]]), data=res)


@tool("brain_split", "Chytré rozdělení mozků: lehké otázky (pozdrav, rychlý dotaz) odpovídá jedna AI – třeba Ollama v PC zdarma "
      "– a těžké úkoly (plán, kód, analýza, mise) jiná – třeba Claude. Na „lehké věci ať dělá Ollama a těžké Claude“, "
      "„vypni rozdělení“.", category="mozek")
async def brain_split(ctx, on: Annotated[bool, "zapnout (true) / vypnout (false)"] = True,
                      easy: Annotated[str, "AI na lehké otázky: ollama | groq | gemini | anthropic | …"] = "",
                      hard: Annotated[str, "AI na těžké úkoly: anthropic | openai | gemini | …"] = "") -> ToolResult:
    from .. import brainpick

    try:
        res = brainpick.split(ctx, on, brainpick.preset_from_words(easy) or easy, brainpick.preset_from_words(hard) or hard)
    except ValueError as e:
        return ToolResult(False, str(e))
    if not res["on"]:
        return ToolResult(True, "Rozdělení je vypnuté – odpovídá AI podle pořadí.", data=res)
    if not res["easy"] or not res["hard"]:
        return ToolResult(False, "Řekni, která AI má dělat lehké otázky a která těžké úkoly (např. Ollama a Claude).", data=res)
    return ToolResult(True, " ".join([f"Hotovo: lehké otázky dělá {res['easy']}, těžké úkoly {res['hard']}.", *res["notes"]]), data=res)
