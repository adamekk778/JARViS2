"""The agent's fast paths (3.18 split out of agent.py): the tools' own words as the whole answer, the short
"Moment, pane." and the spoken progress, Claude's cache warmed again, and the answer asked before the end of your
sentence (speculation). A mixin of Agent – it uses the agent's state (self.rt, self._picked, …)."""
from __future__ import annotations

import asyncio
import logging
import re
import time

from . import tools
from .agent_helpers import CONTINUE, MIDRUN
from .tools import select as sel

log = logging.getLogger("jarvis.agent")


class FastPaths:
    # 3.16 (návrh 5) the tools whose own words are the whole answer ("Hlasitost 40 %", "Pouštím …", "Tisk pozastaven.")
    DONE_CATS = {"média", "aplikace", "okna", "domácnost", "čas", "nastavení", "hlas", "mozek"}
    DONE_TOOLS = {"list_add", "list_done", "hud_control", "show_hud", "model_explode", "run_protocol", "send_to_phone", "remember",
                  "printer_control", "model_view"}
    _ASKS = re.compile(r"\?|\b(proč|proc|jak to|vysvětli|vysvetli|shrň|shrn|porovnej|co si myslíš|co si myslis|poraď|porad|"
                       r"navrhni|napiš|napis|kolik|kdy|kde|který|ktery|jaký|jaky|jaká|jaka)\b", re.I)

    ACKS = ("Moment, {a}.", "Hned to bude, {a}.", "Pracuji na tom, {a}.")
    ACK_AFTER_S = 1.2

    PROGRESS_S = 4.0
    # 3.18 (návrh 13) what a tool brings, in one word, for "počasí mám, ještě kalendář"
    NOUNS = {"weather": "počasí", "calendar_list": "kalendář", "calendar_check": "kalendář", "email_inbox": "e-maily",
             "email_search": "e-maily", "email_read": "e-mail", "world_news": "zprávy", "web_search": "hledání na webu",
             "web_read": "stránku", "google_search": "hledání", "parcels_list": "zásilky", "printer_control": "tiskárnu",
             "home_devices": "domácnost", "search_memory": "paměť", "deep_research": "rešerši", "price": "cenu",
             "exchange_rate": "kurz", "transit_departures": "odjezdy", "hotel_search": "hotely", "flight_search": "lety",
             "trip_plan": "plán cesty", "phone_messages": "zprávy z telefonu", "system_info": "stav PC"}

    def _ack_later(self, speech, run: list | None = None, cards: list | None = None) -> asyncio.Task:
        """3.16 (návrh 7) the tools take a while and nothing was said yet: one short word, so you know he is on it.
        3.18 (návrh 13) several tools and it goes on: what is already there and what is still being fetched."""
        start = len(cards) if cards is not None else 0

        async def go() -> None:
            await asyncio.sleep(self.ACK_AFTER_S)
            if not speech.spoke:
                self._acks = getattr(self, "_acks", -1) + 1
                a = (self.rt.cfg.general.address_as or "pane").strip()
                speech.preface(self.ACKS[self._acks % len(self.ACKS)].format(a=a))
            if not run or cards is None or len(run) < 2:
                return
            said: set[str] = set()
            for _ in range(2):
                await asyncio.sleep(self.PROGRESS_S)
                done_names = [c.get("name") for c in cards[start:]]
                done = list(dict.fromkeys(self.NOUNS[n] for n in done_names if n in self.NOUNS))
                left = list(dict.fromkeys(self.NOUNS[c.name] for c in run if c.name in self.NOUNS and c.name not in done_names))
                if not done or not left:
                    continue
                line = f"{', '.join(done)} mám, ještě {' a '.join(left)}."
                if line not in said:
                    said.add(line)
                    speech.progress(line[0].upper() + line[1:])
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

    # ---------- 3.18 (návrh 12) Claude's cache warm again when you start talking after a long pause ----------
    async def warm_cache(self) -> dict | None:
        rt = self.rt
        b = rt.cfg.brain
        if self.busy or not getattr(b, "cache_warm", True) or not any(p.preset == "anthropic" and p.enabled for p in b.providers):
            return None
        ttl = 3600 if getattr(b, "claude_cache_ttl", "1h") == "1h" else 300
        if time.time() - float(getattr(rt.router, "claude_at", 0.0) or 0.0) < ttl * 0.8 or not hasattr(rt.router, "warm_cache"):
            return None                                # still cached (or this router cannot)
        try:
            msgs, _ = await self._build_messages("…", [], True, "")
            schemas = self._tool_schemas("")
            res = await rt.router.warm_cache(msgs, schemas, self._tool_pack())
        except Exception as e:  # noqa: BLE001
            log.debug("cache warm: %s", e)
            return None
        if res:
            from . import latency

            latency.get(rt).note("cache_warm", res)
        return res

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
