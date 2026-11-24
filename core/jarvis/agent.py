"""The agent loop: message → LLM → tools → … → answer."""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Any

from . import tools
from . import toolcatalog as tc
from .llm.base import AllProvidersFailed, ProviderError, ToolCall
from .prompt import build_system_prompt
from .tools import select as sel
from .tools.base import UNTRUSTED_OUTPUT

log = logging.getLogger(__name__)

MAX_ROUNDS = 8
MAX_ROUNDS_AGENT = 25
CONFIRM_TIMEOUT = 30.0
NO_LIMIT = ("Narazil jsem na limit u všech AI mozků. Chvíli počkej – nebo v Nastavení → Mozek vlož nahoře klíč "
            "od další služby (Groq i Gemini jsou zdarma) a pojedu přes ni.")
NO_BRAIN = ("Omlouvám se, teď se nemůžu spojit s žádným AI mozkem. V Nastavení → Mozek vlož nahoře API klíč "
            "(Groq nebo Gemini, oba zdarma) – nic dalšího není potřeba. Pokud klíč už máš, je PC připojené k internetu?")

TOOL_LABELS = {
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


def _needs_second(call: ToolCall, limits) -> bool:
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


class Agent:
    def __init__(self, rt: Any):
        self.rt = rt
        self._lock = asyncio.Lock()
        self._confirms: dict[str, asyncio.Future] = {}
        self.confirm_info: dict[str, dict] = {}    # OMEGA 219: every approval waiting right now (the approval queue)
        self._task_hint: str | None = None
        self._only: str | None = None           # 3.12 a request for one particular AI (the notch's AI chips)
        self._task: asyncio.Task | None = None
        self.busy = False
        self._goal = ""
        self._sources: list[dict] = []        # OMEGA 550: web pages, files, e-mails behind the current answer
        self._lang = "cs"
        self._gen = 0  # bumped by drop_queued(): requests waiting for the lock are discarded

    # ---------- public ----------
    async def handle(self, text: str, attachments: list[str] | None = None, source: str = "chat",
                     record_user: bool = True, extra_system: str = "", lang: str = "", task_id: str | None = None,
                     ai: str = "", untrusted: bool = False) -> str:
        """untrusted = the message carries text you did not write (the clipboard, a selection): no reflexes, nothing
        learnt, and the AI asks before steps that change something (3.17, trust.foreign_needs_ask)."""
        rt = self.rt
        self._task_hint = task_id           # a queued / interrupted mission this request carries on
        if self._lock.locked() and rt.tasks.current and rt.tasks.current["status"] == "paused":
            msg = "Úkol je pozastavený – nejdřív ho nech pokračovat, nebo ho zruš (Úkoly nebo STOP)."
            rt.bus.publish("error", message=msg)
            return msg
        if self.busy and self._task is not None and not self._task.done() and record_user and MIDRUN.match(text or ""):
            # 3.16 (návrh 21) "ne, tu modrou" while he still works: stop that, and do it right with what was already done
            done = [str(c.get("label") or c.get("name")) for c in getattr(self, "_live_cards", []) if c.get("ok")]
            note = (f"Uživatel tě právě přerušil opravou. Původní požadavek: „{self._goal}“."
                    + (f" Už hotové kroky: {'; '.join(done)[:400]}." if done else "")
                    + " Splň ho podle opravy; co je hotové špatně, oprav nebo vrať, pokud to jde.")
            extra_system = (extra_system + "\n" if extra_system else "") + note
            self.stop()
        gen = self._gen
        async with self._lock:
            if gen != self._gen:  # STOP was pressed while this request waited → drop it
                return ""
            # 3.12 "Zeptej se Claude" in the notch: this one request goes only to that AI (no fallback to others)
            self._only = ai if ai and any(p.id == ai and p.enabled for p in rt.cfg.brain.providers) else None
            self._task = asyncio.current_task()
            self.busy = True
            try:
                from .lang import preferred

                lang = preferred(text, lang, getattr(rt.cfg.general, "language", "cs"))   # 3.14 návrh 114
                rule = {"en": "Odpověz anglicky.", "sk": "Odpovídaj po slovensky.", "de": "Antworte auf Deutsch."}.get(lang)
                if rule:
                    extra_system = (extra_system + "\n" if extra_system else "") + rule
                self._lang = lang if lang in ("cs", "en") else "cs"
                self._foreign_turn = bool(untrusted)
                return await self._handle(text, attachments or [], source, record_user, extra_system)
            finally:
                self.busy = False
                self._task = None
                self.rt.bus.publish("state", state="idle")

    async def run_steps(self, title: str, steps: list, source: str = "protocol", task_id: str | None = None,
                        track: bool = False, say: str = "voice") -> str:
        """A protocol segment: JARVIS lines and tool calls, without the AI. Tools go through the same path as any AI
        tool call (permissions, confirmation of dangerous actions, STOP, task log, chips in the chat).
        `track` = a structured mission: its steps are remembered and shown, steps whose `needs` are done run together
        (in waves), and with `task_id` an interrupted mission continues after its last finished step."""
        rt, bus = self.rt, self.rt.bus
        gen = self._gen
        async with self._lock:
            if gen != self._gen:
                return ""
            self._task = asyncio.current_task()
            self.busy = True
            self._goal = title
            cards: list[dict] = []
            atts: list[str] = []
            said: list[str] = []
            status, cancelled = "done", False
            try:
                um = rt.memory.add_message("user", title, [], source)
                bus.publish("user_message", id=um["id"], text=title, source=source, attachments=[])
                bus.publish("state", state="acting")
                done: set[int] = rt.tasks.done_steps(task_id) if task_id else set()
                if track or task_id:
                    rt.tasks.begin(title, rt.memory.current_conversation, task_id)
                    rt.tasks.set_spec([st.model_dump(mode="json") for st in steps])
                titles = [describe_call(st.tool, st.args) if st.tool else (f"Řekne: {st.say}" if st.say else st.ask or "krok")
                          for st in steps]
                states = ["done" if i in done else "pending" for i in range(len(steps))]
                waves = _waves(steps, done)
                dag = any(getattr(st, "needs", None) for st in steps)
                notes = [f"vlna {_wave_of(waves, i) + 1}" if dag and _wave_of(waves, i) >= 0 else "" for i in range(len(steps))]
                for w, wave in enumerate(waves):
                    if track or task_id:
                        for i in wave:
                            states[i] = "running"
                        rt.tasks.set_step_states(titles, states, notes)
                    budget = rt.tasks.over_budget(getattr(rt.cfg, "limits", None))
                    if budget:
                        raise BudgetExceeded(budget)
                    runnable = [i for i in wave if not (steps[i].when == "playing" and not rt.media_state.get("playing"))]
                    calls = {i: ToolCall(uuid.uuid4().hex[:12], steps[i].tool, dict(steps[i].args)) for i in runnable if steps[i].tool}
                    if len(calls) > 1:
                        await asyncio.gather(*(self._run_call(c, cards, atts) for c in calls.values()))
                    elif calls:
                        await self._run_call(next(iter(calls.values())), cards, atts)
                    for i in wave:
                        st = steps[i]
                        if st.tool in SAY_RESULT and cards:
                            said.append(next((c["summary"] for c in reversed(cards) if c["name"] == st.tool), ""))
                        if st.say:
                            said.append(st.say)
                        states[i] = "done"
                if track or task_id:
                    rt.tasks.set_step_states(titles, states)
                text = "\n\n".join(said) or f"{title}: hotovo."
                failed = [c["label"] for c in cards if not c["ok"]]
                if failed:
                    text += "\n\nNepovedlo se: " + ", ".join(failed) + "."
                bus.publish("assistant_delta", text=text)
            except asyncio.CancelledError:
                cancelled, status = True, "cancelled"
                text = (" ".join(said) + " …(přerušeno)").strip()
            except BudgetExceeded as e:
                status = "failed"
                text = f"{e} Mise zastavena, hotové kroky zůstávají; Zopakovat ji dokončí."
                bus.publish("error", message=text)
            except Exception as e:
                log.exception("protocol failed")
                status = "failed"
                text = f"Omlouvám se, protokol se nepovedl: {e}"
                bus.publish("error", message=text)
            finally:
                self.busy = False
                self._task = None
            if rt.tasks.current is not None:
                rt.tasks.finish(status, _first_sentence(text))
            am = rt.memory.add_message("assistant", text, atts, source, meta={"tools": cards, "brain": None})
            bus.publish("assistant_done", id=am["id"], text=text, tools=cards,
                        attachments=[rt.public_attachment(a) for a in atts])
            bus.publish("state", state="idle")
            # 3.13 how an automation speaks up: aloud (held while you play), only in the notch, or on the phone
            name = title.removeprefix("▶ ").strip()
            if not cancelled and say == "phone":
                rt.phone_push("notify", title=name[:80], body=text[:400])
            elif not cancelled and say != "notch" and rt.cfg.voice.speak_mode != "never":
                rt.speak(text, announce=name)
            return text

    def confirm(self, cid: str, approved: bool) -> bool:
        fut = self._confirms.get(cid)
        if fut and not fut.done():
            fut.set_result(bool(approved))
            self.rt.bus.publish("confirm_resolved", id=cid, approved=bool(approved))
            return True
        return False

    def pending_confirm(self) -> str | None:
        return next((k for k, f in self._confirms.items() if not f.done()), None)

    def drop_queued(self) -> None:
        self._gen += 1

    def cancel_confirms(self) -> None:
        for cid in list(self._confirms):
            self.confirm(cid, False)

    def stop(self) -> None:
        self.cancel_confirms()  # an open "Ano / Ne" must not outlive the task it belongs to
        if self._task and not self._task.done():
            self._task.cancel()

    # ---------- internals ----------
    async def _build_messages(self, text: str, attachments: list[str], voice: bool, extra: str) -> tuple[list[dict], bool]:
        rt = self.rt
        know = getattr(rt, "knowledge", None)
        facts = know.for_prompt() if know else [f["text"] for f in rt.memory.facts()]
        from . import shield

        if shield.guest_on(rt):                     # 3.14 návrh 109: a guest at the PC – nothing about you
            facts = []
            extra = (extra + "\n\n" if extra else "") + shield.GUEST_RULE
        from . import safety

        if safety.kids_on(rt):                      # 3.14 návrh 41: a child at the PC
            facts = []
            extra = (extra + "\n\n" if extra else "") + safety.KIDS_RULE
        from . import persona

        try:                                        # 3.14 návrhy 15, 16: humour that knows when; a voice nobody knows
            stranger = persona.speaker_line(rt) if voice else ""
            if stranger and not shield.guest_on(rt):
                facts = []
                extra = (extra + "\n\n" if extra else "") + stranger
            fun = persona.humour_line(rt, text)
            if fun:
                extra = (extra + "\n\n" if extra else "") + fun
            prev = [m for m in rt.memory.recent(4) if m.get("role") == "assistant"]
            if prev and not getattr(self, "_speculating", False):
                persona.note_reaction(rt, text, str(prev[-1].get("text") or prev[-1].get("content") or ""))
        except Exception as e:  # noqa: BLE001 – never in the way of an answer
            log.debug("persona: %s", e)
        proj = know.project_prompt() if know else ""
        vm = getattr(rt, "voice_mood", None)          # OMEGA P3.12: only when switched on, only fresh, only a hint
        mood = (f"Podle tónu hlasu (ne slov) uživatel teď zní: {vm['mood']} – přizpůsob tón a délku odpovědi, nekomentuj to."
                if voice and vm and time.time() - vm["ts"] < 60 and vm["mood"] not in ("klid", "nevím") else "")
        world = ""
        try:                                         # 3.13 what is going on in the world (its own summary of the news)
            world = rt.world.for_prompt() if getattr(rt, "world", None) is not None else ""
        except Exception:  # noqa: BLE001
            world = ""
        from . import brainplus

        vid = getattr(rt, "voiceid", None)
        plus = [vid.prompt() if voice and vid is not None else "",                     # 3.14 who is speaking
                brainplus.rules_prompt(rt) if getattr(rt.cfg.brain, "learn_corrections", True) else "",
                brainplus.traits_prompt(rt.cfg),
                brainplus.risky(text) if getattr(rt.cfg.brain, "second_opinion", True) else ""]
        extra = "\n\n".join(x for x in (proj, mood, world, *plus, extra) if x)
        history = rt.memory.recent(rt.cfg.memory.context_messages + 1)
        if history and history[-1]["role"] == "user" and history[-1]["text"] == text:
            history = history[:-1]
        from . import chatsummary                   # 3.12 the older part of a long chat as a short summary

        summary, history = chatsummary.apply(rt, history)
        if summary:
            extra = (extra + "\n\n" if extra else "") + f"Shrnutí dřívější části této konverzace: {summary}"
        msgs: list[dict] = [{"role": "system", "content": build_system_prompt(rt.cfg, facts, voice, extra)}]
        msgs += [_stored_to_llm(m) for m in history if m["role"] in ("user", "assistant")]
        need_vision = False
        if attachments:
            parts: list[dict] = [{"type": "text", "text": text or "(uživatel poslal přílohu bez textu — zpracuj ji)"}]
            for aid in attachments:
                att = rt.store.get(aid)
                is_img = bool(att and att.kind == "image")
                need_vision |= is_img
                parts += await rt.store.llm_parts(aid, vision=True)
            msgs.append({"role": "user", "content": parts})
        else:
            msgs.append({"role": "user", "content": text})
        return msgs, need_vision

    async def _ask_confirm(self, call: ToolCall, second: bool = False, timeout: float | None = None, phone: bool = False,
                           why: str = "") -> bool:
        cid = uuid.uuid4().hex[:10]
        fut = asyncio.get_running_loop().create_future()
        desc = describe_call(call.name, call.arguments) + (f" ({why})" if why else "")
        if second:
            desc = f"Opravdu? {desc} (druhé potvrzení – tuhle akci nejde vrátit)"
        spec = tools.REGISTRY.get(call.name)
        details = await asyncio.to_thread(tools.details_for, spec, call.arguments, self.rt) if spec else []
        self.confirm_info[cid] = {"id": cid, "description": desc, "tool": call.name, "details": details, "ts": time.time(),
                                  "second": second}
        # pending only from the moment the request is announced (details are prepared in a thread before that), so
        # whoever sees a pending confirmation also has its request
        self._confirms[cid] = fut
        self.rt.bus.publish("confirm_request", id=cid, description=desc, tool=call.name, args=call.arguments,
                            details=details, second=second)
        self.rt.on_confirm_request(cid, desc, phone=phone)
        try:
            return await asyncio.wait_for(fut, timeout or CONFIRM_TIMEOUT)
        except asyncio.TimeoutError:
            self.rt.bus.publish("confirm_timeout", id=cid)
            return False
        finally:
            self._confirms.pop(cid, None)
            self.confirm_info.pop(cid, None)

    # ---------- which tools go with a message (see tools/select.py: ~650 of them were ~85 000 tokens every time) ----------
    def _allowed_names(self) -> set[str]:
        from .permissions import allowed

        cfg = self.rt.cfg
        off = set(cfg.tools.disabled or ())
        return {n for n, s in tools.REGISTRY.items() if n not in off and allowed(cfg, s)}

    def _tool_schemas(self, text: str) -> list[dict]:
        b = self.rt.cfg.brain
        first = next((p for i in (b.chain or []) for p in b.providers if p.id == i and p.enabled), None)
        local = first is not None and (first.preset or first.id) in ("ollama", "lmstudio") and not self._only
        allowed = self._allowed_names()
        names = sel.pick(tools.REGISTRY, allowed, text or "", getattr(self, "_recent_tools", []),
                         extra=6 if local else sel.MAX_EXTRA)
        try:                                       # 3.16 what worked before, by meaning, the app in front, habits
            from . import toolmind

            more = [n for n in toolmind.suggest(self.rt, tools.REGISTRY, allowed, text or "") if n not in names]
            names = names[:-1] + more[: 3 if local else 6] + names[-1:] if names and names[-1] == sel.FIND else names + more[:6]
        except Exception as e:  # noqa: BLE001 – the memory must never stop an answer
            log.debug("tool memory: %s", e)
        self._picked = names
        return [tools.REGISTRY[n].schema() for n in names]

    # 3.16 (návrh 5) the tools whose own words are the whole answer ("Hlasitost 40 %", "Pouštím …", "Tisk pozastaven.")
    DONE_CATS = {"média", "aplikace", "okna", "domácnost", "čas", "nastavení", "hlas", "mozek"}
    DONE_TOOLS = {"list_add", "list_done", "hud_control", "show_hud", "model_explode", "run_protocol", "send_to_phone", "remember",
                  "printer_control", "model_view"}
    _ASKS = re.compile(r"\?|\b(proč|proc|jak to|vysvětli|vysvetli|shrň|shrn|porovnej|co si myslíš|co si myslis|poraď|porad|"
                       r"navrhni|napiš|napis|kolik|kdy|kde|který|ktery|jaký|jaky|jaká|jaka)\b", re.I)

    ACKS = ("Moment, {a}.", "Hned to bude, {a}.", "Pracuji na tom, {a}.")
    ACK_AFTER_S = 1.2

    def _ack_later(self, speech) -> asyncio.Task:
        """3.16 (návrh 7) the tools take a while and nothing was said yet: one short word, so you know he is on it."""
        async def go() -> None:
            await asyncio.sleep(self.ACK_AFTER_S)
            if not speech.spoke:
                self._acks = getattr(self, "_acks", -1) + 1
                a = (self.rt.cfg.general.address_as or "pane").strip()
                speech.preface(self.ACKS[self._acks % len(self.ACKS)].format(a=a))
        return asyncio.get_running_loop().create_task(go())

    def _done_by_tools(self, text: str, said: str, run: list, cards: list[dict]) -> str:
        """The tools' own words when they are the whole answer (else '' → the AI answers as usual)."""
        if said.strip() or not run or len(run) > 3 or self.rt.cfg.agent.mode or not getattr(self.rt.cfg.agent, "instant", True):
            return ""
        if self._ASKS.search(text or ""):
            return ""                              # a question wants the AI's own answer
        mine = cards[-len(run):] if len(cards) >= len(run) else []
        if len(mine) != len(run) or not all(c.get("ok") for c in mine):
            return ""
        for c in run:
            spec = tools.REGISTRY.get(c.name)
            if spec is None or not (c.name in self.DONE_TOOLS or spec.category in self.DONE_CATS):
                return ""
        parts = [str(c.get("summary") or "").strip() for c in mine]
        if not all(parts) or sum(len(p) for p in parts) > 240 or any("\n" in p for p in parts):
            return ""
        out = " ".join(p if p.endswith((".", "!", "?", "…")) else p + "." for p in parts)
        return out

    def _tool_pack(self):
        """3.16 the whole catalog + the steady tool set for an AI with a prompt cache (the router decides per AI)."""
        from . import toolcatalog as tc

        if getattr(self.rt.cfg.brain, "tool_catalog", "auto") == "off" or self._only:
            return None
        allowed = self._allowed_names()
        steady = [n for n in sel.CORE if n in allowed] + ([tc.USE] if tc.USE in tools.REGISTRY else [])
        picked = [n for n in getattr(self, "_picked", []) if n not in steady and n != sel.FIND]
        extra = []
        try:                                       # 3.16 how it went before + which app is in front
            from . import toolmind

            extra.append(toolmind.examples_hint(self.rt, self._goal or ""))
            app, areas = toolmind.screen_areas(self.rt)
            if app:
                extra.append(f"Na popředí je {app}" + (f" (oblast: {', '.join(areas)})." if areas else "."))
        except Exception as e:  # noqa: BLE001
            log.debug("tool memory hint: %s", e)
        hint = "\n\n".join(x for x in [tc.hint(tools.REGISTRY, picked), *extra] if x)
        return tc.Pack(catalog=tc.catalog(tools.REGISTRY, allowed), tools=[tools.REGISTRY[n].schema() for n in steady],
                       hint=hint, names=set(steady))

    # ---------- 3.17 (návrh 5) the AI asked before the end of your sentence (voice) ----------
    SPEC_FRESH_S = 20.0

    async def speculate(self, text: str) -> bool:
        """At an unsure pause: start the AI on the words so far. Nothing runs (no tool, nothing said) until the final
        words are the same – then the turn takes over the answer already on its way; else it is dropped."""
        rt = self.rt
        if self.busy or not getattr(rt.cfg.voice, "speculate", True) or not (text or "").strip():
            return False
        from . import instant, toolmind

        if instant.plan(text) is not None or MIDRUN.match(text) or CONTINUE.match(text):
            return False
        try:
            if toolmind.reflex(rt, text, self._allowed_names()):
                return False
        except Exception:  # noqa: BLE001
            pass
        self.cancel_spec()
        self._speculating = True
        self._goal = text
        try:
            msgs, need_vision = await self._build_messages(text, [], True, "")
            schemas = self._tool_schemas(text)
            pack = self._tool_pack()
            _tier, tier_kw, private = await self._routing(text, [])
        finally:
            self._speculating = False
        if private or need_vision:
            return False                               # passwords, health…: never ahead of time
        spec = {"key": toolmind.norm(text), "msgs": msgs, "schemas": schemas, "pack": pack, "tier_kw": tier_kw,
                "picked": list(getattr(self, "_picked", [])), "chunks": [], "done": False, "error": None,
                "event": asyncio.Event(), "ts": time.monotonic(), "catalog_used": False}
        spec["task"] = asyncio.get_running_loop().create_task(self._spec_run(spec))
        self._spec = spec
        return True

    async def _spec_run(self, spec: dict) -> None:
        rt = self.rt
        try:
            async for ch in rt.router.stream(spec["msgs"], spec["schemas"], need_vision=False, catalog=spec["pack"],
                                             **spec["tier_kw"]):
                spec["chunks"].append(ch)
                spec["event"].set()
            spec["catalog_used"] = bool(getattr(rt.router, "catalog_used", False))
        except asyncio.CancelledError:
            spec["error"] = asyncio.CancelledError()
        except Exception as e:  # noqa: BLE001
            spec["error"] = e
        finally:
            spec["done"] = True
            spec["event"].set()

    def cancel_spec(self) -> None:
        spec, self._spec = getattr(self, "_spec", None), None
        if spec and not spec["done"]:
            spec["task"].cancel()

    def _take_spec(self, text: str, attachments: list, extra: str, voice: bool) -> dict | None:
        """The speculative request, when it is for exactly these words (else it is dropped)."""
        from . import toolmind

        spec, self._spec = getattr(self, "_spec", None), None
        if not spec:
            return None
        ok = (voice and not attachments and not extra and toolmind.norm(text) == spec["key"]
              and time.monotonic() - spec["ts"] < self.SPEC_FRESH_S
              and not (spec["done"] and spec["error"] is not None and not spec["chunks"]))
        if not ok:
            if not spec["done"]:
                spec["task"].cancel()
            return None
        return spec

    async def _replay(self, spec: dict):
        """The chunks of the speculative answer: those already here at once, then the rest as it comes."""
        i = 0
        while True:
            if i < len(spec["chunks"]):
                yield spec["chunks"][i]
                i += 1
                continue
            if spec["done"]:
                break
            spec["event"].clear()
            if i < len(spec["chunks"]) or spec["done"]:
                continue
            await spec["event"].wait()
        err = spec["error"]
        if err is not None and not isinstance(err, asyncio.CancelledError) and not spec["chunks"]:
            raise err
        self.rt.router.catalog_used = spec.get("catalog_used", False)

    async def _routing(self, text: str, attachments: list) -> tuple[str, dict, bool]:
        """Which AI and how deeply (tier, router keywords, private = only the AI on this PC)."""
        from . import brainplus
        from .llm import difficulty                        # 3.14 návrh 4: the model tier and the depth of thinking

        rt = self.rt

        tier = difficulty.classify(text or "", attachments=len(attachments or []), agent_mode=bool(rt.cfg.agent.mode),
                                   mission=bool(getattr(self, "_task_hint", None)))
        self.tier = tier
        tier_kw: dict = {"effort": difficulty.EFFORT[tier]}
        if tier == "fast" and not self._only:
            tier_kw["fast"] = True
        private = False
        if not self._only and getattr(rt.cfg.brain, "private_local", True) and brainplus.sensitive(text or ""):
            lid = brainplus.local_provider(rt)        # 3.14 návrh 32: passwords, health, bank → the AI on this PC
            ready = False
            if lid and rt.router.local_ready is not None:
                try:
                    ready = await rt.router.local_ready()
                except Exception:  # noqa: BLE001
                    ready = False
            if lid and ready:
                tier_kw["only"] = lid
                tier_kw.pop("fast", None)
                private = True
        if not self._only and not private:
            from . import brainpick

            pref = await brainpick.split_for(rt, tier)     # 3.14 chytré rozdělení: easy → e.g. Ollama, hard → e.g. Claude
            if pref:
                tier_kw["prefer"] = pref
                if tier == "fast" and pref == getattr(rt.cfg.brain, "split_easy", ""):
                    tier_kw.pop("fast", None)          # the easy brain itself, not some other provider's quick model
        return tier, tier_kw, private

    def _rounds(self) -> int:
        return MAX_ROUNDS_AGENT if self.rt.cfg.agent.mode else MAX_ROUNDS

    def _foreign_ask(self, name: str, offered: bool) -> bool:
        """3.17 (návrh 15) foreign text is in this task and the AI chose a step that changes something → ask first."""
        from . import trust

        return bool(getattr(self, "_untrusted_seen", False)) and \
            trust.foreign_needs_ask(tools.REGISTRY.get(name), offered, getattr(self, "_own_words", ""))

    async def _run_call(self, call: ToolCall, tool_cards: list[dict], attachments: list[str],
                        ai_offered: bool | None = None) -> dict:
        """ai_offered: None = not the AI's choice (an everyday command, a reflex, a protocol step); else whether the
        tool was sent with your words (False = the AI reached it itself through use_tool or by its name)."""
        rt = self.rt
        chose_after_foreign = ai_offered is not None and bool(getattr(self, "_untrusted_seen", False))
        await rt.tasks.checkpoint()
        if rt.tasks.current is None:
            rt.tasks.begin(self._goal, rt.memory.current_conversation, self._task_hint)
            self._task_hint = None
        budget = rt.tasks.over_budget(getattr(rt.cfg, "limits", None))
        if budget:
            raise BudgetExceeded(budget)
        spec = tools.REGISTRY.get(call.name)
        disabled = set(rt.cfg.tools.disabled)
        from . import safety, shield

        if spec is None or call.name in disabled:
            res = tools.ToolResult(False, f"Nástroj {call.name} neexistuje nebo je vypnutý.")
        elif (kid_why := safety.kids_blocks(rt, call.name, call.arguments)):     # 3.14 návrh 41: a child at the PC
            res = tools.ToolResult(False, kid_why)
        elif shield.guest_on(rt) and call.name in shield.GUEST_BLOCKED:
            res = tools.ToolResult(False, "V režimu host osobní data (e-maily, zprávy, paměť, kalendář) neukazuji.")
        else:
            approved = True
            from . import trust

            dangerous = tools.is_dangerous(spec, call.arguments, rt.cfg.tools.always_confirm, rt.cfg.tools.trusted, rt)
            foreign = ai_offered is not None and self._foreign_ask(call.name, ai_offered)
            vid = getattr(rt, "voiceid", None)
            owner_block = bool(dangerous and getattr(self, "_source_now", "") == "voice"
                               and getattr(rt.cfg.voice, "owner_only", True) and vid is not None and not vid.owner_ok())
            if owner_block:                            # 3.14 návrh 38: a risky action by voice only in the owner's voice
                approved = False
            elif foreign or (dangerous and not trust.skip_confirm(rt, spec, getattr(self, "_untrusted_seen", False))):
                rt.bus.publish("state", state="waiting")
                rt.tasks.set_waiting(True)
                try:
                    approved = await self._ask_confirm(call, **({"why": "po přečtení cizího textu"} if foreign and not dangerous else {}))
                    if approved and _needs_second(call, getattr(rt.cfg, "limits", None)):
                        approved = await self._ask_confirm(call, second=True)
                finally:
                    rt.tasks.set_waiting(False)
            if owner_block:
                res = tools.ToolResult(False, "Tohle hlasem udělám jen na pokyn majitele (jeho hlas jsem nepoznal). Ať to "
                                              "řekne sám, nebo ať to napíše v chatu. NEPROVEDENO.")
                rt.bus.publish("tool_end", id=call.id, ok=False, summary="Jen hlasem majitele")
            elif not approved:
                res = tools.ToolResult(False, "Uživatel akci nepotvrdil – NEPROVEDENO. Nezkoušej to znovu.")
                rt.bus.publish("tool_end", id=call.id, ok=False, summary="Zrušeno")
            else:
                rt.bus.publish("state", state="acting")
                label = describe_call(call.name, call.arguments)
                rt.bus.publish("tool_start", id=call.id, name=call.name, args=call.arguments, label=label)
                if call.name != "update_plan":
                    rt.tasks.action_started(label)
                t0 = time.monotonic()
                try:                                   # OMEGA 752: the notch moves above the window this step works in
                    from .mochiplus import target_window

                    win = target_window(call.name, call.arguments or {}, await asyncio.to_thread(rt.platform.window_layout))
                    if win:
                        rt.set_anchor(win)
                except Exception as e:  # noqa: BLE001
                    log.debug("anchor: %s", e)
                before = None
                if call.name == "write_text_file":        # 3.12: what JARVIS changes in a file, line by line
                    try:
                        from .changes import _read
                        from .tools.files import resolve as _resolve

                        before = await asyncio.to_thread(_read, str(_resolve((call.arguments or {}).get("path", ""))))
                    except Exception:  # noqa: BLE001
                        before = None
                from . import prefetch                    # 3.16 fetched in the background a moment ago: at once

                pf = prefetch.get(rt)
                res = pf.get(call.name, call.arguments)
                if res is None:
                    res = await tools.call(call.name, call.arguments, rt)
                    pf.put(call.name, call.arguments, res)
                if call.name in UNTRUSTED_OUTPUT:
                    self._untrusted_seen = True
                if before is not None and res.ok:
                    try:
                        from .changes import from_text
                        from .tools.files import resolve as _resolve

                        ch = from_text(str(_resolve(call.arguments.get("path", ""))), before, str(call.arguments.get("content", "")))
                        rt.recent_changes.append(ch)
                        rt.bus.publish("jarvis_changes", items=list(rt.recent_changes)[-12:])
                    except Exception as e:  # noqa: BLE001
                        log.debug("change diff: %s", e)
                try:                                           # 3.15 a live picture under some results (weather, flights…)
                    from .livecards import card as live_card

                    live = live_card(call.name, res.ok, res.data)
                except Exception:  # noqa: BLE001
                    live = None
                rt.bus.publish("tool_end", id=call.id, ok=res.ok, summary=res.summary, preview=res.preview, live=live)
                try:                                           # 3.15 volume / brightness / media → the display on the desktop
                    from .overlayfx import after_tool

                    after_tool(rt, call.name, call.arguments or {}, res.ok, res.data, res.summary)
                except Exception:  # noqa: BLE001
                    pass
                if call.name != "update_plan":
                    ms = int((time.monotonic() - t0) * 1000)
                    rt.tasks.log_action(call.name, call.arguments, res.ok, res.summary, ms)
                    from . import quality

                    quality.record_tool(rt, call.name, res.ok, ms)      # Zdraví JARVISe (návrh 16)
        attachments += [a for a in res.attachments if a not in attachments]
        if res.ok:                                     # OMEGA 550: what the answer rests on
            try:
                from .intelplus import sources_from

                for src in sources_from(call.name, call.arguments or {}, res.data, res.summary):
                    if not any(o["ref"] == src["ref"] for o in self._sources):
                        self._sources.append(src)
            except Exception as e:  # noqa: BLE001
                log.debug("sources: %s", e)
        card = {"name": call.name, "label": describe_call(call.name, call.arguments), "ok": res.ok, "summary": res.summary}
        if res.preview:
            card["preview"] = res.preview
        try:
            from .livecards import card as live_card

            lc = live_card(call.name, res.ok, res.data)
            if lc:
                card["live"] = lc
        except Exception:  # noqa: BLE001
            pass
        tool_cards.append(card)
        calls_now = getattr(self, "_turn_calls", None)
        if calls_now is not None and not chose_after_foreign:   # 3.16 what worked for these words (3.17 not what foreign text led to)
            calls_now.append((call.name, dict(call.arguments or {}), bool(res.ok)))
        return {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": res.for_llm()}

    async def _handle(self, text: str, attachments: list[str], source: str, record_user: bool, extra: str) -> str:
        rt = self.rt
        bus = rt.bus
        voice = source in ("voice", "mobile_voice", "headset")      # spoken: short answers without tables or code
        from . import latency                  # 3.16 how long each step takes (Diagnostika)

        lat = latency.get(rt)
        lat.agent_start(source)
        self._goal = text or "(příloha)"
        self._source_now = source
        self._sources = []
        foreign = bool(getattr(self, "_foreign_turn", False))
        # 3.13 full trust asks again after e-mails / web pages were read; 3.17 a picture or pasted text counts from the start
        self._untrusted_seen = foreign or bool(attachments)
        self._own_words = "" if foreign else (text or "")
        rt.request_text = text or ""           # 3.13 close_app: a game is closed only when you named it
        status = "done"
        from . import brainplus                # 3.14 Mozek+: corrections, traits, think twice, private, preface, check

        correction_of = None
        if record_user and getattr(rt.cfg.brain, "learn_corrections", True) and brainplus.is_correction(text or ""):
            prev = [m for m in rt.memory.recent(4) if m["role"] in ("user", "assistant")]
            if len(prev) >= 2 and prev[-1]["role"] == "assistant" and prev[-2]["role"] == "user":
                correction_of = (prev[-2]["text"], prev[-1]["text"])
        if record_user:
            um = rt.memory.add_message("user", text, attachments, source)
            bus.publish("user_message", id=um["id"], text=text, source=source,
                        attachments=[rt.public_attachment(a) for a in attachments])
        bus.publish("state", state="thinking")
        if rt.cfg.agent.mode:
            extra = (extra + "\n" if extra else "") + AGENT_MODE_RULE
        from . import trust

        if trust.on(rt):
            extra = (extra + "\n" if extra else "") + trust.RULE
        full_text = ""
        tool_cards: list[dict] = []
        self._live_cards = tool_cards               # 3.16 what is done so far (a correction mid-way sees it)
        out_atts: list[str] = []
        used_now: list[str] = []
        self._turn_stats = {"use_tool": 0, "use_tool_errors": 0, "find_tools": 0}
        self._turn_calls: list[tuple[str, dict, bool]] = []
        from . import toolmind
        if correction_of is not None:              # 3.16 "ne, to ne": what was done for those words is not a reflex
            try:
                toolmind.punish(rt, correction_of[0])
            except Exception as e:  # noqa: BLE001
                log.debug("tool memory: %s", e)
        cancelled = False
        quick = None                                       # 3.13 an everyday command: done at once, no AI in between
        un = getattr(rt, "unspoken", None)                 # 3.16 (návrh 23) you talked over him a moment ago
        if un and time.time() - un.get("ts", 0) < 120 and not attachments:
            rt.unspoken = None
            if CONTINUE.match((text or "").strip()):
                quick = un["text"]                         # "pokračuj" → the rest of what he was saying, no AI
            else:
                extra = (extra + "\n\n" if extra else "") + f"Uživatel tě přerušil a neslyšel konec tvé předchozí odpovědi: „{un['text'][:400]}“."
        phrase = None if attachments or foreign else rt.automations.phrase_match(text or "") if hasattr(rt.automations, "phrase_match") else None
        if phrase is not None:                             # 3.14 návrh 48: "jdu spát" → your own routine, no AI
            rt.automations.fire(phrase, {"text": text or ""}, reason="phrase", force=True)
            quick = f"Spouštím {phrase.name}."
        if quick is None and not attachments and not foreign and not self._only and getattr(rt.cfg.agent, "instant", True):
            from . import instant

            p = instant.plan(text)
            if p and p.kind == "app" and p.calls[0][0] == "open_app" and not instant.app_known(rt, p.calls[0][1]["name"]):
                p = None                                   # not an app this PC knows ("spusť herní režim"): the AI decides
            if p:
                try:
                    for n, (name, args) in enumerate(p.calls):
                        await self._run_call(ToolCall(id=f"q{n}", name=name, arguments=dict(args)), tool_cards, out_atts)
                    quick = instant.answer(p, tool_cards)
                except Exception as e:  # noqa: BLE001 – anything odd: the AI takes over
                    log.info("instant %s: %s", p.kind, e)
                    quick = None
                if quick is None:
                    tool_cards.clear()
        reflexed = False
        if quick is None and not attachments and not foreign and not self._only and record_user:
            try:                                   # 3.16 the same words went well twice: do it at once, no AI
                rx = toolmind.reflex(rt, text or "", self._allowed_names())
            except Exception as e:  # noqa: BLE001
                log.debug("reflex: %s", e)
                rx = None
            if rx:
                name, args, said = rx
                await self._run_call(ToolCall(id="r0", name=name, arguments=dict(args)), tool_cards, out_atts)
                ok = bool(tool_cards and tool_cards[-1].get("ok"))
                quick = said if ok else (tool_cards[-1].get("summary") if tool_cards else None) or None
                reflexed = quick is not None
        if quick is None and not attachments and not foreign and not self._only and record_user and not self._ASKS.search(text or ""):
            from . import reflexmodel

            if reflexmodel.enabled(rt):            # 3.16 the small model on this PC decides a clear command at once
                self._tool_schemas(text)

                def ok_tool(name: str, args: dict) -> bool:
                    spec = tools.REGISTRY.get(name)
                    t = rt.cfg.tools
                    return bool(spec) and (name in self.DONE_TOOLS or spec.category in self.DONE_CATS) and \
                        not tools.is_dangerous(spec, args, t.always_confirm, t.trusted, rt)
                try:
                    pick = await reflexmodel.route(rt, text or "", list(getattr(self, "_picked", [])), ok_tool)
                except Exception as e:  # noqa: BLE001
                    log.debug("reflex model: %s", e)
                    pick = None
                if pick:
                    await self._run_call(ToolCall(id="m0", name=pick[0], arguments=dict(pick[1])), tool_cards, out_atts)
                    card = tool_cards[-1] if tool_cards else {}
                    if card.get("ok") and card.get("summary"):
                        said = str(card["summary"]).strip()
                        quick = said if said.endswith((".", "!", "?", "…")) else said + "."
                        self._turn_stats["reflex_model"] = 1
                    else:
                        tool_cards.clear()
        msgs: list[dict] = []
        need_vision = False
        schemas: list[dict] = []
        pack = None
        spec_used = None
        if quick is None:
            spec_used = self._take_spec(text or "", attachments, extra, voice)
            if spec_used is not None:                      # 3.17 the AI was already asked before you finished
                msgs, schemas, pack = spec_used["msgs"], spec_used["schemas"], spec_used["pack"]
                self._picked = spec_used["picked"]
                self._turn_stats["speculative"] = 1
            else:
                msgs, need_vision = await self._build_messages(text, attachments, voice, extra)
                schemas = self._tool_schemas(text)
                pack = self._tool_pack()
        speech = rt.speech_stream(source, self._lang)      # 3.12 speaks from the first sentence on
        if speech is not None:
            speech.turn = lat.cur                          # 3.16 the first sound is measured on this answer
        tier, tier_kw, private = await self._routing(text or "", attachments)
        if spec_used is not None:                          # 3.17 the request that already started before the end
            tier_kw = dict(spec_used["tier_kw"])
        if ((tier == "strong" or (tier == "normal" and brainplus.slow_brain(rt))) and speech is not None and quick is None
                and getattr(rt.cfg.brain, "quick_preface", True) and not private):
            async def _say_first() -> None:            # 3.14 návrh 23: one sentence at once while the main model thinks
                line = await brainplus.preface(rt, text or "")
                if line and not speech.spoke:
                    speech.preface(line)
            asyncio.get_running_loop().create_task(_say_first())
        offered = {sc.get("function", sc).get("name") for sc in schemas}
        from_words = set(offered)                  # 3.17 sent with your words (not reached by the AI later on)
        calls: list[ToolCall] | None = None
        rnd = 0
        try:
            rounds = -1 if quick is not None else self._rounds()
            if quick is not None:
                full_text = quick
                bus.publish("assistant_delta", text=quick)
                if speech:
                    speech.feed(quick)
            for rnd in range(rounds + 1):
                if rnd:
                    await rt.tasks.checkpoint()
                round_text = ""
                calls: list[ToolCall] | None = None
                use_tools = schemas if rnd < rounds else None
                shown = 0                                  # 3.13 how much of round_text is on the screen already
                rt.router.catalog_used = False
                source_stream = self._replay(spec_used) if (rnd == 0 and spec_used is not None) else \
                    rt.router.stream(msgs, use_tools, need_vision=need_vision, **tier_kw, catalog=pack,
                                     **({"only": self._only} if self._only else {}))
                async for ch in source_stream:
                    if ch.text or ch.tool_calls:
                        lat.mark("first_token")
                    if ch.text:
                        round_text += ch.text
                        if not only_dots(round_text):      # "..." alone (some models send it between steps) is not shown
                            if not shown and full_text:
                                bus.publish("assistant_delta", text="\n\n")
                                full_text += "\n\n"
                                if speech:
                                    speech.feed("\n\n")
                            new_text = round_text[shown:]
                            shown = len(round_text)
                            full_text += new_text
                            bus.publish("assistant_delta", text=new_text)
                            if speech:
                                speech.feed(new_text)
                    if ch.tool_calls:
                        calls = ch.tool_calls
                if only_dots(round_text):
                    round_text = ""
                if rt.router.last_used:          # 3.12 with how much of today's free AI is left ("Groq · 70 %")
                    from .llm.quota import brain_state

                    bus.publish("brain", **brain_state(rt))
                if not calls:
                    break
                if rnd >= rounds:
                    break
                msgs.append({"role": "assistant", "content": round_text or None, "tool_calls": [c.as_message() for c in calls]})
                results: dict[str, dict] = {}
                run_calls = []                           # 3.16 use_tool → the real tool (its own confirmation and card)
                for c in calls:
                    if c.name != tc.USE:
                        run_calls.append(c)
                        continue
                    u = tc.unwrap(tools.REGISTRY, self._allowed_names(), c.arguments)
                    self._turn_stats["use_tool"] += 1
                    if u.error:
                        self._turn_stats["use_tool_errors"] += 1
                        results[c.id] = {"role": "tool", "tool_call_id": c.id, "name": c.name, "content": u.error}
                        if u.name in tools.REGISTRY and u.name not in offered:   # its exact description for the next step
                            schemas.append(tools.REGISTRY[u.name].schema())
                            offered.add(u.name)
                        continue
                    run_calls.append(ToolCall(id=c.id, name=u.name, arguments=u.args))
                safe = [c for c in run_calls if not (tools.REGISTRY.get(c.name) and tools.is_dangerous(
                    tools.REGISTRY[c.name], c.arguments, rt.cfg.tools.always_confirm, rt.cfg.tools.trusted, rt))
                    and not self._foreign_ask(c.name, c.name in from_words)]
                ack = self._ack_later(speech) if speech is not None and not speech.spoke and run_calls else None
                try:
                    if len(safe) > 1:
                        outs = await asyncio.gather(*(self._run_call(c, tool_cards, out_atts, ai_offered=c.name in from_words)
                                                      for c in safe))
                        results.update({c.id: o for c, o in zip(safe, outs)})
                    for c in run_calls:
                        if c.id not in results:
                            results[c.id] = await self._run_call(c, tool_cards, out_atts, ai_offered=c.name in from_words)
                finally:
                    if ack is not None:
                        ack.cancel()
                for c in calls:                          # the answer goes back under the name the AI called
                    results[c.id]["name"] = c.name
                msgs += [results[c.id] for c in calls]
                used_now += [c.name for c in run_calls if c.name != sel.FIND]
                if any(c.name == sel.FIND for c in calls):
                    self._turn_stats["find_tools"] += 1
                done_text = self._done_by_tools(text or "", round_text, run_calls, tool_cards) if rnd == 0 else ""
                if done_text:                            # 3.16 the tool already said it all: no second AI round
                    full_text += done_text
                    bus.publish("assistant_delta", text=done_text)
                    if speech:
                        speech.feed(done_text)
                    self._turn_stats["skipped_round"] = 1
                    calls = None
                    break
                for c in calls:                          # the AI asked for more tools → they go with the next step
                    if c.name == sel.FIND:
                        for n in sel.search(tools.REGISTRY, str((c.arguments or {}).get("query", "")), 24):
                            if n not in offered and n in self._allowed_names() and len(offered) < 60:
                                schemas.append(tools.REGISTRY[n].schema())
                                offered.add(n)
                bus.publish("state", state="thinking")
            else:
                pass
            self._recent_tools = list(dict.fromkeys(reversed(used_now)))[:8]   # a follow-up ("a teď ho pošli") has them
            cut = bool(calls) and rnd >= rounds              # stopped by the round limit, not by an empty answer
            if not full_text.strip() and cut:
                full_text = "Hotovo."
                bus.publish("assistant_delta", text=full_text)
            elif not full_text.strip():                       # 3.13 the AI sent nothing: ask once more, never answer "…"
                again = ""
                try:
                    again = await rt.router.complete(msgs + [{"role": "system", "content": "Odpověz uživateli teď – krátce, česky, "
                                                              "skutečnými slovy (ne jen tečkami)."}])
                except Exception as e:  # noqa: BLE001
                    log.info("empty answer retry: %s", e)
                full_text = again.strip() if again and not only_dots(again) else "Hotovo." if tool_cards else \
                    "Promiň, AI mi tentokrát neposlala žádnou odpověď. Zkus to prosím napsat ještě jednou."
                bus.publish("assistant_delta", text=full_text)
                if speech:
                    speech.feed(full_text)
        except AllProvidersFailed as e:
            status = "failed"
            log.warning("all providers failed: %s", e)
            bus.publish("error", message=f"Žádný AI poskytovatel neodpověděl: {e}", kind="limit" if e.is_limit else "brain")
            from .brainkey import BLOCKED

            msg = NO_LIMIT if e.is_limit else BLOCKED if "10013" in str(e) or "zakázan" in str(e) else NO_BRAIN
            full_text = (full_text + "\n\n" if full_text else "") + msg
            bus.publish("assistant_delta", text=msg)
        except ProviderError as e:
            status = "failed"
            bus.publish("error", message=str(e))
            full_text += f"\n\n(Spojení s AI se přerušilo: {e})"
        except asyncio.CancelledError:
            cancelled = True
            status = "cancelled"
            full_text = (full_text + " …(přerušeno)").strip()
        except BudgetExceeded as e:
            status = "failed"
            msg = f"{e} Mise zastavena; co je hotové, zůstává. Limit se mění v Nastavení → Oprávnění."
            bus.publish("error", message=msg)
            full_text = (full_text + "\n\n" if full_text else "") + msg
            bus.publish("assistant_delta", text=msg)
        except Exception as e:  # a bug must not leave the task "running" forever
            log.exception("agent failed")
            status = "failed"
            bus.publish("error", message=f"Něco se pokazilo: {type(e).__name__}: {e}")
            full_text = (full_text + "\n\n" if full_text else "") + "Omlouvám se, při práci se něco pokazilo."
        if getattr(rt, "_anchor", None):
            rt.set_anchor(None)
        if rt.tasks.current is not None:
            rt.tasks.finish(status, _first_sentence(full_text))
        am = rt.memory.add_message("assistant", full_text, out_atts, source,
                                   meta={"tools": tool_cards, "brain": rt.router.last_used, "sources": self._sources[:12],
                                         "tier": getattr(self, "tier", ""), **({"private": True} if private else {})})
        bus.publish("assistant_done", id=am["id"], text=full_text, tools=tool_cards, sources=self._sources[:12],
                    attachments=[rt.public_attachment(a) for a in out_atts])
        lat.finish(tools=len(tool_cards), instant=quick is not None, catalog=bool(getattr(rt.router, "catalog_used", False)),
                   status=status, reflex=reflexed, **self._turn_stats)
        if status == "done" and record_user and not reflexed and not private and not foreign and \
                not getattr(rt, "speedcheck_running", False):
            try:
                toolmind.learn(rt, text or "", self._turn_calls, full_text)
            except Exception as e:  # noqa: BLE001
                log.debug("tool memory: %s", e)
        if speech is not None:                      # spoken as it was written; anything added at the end too
            if cancelled:
                speech.cancel()
            else:
                if full_text.startswith(speech.fed) and len(full_text) > len(speech.fed):
                    speech.feed(full_text[len(speech.fed):])
                asyncio.get_running_loop().create_task(speech.finish())
        elif not cancelled:
            rt.maybe_speak(full_text, source, self._lang)
        if status == "done" and not cancelled:      # 3.12 a long chat: summarise its older part in the background
            from . import chatsummary

            asyncio.get_running_loop().create_task(chatsummary.refresh(rt))
        if correction_of and not cancelled:         # 3.14 návrh 24: a rule from the correction, for next time
            asyncio.get_running_loop().create_task(brainplus.learn(rt, correction_of[0], correction_of[1], text or ""))
        if (status == "done" and not cancelled and getattr(rt.cfg.brain, "verify_answers", True)
                and brainplus.worth_checking(full_text, self._sources)):
            texts = [str(m.get("content") or "") for m in msgs if m.get("role") == "tool"
                     and m.get("name") in ("web_read", "read_website", "web_search", "google_ask", "deep_research", "world_news")]
            asyncio.get_running_loop().create_task(self._check_answer(am["id"], full_text, texts))
        return full_text

    async def _check_answer(self, msg_id: str, answer: str, texts: list[str]) -> None:
        """3.14 návrh 26: claims the read pages do not support → marked under the answer."""
        from . import brainplus

        issues = await brainplus.check_answer(self.rt, answer, texts)
        if not issues:
            return
        row = self.rt.db.one("SELECT meta FROM messages WHERE id=?", (msg_id,))
        try:
            meta = __import__("json").loads((row or {}).get("meta") or "{}")
        except ValueError:
            meta = {}
        meta["check"] = issues
        self.rt.db.exec("UPDATE messages SET meta=? WHERE id=?", (__import__("json").dumps(meta, ensure_ascii=False), msg_id))
        self.rt.bus.publish("answer_check", id=msg_id, issues=issues)
