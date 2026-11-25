"""3.20 Práce+ (261–280) a Firma+ (281–300) tools."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from pathlib import Path
from typing import Literal

from .. import bizx, workx
from .base import ToolResult, tool

WORK_CHANGES = {"autoreply", "send_later", "sign"}     # change a mail account, send later, sign → ask first
BIZ_CHANGES = {"gdpr_delete", "team"}                  # delete someone's data, open a public link → ask first


@tool("work_kit", "Práce: hluboké soustředění (focus minutes, focus_end, focus_stats), pomodoro (pomodoro / pomodoro_stop), jen jedna věc "
      "(only text=„faktury“ / only_end), automatická odpověď (autoreply date=do kdy, text), poznámky z fotky (handwriting attachment), "
      "rychlá poznámka (note text, notes), odeslat ráno (send_later to+subject+text), výkaz (timesheet), 1:1 (one_on_one name), třídění "
      "pošty (triage), překlad Wordu (translate path+lang), prezentace z poznámek (slides text), psaní (write), hromadné koncepty (merge "
      "path=CSV, text=šablona), volný čas pro schůzku (slots date+minutes), nástěnka (board, board_add text, board_move id+col), časté "
      "dotazy (faq_add text+answer, faq text), konec dne (eod, eod_move), podpis PDF (sign path+attachment=podpis).", category="práce",
      danger_if=lambda a: a.get("action") in WORK_CHANGES)
async def work_kit(ctx, action: Literal["focus", "focus_end", "focus_stats", "pomodoro", "pomodoro_stop", "only", "only_end", "autoreply",
                                        "handwriting", "note", "notes", "send_later", "timesheet", "one_on_one", "triage", "translate", "slides",
                                        "write", "merge", "slots", "board", "board_add", "board_move", "faq_add", "faq", "eod", "eod_move", "sign"],
                   text: str = "", minutes: int = 0, date: str = "", attachment: str = "", to: str = "", subject: str = "", name: str = "",
                   path: str = "", lang: str = "en", id: int = 0, col: str = "", answer: str = "") -> ToolResult:  # noqa: A002
    port = ctx.cfg.phone.port
    today = dt.date.today()
    if action == "focus":
        r = await asyncio.to_thread(workx.deep_focus, ctx, minutes or 50)
        return ToolResult(True, f"Soustředění na {minutes or 50} min: telefon na Nerušit, upozornění počkají"
                          + (", rušivé weby blokované." if r["blocked"] else ". (Weby zablokuju jen se spuštěním jako správce.)"), data=r)
    if action == "focus_end":
        await asyncio.to_thread(workx.focus_end, ctx)
        return ToolResult(True, "Soustředění ukončeno.")
    if action == "focus_stats":
        st = workx.focus_stats(ctx)
        return ToolResult(True, "Za týden: " + (", ".join(f"{k} {v['minutes']} min ({v['sessions']}×)" for k, v in st.items()) or "nic."), data=st)
    if action == "pomodoro":
        p = workx.Pomodoro(minutes or 25)
        ctx.pomodoro = p
        st = p.start(time.time())
        ctx.bus.publish("countdown", until=st["until"], title=st["title"])
        return ToolResult(True, f"Pomodoro: {minutes or 25} min práce, pak 5 min pauza. Odpočet je v notchi.")
    if action == "pomodoro_stop":
        ctx.pomodoro = None
        ctx.bus.publish("countdown", until=0, title="")
        return ToolResult(True, "Pomodoro zastaveno.")
    if action == "only":
        ctx.focus_topic = text
        return ToolResult(True, f"Teď jen „{text}“ – ostatní upozornění počkají, dokud neřekneš „konec“.")
    if action == "only_end":
        held = list(getattr(ctx, "focus_held", []) or [])
        ctx.focus_topic, ctx.focus_held = "", []
        return ToolResult(True, f"Hotovo. Mezitím přišlo {len(held)} upozornění" + (": " + "; ".join(held[:5]) if held else "."))
    if action == "autoreply":
        until = dt.date.fromisoformat(date) if date else today + dt.timedelta(days=7)
        msg = text or workx.vacation_text(until, str(getattr(ctx.cfg.general, "user_name", "") or ""))
        done = await workx.set_autoreply(ctx, True, today, until, msg)
        return ToolResult(bool(done), f"Automatická odpověď do {until:%d. %m.} zapnutá ({', '.join(done)}); vypne se sama." if done
                          else "Nemám přístup ke Gmailu ani Outlooku (připoj je v Nastavení → Připojení). Text odpovědi: " + msg)
    if action == "handwriting":
        if not attachment:
            return ToolResult(False, "Vyfoť poznámky a pošli fotku.")
        parts = await ctx.store.llm_parts(attachment, vision=True)
        out = str(await ctx.router.complete([{"role": "user", "content": [*parts, {"type": "text", "text": workx.HANDWRITING_PROMPT}]}],
                                            need_vision=True)).strip()
        workx.quick_note(ctx, out)
        return ToolResult(True, out)
    if action == "note":
        r = workx.quick_note(ctx, text)
        return ToolResult(True, f"Poznámka uložena ({r['category']}).", data=r)
    if action == "notes":
        rows = [dict(r) for r in workx.db(ctx).all("SELECT * FROM wk_notes ORDER BY ts DESC LIMIT 20")]
        return ToolResult(True, "\n".join(f"[{r['category']}] {r['text'][:120]}" for r in rows) or "Žádné poznámky.")
    if action == "send_later":
        slot = workx.morning_slot(dt.datetime.now())
        if slot is None:
            return ToolResult(False, "Je pracovní doba – pošli to rovnou (email_send).")
        job = ctx.scheduler.add_once(slot, "send_mail", {"to": to, "subject": subject, "body": text}, title=f"E-mail {subject[:40]}")
        return ToolResult(True, f"E-mail odejde {slot:%d. %m. v %H:%M}.", data=job)
    if action == "timesheet":
        start = today - dt.timedelta(days=today.weekday())
        rows = workx.timesheet(ctx, start, today)
        return ToolResult(True, "\n".join(f"{r['project']}: {r['hours']} h" for r in rows) or "Výkaz je prázdný – nastav projekty v Nastavení → Práce.",
                          data=rows)
    if action == "one_on_one":
        mails = []
        try:
            from .mail_tools import _mail

            acc = _mail(ctx).account("")
            mails = await asyncio.to_thread(acc.list, False, 15, name)
        except Exception:  # noqa: BLE001
            pass
        board = [r["title"] for r in workx.db(ctx).all("SELECT title FROM wk_board WHERE col != 'done'") if workx.fold(name) in workx.fold(r["title"])]
        ctx_text = "\n".join(f"- {m.get('subject', '')}: {m.get('snippet', '')[:200]}" for m in mails[:12]) + "\n" + "\n".join(f"- úkol: {b}" for b in board)
        out = await ctx.router.complete([{"role": "user", "content": f"Připrav body na schůzku 1:1 s {name}: co je hotovo, co čeká, "
                                          "otázky, rozhodnutí. Krátké odrážky česky. Podklady:\n" + ctx_text[:6000]}])
        return ToolResult(True, str(out).strip())
    if action == "triage":
        try:
            from .mail_tools import _mail

            acc = _mail(ctx).account("")
            mails = await asyncio.to_thread(acc.list, True, 40, "")
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"Pošta teď nejde přečíst: {e}")
        groups: dict[str, list[str]] = {"reply": [], "read": [], "archive": []}
        for m in mails:
            groups[workx.triage(m)].append(f"{m.get('from_name') or m.get('from', '')}: {m.get('subject', '')}")
        return ToolResult(True, f"Odpovědět ({len(groups['reply'])}): " + "; ".join(groups["reply"][:6]) +
                          f"\nPřečíst ({len(groups['read'])}). Archivovat ({len(groups['archive'])}).", data=groups)
    if action == "translate":
        src = Path(path)
        if src.suffix.lower() != ".docx" or not src.is_file():
            return ToolResult(False, "Pošli soubor .docx (PDF převeď nejdřív do Wordu).")

        def tr(t: str) -> str:
            fut = asyncio.run_coroutine_threadsafe(ctx.router.complete([{"role": "user", "content": f"Přelož do jazyka {lang}. Vrať jen překlad:\n{t}"}],
                                                                       fast=True), loop)
            return str(fut.result(120)).strip()

        loop = asyncio.get_running_loop()
        dst = src.with_name(f"{src.stem}-{lang}.docx")
        n = await asyncio.to_thread(workx.translate_docx, src, dst, tr)
        return ToolResult(True, f"Přeloženo {n} odstavců se zachováním formátu: {dst}", data={"path": str(dst)})
    if action == "slides":
        outline = workx.parse_outline(text)
        if not outline:
            return ToolResult(False, "Pošli poznámky (nadpisy a odrážky).")
        from .. import paths

        dst = paths.sub("prezentace") / f"prezentace-{int(time.time())}.pptx"
        await asyncio.to_thread(workx.outline_to_pptx, outline, dst, name or outline[0]["title"])
        att = await ctx.store.save_path(dst, "application/vnd.openxmlformats-officedocument.presentationml.presentation")
        return ToolResult(True, f"Kostra prezentace má {len(outline)} snímků.", attachments=[att.id])
    if action == "write":
        ctx.platform.open_url(f"http://localhost:{port}/write")
        return ToolResult(True, "Otevřel jsem editor bez rozptýlení (F11 = celá obrazovka).")
    if action == "merge":
        try:
            rows = workx.merge_rows(Path(path).read_text(encoding="utf-8-sig"))
        except OSError:
            return ToolResult(False, "Pošli seznam jako CSV (se sloupci jméno, e-mail…).")
        from .. import paths

        folder = paths.sub("koncepty") / f"hromadne-{int(time.time())}"
        folder.mkdir(parents=True, exist_ok=True)
        missing = 0
        for i, r in enumerate(rows, 1):
            body = workx.merge(text, r)
            missing += "[chybí:" in body
            (folder / f"{i:03d}-{(r.get('email') or r.get('e-mail') or 'koncept')}.txt").write_text(body, encoding="utf-8")
        return ToolResult(True, f"{len(rows)} konceptů ve složce {folder} – nic jsem neodeslal. Zkontroluj je" +
                          (f" ({missing} mají chybějící údaje)." if missing else "."), data={"folder": str(folder)})
    if action == "slots":
        day = dt.date.fromisoformat(date) if date else today + dt.timedelta(days=1)
        from ..proactx import upcoming_events

        a = dt.datetime.combine(day, dt.time()).timestamp()
        busy = [(dt.datetime.fromtimestamp(float(e["start"])), dt.datetime.fromtimestamp(float(e["end"] or e["start"])))
                for e in upcoming_events(ctx, a, a + 86400)]
        slots = workx.free_slots(busy, day, minutes or 60)
        return ToolResult(True, f"{day:%d. %m.} volno: " + (", ".join(f"{s:%H:%M}" for s in slots[:8]) or "nic") +
                          ". (Kalendáře ostatních přidám, když mi pošleš jejich obsazenost.)", data=[s.isoformat() for s in slots])
    if action == "board":
        return ToolResult(True, f"Nástěnka: http://localhost:{port}/board")
    if action == "board_add":
        bid = workx.board_add(ctx, text, col or "todo", "ručně")
        return ToolResult(True, f"Na nástěnce (#{bid}).")
    if action == "board_move":
        return ToolResult(workx.board_move(ctx, id, col), "Přesunuto." if col in workx.COLS else "Sloupce: todo, doing, done.")
    if action == "faq_add":
        workx.faq_add(ctx, text, answer)
        return ToolResult(True, "Uloženo mezi časté dotazy.")
    if action == "faq":
        hit = workx.faq_find(ctx, text)
        return ToolResult(bool(hit), hit["answer"] if hit else "Na tohle odpověď uloženou nemám.", data=hit)
    if action == "eod":
        items = workx.open_items(ctx)
        return ToolResult(True, ("Rozdělané: \n" + "\n".join(items) + "\nŘekni „přesuň na zítra“.") if items else "Nic rozdělaného – hezký večer!")
    if action == "eod_move":
        n = workx.move_to_tomorrow(ctx)
        return ToolResult(True, f"Přesunuto na zítra: {n}.")
    sig = ctx.store.get(attachment) if attachment else None
    if not sig or not Path(path).is_file():
        return ToolResult(False, "Pošli PDF a obrázek podpisu (PNG s průhledným pozadím).")
    dst = Path(path).with_name(Path(path).stem + "-podepsano.pdf")
    await asyncio.to_thread(workx.sign_pdf, Path(path), Path(sig.path), dst)
    return ToolResult(True, f"Podepsáno obrázkem podpisu: {dst}. (Kvalifikovaný elektronický podpis potřebuje certifikát.)", data={"path": str(dst)})


@tool("biz_kit", "Firma: ověření firmy v ARES + DPH + insolvence (company text=IČO), rizika smlouvy (contract path), docházka (in name, out "
      "name, hours date=RRRR-MM), cash flow (cashflow amount=zůstatek, income, spend), směny (shifts text=JSON dostupnosti), reklamace "
      "(claim name+text, claims, claim_done id), GDPR (gdpr name, gdpr_delete name), dodavatelé (suppliers text=JSON), cestovní příkaz "
      "(travel_order text=JSON), marže (margin amount=cena, cost, fee, shipping), balíček pro účetní (accountant date), tým (team), "
      "smlouva ze šablony (contract_template kind=nda/dilo, text=IČO klienta + JSON), nábor (cv path, text=požadavky), nástup "
      "(onboard name, onboard_tick name+text), kurzový rozdíl (fx amount, currency, date=vystavení, date2=úhrada).", category="firma",
      danger_if=lambda a: a.get("action") in BIZ_CHANGES)
async def biz_kit(ctx, action: Literal["company", "contract", "in", "out", "hours", "cashflow", "shifts", "claim", "claims", "claim_done", "gdpr",
                                       "gdpr_delete", "suppliers", "travel_order", "margin", "accountant", "team", "contract_template", "cv",
                                       "onboard", "onboard_tick", "fx"],
                  text: str = "", name: str = "", path: str = "", amount: float = 0, income: float = 0, spend: float = 0, cost: float = 0,
                  fee: float = 0, shipping: float = 0, id: int = 0, date: str = "", date2: str = "", kind: str = "",  # noqa: A002
                  currency: str = "EUR") -> ToolResult:
    today = dt.date.today()
    if action == "company":
        try:
            a = await bizx.ares(ctx, text)
        except ValueError as e:
            return ToolResult(False, str(e))
        bits = [f"{a['name']}, {a['address']}" + (f", DIČ {a['dic']}" if a["dic"] else "") + (f" – ZANIKLA {a['ended']}" if a["ended"] else "")]
        if a["dic"]:
            try:
                v = await bizx.vat_status(ctx, a["dic"])
                if v.get("known"):
                    bits.append("NESPOLEHLIVÝ plátce DPH!" if v["unreliable"] else "spolehlivý plátce DPH" +
                                (f", zveřejněné účty: {', '.join(v['accounts'][:3])}" if v.get("accounts") else ""))
            except Exception as e:  # noqa: BLE001
                bits.append(f"registr DPH neodpověděl ({type(e).__name__})")
        try:
            i = await bizx.insolvency(ctx, text)
            bits.append(("V INSOLVENČNÍM REJSTŘÍKU: " + ", ".join(i.get("cases", []))) if i.get("found") else "v insolvenčním rejstříku není")
        except Exception as e:  # noqa: BLE001
            bits.append(f"insolvenční rejstřík neodpověděl ({type(e).__name__})")
        return ToolResult(True, ". ".join(bits) + ".", data=a)
    if action == "contract":
        p = Path(path)
        if not p.is_file():
            return ToolResult(False, "Pošli smlouvu (PDF, Word nebo text).")
        if p.suffix.lower() == ".pdf":
            from ..moneyx import pdf_text

            body = await asyncio.to_thread(pdf_text, p)
        elif p.suffix.lower() == ".docx":
            from docx import Document

            body = "\n".join(par.text for par in Document(str(p)).paragraphs)
        else:
            body = p.read_text(encoding="utf-8", errors="ignore")
        risks = bizx.contract_risks(body)
        return ToolResult(True, ("\n".join(f"⚠ {r['risk']}: {r['excerpt']}" for r in risks) if risks else "Obvyklá riziková místa jsem nenašel.")
                          + " (Orientační kontrola, ne právní rada.)", data=risks)
    if action == "in":
        try:
            bizx.clock_in(ctx, name)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"{name}: příchod {dt.datetime.now():%H:%M}.")
    if action == "out":
        try:
            h = bizx.clock_out(ctx, name)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"{name}: odchod, odpracováno {h} h.")
    if action == "hours":
        hs = bizx.hours(ctx, date or f"{today:%Y-%m}")
        return ToolResult(True, "\n".join(f"{p}: {h} h" for p, h in hs.items()) or "Žádná docházka.", data=hs)
    if action == "cashflow":
        rows = bizx.forecast(amount, income, spend)
        return ToolResult(True, " · ".join(f"{r['month']}: {bizx.kc(r['balance'])}" + (" ⚠" if r["low"] else "") for r in rows), data=rows)
    if action == "shifts":
        try:
            d = json.loads(text)
        except ValueError:
            return ToolResult(False, "Pošli JSON: {days: [po, út…], shifts: [ranní, odpolední], available: {Jana: [po-ranní…]}}.")
        r = bizx.plan_shifts(d["days"], d["shifts"], d["available"], int(d.get("need", 1)))
        return ToolResult(True, "\n".join(f"{k}: {', '.join(v) or '—'}" for k, v in r["plan"].items()) +
                          (f"\nNeobsazeno: {', '.join(r['gaps'])}" if r["gaps"] else ""), data=r)
    if action == "claim":
        cid = bizx.claim_add(ctx, name, text, date)
        return ToolResult(True, f"Reklamace #{cid} – vyřídit do {(dt.date.fromisoformat(date) if date else today) + dt.timedelta(days=30):%d. %m.}.")
    if action == "claims":
        rows = [dict(r) for r in bizx.db(ctx).all("SELECT * FROM bz_claims WHERE state != 'vyřízeno' ORDER BY received")]
        return ToolResult(True, "\n".join(f"#{r['id']} {r['customer']}: {r['item']} (od {r['received']})" for r in rows) or "Žádné otevřené reklamace.")
    if action == "claim_done":
        return ToolResult(bizx.claim_close(ctx, id, text), "Reklamace vyřízena.")
    if action == "gdpr":
        r = bizx.gdpr_find(ctx, name)
        return ToolResult(True, f"O „{name}“ mám: " + (", ".join(f"{k} ({len(v)})" for k, v in r["found"].items()) or "nic") +
                          f". Odpověz do 30 dnů. Zkontroluj i: {', '.join(r['elsewhere'])}.", data=r)
    if action == "gdpr_delete":
        n = bizx.gdpr_delete(ctx, name)
        return ToolResult(True, f"Smazáno {n} záznamů z JARVISe. Účetní doklady zákon nařizuje uchovat.")
    if action == "suppliers":
        try:
            rows = json.loads(text)
        except ValueError:
            return ToolResult(False, "Pošli JSON: [{item, supplier, price}, …].")
        best = bizx.compare_suppliers(rows)
        return ToolResult(True, "\n".join(f"{x['item']}: nejlevněji {x['best']} ({x['price']:.2f})" for x in best), data=best)
    if action == "travel_order":
        try:
            d = json.loads(text)
        except ValueError:
            return ToolResult(False, "Pošli JSON s name, start, end, dest, purpose, transport (km, rate_km).")
        from .. import paths, tripcare

        pd = tripcare.per_diem(ctx, d["start"], d["end"], d.get("country", "CZ"))
        pd["text"] = f"{pd['total']:,.0f} {pd['currency']}".replace(",", " ") if pd.get("ok") else pd.get("why", "")
        page = bizx.travel_order_html(d.get("name", ""), d["start"], d["end"], d.get("dest", ""), d.get("purpose", ""), d.get("transport", ""),
                                      pd, float(d.get("km", 0)), float(d.get("rate_km", 0)))
        out = paths.sub("firma") / f"cestovni-prikaz-{d['start'][:10]}.html"
        out.write_text(page, encoding="utf-8")
        return ToolResult(True, f"Cestovní příkaz: {out}", data={"path": str(out)})
    if action == "margin":
        m = bizx.margin(amount, cost, fee, shipping)
        return ToolResult(True, f"Bez DPH {m['net_price']:.2f} Kč, poplatky {m['fees']:.2f}, zisk {m['profit']:.2f} Kč = marže {m['margin_pct']} %.", data=m)
    if action == "accountant":
        from .. import paths

        month = date or f"{(today.replace(day=1) - dt.timedelta(days=1)):%Y-%m}"
        r = await asyncio.to_thread(bizx.accountant_pack, ctx, month, paths.sub("firma") / f"ucetni-{month}.zip")
        return ToolResult(True, f"Balíček pro účetní za {month}: {r['documents']} dokladů – {r['path']}", data=r)
    if action == "team":
        tok = bizx.team_create(ctx)
        base = str(getattr(ctx.cfg.phone_link, "public_url", "") or "").rstrip("/") or f"http://localhost:{ctx.cfg.phone.port}"
        return ToolResult(True, f"Týmové úkoly: {base}/team/{tok} – pošli odkaz kolegům.")
    if action == "contract_template":
        data: dict = {}
        if text and text.strip()[:1].isdigit():
            try:
                firm = await bizx.ares(ctx, text.split()[0])
                data.update(name=firm["name"], ico=firm["ico"], address=firm["address"])
            except ValueError as e:
                return ToolResult(False, str(e))
        c = ctx.cfg.bizx
        data.update(my_name=c.my_name, my_ico=c.my_ico, my_address=c.my_address)
        if "{" in text:
            data.update(json.loads(text[text.index("{"):]))
        try:
            doc = bizx.contract_from_template(kind or "nda", data)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, doc)
    if action == "cv":
        p = Path(path)
        if not p.is_file():
            return ToolResult(False, "Pošli životopis (PDF).")
        from ..moneyx import pdf_text

        body = await asyncio.to_thread(pdf_text, p) if p.suffix.lower() == ".pdf" else p.read_text(encoding="utf-8", errors="ignore")
        must = [w.strip() for w in text.split(",") if w.strip()]
        r = bizx.cv_score(body, must)
        return ToolResult(True, f"Shoda {r['score']} %. Má: {', '.join(r['has']) or '—'}. Chybí: {', '.join(r['missing']) or '—'}."
                          + (f" Praxe asi {r['years']} let." if r["years"] else ""), data=r)
    if action == "onboard":
        n = bizx.onboard_start(ctx, name)
        return ToolResult(True, f"Nástup {name}: {n} bodů kontrolního seznamu.")
    if action == "onboard_tick":
        r = bizx.onboard_tick(ctx, name, text)
        return ToolResult(bool(r["ticked"]), f"Hotovo: {r['ticked'] or '?'}. Zbývá {len(r['left'])}: " + "; ".join(r["left"][:4]), data=r)
    try:
        rate_a = await bizx.cnb_rate(ctx, currency, dt.date.fromisoformat(date))
        rate_b = await bizx.cnb_rate(ctx, currency, dt.date.fromisoformat(date2) if date2 else today)
    except (ValueError, KeyError) as e:
        return ToolResult(False, f"Kurz nejde zjistit: {e}")
    r = bizx.fx_difference(amount, rate_a, rate_b)
    return ToolResult(True, f"{amount:g} {currency}: při vystavení {r['issued_czk']:.2f} Kč, při úhradě {r['paid_czk']:.2f} Kč → {r['kind']} "
                      f"{abs(r['difference']):.2f} Kč.", data=r)
