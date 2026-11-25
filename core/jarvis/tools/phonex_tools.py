"""3.20 Telefon + Hodinky (121–160) tools."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from .. import phonex
from .base import ToolResult, tool


@tool("phone_kit", "Telefon: NFC štítky (nfc_bind name+text = povel, nfc_list, nfc_remove), ovládání PC z telefonu (pc action_name: "
      "mute/lock/vol_up/vol_down/play_pause/next/prev/next_slide/prev_slide), režim v autě (drive on/off), Nerušit teď "
      "(dnd on/off), stav na zamčené obrazovce (lock_status), roaming v zemi (roaming text=kód země), dovolená (vacation on/off, "
      "until), sdílení polohy na čas (share_location minutes, name; share_stop), poznámky k hovorům (call_notes text=kdo), "
      "sken stránek do PDF (scan attachments=id fotek oddělené čárkou, text=doc/bw/color), telefon jako webkamera (webcam), "
      "přehled (status).", category="telefon", danger_if=lambda a: a.get("action") == "share_location")
async def phone_kit(ctx, action: Literal["nfc_bind", "nfc_list", "nfc_remove", "pc", "drive", "dnd", "lock_status", "roaming",
                                         "vacation", "share_location", "share_stop", "call_notes", "scan", "webcam", "status"],
                    name: str = "", text: str = "", on: bool = True, minutes: int = 60, until: str = "", attachments: str = "",
                    action_name: str = "") -> ToolResult:
    if action == "nfc_bind":
        try:
            r = phonex.nfc_bind(ctx, name, text)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Štítek „{r['tag']}“ = {r['command']}. Na NFC nálepku zapiš adresu {r['uri']} (třeba aplikací "
                                "NFC Tools) a pak stačí ťuknout telefonem.", data=r)
    if action == "nfc_list":
        tags = phonex.nfc_list(ctx)
        return ToolResult(True, "\n".join(f"{t['tag']} → {t['command']}" for t in tags) or "Žádné NFC štítky zatím nemáš.", data=tags)
    if action == "nfc_remove":
        try:
            ok = phonex.nfc_remove(ctx, name)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(ok, "Štítek smazán." if ok else "Takový štítek neznám.")
    if action == "pc":
        ok, msg = await phonex.pc_action(ctx, action_name or text)
        return ToolResult(ok, msg)
    if action == "drive":
        ctx.driving = bool(on)
        ctx.bus.publish("driving", on=ctx.driving, car="")
        return ToolResult(True, "Režim v autě: krátké odpovědi nahlas, nic ke čtení." if on else "Režim v autě vypnut.")
    if action == "dnd":
        ok = ctx.phone_push("dnd", on=bool(on), why="na tvůj pokyn")
        return ToolResult(ok, ("Nerušit zapnuto." if on else "Nerušit vypnuto.") if ok else "Telefon teď není připojený.")
    if action == "lock_status":
        line = phonex.status_line(ctx)
        ok = ctx.phone_push("lock_status", line=line, controls=True)
        return ToolResult(ok, f"Na zamčené obrazovce: {line}" if ok else "Telefon teď není připojený.")
    if action == "roaming":
        t = phonex.roaming_text(text or name, str(getattr(ctx.cfg.mobx, "home_country", "cz")))
        return ToolResult(bool(t), t or "To je domácí země – žádný roaming.")
    if action == "vacation":
        return ToolResult(True, phonex.vacation(ctx, bool(on), until or text))
    if action == "share_location":
        r = phonex.share_start(ctx, minutes, name)
        note = "" if r["phone"] else " Telefon teď není připojený – poloha začne chodit, až se ozve."
        pub = "" if str(r["url"]).startswith("http") else (" Odkaz funguje jen doma; pro sdílení ven nastav veřejnou adresu "
                                                             "(Nastavení → Telefon → Veřejná adresa).")
        return ToolResult(True, f"Sdílím polohu {r['minutes']} min: {r['url']}.{note}{pub}", data=r)
    if action == "share_stop":
        n = phonex.share_stop(ctx)
        return ToolResult(True, f"Sdílení polohy ukončeno ({n}).")
    if action == "call_notes":
        notes = phonex.call_notes(ctx, text or name)
        return ToolResult(True, "\n".join(f"{n['who']}: {n['text']}" for n in notes) or "Žádné poznámky k hovorům.", data=notes)
    if action == "scan":
        paths = []
        for aid in [a.strip() for a in attachments.split(",") if a.strip()]:
            att = ctx.store.get(aid)
            if att:
                paths.append(Path(att.path))
        if not paths:
            return ToolResult(False, "Pošli fotky stránek (přílohy) a pak řekni „udělej z nich PDF“.")
        import time

        out = Path(ctx.store.root) / "scans" / f"sken-{time.strftime('%Y%m%d-%H%M%S')}.pdf"
        mode = text if text in ("doc", "bw", "color") else "doc"
        phonex.scan_pdf(paths, out, mode)
        att = await ctx.store.save_path(out, "application/pdf", conv_id=ctx.memory.current_conversation)
        return ToolResult(True, f"PDF ze {len(paths)} stránek je hotové.", data=att.public(), attachments=[att.id])
    if action == "webcam":
        live = phonex.camfeed(ctx).fresh()
        return ToolResult(True, ("Kamera telefonu běží: " if live else "V telefonu otevři Kamera → Webkamera pro PC. Obraz pak najdeš na ")
                          + "http://localhost:8765/api/phonecam.mjpg (v OBS jako Zdroj → Prohlížeč nebo Zdroj médií).")
    snap = phonex.snapshot(ctx)
    lines = [f"Hodinky: {'připojené' if snap['watch'] else 'nepřipojené'}", f"Režim v autě: {'ano' if snap['driving'] else 'ne'}",
             f"Dovolená: {'ano' if snap['vacation'] else 'ne'}", f"NFC štítků: {len(snap['nfc'])}", snap["workouts"]]
    return ToolResult(True, "\n".join(lines), data=snap)


@tool("watch_kit", "Hodinky: vibrační kódy (legend), najdi hodinky (find), minutka na zápěstí (timer minutes, text), tichý budík jen "
      "na hodinkách (silent_alarm when), navigace vibracemi (route text=cíl, lat, lon), tep teď / při hraní (hr), stres z tepu "
      "(stress – odhad), hrudní pás přes Bluetooth (ble_hr seconds), tréninky (workout_add kind+minutes+km, workouts, week), "
      "zapomenutý telefon a další hlídání (status).", category="telefon")
async def watch_kit(ctx, action: Literal["legend", "find", "timer", "silent_alarm", "route", "hr", "stress", "ble_hr", "workout_add",
                                         "workouts", "week", "status"],
                    text: str = "", minutes: float = 0, when: str = "", lat: float = 0, lon: float = 0, seconds: int = 60,
                    kind: str = "run", km: float = 0) -> ToolResult:
    if action == "legend":
        return ToolResult(True, "\n".join(phonex.VIBE_LEGEND.values()), data=phonex.VIBE_LEGEND)
    if action == "find":
        ok, msg = phonex.find_watch(ctx)
        return ToolResult(ok, msg)
    if action == "timer":
        secs = int(minutes * 60)
        if secs <= 0:
            return ToolResult(False, "Na kolik minut?")
        t = ctx.timers.add(secs, text or "Časovač")
        ok = phonex.watch_timer(ctx, secs, text or "Časovač")
        return ToolResult(True, f"Minutka {minutes:g} min" + (" – i na hodinkách." if ok else " (hodinky nejsou připojené, zazvoní PC a telefon)."),
                          data=t)
    if action == "silent_alarm":
        try:
            job = phonex.schedule_silent_alarm(ctx, when or text)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"{job.get('title', 'Tichý budík')}: hodinky budou vibrovat, dokud neťukneš. Když nebudou "
                                "připojené, zazvoní telefon.", data=job)
    if action == "route":
        if not text:
            return ToolResult(False, "Kam to bude?")
        if not (lat or lon):
            return ToolResult(False, "Navigaci spusť z hodinek (Navigace → řekni cíl) – potřebuju jejich polohu.")
        try:
            r = await phonex.route(ctx, lat, lon, text)
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"Trasa nejde spočítat: {e}")
        if not r.get("ok"):
            return ToolResult(False, r.get("message", "Trasa nenalezena."))
        return ToolResult(True, f"{r['km']} km pěšky, asi {r['minutes']} min, {len(r['steps'])} odboček. Hodinky zavibrují před "
                                "každou: dvakrát doleva, třikrát doprava.", data=r)
    if action == "hr":
        rows = phonex.db(ctx).all("SELECT ts, bpm, ctx FROM phx_hr ORDER BY ts DESC LIMIT 1")
        if not rows:
            return ToolResult(False, "Zatím žádný tep – hodinky ho posílají, když je zapnuté spojení (aplikace JARVIS na hodinkách).")
        return ToolResult(True, f"Tep {rows[0]['bpm']}" + (" (při hře)" if rows[0]["ctx"] == "game" else ""), data=dict(rows[0]))
    if action == "stress":
        s = phonex.stress(ctx)
        if not s["hours"]:
            return ToolResult(True, "Dnes nemám z hodinek žádný tep.", data=s)
        worst = max((h for h in s["hours"] if h["level"] is not None), key=lambda h: h["level"], default=None)
        line = f"Nejvíc v {worst['hour']}:00 (úroveň {worst['level']}/100)." if worst else "Na odhad potřebuju pár dní tepu."
        return ToolResult(True, f"{line} {s['note']}", data=s)
    if action == "ble_hr":
        r = await phonex.ble_hr(ctx, text, seconds)
        return ToolResult(bool(r.get("ok")), r["message"], data=r)
    if action == "workout_add":
        try:
            w = phonex.add_workout(ctx, kind, minutes, km, note=text)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Zapsáno: {w['text']}.", data=w)
    if action == "workouts":
        ws = phonex.workouts(ctx, 30)
        return ToolResult(True, "\n".join(f"{phonex.KINDS.get(w['kind'], w['kind'])} {w['minutes']:.0f} min"
                                          + (f", {w['km']:.1f} km" if w["km"] else "") for w in ws) or "Žádné tréninky za 30 dní.", data=ws)
    if action == "week":
        return ToolResult(True, phonex.week_summary(ctx))
    snap = phonex.snapshot(ctx)
    return ToolResult(True, f"Hodinky {'připojené' if snap['watch'] else 'nepřipojené'}. {snap['workouts']}", data=snap)
