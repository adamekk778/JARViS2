"""OMEGA wave 29 by voice: running the business – quotes register, billing basis, customer requests, supplier offers,
campaigns, and income / expenses from a bank statement."""
from __future__ import annotations

import asyncio
import re
import time
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .files import resolve


def _kc(x) -> str:
    from ..business import _kc as k

    return k(x)


@tool("quotes_overview", "Přehled cenových nabídek: kolik je otevřených a za kolik, které brzy propadnou, kolik se přijalo, "
      "úspěšnost, průměrná zakázka a doba rozhodnutí, nejlepší klienti.", category="byznys")
async def quotes_overview(ctx) -> ToolResult:
    from .. import bizops

    r = bizops.quotes_overview(ctx)
    if not r["recent"]:
        return ToolResult(True, "Zatím žádná nabídka – vytvoř ji příkazem „udělej nabídku pro…“.", data=r)
    msg = f"Otevřené: {r['open']} za {_kc(r['open_value'])}"
    if r["expiring"]:
        msg += "; brzy propadnou: " + ", ".join(f"{x['number']} {x['client']} ({x['days']} d)" for x in r["expiring"][:4])
    if r["win_rate"] is not None:
        msg += f"; úspěšnost {r['win_rate']:g} % ({r['won']} přijatých za {_kc(r['won_value'])})"
    return ToolResult(True, msg + ".", data=r)


@tool("quote_status", "Zapíše, jak dopadla nabídka: přijatá / odmítnutá (podle čísla nabídky nebo jména klienta).", category="byznys")
async def quote_status(ctx, which: Annotated[str, "číslo N-RRRR-NNNN nebo jméno klienta"], status: Annotated[str, "přijatá / odmítnutá / zrušená"]) -> ToolResult:
    from .. import bizops

    try:
        r = bizops.set_quote_status(ctx, which, status)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Nabídka {r['number']} ({r['client']}, {_kc(r['total'])}) je {r['status']}.", data=r)


@tool("billing_basis", "Podklad k fakturaci z výkazu práce (CSV: datum, klient, projekt, hodiny, sazba, popis, náklady, "
      "fakturováno): po klientech hodiny × sazba, přefakturované náklady, DPH a co se dělalo; jen dosud nevyfakturované.",
      category="byznys", perm="files_read")
async def billing_basis(ctx, file: str, client: str = "", period: Annotated[str, "RRRR-MM nebo RRRR"] = "", default_rate: float = 0,
                        vat_pct: float = 21, vat_payer: bool = True, documents: bool = True) -> ToolResult:
    from .. import bizops

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Výkaz neexistuje: {p}")
    try:
        r = await asyncio.to_thread(bizops.billing, p, client, period, default_rate, vat_pct, vat_payer)
    except ValueError as e:
        return ToolResult(False, str(e))
    if not r["clients"]:
        return ToolResult(True, "Nic k fakturaci" + (f" ({r['skipped_billed']} řádků už vyfakturováno)" if r["skipped_billed"] else "") + ".", data=r)
    files = []
    if documents:
        d = paths.data_dir() / "fakturace"
        d.mkdir(parents=True, exist_ok=True)
        supplier = getattr(ctx.cfg.general, "user_name", "") or "Dodavatel"
        for cl, b in r["clients"].items():
            slug = re.sub(r"[^\w-]+", "-", cl.lower()).strip("-")[:30] or "klient"
            dest = d / f"podklad-{slug}-{time.strftime('%Y%m%d-%H%M%S')}.docx"
            await asyncio.to_thread(bizops.billing_docx, dest, cl, b, supplier)
            files.append(str(dest))
    warn = [cl for cl, b in r["clients"].items() if b["missing_rate"]]
    msg = "; ".join(f"{cl}: {b['hours']:g} h, celkem {_kc(b['total'])}" for cl, b in r["clients"].items())
    if warn:
        msg += f". Bez sazby u {', '.join(warn)} – zadej výchozí sazbu"
    return ToolResult(True, msg + ".", data=r | {"files": files}, attachments=files)


@tool("customer_request", "Zapíše požadavek zákazníka (co chce, odkud přišel); prioritu a termín odhadne podle textu "
      "(„nefunguje“ = vysoká). Nebo ho označí za vyřízený.", category="byznys")
async def customer_request(ctx, client: str = "", text: str = "", source: str = "", priority: str = "", due: str = "",
                           close: Annotated[str, "číslo nebo slovo z vyřízeného požadavku"] = "") -> ToolResult:
    from .. import bizops

    try:
        if close:
            r = bizops.close_request(ctx, close)
            return ToolResult(True, f"Vyřízeno: {r['client']} – {r['text'][:80]}.", data=r)
        if not client or not text:
            return ToolResult(False, "Zadej zákazníka a co chce.")
        r = bizops.add_request(ctx, client, text, source, priority, due)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Zapsáno č. {r['id']} ({r['priority']} priorita, do {r['due']}).", data=r)


@tool("customer_requests", "Otevřené požadavky zákazníků: co je po termínu, podle priority, kolik má který zákazník.", category="byznys")
async def customer_requests(ctx, client: str = "", include_closed: bool = False) -> ToolResult:
    from .. import bizops

    r = bizops.requests(ctx, client, include_closed)
    if not r["requests"]:
        return ToolResult(True, "Žádné otevřené požadavky.", data=r)
    msg = f"{r['open']} otevřených, {r['overdue']} po termínu: " + "; ".join(
        f"č. {x['id']} {x['client']} – {x['text'][:50]} ({x['priority']}" + (f", {x['overdue_days']} d po termínu" if x["overdue_days"] else f", do {x['due']}") + ")"
        for x in r["requests"][:6])
    return ToolResult(True, msg + ".", data=r)


@tool("compare_offers", "Porovná nabídky dodavatelů podle vah (cena, termín dodání, záruka, splatnost, hodnocení, nebo náklady "
      "za dobu užívání) a řekne vítěze, náskok a jestli by vyhrál i při jiných vahách.", category="byznys")
async def compare_offers(ctx, offers: Annotated[list[dict], "[{supplier, price, delivery_days, warranty_months, payment_days, rating, yearly_cost, shipping}]"],
                         weights: dict[str, float] | None = None, years: float = 0) -> ToolResult:
    from .. import bizops

    try:
        r = bizops.compare_offers(offers, weights, years)
    except (ValueError, KeyError, TypeError) as e:
        return ToolResult(False, f"Nabídky nesedí: {e}")
    msg = "Pořadí: " + ", ".join(f"{x['supplier']} {x['score']:g}" for x in r["ranking"]) + f". Vítěz {r['winner']} o {r['margin']:g} bodů"
    msg += " – vyhraje i při jiných vahách." if r["robust"] else f" – ale záleží na vahách ({'; '.join(r['flips'][:3])})."
    return ToolResult(True, msg, data=r)


@tool("campaign_report", "Vyhodnotí reklamní kampaně (CSV: kampaň, náklady, zobrazení, prokliky, konverze, tržby): CTR, cena "
      "prokliku a konverze, ROAS, ROI, jestli se kampaň opravdu liší, a kam přesunout rozpočet.", category="byznys", perm="files_read")
async def campaign_report(ctx, file: str) -> ToolResult:
    from .. import bizops
    from ..science import read_csv

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    header, rows, _, _ = await asyncio.to_thread(read_csv, p)
    try:
        r = bizops.campaigns(header, rows)
    except ValueError as e:
        return ToolResult(False, str(e))
    t = r["total"]
    msg = f"Celkem {_kc(t['spend'])} → tržby {_kc(t['revenue'])} (ROAS {t['roas']}). " + "; ".join(
        f"{c['campaign']}: ROAS {c['roas']}, konverze za {_kc(c['cpa']) if c['cpa'] else '–'}" for c in r["campaigns"][:5])
    if r["move_budget"]:
        m = r["move_budget"]
        msg += f". Přesunout {_kc(m['amount'])} z {', '.join(m['from'])} do {m['to']} (+{_kc(m['extra_revenue_if_roas_holds'])}, pokud ROAS vydrží)"
    return ToolResult(True, msg + ".", data=r)


@tool("cashflow_report", "Příjmy a výdaje z výpisu z banky (CSV z Fio, ČSOB, KB, Air Bank, Revolut…): po měsících, kolik se "
      "ušetřilo, za co jdou peníze, pravidelné platby a předplatná, neobvyklé výkyvy a největší platby. Nic neodesílá.",
      category="byznys", perm="files_read")
async def cashflow_report(ctx, file: str, rules: Annotated[dict[str, list[str]] | None, "vlastní kategorie: {kategorie: [slova]}"] = None) -> ToolResult:
    from .. import bizops
    from ..science import read_csv

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Výpis neexistuje: {p}")
    header, rows, _, _ = await asyncio.to_thread(read_csv, p)
    try:
        r = bizops.cashflow(header, rows, rules)
    except ValueError as e:
        return ToolResult(False, str(e))
    last = r["months"][-1]
    msg = f"{last['month']}: příjmy {_kc(last['income'])}, výdaje {_kc(last['expenses'])}" + (f", ušetřeno {last['savings_pct']:g} %" if last["savings_pct"] is not None else "")
    msg += ". Nejvíc: " + ", ".join(f"{c['category']} {c['pct']:g} %" for c in r["categories"][:4])
    if r["recurring"]:
        msg += f". Pravidelné platby {_kc(r['recurring_monthly'])} měsíčně ({len(r['recurring'])})"
    if r["spikes"]:
        msg += ". Výkyv: " + ", ".join(f"{s['category']} {_kc(s['last'])} (obvykle {_kc(s['usual'])})" for s in r["spikes"][:3])
    return ToolResult(True, msg + ".", data=r)


@tool("seo_audit", "SEO audit webu: projde stránky webu (do zadaného počtu) a najde chybějící / špatně dlouhé titulky a popisy, "
      "H1, obrázky bez alt textu, stránky s málem textu, nefunkční odkazy, duplicity, chybějící sitemap a robots.txt. Jen čte.",
      category="web")
async def seo_audit(ctx, url: str, max_pages: int = 15) -> ToolResult:
    from .. import webbiz

    try:
        r = await webbiz.seo_audit(ctx, url, max(1, min(max_pages, 60)))
    except Exception as e:  # noqa: BLE001 – unreachable site
        return ToolResult(False, f"Web nejde projít: {type(e).__name__}")
    if not r["pages"]:
        return ToolResult(False, "Nepodařilo se načíst žádnou stránku." + (f" Nefunkční: {r['broken'][0]['url']}" if r["broken"] else ""), data=r)
    top = ", ".join(f"{k} ({n}×)" for k, n in r["top_problems"][:5])
    return ToolResult(True, f"SEO skóre {r['score']}/100 ({r['crawled']} stránek). Nejčastěji: {top or 'nic'}" +
                      (f". Web: {'; '.join(r['site_issues'])}" if r["site_issues"] else "") + ".", data=r)


@tool("keyword_gap", "Klíčová slova, která konkurence na stránce používá (i v nadpisech) a tvoje stránka ne – nápady na obsah a SEO.",
      category="web")
async def keyword_gap(ctx, my_url: str, competitor_url: str) -> ToolResult:
    from .. import webbiz

    try:
        r = await webbiz.keyword_gap(ctx, my_url, competitor_url)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Stránku nejde načíst: {type(e).__name__}")
    if not r["gaps"]:
        return ToolResult(True, "Konkurence nepoužívá nic, co bys neměl i ty.", data=r)
    return ToolResult(True, "Chybí ti: " + ", ".join(f"{g['term']}{' (nadpisy)' if g['in_headings'] else ''}" for g in r["gaps"][:12]) + ".", data=r)


@tool("competitor_watch", "Hlídá stránku konkurence: při každé kontrole porovná s minulou – nové a zmizelé nadpisy (produkty, služby), "
      "změny cen, nové položky. Poprvé si stránku jen uloží.", category="web")
async def competitor_watch(ctx, url: str) -> ToolResult:
    from .. import webbiz

    try:
        r = await webbiz.watch_competitor(ctx, url)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Stránku nejde načíst: {type(e).__name__}")
    if r["first"]:
        return ToolResult(True, f"Uloženo: {len(r['now']['heads'])} nadpisů, {len(r['now']['prices'])} cen. Příště řeknu, co se změnilo.", data=r)
    parts = []
    if r["price_changes"]:
        parts.append("ceny: " + ", ".join(f"{p['item']} {p['before']:g} → {p['after']:g} ({p['pct']:+g} %)" for p in r["price_changes"][:5]))
    if r["new_items"] or r["new_headings"]:
        parts.append("nové: " + ", ".join((r["new_items"] + r["new_headings"])[:5]))
    if r["removed_items"] or r["removed_headings"]:
        parts.append("zmizelo: " + ", ".join((r["removed_items"] + r["removed_headings"])[:5]))
    return ToolResult(True, (f"Od {r['since']}: " + "; ".join(parts) if parts else f"Od {r['since']} beze změny" + (" (jen drobné úpravy textu)" if r["changed"] else "")) + ".",
                      data=r)


@tool("feature_matrix", "Srovnání s konkurencí: které z vyjmenovaných vlastností / služeb zmiňuje který web (tabulka), co má jen jeden a "
      "co komu chybí. Alternativy odděl lomítkem: „doprava zdarma / doprava zadarmo“.", category="web")
async def feature_matrix(ctx, urls: list[str], features: list[str]) -> ToolResult:
    from .. import webbiz

    if len(urls) < 2 or not features:
        return ToolResult(False, "Zadej aspoň dva weby a seznam vlastností.")
    r = await webbiz.feature_matrix(ctx, urls, features)
    lines = [f"{f}: " + ", ".join(f"{u.split('//')[-1].split('/')[0]} {'✓' if v else '–' if v is False else '?'}" for u, v in row.items())
             for f, row in r["matrix"].items()]
    return ToolResult(True, " | ".join(lines[:10]), data=r)


@tool("bought_together", "Co zákazníci kupují spolu (z objednávek v CSV: objednávka, zákazník, produkt) – síla vazby (lift), "
      "a komu nabídnout druhý produkt, protože si koupil jen první.", category="byznys", perm="files_read")
async def bought_together(ctx, file: str, min_orders: int = 2) -> ToolResult:
    from .. import webbiz

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    header, rows = await asyncio.to_thread(webbiz.load_csv, p)
    try:
        r = webbiz.basket(header, rows, max(1, min_orders))
    except ValueError as e:
        return ToolResult(False, str(e))
    if not r["rules"]:
        return ToolResult(True, f"V {r['orders']} objednávkách nic nekupují výrazně spolu.", data=r)
    msg = "Spolu: " + "; ".join(f"{x['if']} → {x['then']} ({x['confidence_pct']:g} %, lift {x['lift']:g})" for x in r["rules"][:4])
    if r["cross_sell"]:
        t = r["cross_sell"][0]
        msg += f". Nabídni {t['offer']} {t['count']} zákazníkům, kteří mají {t['to_buyers_of']}"
    return ToolResult(True, msg + ".", data=r)


@tool("follow_ups", "Koho dnes oslovit: nabídky bez odpovědi nebo před propadnutím, požadavky po termínu, spokojenost měsíc po "
      "zakázce, klienti dlouho bez zakázky – s návrhem krátké zprávy (nic se neodesílá).", category="byznys")
async def follow_ups(ctx) -> ToolResult:
    from .. import webbiz

    r = webbiz.follow_ups(ctx)
    if not r:
        return ToolResult(True, "Dnes nikoho oslovovat nemusíš.", data=[])
    return ToolResult(True, "; ".join(f"{x['who']} – {x['why']}" for x in r[:8]) + ".", data=r)


@tool("business_dashboard", "Obchodní přehled na jednom místě: nabídky, úspěšnost, požadavky, koho oslovit, a když dáš výpis z banky "
      "a export kampaní, i příjmy, výdaje a ROAS – s upozorněními.", category="byznys", perm="files_read")
async def business_dashboard(ctx, bank_file: str = "", campaigns_file: str = "") -> ToolResult:
    from .. import bizops, webbiz

    cash = camp = None
    try:
        if bank_file:
            cash = bizops.cashflow(*await asyncio.to_thread(webbiz.load_csv, resolve(bank_file)))
        if campaigns_file:
            camp = bizops.campaigns(*await asyncio.to_thread(webbiz.load_csv, resolve(campaigns_file)))
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    r = webbiz.dashboard(ctx, cash, camp)
    shown = ", ".join(f"{k} {(_kc(v) if isinstance(v, float) and v > 1000 else v)}" for k, v in r["kpi"].items() if v is not None)
    return ToolResult(True, shown + (". Pozor: " + "; ".join(r["alerts"]) if r["alerts"] else "") + ".", data=r)
