"""3.20 Paměť+ (41–60) and Proaktivita+ (61–80) tools."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

from .. import memx, proactx
from .base import ToolResult, tool


@tool("memory_kit", "Paměť: wiki všeho, co o tobě ví (wiki), oprava faktu (edit, id, text), zapomenout i ze záloh (forget_all, text), "
      "přání blízkých jako tipy na dárky (wish_add person+text, wishes), časová osa života (timeline, year), odkud něco ví (origin), "
      "výročí a narozeniny (date_add text, dates), kam jsem dal věc (put text) a kde je (where text), doporučení od lidí (rec_add, recs), "
      "vzpomínka s fotkou (photo, attachment), sdílet s rodinou (share/unshare), rok v kostce (year), deník (diary_add, diary), "
      "fotky podle místa a lidí (photos_index folder, photos_search query), oblíbené odpovědi (favorites), dočasná vzpomínka "
      "(until text), citlivé údaje v paměti (sensitive), soukromé pod PINem (set_pin, lock, unlock), poslat vzpomínku (send).",
      category="paměť")
async def memory_kit(ctx, action: Literal["wiki", "edit", "forget_all", "wish_add", "wishes", "timeline", "origin", "date_add", "dates",
                                          "put", "where", "rec_add", "recs", "photo", "share", "unshare", "year", "diary_add", "diary",
                                          "photos_index", "photos_search", "favorites", "until", "sensitive", "set_pin", "lock",
                                          "unlock", "send", "sync"],
                     text: str = "", person: str = "", id: int = 0, year: int = 0, query: str = "", folder: str = "",  # noqa: A002
                     attachment: str = "", pin: str = "", to: str = "") -> ToolResult:
    if action == "wiki":
        p = memx.write_wiki(ctx)
        n = sum(len(v) for v in memx.wiki_pages(ctx).values())
        return ToolResult(True, f"Wiki s {n} věcmi, které o tobě vím: {p}", data={"path": str(p)}, attachments=[])
    if action == "edit":
        ok = memx.edit_fact(ctx, id, text)
        return ToolResult(ok, f"Opraveno: #{id} = {text}" if ok else f"Fakt #{id} neznám.")
    if action == "forget_all":
        try:
            r = memx.forget_everywhere(ctx, text)
        except ValueError as e:
            return ToolResult(False, str(e))
        if not r["deleted"]:
            return ToolResult(False, f"Nic jako „{text}“ si nepamatuju.")
        return ToolResult(True, f"Zapomenuto ({len(r['deleted'])}×), i v zálohách ({r['in_backups']}×). Po obnovení zálohy se to nevrátí.",
                          data=r)
    if action == "wish_add":
        if not person or not text:
            return ToolResult(False, "Kdo a co by chtěl?")
        memx.add_wish(ctx, person, text, "rozhovor")
        return ToolResult(True, f"Zapsáno jako tip na dárek pro {person}: {text}.")
    if action == "wishes":
        w = memx.wishes(ctx, person)
        return ToolResult(True, "\n".join(f"{x['person']}: {x['item']}" for x in w) or "Žádná přání zatím nemám.", data=w)
    if action == "timeline":
        tl = memx.timeline(ctx, year or None)
        if not tl:
            return ToolResult(True, "Na časové ose zatím nic není – deník, cesty a fotky ji naplní.")
        return ToolResult(True, "\n".join(f"{e['date']} · {e['kind']}: {e['text']}" for e in tl[-60:]), data=tl)
    if action == "origin":
        o = memx.origin(ctx, query or text)
        if not o:
            return ToolResult(True, "Nic takového si nepamatuju.")
        return ToolResult(True, "\n".join(f"#{x['id']} „{x['text']}“ – {x['when']}, {x['source']}" + (f" (řekl jsi: „{x['said']}“)" if x["said"] else "")
                                          for x in o), data=o)
    if action == "date_add":
        p = proactx.parse_deadline(text) if text else None
        if not p:
            return ToolResult(False, "Potřebuju název a datum, třeba „výročí svatby 12. 6. 2015“.")
        title, day, _ = p
        kind = "narozeniny" if "narozenin" in memx.fold(text) else "výročí"
        year_m = memx.DATE_FACT.search(text)
        memx.add_date(ctx, title, day.day, day.month, int(year_m.group("y")) if year_m and year_m.group("y") else None, kind,
                      person or "")
        return ToolResult(True, f"Budu hlídat: {title} ({day.day}. {day.month}.) – týden a den předem ti dám vědět.")
    if action == "dates":
        memx.dates_from_facts(ctx)
        up = memx.upcoming_dates(ctx, 60)
        return ToolResult(True, " ".join(memx.date_line(e, ctx) for e in up) or "Žádná výročí v příštích 60 dnech.", data=up)
    if action == "put":
        r = memx.put(ctx, text)
        return ToolResult(bool(r), f"Zapamatováno: {r[0]} – {r[1]}." if r else "Nerozumím, co a kam jsi dal.")
    if action == "where":
        return ToolResult(True, memx.where_is(ctx, text) or "Nerozumím, co hledáš.")
    if action == "rec_add":
        r = memx.add_rec(ctx, text)
        return ToolResult(bool(r), f"Zapsáno: {r['kind']} „{r['title']}“ (doporučil {r['by']})." if r else "Nerozumím doporučení.")
    if action == "recs":
        rs = memx.recs(ctx, query or text)
        return ToolResult(True, "\n".join(f"{r['kind']}: {r['title']} (od {r['by']})" for r in rs) or "Zatím žádná doporučení.", data=rs)
    if action == "photo":
        if not attachment:
            return ToolResult(False, "Pošli mi k tomu fotku.")
        fid = memx.photo_memory(ctx, text, attachment)
        return ToolResult(True, "Zapamatováno i s fotkou.", data={"id": fid})
    if action in ("share", "unshare"):
        n = memx.share_fact(ctx, text, action == "share")
        return ToolResult(bool(n), (f"Sdíleno s rodinou ({n})." if action == "share" else f"Už jen pro tebe ({n}).") if n else "Nic takového nevím.")
    if action == "year":
        y = year or dt.date.today().year
        return ToolResult(True, await memx.year_story(ctx, y))
    if action == "diary_add":
        memx.diary_add(ctx, text)
        return ToolResult(True, "Zapsáno do deníku.")
    if action == "diary":
        d = memx.diary(ctx, query or text)
        return ToolResult(True, "\n".join(f"{x['day']}: {x['text']}" for x in d) or "V deníku zatím nic není.", data=d)
    if action == "photos_index":
        root = Path(folder).expanduser() if folder else Path.home() / "Pictures"
        if not root.is_dir():
            return ToolResult(False, f"Složku {root} nenacházím.")
        r = await memx.index_photos(ctx, root)
        return ToolResult(True, f"Prošel jsem {r['seen']} fotek, nových {r['new']}. Teď je najdu podle místa, lidí a data.", data=r)
    if action == "photos_search":
        ph = memx.search_photos(ctx, query or text)
        if not ph:
            return ToolResult(True, "Žádné takové fotky nenacházím (nejdřív „projdi moje fotky“).")
        return ToolResult(True, f"Našel jsem {len(ph)} fotek: " + ", ".join(Path(p["path"]).name for p in ph[:10]),
                          data=[{"path": p["path"], "place": p["place"], "taken": p["taken"]} for p in ph])
    if action == "favorites":
        fv = memx.favorites(ctx, query or text)
        return ToolResult(True, "\n\n".join(f"★ {f['text'][:400]}" for f in fv[:10]) or "Zatím nemáš žádné oblíbené odpovědi (★ u zprávy).",
                          data=fv)
    if action == "until":
        p = memx.parse_until(text)
        if not p:
            return ToolResult(False, "Do kdy si to mám pamatovat?")
        what, at = p
        memx.remember_until(ctx, what, at)
        return ToolResult(True, f"Zapamatováno do {at:%d. %m.}, pak to zapomenu: {what}")
    if action == "sensitive":
        hits = memx.sensitive_scan(ctx)
        if not hits:
            return ToolResult(True, "V paměti nemám žádná čísla karet, hesla ani rodná čísla.")
        return ToolResult(True, "Citlivé údaje v paměti: " + "; ".join(f"#{h['id']} {h['kind']}: {h['text']}" for h in hits) +
                          ". Řekni „zapomeň #číslo“, nebo „zamkni #číslo“ pod PIN.", data=hits)
    if action == "set_pin":
        try:
            memx.set_pin(ctx, pin)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, "PIN pro soukromou paměť je nastavený.")
    if action == "lock":
        try:
            n = memx.lock_fact(ctx, text or str(id))
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(bool(n), f"Zamčeno ({n}) – bez PINu to nikde neuvidíš ani neřeknu." if n else "Nic takového nevím.")
    if action == "unlock":
        ok = memx.unlock(ctx, pin)
        return ToolResult(ok, f"Odemčeno na {memx.UNLOCK_S // 60} minut." if ok else "Špatný PIN.")
    if action == "sync":                                  # (60) the same memory on your other PCs
        from .. import nodes

        targets = [n for n in nodes.nodes(ctx) if not to or nodes._fold(n["name"]) == nodes._fold(to)]
        if not targets:
            return ToolResult(False, "Nemám žádný další počítač s JARVISem (Nastavení → Domov → Další počítače).")
        out = []
        for n in targets:
            try:
                r = await memx.sync_node(ctx, n)
                out.append(f"{n['name']}: tam +{r['sent_added']}, sem +{r['got_added']}")
            except Exception as e:  # noqa: BLE001
                out.append(f"{n['name']}: nepovedlo se ({e})")
        return ToolResult(True, "Paměť sjednocena – " + "; ".join(out) + ".")
    if not to or not (text or id):
        return ToolResult(False, "Komu a co mám poslat?")
    body = text
    if id:
        r = ctx.db.one("SELECT text, locked FROM facts WHERE id=?", (int(id),))
        if not r or (r["locked"] and not memx.unlocked(ctx)):
            return ToolResult(False, f"Vzpomínku #{id} nemám (nebo je zamčená).")
        body = r["text"]
    from .phone_link_tools import whatsapp_message

    return await whatsapp_message(ctx, to, body)


@tool("day_kit", "Den a rutiny: termíny STK, pojištění, pasu, faktur (deadline_add text, deadlines, deadline_remove id), nemocenský den "
      "(sick_day), kontrola před dovolenou (vacation_check), uzávěrka měsíce (month_close), návrh týdne (week_plan), sušení prádla "
      "(laundry), víkendová předpověď (weekend), svátky a zavřené obchody (holidays), sezónní úkoly (seasonal, seasonal_done key), "
      "kamarádi, kterým se ozvat (friend_add name+days, friend_contact name, friends), které rutiny používáš (routines), "
      "konec pracovního dne (end_of_day).", category="proaktivní")
async def day_kit(ctx, action: Literal["deadline_add", "deadlines", "deadline_remove", "sick_day", "vacation_check", "month_close",
                                       "week_plan", "laundry", "weekend", "holidays", "seasonal", "seasonal_done", "friend_add",
                                       "friend_contact", "friends", "routines", "end_of_day"],
                  text: str = "", name: str = "", days: int = 60, id: int = 0, key: str = "") -> ToolResult:  # noqa: A002
    if action == "deadline_add":
        p = proactx.parse_deadline(text)
        if not p:
            return ToolResult(False, "Potřebuju co a do kdy, třeba „STK do 3. 4. 2027“.")
        proactx.add_deadline(ctx, *p)
        return ToolResult(True, f"Hlídám: {p[0]} do {p[1]:%d. %m. %Y} – ozvu se týden a den předem.")
    if action == "deadlines":
        proactx.deadlines_from_facts(ctx)
        d = proactx.deadlines(ctx)
        return ToolResult(True, "\n".join(f"#{r['id']} {r['title']} – {dt.date.fromisoformat(r['day']):%d. %m. %Y}" for r in d)
                          or "Žádné termíny nehlídám.", data=d)
    if action == "deadline_remove":
        ok = proactx.db(ctx).exec("DELETE FROM px_deadlines WHERE id=?", (int(id),)).rowcount > 0
        return ToolResult(ok, "Smazáno." if ok else "Takový termín nemám.")
    if action == "sick_day":
        r = await proactx.sick_day(ctx)
        ev = "; ".join(r["events"]) if r["events"] else "dnes nemáš nic v kalendáři"
        return ToolResult(True, f"Brzy se uzdrav. Ztišil jsem upozornění na celý den, připomenu pití. Dnešní plán: {ev} – "
                                "mám někomu napsat omluvu?", data=r)
    if action == "vacation_check":
        items = await proactx.vacation_check(ctx)
        return ToolResult(True, "\n".join(f"{s} {t}" for s, t in items), data=items)
    if action == "month_close":
        return ToolResult(True, await proactx.month_close(ctx))
    if action == "week_plan":
        return ToolResult(True, await proactx.week_plan(ctx))
    if action in ("laundry", "weekend"):
        if not proactx.weather(ctx):
            await proactx.refresh_weather(ctx)
        s = proactx.laundry_window(ctx) if action == "laundry" else proactx.weekend_forecast(ctx)
        return ToolResult(True, s or ("Dnes to na sušení venku moc není." if action == "laundry" else "Předpověď na víkend zatím nemám."))
    if action == "holidays":
        today = dt.date.today()
        hol = sorted((d, n) for d, n in {**proactx.cz_holidays(today.year), **proactx.cz_holidays(today.year + 1)}.items() if d >= today)[:5]
        return ToolResult(True, "; ".join(f"{d:%d. %m.} {n}" + (f" (obchody zavřené {proactx.shops_closed(d)})" if proactx.shops_closed(d) else "")
                                          for d, n in hol))
    if action == "seasonal":
        due = proactx.seasonal_due(ctx)
        return ToolResult(True, "\n".join(f"{k}: {t}" for k, t in due) or "Teď nic sezónního nečeká.", data=due)
    if action == "seasonal_done":
        proactx.seasonal_mark(ctx, key or text)
        return ToolResult(True, "Odškrtnuto pro letošek.")
    if action == "friend_add":
        proactx.friend_add(ctx, name or text, days)
        return ToolResult(True, f"Když se {name or text} {days} dní neozveš, připomenu ti to.")
    if action == "friend_contact":
        ok = proactx.friend_contact(ctx, name or text)
        return ToolResult(True, "Zapsáno." if ok else f"Zapsáno ({name or text} ale nemám v seznamu kamarádů).")
    if action == "friends":
        return ToolResult(True, " ".join(proactx.friends_overdue(ctx)) or "Se všemi jsi v kontaktu.")
    if action == "routines":
        r = proactx.routines_report(ctx)
        parts = []
        if r["used"]:
            parts.append("Používáš: " + ", ".join(r["used"]))
        if r["idle"]:
            parts.append("Měsíc se nespustily: " + ", ".join(r["idle"]) + " – vypnout je?")
        if r["off"]:
            parts.append("Vypnuté: " + ", ".join(r["off"]))
        return ToolResult(True, ". ".join(parts) or "Zatím nemáš žádné rutiny.", data=r)
    return ToolResult(True, await proactx.end_of_day(ctx))
