"""3.20 Hlas+ tools (nápady 1–20): sčítání, navigace v odpovědi, budíček, vzkaz do budoucna, hlasové poznámky, čtení
textů nahlas, rodinné hlasování, hlasová zpráva, nácvik prezentace, vlastní hlas."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Literal

from .. import voicex
from .base import ToolResult, tool


@tool("voice_kit", "Hlasové pomůcky: sčítání nahlas (action=tally, text = „sečti 120 a 250“ / „a ještě 80“ / „kolik to dělá“), "
      "přeskoč / vrať se o větu / jen závěr / pomaleji v poslední odpovědi (skip, back, end, slow), budíček s ranním "
      "souhrnem (alarm, when = „7:30“ nebo „zítra v 6“, days = „po-pa“), vzkaz pro budoucí já (future, text, when = "
      "„24. 12. 2027“ / „za rok“), hlasová poznámka s časem a místem (note, text) a jejich seznam (notes).",
      category="hlas")
async def voice_kit(ctx, action: Literal["tally", "skip", "back", "end", "slow", "alarm", "future", "note", "notes"],
                    text: str = "", when: str = "", days: str = "") -> ToolResult:
    if action == "tally":
        return ToolResult(True, voicex.tally(ctx, text))
    if action in ("skip", "back", "end", "slow"):
        say, rate = voicex.navigate(ctx, action)
        sp = getattr(ctx, "speaker", None)
        if sp is not None and say and rate:
            async def _slow() -> None:
                audio, _ = await sp.synth(say, "cs", override={"tts_rate": rate})
                sp._stop.clear()
                await asyncio.to_thread(sp._play, audio)
            asyncio.get_running_loop().create_task(_slow())
            return ToolResult(True, say, data={"spoken": True})
        return ToolResult(True, say)
    if action == "alarm":
        try:
            job = voicex.schedule_alarm(ctx, when or text, days)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Budíček nastaven: {job.get('spec_text') or job.get('title', '')}. Vzbudím tě tónem a ranním "
                                "souhrnem.", data=job)
    if action == "future":
        if not text.strip():
            return ToolResult(False, "Co ti mám vzkázat?")
        try:
            job = voicex.schedule_future(ctx, text, when)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Uloženo. Vzkaz ti dám {job.get('spec_text') or when}.", data=job)
    if action == "note":
        if not text.strip():
            return ToolResult(False, "Co si mám poznamenat?")
        pcm = getattr(ctx, "voicex_last_pcm", None) if getattr(ctx, "voicex_last_pcm_text", "") and \
            voicex.fold(text)[:20] in voicex.fold(getattr(ctx, "voicex_last_pcm_text", "")) else None
        r = voicex.save_voice_note(ctx, text, pcm)
        where = f", {r['place']}" if r["place"] else ""
        return ToolResult(True, f"Poznamenáno ({r['when']}{where})" + (" i s nahrávkou." if r["wav"] else "."), data=r)
    rows = voicex.voice_notes(ctx)
    if not rows:
        return ToolResult(True, "Zatím nemáš žádné hlasové poznámky.")
    import datetime as dt

    lines = [f"{dt.datetime.fromtimestamp(r['ts']):%d. %m. %H:%M}{' (' + r['place'] + ')' if r['place'] else ''}: {r['text']}" for r in rows]
    return ToolResult(True, "\n".join(lines), data=rows)


@tool("read_aloud", "Přečte dlouhý text nahlas – článek (url), soubor (path, PDF/TXT/DOCX) nebo vložený text – a pamatuje si, "
      "kde jsi skončil. action: start, pause, resume, faster, slower, where.", category="hlas")
async def read_aloud(ctx, action: Literal["start", "pause", "resume", "faster", "slower", "where"] = "start",
                     url: str = "", path: str = "", text: str = "", title: str = "") -> ToolResult:
    if action == "where":
        return ToolResult(True, voicex.where_reading(ctx))
    if action in ("faster", "slower"):
        r = voicex.reading_rate(ctx, 10 if action == "faster" else -10)
        return ToolResult(True, f"Rychlost čtení {r:+d} %.")
    if action == "pause":
        st = voicex._reading_state(ctx)
        st["paused"] = True
        sp = getattr(ctx, "speaker", None)
        if sp is not None:
            sp.stop()
        return ToolResult(True, "Pozastaveno. Řekni „pokračuj ve čtení“.")
    if action == "start":
        body = text
        if url:
            from .web import web_read

            r = await web_read(ctx, url, max_chars=200_000)
            if not r.ok:
                return ToolResult(False, f"Stránku jsem nepřečetl: {r.summary}")
            body = r.summary
        elif path:
            p = Path(path).expanduser()
            if not p.is_file():
                return ToolResult(False, f"Soubor {path} nenacházím.")
            from ..attachments.extract import extract, kind_of

            body = await asyncio.to_thread(extract, p, kind_of(p.name, ""))
        if not body or len(body.strip()) < 20:
            return ToolResult(False, "Nemám co číst – dej mi odkaz, soubor nebo text.")
        info = voicex.start_reading(ctx, title or Path(path).name if path else title or url[:60], body, url or path)
    if getattr(ctx, "speaker", None) is None:
        return ToolResult(False, "Hlas tu neběží.")
    ctx.voicex_reader = asyncio.get_running_loop().create_task(voicex.read_loop(ctx))
    if action == "start":
        msg = f"Čtu od {info['pos'] + 1}. věty ze {info['total']} (navazuji, kde jsi skončil)." if info["resumed"] else \
            f"Čtu ({info['total']} vět). „Zastav“ pozastaví, „rychleji / pomaleji“ změní tempo."
        return ToolResult(True, msg, data=info)
    return ToolResult(True, "Pokračuji ve čtení.")


@tool("family_poll", "Rodinné hlasování: zeptá se ve všech místnostech i na telefonech („Kdo chce pizzu?“) a sečte odpovědi. "
      "action: start (question, options, minutes), result.", category="hlas")
async def family_poll(ctx, action: Literal["start", "result"] = "start", question: str = "",
                      options: list[str] | None = None, minutes: int = 5) -> ToolResult:
    if action == "result":
        return ToolResult(True, voicex.poll_result(ctx))
    if not question.strip():
        return ToolResult(False, "Na co se mám zeptat?")
    p = voicex.poll_start(ctx, question, options, minutes)
    ask = f"Hlasování: {question.strip()} Možnosti: {', '.join(p['options'])}. Odpovězte do {minutes} minut."
    if voicex.house_speakers_ok(ctx):
        from .. import house

        try:
            await house.announce(ctx, ask, "all")
        except Exception:  # noqa: BLE001 – no house speakers: the PC and the phones still ask
            pass
    ctx.notify("Hlasování", ask, speak=True)

    async def _close() -> None:
        await asyncio.sleep(60 * max(1, minutes))
        ctx.notify("Výsledek hlasování", f"{question.strip()} – {voicex.poll_result(ctx)}", speak=True)
    asyncio.get_running_loop().create_task(_close())
    return ToolResult(True, f"Ptám se všech: „{question.strip()}“ ({', '.join(p['options'])}). Výsledek řeknu za {minutes} min.",
                      data=p)


@tool("voice_message", "Pošle blízkému HLASOVOU zprávu: text namluví hlasem JARVISe a telefon ji otevře ve WhatsAppu u kontaktu "
      "(„řekni Janě, že přijdu později“).", category="telefon", perm="apps")
async def voice_message(ctx, to: Annotated[str, "jméno z kontaktů nebo číslo"], text: str) -> ToolResult:
    if getattr(ctx, "speaker", None) is None:
        return ToolResult(False, "Hlas JARVISe tu neběží.")
    path, mime = await voicex.voice_file(ctx, text)
    from .. import house

    tid = house.keep_audio(path.read_bytes(), mime)
    url = f"http://{house.lan_ip()}:{ctx.cfg.phone.port}/tts/{tid}.{path.suffix.lstrip('.')}"
    from .phone_link_tools import _phone_cmd

    state, err = await _phone_cmd(ctx, "voice_share", to=to, url=url, text=text)
    if err:
        return ToolResult(False, err, attachments=[])
    if state and state.startswith("notfound"):
        return ToolResult(False, f"V kontaktech jsem „{to}“ nenašel.")
    if state is None or state == "unknown":
        state, err = await _phone_cmd(ctx, "whatsapp", to=to, text=text)     # an older app: the words as text
        return ToolResult(state is not None, "Telefon hlasové zprávy ještě neumí – připravil jsem ve WhatsAppu text." if state
                          else "Telefon nereaguje.", data={"file": str(path)})
    return ToolResult(True, f"Hlasová zpráva pro {to} je připravená ve WhatsAppu, stačí ji v telefonu odeslat.",
                      data={"file": str(path)})


@tool("speech_coach", "Nácvik prezentace: action=start začne poslouchat, stop vyhodnotí tempo (slov za minutu), výplňová slova "
      "(ehm, jako, prostě), délku a dlouhé pauzy a dá rady.", category="hlas")
async def speech_coach(ctx, action: Literal["start", "stop"] = "start") -> ToolResult:
    vl = getattr(ctx, "voice", None)
    if action == "start":
        if vl is None or not hasattr(vl, "start_raw_recording"):
            return ToolResult(False, "Mikrofon tu neběží – nácvik potřebuje JARVISe s hlasem na tomhle PC.")
        vl.start_raw_recording()
        ctx.voicex_coach_t0 = asyncio.get_running_loop().time()
        return ToolResult(True, "Poslouchám. Mluv, jako bys prezentoval. Až skončíš, řekni „konec nácviku“.")
    if vl is None or not hasattr(vl, "stop_raw_recording"):
        return ToolResult(False, "Nácvik neběží.")
    pcm = vl.stop_raw_recording()
    if not pcm:
        return ToolResult(False, "Nic jsem nezaslechl.")
    secs = len(pcm) / 2 / 16000
    text = await asyncio.to_thread(vl.transcriber.transcribe, pcm, 16000)
    r = voicex.coach(text, secs, voicex.pauses_of(pcm))
    msg = (f"Délka {r['length']}, tempo {r['wpm']} slov/min, výplňová slova {round(r['filler_share'] * 100)} %. " + " ".join(r["tips"]))
    return ToolResult(True, msg, data={**r, "text": text[:3000]})


@tool("voice_clone", "Vlastní hlas JARVISe z TVÉ nahrávky (ElevenLabs, aspoň ~30 s). Jen s výslovným souhlasem (consent=true), "
      "jen tvůj vlastní hlas a jen pro tvého JARVISe.", category="hlas", danger=True)
async def voice_clone(ctx, path: Annotated[str, "nahrávka WAV/MP3"], consent: bool = False, name: str = "Můj hlas") -> ToolResult:
    try:
        r = await voicex.clone_voice(ctx, path, name, consent)
    except (ValueError, RuntimeError) as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Hotovo – JARVIS teď mluví hlasem „{r['name']}“ (ElevenLabs). Vrátit jde v Nastavení → Hlas.", data=r)
