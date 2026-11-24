"""The agent's helpers (3.18 split out of agent.py): how a tool call is described to you, protocol steps in waves,
the second confirmation, the "ne, tu modrou" / "pokračuj" phrases. agent.py re-exports all of it."""
from __future__ import annotations

import re

from .llm.base import ToolCall

TOOL_LABELS = {
    "hotel_search": "Hledám hotel", "flight_search": "Hledám letenky", "travel_offers": "Nabídky",
    "travel_book": "Rezervovat a zaplatit", "booking_list": "Moje rezervace", "booking_cancel_check": "Podmínky zrušení",
    "booking_cancel": "Zrušit rezervaci", "booking_change": "Změna termínu", "hotel_message": "Zpráva hotelu",
    "trip_plan": "Plánuji cestu", "experiences": "Vstupenky a zážitky", "travel_watch": "Hlídání ceny",
    "travel_spend": "Útrata za cesty",
    "youtube_play": "Pouštím YouTube", "open_app": "Spouštím aplikaci", "close_app": "Zavírám aplikaci",
    "web_search": "Hledám na webu", "web_read": "Čtu stránku", "weather": "Zjišťuji počasí",
    "google_ask": "Ptám se Googlu", "world_news": "Čtu zprávy",
    "money_action": "Peníze – schválíš?", "multitask_start": "Rozděluji se na agenty", "multitask_stop": "Zastavuji agenty",
    "volume": "Hlasitost", "media_control": "Média", "screenshot": "Snímek obrazovky",
    "system_power": "Napájení", "run_shell": "PowerShell", "computer_use": "Ovládám počítač",
    "run_python": "Spouštím kód", "generate_image": "Kreslím obrázek", "set_timer": "Časovač",
    "set_reminder": "Připomínka", "find_file": "Hledám soubor", "open_file": "Otevírám soubor",
    "remember": "Pamatuji si", "send_file": "Posílám soubor", "send_to_phone": "Posílám na telefon",
    "create_skill": "Učím se novou dovednost", "schedule_task": "Plánuji úlohu",
    "browser_open": "Otevírám stránku", "browser_click": "Klikám v prohlížeči", "browser_type": "Píšu do prohlížeče",
    "ui_click": "Klikám", "ui_type": "Píšu do aplikace", "ui_inspect": "Prohlížím okno", "ui_read": "Čtu okno",
    "ui_wait": "Čekám na okno", "mouse": "Myš", "move_files": "Přesouvám soubory", "update_plan": "Plán",
    "git_status": "Git stav", "git_diff": "Git změny", "git_commit": "Git commit", "git_push": "Git push",
    "checkpoint": "Záchytný bod", "restore_checkpoint": "Obnovuji záchytný bod", "compare_files": "Porovnávám soubory",
    "run_tests": "Spouštím testy", "claude_code": "Claude Code",
    "make_website": "Stavím web", "read_website": "Čtu web", "list_websites": "Moje weby",
    "set_dark_mode": "Tmavý režim", "briefing": "Brífink", "run_protocol": "Protokol", "list_protocols": "Protokoly",
    "show_hud": "Stark HUD", "system_info": "Stav systémů",
    "create_automation": "Nová automatizace", "list_automations": "Automatizace", "delete_automation": "Mažu automatizaci",
    "toggle_automation": "Automatizace", "home_devices": "Chytrá domácnost", "home_control": "Domácnost",
    "home_scene": "Scéna", "list_add": "Přidávám na seznam", "list_show": "Seznam", "list_done": "Odškrtávám",
    "list_clear": "Mažu seznam", "list_to_phone": "Seznam do mobilu", "exchange_rate": "Kurz ČNB", "price": "Cena",
    "price_alert": "Hlídám cenu", "network_devices": "Zařízení v síti", "name_device": "Pojmenovávám zařízení",
    "wake_device": "Budím počítač", "find_phone": "Hledám telefon", "phone_battery": "Baterie telefonu",
    "pc_health_report": "Diagnostika PC (jen čtení)", "save_mission_as_skill": "Skill Forge: nová dovednost",
}
SAY_RESULT = {"briefing", "pc_health_report"}   # in a protocol/mission, JARVIS says what these found
MEDIA_ACTIONS = {"play_pause": "přehrát / pauza", "next": "další", "previous": "předchozí", "stop": "stop"}


class BudgetExceeded(Exception):
    """A mission used up its budget (actions / minutes, Nastavení → Oprávnění)."""


def _waves(steps: list, done: set[int]) -> list[list[int]]:
    """Steps in dependency order: each wave holds the steps whose `needs` are all finished. Without any `needs` the
    steps run one by one, as written (a protocol's order matters: say → pause music → …)."""
    todo = [i for i in range(len(steps)) if i not in done]
    if not any(getattr(st, "needs", None) for st in steps):
        return [[i] for i in todo]
    finished, out = set(done), []
    while todo:
        wave = [i for i in todo if all(n in finished or n >= len(steps) or n < 0 for n in steps[i].needs)]
        if not wave:            # a cycle → run the rest in order instead of hanging
            wave = [todo[0]]
        out.append(wave)
        finished |= set(wave)
        todo = [i for i in todo if i not in wave]
    return out


# OMEGA 182: what cannot be undone asks twice
DOUBLE_TOOLS = {"delete_file", "clean_pc", "email_delete"}
# 3.18/3.19 money – always twice (whatever the settings), the second time with the exact amount, also to the phone
from .trust import MONEY_TOOLS, is_money  # noqa: E402,F401


def _needs_second(call: ToolCall, limits) -> bool:
    if is_money(call.name, call.arguments):
        return True
    if limits is None or not limits.double_confirm:
        return False
    a = call.arguments or {}
    return (call.name in DOUBLE_TOOLS
            or (call.name == "system_power" and a.get("action") in ("shutdown", "restart", "logoff", "hibernate"))
            or (call.name == "home_control" and a.get("action") == "unlock"))


def _wave_of(waves: list[list[int]], i: int) -> int:
    return next((k for k, w in enumerate(waves) if i in w), -1)


_DOTS = re.compile(r"^[\s.…·]*$")


def only_dots(text: str) -> bool:
    """3.13 "...", "…", ". . ." – no words at all (not shown, not spoken, not kept)."""
    return bool(_DOTS.match(text or ""))


AGENT_MODE_RULE = ("Režim Agent: u úkolu s více kroky nejdřív zavolej update_plan se seznamem kroků, po každém kroku "
                   "ho aktualizuj a na konci ověř výsledek.")


def _first_sentence(text: str) -> str:
    import re

    m = re.match(r"\s*(.+?[.!?])(\s|$)", text or "", re.S)
    return (m.group(1) if m else (text or "")).strip()[:300]


# 3.12 Propojení: the actions that wait for a click, in words (what is sent / changed and where)
CONNECTOR_LABELS = {
    "google_gmail_send": "Odeslat e-mail", "google_gmail_draft": "Koncept e-mailu", "google_calendar_create": "Nová událost v kalendáři",
    "google_sheets_append": "Zapsat do Google Tabulky", "google_docs_create": "Nový Google Dokument", "supabase_sql": "SQL v Supabase",
    "spaceship_dns_set": "Změnit DNS záznam", "github_issue_create": "Nové issue na GitHubu", "notion_append": "Zapsat do Notionu",
    "slack_post": "Zpráva do Slacku", "google_tasks_add": "Nový úkol v Google Úkolech",
    "outlook_mail_send": "Odeslat e-mail (Outlook)", "outlook_mail_draft": "Koncept e-mailu (Outlook)",
    "outlook_calendar_create": "Nová událost v kalendáři Outlook", "mstodo_add": "Nový úkol v Microsoft To Do",
    "stripe_refund": "Vrátit peníze (Stripe)", "stripe_payment_link": "Platební odkaz (Stripe)",
    "fakturoid_invoice_create": "Vystavit fakturu (Fakturoid)", "hubspot_contact_create": "Nový kontakt v HubSpotu",
    "hubspot_note": "Poznámka v HubSpotu", "pipedrive_deal_create": "Nový obchod v Pipedrive", "todoist_add": "Nový úkol v Todoistu",
    "todoist_done": "Dokončit úkol v Todoistu", "trello_card_create": "Nová karta v Trellu", "asana_task_create": "Nový úkol v Asaně",
    "linear_issue_create": "Nové issue v Linearu", "jira_issue_create": "Nový úkol v Jiře", "clickup_task_create": "Nový úkol v ClickUpu",
    "airtable_create": "Nový záznam v Airtable", "monday_item_create": "Nová položka v monday.com", "toggl_timer": "Stopky v Togglu",
    "cloudflare_dns_set": "Změnit DNS (Cloudflare)", "telegram_send": "Zpráva na Telegram", "discord_send": "Zpráva na Discord",
    "webhook_send": "Spustit automatizaci",
}


def describe_call(name: str, args: dict) -> str:
    label = CONNECTOR_LABELS.get(name) or TOOL_LABELS.get(name, name)
    if name == "travel_book":
        try:
            money = f"{float(args.get('expected_total') or 0):,.2f}".replace(",", " ")
        except (TypeError, ValueError):
            money = "?"
        return f"{label}: {money} {args.get('currency', '')} – nabídka {args.get('option', '?')}"
    if name in ("booking_cancel", "booking_cancel_check", "booking_change", "hotel_message") and args.get("booking_ref"):
        return f"{label}: {args['booking_ref']}"
    if name in ("google_gmail_send", "google_gmail_draft", "outlook_mail_send", "outlook_mail_draft") and args.get("to"):
        return f"{label}: {args['to']} – {args.get('subject', '')}"
    if name == "spaceship_dns_set" and args.get("domain"):
        return f"{label}: {args['domain']} {args.get('type', '')} {args.get('name', '@')} → {args.get('value', '')}"
    if name == "cloudflare_dns_set" and args.get("domain"):
        return f"{label}: {args['domain']} {args.get('type', '')} {args.get('name', '@')} → {args.get('content', '')}"
    if name == "fakturoid_invoice_create" and args.get("client"):
        return f"{label}: {args['client']}"
    if name == "stripe_refund" and args.get("payment_id"):
        return f"{label}: {args['payment_id']}" + (f" ({args['amount']})" if args.get("amount") else "")
    if name == "slack_post" and args.get("channel"):
        return f"{label}: {args['channel']}"
    if name == "volume" and args.get("action") == "set" and args.get("level") is not None:
        return f"{label}: {args['level']} %"
    if name == "media_control" and args.get("action") in MEDIA_ACTIONS:
        return f"{label}: {MEDIA_ACTIONS[args['action']]}"
    if name == "set_dark_mode" and "dark" in args:
        return f"{label}: {'zapnout' if args['dark'] else 'vypnout'}"
    key = next((args[k] for k in ("query", "name", "text", "task", "prompt", "url", "command", "action", "path", "city", "title")
                if isinstance(args.get(k), (str, int)) and args.get(k) != ""), None)
    return f"{label}: {key}" if key is not None else label


def _stored_to_llm(m: dict) -> dict:
    text = m["text"] or ""
    if m["attachments"]:
        text += "\n" + " ".join(f"[příloha id={a}]" for a in m["attachments"])
    return {"role": "assistant" if m["role"] == "assistant" else "user", "content": text}


MIDRUN = re.compile(r"^\s*(?:jarvis\w*[ ,]+)?(?:ne+\b|počkej|pockej|vlastně|vlastne|myslel jsem|myslela jsem|ale ne\b|"
                    r"spíš|spis\b|oprava\b)", re.I)
CONTINUE = re.compile(r"^(?:jarvis\w*[ ,]+)?(?:pokračuj|pokracuj|dokonči(?: to| větu)?|dokonci(?: to| vetu)?|mluv dál|mluv dal|"
                      r"co jsi chtěl říct|co jsi chtel rict|a dál|a dal|dál|dal)\s*[.!?…]*$", re.I)
