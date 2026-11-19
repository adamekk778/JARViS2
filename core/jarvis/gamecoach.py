"""3.13 Herní pomocník: JARVIS knows what you play (the program in front), says so quietly in the notch, gives a short
tip for that game every few minutes, keeps your playing time and results (Herní statistiky) and, while you play, gives
the graphics card back to the game (an offline AI model in memory is unloaded).

Tips: a hand-written set for the most played games; for any other game the AI writes a set once (cached, in Czech).
Nothing here touches the game: it only looks at which program is in front – never inside the game, never its memory.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

log = logging.getLogger(__name__)

TICK_S = 5.0
END_AFTER_S = 60.0          # the game not in front this long = the session is over (alt-tab for a moment is not)
MIN_SESSION_S = 60.0        # shorter than this is not counted

# the program (exe, lower case) → the game's name
KNOWN = {
    "valorant": "Valorant", "cs2": "Counter-Strike 2", "csgo": "Counter-Strike 2", "league of legends": "League of Legends",
    "leagueoflegends": "League of Legends", "fortniteclient": "Fortnite", "robloxplayer": "Roblox", "r5apex": "Apex Legends",
    "overwatch": "Overwatch 2", "rocketleague": "Rocket League", "gta5": "GTA V", "gtav": "GTA V", "eldenring": "Elden Ring",
    "dota2": "Dota 2", "rainbowsix": "Rainbow Six Siege", "fc25": "EA Sports FC", "fc26": "EA Sports FC", "cod": "Call of Duty",
    "minecraft": "Minecraft", "pubg": "PUBG", "tslgame": "PUBG", "deadbydaylight": "Dead by Daylight", "rust": "Rust",
    "cyberpunk2077": "Cyberpunk 2077", "witcher3": "Zaklínač 3", "helldivers2": "Helldivers 2", "marvelrivals": "Marvel Rivals",
}
TIPS: dict[str, list[str]] = {
    "Valorant": [
        "Zastav se před výstřelem – Valorant trestá střelbu za běhu, první kulka je nejpřesnější.",
        "Drž zaměřovač ve výšce hlavy a předmiř roh, odkud soupeř vyleze.",
        "Po každém kole se podívej na minimapu: kde naposled byli, tam budou znovu.",
        "Šetři v kole, kdy nemáš na pušku – v dalším koupíš celý set.",
        "Jett: dash (E) si nech na útěk po zabití, ne na vstup do místnosti.",
        "Komunikuj krátce: kolik jich je, kde a kolik mají života.",
        "Neházej utility naslepo – každý smoke nebo flash má mít důvod.",
        "Když prohráváš souboj, změň úhel – stejný peek dvakrát po sobě soupeř čeká.",
    ],
    "Counter-Strike 2": [
        "Counter-strafe: pusť pohyb a ťukni opačným směrem, pak střílej – přesnost hned.",
        "Krátké dávky na dálku, plný sprej jen zblízka a s kontrolou zpětného rázu.",
        "Kup granáty – jeden dobrý smoke vyhraje kolo víc než lepší zbraň.",
        "Hraj s výhodou čísla: 2 na 1 neber souboj sám.",
        "Poslouchej kroky a házení granátů, zvuk ti řekne, kam jdou.",
    ],
    "League of Legends": [
        "Dívej se na minimapu každých pár vteřin – většina gankerů je vidět předem.",
        "Last-hit miniony: každá zlaťák navíc je rychlejší item.",
        "Warduj křoví u řeky a dráčka, vision vyhrává zápasy.",
        "Po zabití tlač věž nebo ber dráka, neběhej zbytečně zpátky.",
        "Hlídej si cooldowny soupeřů – bez flashe je zranitelný.",
    ],
    "Minecraft": [
        "První noc: postav malý úkryt a pochodně, zombie a creepeři se objevují ve tmě.",
        "Diamanty hledej kolem výšky Y = -58, stripminuj ve dvoublokových chodbách.",
        "Postel nastaví místo znovuzrození – vezmi ji s sebou na výpravu.",
        "Farma na jídlo (pšenice, mrkev) ušetří spoustu času.",
        "Vodní kbelík zachrání pád i lávu – měj ho vždy v hotbaru.",
    ],
    "Roblox": [
        "Nikomu nedávej heslo ani kód z e-mailu – „free Robux“ jsou vždycky podvod.",
        "Přečti si ve hře pravidla a ovládání v menu, každá hra je jiná.",
        "Soukromé servery s kamarády bývají klidnější.",
    ],
    "Fortnite": [
        "Přistávej dál od hlavní cesty bus, v klidu nasbíráš lepší vybavení.",
        "Při přestřelce stav – zeď a rampa dají krytí a výšku.",
        "Hlídej si zónu, ať nemusíš běžet přes otevřené pole.",
        "Léčení si nech na klidnou chvíli za krytem.",
    ],
    "Apex Legends": [
        "Bojuj s týmem – sám proti trojici skoro vždy prohraješ.",
        "Po souboji nejdřív štíty, pak loot.",
        "Pozice na výšce je v Apexu výhoda, ber ji dřív než soupeř.",
    ],
}
GENERIC = [
    "Krátká pauza po pár zápasech osvěží reakce víc než další hra navíc.",
    "Napij se – i lehká žízeň zpomaluje reakce.",
    "Pozor na únavu očí: každých 20 minut se na 20 s podívej do dálky.",
]


def _plain(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower())


def name_for(info: dict) -> str:
    """The game's name from the program in front ('VALORANT-Win64-Shipping.exe' → Valorant)."""
    exe = _plain(str(info.get("exe") or "").lower().removesuffix(".exe")).replace(" ", "")
    title = str(info.get("title") or "")
    for key, name in KNOWN.items():
        k = key.replace(" ", "")
        if k and (k in exe or (len(k) > 4 and k in _plain(title).replace(" ", ""))):
            return name
    if title.strip():
        return re.split(r"\s+[-–|]\s+", title.strip())[0][:40]
    stem = str(info.get("exe") or "").removesuffix(".exe").removesuffix(".EXE")
    return stem[:40] or "hra"


class GameCoach:
    def __init__(self, rt: Any):
        self.rt = rt
        self.game = ""                  # what is being played now ("" = nothing)
        self.since = 0.0
        self.last_seen = 0.0
        self.last_tip = 0.0
        self._tip_i: dict[str, int] = {}
        self._ai_tips: dict[str, list[str]] = {}
        self._asking: set[str] = set()

    # ---------- settings ----------
    def _cfg(self):
        return getattr(self.rt.cfg, "games", None)

    def _on(self, key: str, default: bool = True) -> bool:
        c = self._cfg()
        return bool(getattr(c, key, default)) if c is not None else default

    # ---------- the playing time ----------
    def _db(self):
        db = getattr(self.rt, "db", None)
        if db is not None:
            db.exec("CREATE TABLE IF NOT EXISTS game_sessions (game TEXT, start REAL, seconds REAL)")
            db.exec("CREATE TABLE IF NOT EXISTS game_results (game TEXT, at REAL, result TEXT, score TEXT, note TEXT)")
        return db

    def tick(self, info: dict | None, playing: bool, now: float | None = None) -> None:
        """Called every few seconds with the program in front and whether it is a game."""
        now = time.time() if now is None else now
        if playing and info:
            name = name_for(info)
            if self.game and name != self.game:
                self._end(now)
            if not self.game:
                self._start(name, now)
            self.last_seen = now
            self._maybe_tip(now)
        elif self.game and now - self.last_seen > END_AFTER_S:
            self._end(self.last_seen)

    def _start(self, name: str, now: float) -> None:
        self.game, self.since, self.last_seen = name, now, now
        self.last_tip = now - self._every() + 90          # the first tip a minute and a half in, not at once
        self.rt.bus.publish("game_state", on=True, game=name)
        log.info("game: %s started", name)
        if self._on("boost"):
            self._boost()

    def _end(self, last: float) -> None:
        name, start = self.game, self.since
        self.game, self.since = "", 0.0
        secs = max(0.0, last - start)
        if secs >= MIN_SESSION_S:
            db = self._db()
            if db is not None:
                db.exec("INSERT INTO game_sessions (game, start, seconds) VALUES (?, ?, ?)", (name, start, round(secs, 1)))
        self.rt.bus.publish("game_state", on=False, game=name, minutes=round(secs / 60))
        log.info("game: %s ended after %d min", name, secs // 60)

    # ---------- the graphics card back to the game ----------
    def _boost(self) -> None:
        """A model of the offline AI holds gigabytes of the graphics card: while you play it is unloaded (it loads
        again by itself at the next question). Nothing else is closed."""
        local = getattr(self.rt, "local", None)
        agent = getattr(self.rt, "agent", None)
        if local is None or (agent is not None and getattr(agent, "busy", False)):
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:                      # no running loop (tests): nothing to unload from here
            return
        from .background import bg

        bg(local.unload())

    # ---------- tips ----------
    def _every(self) -> float:
        c = self._cfg()
        return max(2, min(int(getattr(c, "tips_every", 6) or 6), 60)) * 60.0

    def tips_for(self, game: str) -> list[str]:
        return TIPS.get(game) or self._ai_tips.get(game) or self._cached(game) or GENERIC

    def next_tip(self, game: str) -> str:
        tips = self.tips_for(game)
        i = self._tip_i.get(game, 0)
        self._tip_i[game] = i + 1
        return tips[i % len(tips)]

    def _maybe_tip(self, now: float) -> None:
        if not self._on("tips") or now - self.last_tip < self._every():
            return
        self.last_tip = now
        if self.game not in TIPS and not self._cached(self.game):
            self._ask_ai(self.game)
        self.show_tip(self.game, self.next_tip(self.game))

    def show_tip(self, game: str, tip: str) -> None:
        """A quiet card in the notch – the notch shows itself over the game for a moment (never taking the focus)."""
        self.rt.bus.publish("game_tip", game=game, tip=tip)
        hook = getattr(self.rt, "on_game_tip", None)
        if hook is not None:
            try:
                hook()
            except Exception as e:  # noqa: BLE001
                log.debug("game tip hook: %s", e)

    def _cache_file(self):
        from . import paths

        return paths.data_dir() / "game_tips.json"

    def _cached(self, game: str) -> list[str]:
        if game in self._ai_tips:
            return self._ai_tips[game]
        try:
            tips = json.loads(self._cache_file().read_text(encoding="utf-8")).get(game) or []
        except (OSError, ValueError):
            tips = []
        if tips:
            self._ai_tips[game] = tips
        return tips

    def _ask_ai(self, game: str) -> None:
        if game in self._asking or not getattr(self.rt, "router", None):
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._asking.add(game)

        async def run() -> None:
            try:
                text = await self.rt.router.complete([
                    {"role": "system", "content": "Odpovídáš jen JSON polem řetězců, nic jiného."},
                    {"role": "user", "content": f"Napiš 8 krátkých praktických tipů pro hru „{game}“ česky, každý nejvýš "
                                                "120 znaků, pro běžného hráče. Žádné cheaty ani obcházení pravidel."}])
                m = re.search(r"\[.*\]", text or "", re.S)
                tips = [str(t).strip()[:160] for t in json.loads(m.group(0))][:10] if m else []
                if tips:
                    self._ai_tips[game] = tips
                    f = self._cache_file()
                    try:
                        d = json.loads(f.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        d = {}
                    d[game] = tips
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception as e:  # noqa: BLE001 – no AI now: the general tips stay
                log.debug("game tips for %s: %s", game, e)
            finally:
                self._asking.discard(game)
        from .background import bg

        bg(run())

    # ---------- results and statistics ----------
    def log_result(self, result: str, score: str = "", game: str = "", note: str = "", now: float | None = None) -> dict:
        r = {"výhra": "win", "vyhra": "win", "win": "win", "prohra": "loss", "loss": "loss", "remíza": "draw", "remiza": "draw",
             "draw": "draw"}.get(result.strip().lower(), result.strip().lower())
        if r not in ("win", "loss", "draw"):
            raise ValueError("Výsledek je výhra, prohra nebo remíza.")
        g = (game or self.game or self._last_game() or "").strip()
        if not g:
            raise ValueError("Nevím, jakou hru – řekni její název.")
        now = time.time() if now is None else now
        db = self._db()
        if db is not None:
            db.exec("INSERT INTO game_results (game, at, result, score, note) VALUES (?, ?, ?, ?, ?)",
                    (g, now, r, score.strip()[:20], note.strip()[:200]))
        return {"game": g, "result": r, "score": score}

    def _last_game(self) -> str:
        db = self._db()
        row = db.one("SELECT game FROM game_sessions ORDER BY start DESC LIMIT 1") if db is not None else None
        return row["game"] if row else ""

    def stats(self, days: int = 7, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        since = now - days * 86400
        db = self._db()
        per: dict[str, dict] = {}
        if db is not None:
            for r in db.all("SELECT game, SUM(seconds) AS s, COUNT(*) AS n FROM game_sessions WHERE start >= ? GROUP BY game", (since,)):
                per[r["game"]] = {"game": r["game"], "minutes": round(float(r["s"] or 0) / 60), "sessions": int(r["n"] or 0),
                                  "wins": 0, "losses": 0, "draws": 0}
            for r in db.all("SELECT game, result, COUNT(*) AS n FROM game_results WHERE at >= ? GROUP BY game, result", (since,)):
                g = per.setdefault(r["game"], {"game": r["game"], "minutes": 0, "sessions": 0, "wins": 0, "losses": 0, "draws": 0})
                g[{"win": "wins", "loss": "losses", "draw": "draws"}.get(r["result"], "draws")] += int(r["n"] or 0)
        if self.game:                                   # the running session counts too
            g = per.setdefault(self.game, {"game": self.game, "minutes": 0, "sessions": 0, "wins": 0, "losses": 0, "draws": 0})
            g["minutes"] += round((now - self.since) / 60)
            g["sessions"] += 1
        games = sorted(per.values(), key=lambda x: -x["minutes"])
        return {"days": days, "games": games, "minutes": sum(g["minutes"] for g in games), "playing": self.game}


def describe_stats(s: dict) -> str:
    if not s["games"]:
        return f"Za posledních {s['days']} dní jsem žádné hraní nezaznamenal."
    parts = []
    for g in s["games"][:5]:
        h, m = divmod(g["minutes"], 60)
        t = f"{h} h {m} min" if h else f"{m} min"
        wl = f", {g['wins']} výher / {g['losses']} proher" if g["wins"] or g["losses"] else ""
        parts.append(f"{g['game']} {t} ({g['sessions']}×{wl})")
    return f"Za posledních {s['days']} dní: " + "; ".join(parts) + "."


async def loop(rt: Any) -> None:  # pragma: no cover – Windows: the program in front
    coach = rt.gamecoach
    from .tools.apps import front_is_game

    while True:
        await asyncio.sleep(TICK_S)
        try:
            info = await asyncio.to_thread(rt.platform.foreground_info) or {}
            playing = await asyncio.to_thread(front_is_game, info if info.get("path") else None)
            coach.tick(info, playing)
        except Exception as e:  # noqa: BLE001
            log.debug("game coach: %s", e)

