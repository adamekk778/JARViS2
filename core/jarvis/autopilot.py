"""3.13 Hraní za tebe: "zahraj si za mě Roblox, budu pryč" – JARVIS looks at the screen, decides what to do (by what
you explained about the game) and presses keys / turns the camera / clicks, again and again, until the time is up.

- It stops by itself when you touch the mouse or keyboard (you are back), on STOP, on "Převzít kontrolu" in the notch,
  when the time is up, or when the AI keeps failing.
- It never writes in the game's chat, never buys anything (real money, Robux), never leaves the game or changes the
  account – those keys and actions are not given to the AI at all.
- What you explained about a game is remembered: next time "zahraj si za mě Roblox" is enough.
- It is as fast as the AI answers (about one move a second or two) – fine for exploring, collecting, AFK games;
  not for fast fights. Many online games (Roblox too) forbid bots in their rules and can ban an account for it.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import time
from typing import Any

log = logging.getLogger(__name__)
MAX_MINUTES = 240
MAX_ACTIONS = 5
SHOT_W = 960
# the only keys the AI gets: movement, jump, sprint, interact, tools – no chat ("/", Enter), no Esc (menu → leave)
KEYS = {"w", "a", "s", "d", "space", "shift", "ctrl", "e", "q", "r", "f", "g", "c", "x", "z", "v", "1", "2", "3", "4", "5", "6", "7",
        "8", "9", "up", "down", "left", "right"}
RULE = ("Hraješ za uživatele počítačovou hru „{game}“, zatímco je pryč od PC. Co uživatel o hře řekl (drž se toho):\n{how}\n\n"
        "Dostaneš snímek obrazovky {w}×{h} px. Odpověz JEN JSON: {{\"note\": \"co vidíš a co teď děláš (jedna krátká věta česky)\", "
        "\"actions\": [nejvýš {n} akcí], \"done\": false}}. Akce:\n"
        "{{\"keys\": [\"w\"], \"ms\": 800}} = drž klávesy (dovolené: {keys}); {{\"mouse\": [dx, dy]}} = otoč kamerou o tolik pixelů "
        "(−400…400); {{\"click\": [x, y]}} = klikni na místo na snímku; {{\"button\": \"left\"|\"right\", \"ms\": 100}} = klikni tam, "
        "kde je kurzor; {{\"wait\": 500}} = počkej.\n"
        "NIKDY: nepiš do chatu, nenakupuj (skutečné peníze, Robux, prémiové věci), neklikej na nákupní okna ani reklamy, neopouštěj "
        "hru, neměň nastavení účtu. Když je na obrazovce nákup nebo dialog, který neznáš, zavři ho jen tlačítkem křížku. "
        "\"done\": true jen když je úkol od uživatele splněný nebo hra skončila.")


def _memory_file():
    from . import paths

    return paths.data_dir() / "autopilot.json"


def saved_how(game: str) -> str:
    try:
        return json.loads(_memory_file().read_text(encoding="utf-8")).get(game.strip().lower(), "")
    except (OSError, ValueError):
        return ""


def remember_how(game: str, how: str) -> None:
    f = _memory_file()
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d[game.strip().lower()] = how[:4000]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def parse(text: str) -> dict:
    """The AI's answer → {"note", "actions", "done"}; only the allowed actions survive."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("AI neposlala tah")
    d = json.loads(m.group(0))
    out: list[dict] = []
    for a in d.get("actions") or []:
        if len(out) >= MAX_ACTIONS:
            break
        if not isinstance(a, dict):
            continue
        if "keys" in a:
            ks = [str(k).lower() for k in (a["keys"] if isinstance(a["keys"], list) else [a["keys"]])][:3]
            if ks and all(k in KEYS for k in ks):
                out.append({"keys": ks, "ms": max(30, min(int(a.get("ms") or 300), 3000))})
        elif "mouse" in a:
            dx, dy = (list(a["mouse"]) + [0, 0])[:2]
            out.append({"mouse": [max(-400, min(int(dx), 400)), max(-400, min(int(dy), 400))]})
        elif "click" in a:
            x, y = (list(a["click"]) + [0, 0])[:2]
            out.append({"click": [int(x), int(y)]})
        elif "button" in a:
            out.append({"button": "right" if a["button"] == "right" else "left", "ms": max(20, min(int(a.get("ms") or 80), 1500))})
        elif "wait" in a:
            out.append({"wait": max(0, min(int(a["wait"]), 3000))})
    return {"note": str(d.get("note") or "")[:200], "actions": out, "done": bool(d.get("done"))}


class Autopilot:
    def __init__(self, rt: Any):
        self.rt = rt
        self.task: asyncio.Task | None = None
        self.game = ""
        self.how = ""
        self.until = 0.0
        self.started = 0.0
        self.steps = 0
        self.note = ""
        self.why = ""

    @property
    def on(self) -> bool:
        return self.task is not None and not self.task.done()

    def status(self) -> dict:
        return {"on": self.on, "game": self.game, "steps": self.steps, "note": self.note, "why": self.why,
                "left_s": max(0, round(self.until - time.time())) if self.on else 0}

    def _emit(self) -> None:
        self.rt.bus.publish("autopilot", **self.status())

    async def start(self, game: str, how: str = "", minutes: int = 30) -> str:
        p = self.rt.platform
        if not getattr(p, "game_input_ok", lambda: False)():
            raise ValueError("Hrát za tebe umím jen ve Windows.")
        game = " ".join(str(game or "").split())[:60] or "hra"
        first = not saved_how(game)
        if how.strip():
            remember_how(game, how.strip())
        self.how = how.strip() or saved_how(game) or "Uživatel nic nevysvětlil – zjisti z obrazovky, o co ve hře jde, a hraj rozumně."
        if self.on:
            await self.stop("nová hra")
        self.game, self.steps, self.note, self.why = game, 0, "", ""
        self.started = time.time()
        self.until = self.started + max(1, min(int(minutes or 30), MAX_MINUTES)) * 60
        try:                                              # the game's window in front
            await asyncio.to_thread(p.window_action, "focus", game)
        except Exception as e:  # noqa: BLE001
            log.debug("autopilot focus: %s", e)
        self.task = asyncio.get_running_loop().create_task(self._loop())
        self._emit()
        warn = (" (Jen jednou pro info: pravidla online her jako Roblox boty zakazují a za hraní programem může přijít ban účtu.)"
                if first and how.strip() else "")
        return (f"Hraju {game} za tebe ({max(1, min(int(minutes or 30), MAX_MINUTES))} min). Jakmile sáhneš na myš nebo klávesnici, "
                "hru ti hned vrátím." + warn)

    async def stop(self, why: str = "") -> None:
        self.why = why or self.why
        t, self.task = self.task, None
        if t and not t.done() and t is not asyncio.current_task():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        try:
            self.rt.platform.release_all_input()
        except Exception:  # noqa: BLE001
            pass
        self._emit()

    def _shot(self) -> tuple[str, int, int, float]:
        from PIL import Image

        raw = self.rt.platform.screenshot()
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        scale = SHOT_W / im.width if im.width > SHOT_W else 1.0
        if scale != 1.0:
            im = im.resize((SHOT_W, int(im.height * scale)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=60)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), im.width, im.height, scale

    async def _ask(self, url: str, w: int, h: int, last: list[str]) -> dict:
        sys_text = RULE.format(game=self.game, how=self.how, w=w, h=h, n=MAX_ACTIONS, keys=", ".join(sorted(KEYS)))
        msgs = [{"role": "system", "content": sys_text},
                {"role": "user", "content": [{"type": "text", "text": f"Tah {self.steps + 1}. Tvoje poslední tahy: "
                                              + (" | ".join(last[-4:]) or "zatím žádné") + ". Co uděláš teď?"},
                                             {"type": "image_url", "image_url": {"url": url}}]}]
        return parse(await self.rt.router.complete(msgs, need_vision=True, fast=True))

    async def _do(self, a: dict, scale: float) -> None:
        p = self.rt.platform
        if "keys" in a:
            await asyncio.to_thread(p.game_keys, a["keys"], a["ms"])
        elif "mouse" in a:
            await asyncio.to_thread(p.game_mouse, *a["mouse"])
        elif "click" in a:
            await asyncio.to_thread(p.move, int(a["click"][0] / scale), int(a["click"][1] / scale))
            await asyncio.to_thread(p.game_click, "left", 60)
        elif "button" in a:
            await asyncio.to_thread(p.game_click, a["button"], a["ms"])
        elif "wait" in a:
            await asyncio.sleep(a["wait"] / 1000)

    def _you_are_back(self, ours: float) -> bool:
        """Input that is not ours: Windows' idle time is shorter than the time since our own last move."""
        try:
            idle = float(self.rt.platform.idle_seconds() or 0)
        except Exception:  # noqa: BLE001
            return False
        return 0 < idle < (time.monotonic() - ours) - 0.6

    async def _loop(self) -> None:
        fails, last, ours = 0, [], time.monotonic()
        try:
            while time.time() < self.until:
                await self.rt.pc_control.wait_if_taken()        # "Převzít kontrolu" in the notch: wait
                if self._you_are_back(ours):
                    self.why = "Jsi zpátky – hra je zase tvoje."
                    break
                try:
                    url, w, h, scale = await asyncio.to_thread(self._shot)
                    move = await self._ask(url, w, h, last)
                    fails = 0
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 – the AI is busy / a limit: wait and try again
                    fails += 1
                    log.info("autopilot step: %s", e)
                    if fails >= 6:
                        self.why = f"AI teď neodpovídá ({str(e)[:80]}) – hraní jsem ukončil."
                        break
                    await asyncio.sleep(min(30, 4 * fails))
                    continue
                if self._you_are_back(ours):
                    self.why = "Jsi zpátky – hra je zase tvoje."
                    break
                self.steps += 1
                self.note = move["note"]
                last.append(move["note"] or ", ".join(next(iter(a)) for a in move["actions"]))
                async with self.rt.pc_control.session("game"):
                    for a in move["actions"]:
                        await self._do(a, scale)
                ours = time.monotonic()
                self._emit()
                if move["done"]:
                    self.why = "Úkol ve hře je hotový."
                    break
                await asyncio.sleep(0.3)
            else:
                self.why = "Čas na hraní vypršel."
        except asyncio.CancelledError:
            self.why = self.why or "Zastaveno."
            raise
        finally:
            try:
                self.rt.platform.release_all_input()
            except Exception:  # noqa: BLE001
                pass
            self.task = None
            self._emit()
            try:
                self.rt.notify(f"Hraní za tebe skončilo ({self.game})", f"{self.why} Tahů: {self.steps}.", speak=False)
            except Exception:  # noqa: BLE001
                pass


def of(rt: Any) -> Autopilot:
    ap = getattr(rt, "autopilot", None)
    if ap is None:
        ap = Autopilot(rt)
        rt.autopilot = ap
    return ap
