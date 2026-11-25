"""3.20 Zdraví+ (241–260), Učení+ (361–380) a Rodina+ (381–400) tools."""
from __future__ import annotations

import datetime as dt
import json
from typing import Literal

from .. import familyx, healthx, learnx
from .base import ToolResult, tool

NOT_MEDICAL = " (Není to lékařská rada.)"


@tool("health_kit", "Zdraví: léky (med_set name+times=„8:00,20:00“+amount=zásoba, med_taken name, meds), dýchání v notchi (breathe "
      "text=klid/box/4-7-8), deník příznaků (symptom text+amount=síla, person), pro lékaře (doctor person, text=otázky), prevence "
      "(prevent person+kind+date), lékárnička (pharmacy_add name+date, pharmacy), horečka dítěte (fever person+amount=teplota, "
      "text=lék, dose), další dávka (next_dose person+text, weight), cviky (exercises), káva (coffee text), voda (water, water_week), "
      "pyl (pollen), karta pro nouzi do telefonu (ice), budík podle cyklů (cycle_alarm text=„23:30 6:30-7:00“), světlo u stolu (light).",
      category="zdraví")
async def health_kit(ctx, action: Literal["med_set", "med_taken", "meds", "breathe", "symptom", "doctor", "prevent", "pharmacy_add", "pharmacy",
                                          "fever", "next_dose", "exercises", "coffee", "water", "water_week", "pollen", "ice", "cycle_alarm",
                                          "light"],
                     name: str = "", text: str = "", times: str = "", amount: float = 0, person: str = "", kind: str = "", date: str = "",
                     dose: float = 0, weight: float = 0) -> ToolResult:
    today = dt.date.today()
    if action == "med_set":
        try:
            healthx.med_set(ctx, name, [t.strip() for t in times.split(",") if t.strip()], text, amount, 1, person)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"{name}: připomenu v {times}" + (f", zásoba {amount:g} ks." if amount else "."))
    if action == "med_taken":
        try:
            r = healthx.med_taken(ctx, name)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, "Zapsáno." + (f" Zásoba na {r['days_left']} dní." if r["days_left"] is not None else ""), data=r)
    if action == "meds":
        rows = [dict(r) for r in healthx.db(ctx).all("SELECT * FROM hl_meds ORDER BY person, name")]
        return ToolResult(True, "\n".join(f"{r['name']} ({', '.join(json.loads(r['times']))})" + (f" – {r['person']}" if r["person"] else "")
                                          + (f", zásoba {r['stock']:g}" if r["stock"] else "") for r in rows) or "Žádné léky.")
    if action == "breathe":
        b = healthx.breathing(text or "klid", amount or 2)
        ctx.bus.publish("breathe", **b)
        return ToolResult(True, f"Dýchej podle notche – {b['seconds'] // 60} min.")
    if action == "symptom":
        healthx.symptom_add(ctx, text or name, int(amount or 3), "", person)
        return ToolResult(True, "Zapsáno do zdravotního deníku.")
    if action == "doctor":
        qs = [q.strip() for q in text.split("?") if q.strip()]
        return ToolResult(True, healthx.doctor_brief(ctx, person, questions=[q + "?" for q in qs]))
    if action == "prevent":
        try:
            healthx.prevent_set(ctx, person or "já", kind, date or today.isoformat())
        except ValueError:
            return ToolResult(False, "Datum napiš jako RRRR-MM-DD.")
        return ToolResult(True, "Zapsáno – připomenu se včas.")
    if action == "pharmacy_add":
        try:
            healthx.pharmacy_set(ctx, name, date, int(amount or 1))
        except ValueError:
            return ToolResult(False, "Expiraci napiš jako RRRR-MM-DD.")
        return ToolResult(True, f"{name} do {date}.")
    if action == "pharmacy":
        r = healthx.pharmacy_check(ctx, today)
        bits = ([f"prošlé: {', '.join(r['expired'])}"] if r["expired"] else []) + ([f"brzy projde: {', '.join(r['soon'])}"] if r["soon"] else [])
        bits += [f"chybí: {', '.join(r['missing'])}"] if r["missing"] else []
        return ToolResult(True, "Lékárnička – " + ("; ".join(bits) if bits else "vše v pořádku") + ".", data=r)
    if action == "fever":
        try:
            healthx.fever_log(ctx, person or name, amount, text, dose)
        except ValueError as e:
            return ToolResult(False, str(e))
        warn = " Nad 39,5 °C nebo když je dítě apatické, volej lékaře." if amount >= 39.5 else ""
        return ToolResult(True, f"Zapsáno {amount:.1f} °C" + (f" a {text} {dose:g} mg" if text else "") + "." + warn)
    if action == "next_dose":
        try:
            r = healthx.next_dose(ctx, person or name, text, weight)
        except ValueError as e:
            return ToolResult(False, str(e))
        when = "teď můžeš" if r["now_ok"] else f"nejdřív v {dt.datetime.fromtimestamp(r['next_ts']):%H:%M}"
        return ToolResult(True, f"{r['med'].capitalize()}: {when} (za 24 h podáno {r['doses_24h']}×)" +
                          (f", obvyklá dávka asi {r['dose_mg']} mg" if r.get("dose_mg") else "") + f". {r['note']}", data=r)
    if action == "exercises":
        ex = healthx.exercise_set(3)
        return ToolResult(True, "\n".join(f"{e['name']}: {e['how']}" for e in ex))
    if action == "coffee":
        r = healthx.coffee(ctx, text or "káva")
        return ToolResult(True, f"Dnes {int(r['today'])} mg kofeinu." + (f" {r['warn']}" if r["warn"] else ""), data=r)
    if action == "water":
        n = healthx.water_add(ctx)
        return ToolResult(True, f"{n}. sklenice dnes.")
    if action == "water_week":
        w = healthx.water_week(ctx)
        return ToolResult(True, " · ".join(f"{d}: {n}" for d, n in w), data=w)
    if action == "pollen":
        from ..proactx import weather

        wx = weather(ctx) or {}
        if wx.get("lat") is None:
            return ToolResult(False, "Nevím, kde jsi – nastav město.")
        t = healthx.pollen_alert(await healthx.pollen(ctx, float(wx["lat"]), float(wx["lon"])), ctx.cfg.healthx.pollen or ["bříza", "trávy"], 20)
        return ToolResult(True, t or "Pylu tvých alergenů je dnes málo.")
    if action == "ice":
        card = healthx.ice_card(ctx)
        if not card:
            return ToolResult(False, "Vyplň krevní skupinu, alergie a kontakt v Nastavení → Zdraví.")
        ok = ctx.phone_push("ice_card", text=card)
        return ToolResult(ok, "Zdravotní karta je na zamčené obrazovce telefonu." if ok else "Telefon teď není připojený.")
    if action == "cycle_alarm":
        import re as _re

        m = _re.match(r"\s*(\d{1,2}:\d{2})\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", text)
        if not m:
            return ToolResult(False, "Napiš: kdy jdu spát a okno buzení, např. „23:30 6:30-7:00“.")
        now = dt.datetime.now()
        bed = dt.datetime.combine(today, dt.time.fromisoformat(m.group(1).zfill(5)))
        ws = dt.datetime.combine(today + dt.timedelta(days=1), dt.time.fromisoformat(m.group(2).zfill(5)))
        we = dt.datetime.combine(today + dt.timedelta(days=1), dt.time.fromisoformat(m.group(3).zfill(5)))
        if bed < now - dt.timedelta(hours=12):
            bed += dt.timedelta(days=1)
        at = healthx.cycle_alarm(bed, ws, we)
        job = ctx.scheduler.add_once(at, "voice_alarm", {}, title=f"Budík ve vhodné fázi {at:%H:%M}") if getattr(ctx, "scheduler", None) else None
        return ToolResult(True, f"Budík na {at:%H:%M} – konec spánkového cyklu (odhad podle 90min cyklů, ne podle měření).", data=job)
    import asyncio

    from .. import webcam

    try:
        frame = await asyncio.to_thread(webcam.grab, int(getattr(ctx.cfg.voice, "camera_index", 0) or 0))
        mean = tuple(float(x) for x in frame.reshape(-1, 3).mean(axis=0)[::-1])
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Kamera teď nejde použít: {e}")
    lum = healthx.luminance((mean[0], mean[1], mean[2]))
    return ToolResult(True, healthx.light_advice(lum) or "Světla máš dost.", data={"luminance": round(lum)})


@tool("learn_kit", "Učení: ladička a metronom (tuner), noty a akordy (chord text=Am7, scale text=D, kind=dur/moll), slovíčko (word "
      "text=en/de), konverzace v jazyce s opravami (practice text=en / stop), vysvětli jako dítěti / úkol / sloh / dějepis (mode "
      "kind=eli5/homework/essay/history), shrnutí videa (video url), psaní všemi deseti (typing), šachy (chess text=PGN), autoškola "
      "(driving n, answer), citace ISO 690 (cite text=JSON), hlavní města (capital n / answer+text=země), knihy (book_add text, "
      "book_note text+name=kniha, book_done name, books), rychločtení v notchi (rsvp text, n=slov/min), čtení s dítětem (read_check "
      "text=cílový text, answer=co přečetlo), peníze pro děti (money n).", category="učení")
async def learn_kit(ctx, action: Literal["tuner", "chord", "scale", "word", "practice", "mode", "video", "typing", "chess", "driving", "cite",
                                         "capital", "book_add", "book_note", "book_done", "books", "rsvp", "read_check", "money"],
                    text: str = "", kind: str = "", url: str = "", n: int = 0, answer: str = "", name: str = "") -> ToolResult:
    port = ctx.cfg.phone.port
    if action == "tuner":
        ctx.platform.open_url(f"http://localhost:{port}/learn/tuner")
        return ToolResult(True, "Otevřel jsem ladičku a metronom.")
    if action in ("chord", "scale"):
        try:
            notes = learnx.chord_notes(text) if action == "chord" else learnx.scale_notes(text, kind or "dur")
        except ValueError as e:
            return ToolResult(False, str(e))
        atts = []
        if action == "chord":
            att = await ctx.store.save(f"akord-{text}.wav", learnx.chord_wav(notes), "audio/wav")
            atts = [att.id]
        return ToolResult(True, f"{text}: {' – '.join(notes)}", data={"notes": notes}, attachments=atts)
    if action == "word":
        w = learnx.word_of_day(text or "en")
        return ToolResult(True, f"{w['word']} = {w['cs']}. Příklad: {w['example']}", data=w)
    if action == "practice":
        ctx.lang_practice = "" if text in ("", "stop", "konec") else text[:2]
        return ToolResult(True, "Dobře, mluvme – budu opravovat chyby." if ctx.lang_practice else "Trénink ukončen.")
    if action == "mode":
        rule = learnx.ask_rule(kind)
        if not rule:
            return ToolResult(False, "Režimy: eli5, homework, essay, history.")
        return ToolResult(True, rule, data={"rule": rule})
    if action == "video":
        try:
            lines = await learnx.youtube_transcript(url or text)
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"Přepis videa nejde získat: {e}")
        out = await ctx.router.complete([{"role": "user", "content": learnx.VIDEO_PROMPT + learnx.transcript_text(lines)}])
        return ToolResult(True, str(out).strip())
    if action == "typing":
        ctx.platform.open_url(f"http://localhost:{port}/learn/typing")
        rows = [dict(r) for r in learnx.db(ctx).all("SELECT * FROM ln_typing ORDER BY ts DESC LIMIT 10")]
        best = max((r["wpm"] for r in rows), default=0)
        return ToolResult(True, "Otevřel jsem trenažér." + (f" Tvůj rekord: {best:.0f} slov/min." if best else ""))
    if action == "chess":
        moves = " ".join(t for t in (text or "").replace("\n", " ").split() if not t.endswith(".") and not t.startswith(("[", "{")))
        if not moves:
            return ToolResult(False, "Pošli partii (PGN nebo tahy).")
        out = await ctx.router.complete([{"role": "user", "content": "Jsi šachový trenér. Rozeber tuto partii česky: 3–5 klíčových "
                                          "momentů s číslem tahu, co bylo chybou a proč, lepší tah a jedno obecné poučení. Bez šachového "
                                          "enginu – když si nejsi jistý, řekni to. Partie: " + moves[:4000]}])
        return ToolResult(True, str(out).strip())
    if action == "driving":
        if answer:
            ok, why = learnx.driving_check(n, answer)
            return ToolResult(ok, why)
        q = learnx.driving_question(n)
        return ToolResult(True, f"{q['q']}\n" + "\n".join(f"{i}) {o}" for i, o in enumerate(q["options"], 1)), data=q)
    if action == "cite":
        try:
            d = json.loads(text)
        except ValueError:
            return ToolResult(False, "Údaje pošli jako JSON: {kind: book/article/web, authors: […], title, year, …}.")
        kw = {k: str(v) for k, v in d.items() if k not in ("kind", "authors")}
        return ToolResult(True, learnx.iso690(d.get("kind", "book"), list(d.get("authors") or []), **kw))
    if action == "capital":
        if answer:
            ok, why = learnx.capital_check(text, answer)
            return ToolResult(ok, why)
        country, _cap = learnx.capital_question(n)
        return ToolResult(True, f"Jaké je hlavní město: {country}?", data={"country": country})
    if action == "book_add":
        learnx.book_add(ctx, text, name)
        return ToolResult(True, f"Přidáno do čtenářského deníku: {text}.")
    if action == "book_note":
        ok = learnx.book_note(ctx, name, text, quote=kind == "quote")
        return ToolResult(ok, "Poznámka uložena." if ok else "Takovou knihu nemám.")
    if action == "book_done":
        ok = learnx.book_done(ctx, name or text, n)
        return ToolResult(ok, "Dočteno – zapsáno." if ok else "Takovou knihu nemám.")
    if action == "books":
        rows = [dict(r) for r in learnx.db(ctx).all("SELECT * FROM ln_books ORDER BY id DESC LIMIT 30")]
        return ToolResult(True, "\n".join(f"{r['title']} – {r['author'] or '?'} ({r['status']})" + (f" {'★' * r['rating']}" if r["rating"] else "")
                                          for r in rows) or "Deník je prázdný.")
    if action == "rsvp":
        r = learnx.rsvp_words(text, n or 300)
        ctx.bus.publish("rsvp", words=r["words"], ms=r["ms"])
        return ToolResult(True, f"Čti v notchi – asi {r['minutes']} min.")
    if action == "read_check":
        r = learnx.reading_check(text, answer)
        hard = ", ".join(f"{w} ({learnx.syllables(w)})" for w in r["hard"])
        return ToolResult(True, f"Přečteno na {r['ok']} %." + (f" Těžká slova: {hard}." if hard else " Výborně, bez chyby!"), data=r)
    les = learnx.money_lesson(n)
    return ToolResult(True, f"Lekce {les['n']}/{les['of']}: {les['title']}\n{les['text']}", data=les)


@tool("family_kit", "Rodina: členové a barvy (member name, kind=dítě), kalendář (calendar), úkoly dětí za body (chore name=dítě+text+n, "
      "chore_done name+text, points name), jídelníček a nákup (menu n=lidí, text=co rádi), recept hlasem (recipe text / next / repeat), "
      "lednice (fridge_add text+date, fridge, fridge_remove text), rostliny (plant text+kind=druh, watered text, plants), péče o "
      "mazlíčka / dům / rodiče (care name=kdo+kind=pet/dum/rodic+text+n=dní, care_done n, house_defaults, parent name), rozvrh dětí "
      "(schedule name+day+time+text+who), pohádka (story name+n=věk+text), pravidla pro děti (rules), úklid (cleaning text=lidé, kind="
      "úkoly), Wi-Fi QR pro hosty (wifi), karta pro hlídání (babysitter), kronika (chronicle), svoz odpadu (waste text=popelnice+day+n).",
      category="domácnost")
async def family_kit(ctx, action: Literal["member", "calendar", "chore", "chore_done", "points", "menu", "recipe", "next", "repeat", "fridge_add",
                                          "fridge", "fridge_remove", "plant", "watered", "plants", "care", "care_done", "house_defaults", "parent",
                                          "schedule", "story", "rules", "cleaning", "wifi", "babysitter", "chronicle", "waste"],
                     name: str = "", text: str = "", kind: str = "", n: int = 0, date: str = "", day: str = "", time: str = "",
                     who: str = "") -> ToolResult:
    today = dt.date.today()
    if action == "member":
        c = familyx.member_add(ctx, name, kind in ("dítě", "dite", "kid"))
        return ToolResult(True, f"{name} má v kalendáři barvu {c}.")
    if action == "calendar":
        return ToolResult(True, f"Rodinný kalendář: http://localhost:{ctx.cfg.phone.port}/family-calendar")
    if action == "chore":
        familyx.chore_add(ctx, name, text, n or 5)
        return ToolResult(True, f"{name}: {text} za {n or 5} bodů.")
    if action == "chore_done":
        try:
            r = familyx.chore_done(ctx, name, text)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Hotovo! {name} má {r['points']} bodů.")
    if action == "points":
        return ToolResult(True, f"{name}: {familyx.points(ctx, name)} bodů.")
    if action == "menu":
        have = [r["item"] for r in familyx.fridge(ctx, today)["items"]]
        out = await ctx.router.complete([{"role": "user", "content": familyx.menu_prompt(n or 2, text, kind, have)}])
        try:
            m = familyx.parse_menu(str(out))
        except ValueError as e:
            return ToolResult(False, str(e))
        from .list_tools import add_items

        add_items(ctx, "nákup", m["shopping"])
        lines = [f"{d.get('day', '')}: {d.get('lunch', '')} / {d.get('dinner', '')}" for d in m["days"]]
        return ToolResult(True, "\n".join(lines) + f"\nNákup ({len(m['shopping'])} položek) jsem dal do seznamu „nákup“.", data=m)
    if action in ("recipe", "next", "repeat"):
        if action == "recipe":
            steps = familyx.recipe_steps(text)
            if not steps:
                return ToolResult(False, "Pošli recept s postupem.")
            ctx.recipe = familyx.Recipe(steps)
        rec = getattr(ctx, "recipe", None)
        if rec is None:
            return ToolResult(False, "Nejdřív mi dej recept.")
        st = rec.repeat() if action == "repeat" else rec.next()
        if st is None:
            ctx.recipe = None
            return ToolResult(True, "To byl poslední krok – dobrou chuť!")
        if st["timer"]:
            ctx.timers.add(st["timer"], f"Recept krok {st['n']}")
        return ToolResult(True, f"Krok {st['n']} z {st['of']}: {st['text']}" + (" (minutka běží)" if st["timer"] else "") + " – řekni „další“.")
    if action == "fridge_add":
        try:
            familyx.fridge_add(ctx, text, date)
        except ValueError:
            return ToolResult(False, "Datum spotřeby napiš jako RRRR-MM-DD.")
        return ToolResult(True, f"{text} do {date}.")
    if action == "fridge":
        f = familyx.fridge(ctx, today)
        return ToolResult(True, "\n".join(f"{r['item']} do {r['until']}" for r in f["items"]) or "Lednice je v seznamu prázdná.", data=f)
    if action == "fridge_remove":
        return ToolResult(familyx.fridge_remove(ctx, text), "Odebráno.")
    if action == "plant":
        d = familyx.plant_add(ctx, text, kind)
        return ToolResult(True, f"{text}: zalévat každých {d} dní.")
    if action == "watered":
        return ToolResult(familyx.plant_watered(ctx, text), "Zapsáno.")
    if action == "plants":
        due = familyx.plants_due(ctx, today)
        return ToolResult(True, ("Zalij: " + ", ".join(due)) if due else "Všechny rostliny mají dost vody.")
    if action == "care":
        cid = familyx.care_add(ctx, name, kind or "pet", text, n or 365, date, time)
        return ToolResult(True, f"Zapsáno (#{cid}).")
    if action == "care_done":
        return ToolResult(familyx.care_done(ctx, n), "Hotovo, další termín je naplánovaný.")
    if action == "house_defaults":
        k = familyx.house_defaults(ctx)
        return ToolResult(True, f"Přidáno {k} úkolů údržby domu (filtry, kotel, komín, detektory…).")
    if action == "parent":
        return ToolResult(True, "\n".join(familyx.parent_status(ctx, name, today)))
    if action == "schedule":
        try:
            familyx.schedule_add(ctx, name, familyx.weekday_of(day), time, text, who)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"{name}: {day} {time} {text}" + (f", veze {who}" if who else "") + ".")
    if action == "story":
        out = await ctx.router.complete([{"role": "user", "content": familyx.story_prompt(name or "dítě", n or 6, text)}])
        return ToolResult(True, str(out).strip())
    if action == "rules":
        r = ctx.cfg.familyx.kid_rules
        return ToolResult(True, familyx.kid_rules_text(r) or "Pravidla nastavíš v Nastavení → Rodina (od kdy hry, do kdy obrazovky, kolik minut).")
    if action == "cleaning":
        people = [p.strip() for p in text.split(",") if p.strip()]
        chores = [c.strip() for c in kind.split(",") if c.strip()] or ["vysávání", "koupelna", "kuchyň", "prach", "koše"]
        plan = familyx.chores_rotation(people, chores, today.isocalendar()[1])
        return ToolResult(bool(plan), "\n".join(f"{p}: {', '.join(c) or '—'}" for p, c in plan.items()) or "Pro koho?", data=plan)
    if action == "wifi":
        import asyncio

        from .. import moneyx, paths, pcx

        ssid, pw = text, ""
        if pcx.WIN:
            try:
                out = await asyncio.to_thread(pcx.run, ["netsh", "wlan", "show", "profiles"], 30)
                nets = pcx.wifi_profiles(out.stdout)
                ssid = next((x for x in nets if text and pcx.fold(text) in pcx.fold(x)), text or (nets[0] if nets else ""))
                if ssid:
                    k = await asyncio.to_thread(pcx.run, ["netsh", "wlan", "show", "profile", f"name={ssid}", "key=clear"], 30)
                    pw = pcx.wifi_key(k.stdout)
            except Exception:  # noqa: BLE001
                pass
        if kind:                                        # the guest network's password said aloud / typed
            pw = kind
        if not ssid:
            return ToolResult(False, "Jak se síť jmenuje?")
        png = moneyx.qr_png(familyx.wifi_qr_text(ssid, pw), paths.sub("qr") / "wifi-host.png")
        att = await ctx.store.save_path(png, "image/png")
        return ToolResult(True, f"QR pro Wi-Fi „{ssid}“ – host ji naskenuje fotoaparátem.", attachments=[att.id])
    if action == "babysitter":
        from .. import paths

        kids = [m for m in familyx.members(ctx) if m["kid"]]
        info = json.loads(text) if text.startswith("{") else {}
        page = familyx.babysitter_html([{"name": k["name"], "age": info.get("ages", {}).get(k["name"], ""), "allergies": info.get("allergies", {}).get(k["name"], "")}
                                        for k in kids], info.get("contacts", []), info.get("rules", []),
                                       [f"{r['kid']}: {familyx.WEEKDAYS[r['weekday']]} {r['start']} {r['what']}"
                                        for r in familyx.db(ctx).all("SELECT * FROM fm_schedule ORDER BY weekday, start")])
        out = paths.sub("rodina") / "karta-pro-hlidani.html"
        out.write_text(page, encoding="utf-8")
        return ToolResult(True, f"Karta pro hlídání: {out} (vytiskni ji).", data={"path": str(out)})
    if action == "chronicle":
        from .. import memx, paths

        years: dict[int, list[dict]] = {}
        for e in memx.timeline(ctx):
            try:
                y = int(str(e["date"])[:4])
            except ValueError:
                continue
            years.setdefault(y, []).append({"date": e["date"], "text": f"{e['kind']}: {e['text']}"})
        out = paths.sub("rodina") / "kronika.html"
        out.write_text(familyx.chronicle_html(name or "", years), encoding="utf-8")
        return ToolResult(True, f"Kronika: {out}", data={"path": str(out)})
    bins = {"smesny": "smesny", "směsný": "smesny", "papír": "papir", "papir": "papir", "plast": "plast", "bio": "bio", "sklo": "sklo"}
    if text:
        try:
            familyx.waste_set(ctx, bins.get(text.lower(), text.lower()), familyx.weekday_of(day), n or 1, today.isocalendar()[1] % max(1, n or 1))
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"{text}: {day}" + (f" každý {n}. týden (počínaje tímto)" if n and n > 1 else " každý týden") + ". Večer předem připomenu.")
    t = familyx.waste_tomorrow(ctx, today)
    return ToolResult(True, ("Zítra: " + ", ".join(t)) if t else "Zítra se nic nevyváží.")
