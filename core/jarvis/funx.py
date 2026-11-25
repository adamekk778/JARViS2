"""3.20 Zábava+ (ideas 341–360): a coach line after a match, a playlist by mood, board-game scores, a film for tonight,
one library of Steam / Epic / GOG games, sales on your wish list, a music quiz and a quiz on the guests' phones, podcasts
without the sponsor parts, a text adventure, a kids' play timer, an equaliser by genre, photos into albums, a video
shortened by voice, songs from the radio into a list, a Discord companion, series you watch, a random game for today,
concerts of your bands, and your own notification sounds.

Services that need a key (TMDB for films, Ticketmaster for concerts) say so; the rest is free or local."""
from __future__ import annotations

import datetime as dt
import io
import json
import math
import os
import random
import re
import secrets as pysecrets
import shutil
import sys
import subprocess
import time
import unicodedata
import wave
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS fx_scores (game TEXT, player TEXT, points REAL, ts REAL);
CREATE TABLE IF NOT EXISTS fx_wish (title TEXT PRIMARY KEY, target REAL, last REAL, deal TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS fx_shows (name TEXT PRIMARY KEY, tvmaze INTEGER, season INTEGER, episode INTEGER, next_air TEXT, told TEXT);
CREATE TABLE IF NOT EXISTS fx_play (kid TEXT, day TEXT, minutes REAL, started REAL, warned INTEGER, PRIMARY KEY (kid, day));
CREATE TABLE IF NOT EXISTS fx_quiz (token TEXT PRIMARY KEY, data TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS fx_adventure (id INTEGER PRIMARY KEY CHECK (id = 1), state TEXT, log TEXT);
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_funx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._funx_ready = True
    return rt.db


def cfg(rt: Any) -> Any:
    from .config import FunXCfg

    return getattr(rt.cfg, "funx", None) or FunXCfg()


# ------------------------------------------------------------------ (341) the coach after a match
def coach_line(results: list[dict], sessions: list[dict], now: float) -> str:
    """One piece of advice from your own numbers (results newest first: {result, at}; sessions: {start, seconds})."""
    if not results:
        return ""
    streak = 0
    for r in results:
        if r["result"] != "loss":
            break
        streak += 1
    if streak >= 3:
        return f"{streak} prohry za sebou – dej si 10 minut pauzu, tilt hraje proti tobě."
    late = [r for r in results if dt.datetime.fromtimestamp(r["at"]).hour >= 23 or dt.datetime.fromtimestamp(r["at"]).hour < 4]
    day = [r for r in results if r not in late]
    if len(late) >= 5 and len(day) >= 5:
        wl = sum(r["result"] == "win" for r in late) / len(late)
        wd = sum(r["result"] == "win" for r in day) / len(day)
        if wd - wl >= 0.15:
            return f"Po jedenácté večer vyhráváš {wl:.0%}, přes den {wd:.0%} – ranked hraj radši dřív."
    today = [s for s in sessions if now - s["start"] < 86400]
    hours = sum(s["seconds"] for s in today) / 3600
    if hours >= 3:
        return f"Dnes už máš {hours:.1f} h – po třech hodinách klesá reakční doba, protáhni se a napij se."
    last10 = results[:10]
    if len(last10) >= 6:
        rate = sum(r["result"] == "win" for r in last10) / len(last10)
        if rate >= 0.7:
            return f"Posledních {len(last10)} zápasů {rate:.0%} výher – formu máš, drž stejnou rutinu."
    return ""


def coach_for(rt: Any, game: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    try:
        res = [dict(r) for r in rt.db.all("SELECT result, at FROM game_results WHERE game=? ORDER BY at DESC LIMIT 60", (game,))]
        ses = [dict(r) for r in rt.db.all("SELECT start, seconds FROM game_sessions WHERE start >= ?", (now - 86400,))]
    except Exception:  # noqa: BLE001 – no game tables yet
        return ""
    return coach_line(res, ses, now)


# ------------------------------------------------------------------ (342) playlist by mood
MOODS = {
    "soustred": ("lo-fi beats focus instrumental", 60, 90), "prace": ("deep focus instrumental", 60, 100),
    "uceni": ("study music piano ambient", 50, 80), "klid": ("calm acoustic chill", 50, 85), "span": ("sleep ambient soft", 40, 65),
    "energ": ("upbeat energetic pop rock", 120, 170), "cvic": ("workout gym motivation", 125, 175), "beh": ("running 170 bpm", 160, 180),
    "parta": ("party hits dance", 115, 130), "smut": ("sad acoustic ballads", 55, 85), "romant": ("romantic love songs", 60, 100),
    "vari": ("cooking jazz bossa nova", 80, 120), "rano": ("morning coffee acoustic", 80, 110), "auto": ("road trip classics", 100, 140),
}


def mood_of(text: str) -> str:
    t = fold(text)
    return next((k for k in MOODS if k in t), "klid")


def mood_query(text: str, history: list[dict] | None = None) -> dict:
    """A search for the mood, nudged toward artists you already play (history: [{artist, title}], newest first)."""
    key = mood_of(text)
    q, lo, hi = MOODS[key]
    artists = [h.get("artist", "") for h in (history or []) if h.get("artist")]
    fav = max(set(artists), key=artists.count) if artists else ""
    return {"mood": key, "query": q if not fav or key in ("span", "soustred", "uceni") else f"{fav} {q.split()[0]} mix",
            "bpm": (lo, hi), "fav": fav}


# ------------------------------------------------------------------ (343) board games
def score_add(rt: Any, game: str, player: str, points: float) -> None:
    db(rt).exec("INSERT INTO fx_scores VALUES (?,?,?,?)", (fold(game), player.strip().capitalize(), points, time.time()))


def score_table(rt: Any, game: str, since_h: float = 12) -> list[dict]:
    rows = db(rt).all("SELECT player, SUM(points) p, COUNT(*) n FROM fx_scores WHERE game=? AND ts >= ? GROUP BY player ORDER BY p DESC",
                      (fold(game), time.time() - since_h * 3600))
    return [{"player": r["player"], "points": r["p"], "rounds": r["n"]} for r in rows]


def score_reset(rt: Any, game: str) -> None:
    db(rt).exec("DELETE FROM fx_scores WHERE game=?", (fold(game),))


RULES_PROMPT = ("Jsi rozhodčí deskových her. Odpověz česky, krátce a přesně podle oficiálních pravidel hry „{game}“: {ask}. "
                "Když si nejsi jistý nebo se pravidla liší podle vydání, řekni to.")


# ------------------------------------------------------------------ (344) a film for tonight (TMDB)
MOOD_GENRES = {"smich": [35], "komed": [35], "napet": [53, 80], "strach": [27], "akc": [28], "romant": [10749], "rodin": [10751, 16],
               "deti": [16, 10751], "dokument": [99], "sci": [878], "fantas": [14], "drama": [18], "valk": [10752], "krimi": [80],
               "historic": [36], "hudb": [10402], "western": [37], "dobrodruz": [12]}
PROVIDERS_CZ = {"netflix": 8, "disney": 337, "hbo": 1899, "max": 1899, "prime": 119, "amazon": 119, "apple": 350, "skyshowtime": 1773,
                "voyo": 1830, "oneplay": 2412}


def genres_for(text: str) -> list[int]:
    t = fold(text)
    out: list[int] = []
    for k, g in MOOD_GENRES.items():
        if k in t:
            out += g
    return sorted(set(out))


def parse_tmdb(data: dict, limit: int = 5) -> list[dict]:
    out = []
    for m in (data.get("results") or [])[:limit]:
        out.append({"title": m.get("title") or m.get("name") or "", "year": (m.get("release_date") or "")[:4],
                    "rating": m.get("vote_average"), "overview": (m.get("overview") or "")[:240], "id": m.get("id")})
    return out


async def film_tonight(rt: Any, mood: str, services: list[str], client=None) -> list[dict]:
    import httpx

    from . import secrets

    key = secrets.get("tmdb")
    if not key:
        raise ValueError("Na filmy podle tvých služeb potřebuju klíč TMDB (themoviedb.org → Nastavení → API, zdarma) – ulož ho jako „tmdb“.")
    prov = sorted({PROVIDERS_CZ[s] for s in (fold(x) for x in services) if s in PROVIDERS_CZ})
    params: dict[str, Any] = {"api_key": key, "language": "cs-CZ", "watch_region": "CZ", "sort_by": "popularity.desc",
                              "vote_average.gte": 6.5, "vote_count.gte": 300}
    if prov:
        params["with_watch_providers"] = "|".join(map(str, prov))
        params["with_watch_monetization_types"] = "flatrate"
    g = genres_for(mood)
    if g:
        params["with_genres"] = "|".join(map(str, g))
    own = client is None
    c = client or httpx.AsyncClient(timeout=15)
    try:
        r = await c.get("https://api.themoviedb.org/3/discover/movie", params=params)
        r.raise_for_status()
        films = parse_tmdb(r.json(), 8)
    finally:
        if own:
            await c.aclose()
    random.shuffle(films)
    return films[:3]


# ------------------------------------------------------------------ (345) one game library, (358) a random game
def parse_vdf(text: str) -> dict:
    """Valve's KeyValues text (libraryfolders.vdf, appmanifest_*.acf) → nested dicts."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack: list[dict] = [{}]
    key = None
    for s, brace in tokens:
        if brace == "{":
            new: dict = {}
            stack[-1][key or ""] = new
            stack.append(new)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = s
        else:
            stack[-1][key] = s
            key = None
    return stack[0]


def steam_games(steam_dir: Path) -> list[dict]:
    lib = steam_dir / "steamapps" / "libraryfolders.vdf"
    folders = [steam_dir]
    if lib.is_file():
        data = parse_vdf(lib.read_text(encoding="utf-8", errors="ignore")).get("libraryfolders", {})
        folders += [Path(v["path"]) for v in data.values() if isinstance(v, dict) and v.get("path")]
    out = {}
    for f in folders:
        for acf in (f / "steamapps").glob("appmanifest_*.acf"):
            st = parse_vdf(acf.read_text(encoding="utf-8", errors="ignore")).get("AppState", {})
            if st.get("appid") and st.get("name") and "Steamworks" not in st["name"] and "Redistributable" not in st["name"]:
                out[st["appid"]] = {"store": "Steam", "id": st["appid"], "name": st["name"], "launch": f"steam://rungameid/{st['appid']}",
                                    "size_gb": round(int(st.get("SizeOnDisk", 0) or 0) / 1e9, 1),
                                    "last": int(st.get("LastPlayed", 0) or st.get("LastUpdated", 0) or 0)}
    return list(out.values())


def epic_games(manifests: Path) -> list[dict]:
    out = []
    for item in manifests.glob("*.item"):
        try:
            d = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
        except ValueError:
            continue
        if d.get("bIsApplication", True) and d.get("DisplayName") and not d.get("bIsIncompleteInstall"):
            out.append({"store": "Epic", "id": d.get("AppName", ""), "name": d["DisplayName"],
                        "launch": f"com.epicgames.launcher://apps/{d.get('CatalogNamespace', '')}%3A{d.get('CatalogItemId', '')}%3A"
                                  f"{d.get('AppName', '')}?action=launch&silent=true", "size_gb": round(int(d.get("InstallSize", 0) or 0) / 1e9, 1),
                        "last": 0})
    return out


def gog_games() -> list[dict]:  # pragma: no cover – Windows registry
    out: list[dict] = []
    if sys.platform != "win32":
        return out
    import winreg
    for base in (r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"):
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
        except OSError:
            continue
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                k = winreg.OpenKey(root, sub)
                name = winreg.QueryValueEx(k, "gameName")[0]
                exe = winreg.QueryValueEx(k, "exe")[0]
                out.append({"store": "GOG", "id": sub, "name": name, "launch": exe, "size_gb": 0, "last": 0})
            except OSError:
                continue
    return out


def game_library(steam_dir: str = "", epic_dir: str = "") -> list[dict]:
    games: list[dict] = []
    sd = Path(steam_dir) if steam_dir else Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam"
    if (sd / "steamapps").is_dir():
        games += steam_games(sd)
    ed = Path(epic_dir) if epic_dir else Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    if ed.is_dir():
        games += epic_games(ed)
    games += gog_games()
    return sorted(games, key=lambda g: g["name"].lower())


def random_game(games: list[dict], played_recently: set[str] | None = None, rnd: random.Random | None = None) -> dict | None:
    """Rather something you have not played for a while (weights by days since the last play)."""
    if not games:
        return None
    r = rnd or random.Random()
    recent = {fold(x) for x in (played_recently or set())}
    now = time.time()
    weights = []
    for g in games:
        days = (now - g["last"]) / 86400 if g.get("last") else 60
        weights.append(0.2 if fold(g["name"]) in recent else 1 + min(days, 120) / 30)
    return r.choices(games, weights=weights, k=1)[0]


# ------------------------------------------------------------------ (346) sales on the wish list (CheapShark, free)
def parse_cheapshark(items: list[dict]) -> dict | None:
    if not items:
        return None
    best = min(items, key=lambda x: float(x.get("cheapest") or 9e9))
    return {"title": best.get("external", ""), "price": float(best.get("cheapest") or 0), "id": best.get("gameID", ""),
            "url": f"https://www.cheapshark.com/redirect?dealID={best.get('cheapestDealID', '')}" if best.get("cheapestDealID") else ""}


def wish_add(rt: Any, title: str, target: float = 0) -> None:
    db(rt).exec("INSERT OR REPLACE INTO fx_wish VALUES (?,?,?,?,?)", (title.strip(), target, None, "", time.time()))


def wish_list(rt: Any) -> list[dict]:
    return [dict(r) for r in db(rt).all("SELECT * FROM fx_wish ORDER BY title")]


async def wish_check(rt: Any, client=None) -> list[str]:
    import httpx

    said = []
    own = client is None
    c = client or httpx.AsyncClient(timeout=15)
    try:
        for w in wish_list(rt):
            r = await c.get("https://www.cheapshark.com/api/1.0/games", params={"title": w["title"], "limit": 5})
            if r.status_code != 200:
                continue
            deal = parse_cheapshark(r.json())
            if not deal:
                continue
            last = w["last"]
            hit = (w["target"] and deal["price"] <= w["target"]) or (last is not None and deal["price"] < float(last) * 0.75)
            db(rt).exec("UPDATE fx_wish SET last=?, deal=? WHERE title=?", (deal["price"], deal["url"], w["title"]))
            if hit and (last is None or deal["price"] < float(last)):
                said.append(f"{deal['title'] or w['title']} je teď za ${deal['price']:.2f}" + (f" (hlídáš ${w['target']:g})" if w["target"] else "")
                            + (f": {deal['url']}" if deal["url"] else ""))
    finally:
        if own:
            await c.aclose()
    return said


# ------------------------------------------------------------------ (347, 355) quiz on the guests' phones
BUILTIN_QUIZ = [
    {"q": "Kolik kostí má dospělý člověk?", "a": ["206", "186", "226", "306"], "ok": 0},
    {"q": "Které je nejvyšší pohoří České republiky?", "a": ["Šumava", "Krkonoše", "Jeseníky", "Beskydy"], "ok": 1},
    {"q": "Kolik nohou má pavouk?", "a": ["6", "8", "10", "12"], "ok": 1},
    {"q": "Jaká planeta je nejblíž Slunci?", "a": ["Venuše", "Mars", "Merkur", "Země"], "ok": 2},
    {"q": "Ve kterém roce vznikla Česká republika?", "a": ["1989", "1992", "1993", "2004"], "ok": 2},
    {"q": "Kolik minut má den?", "a": ["1 240", "1 440", "1 560", "1 640"], "ok": 1},
    {"q": "Jaký prvek má značku Fe?", "a": ["Fluor", "Železo", "Fosfor", "Ferum"], "ok": 1},
    {"q": "Kolik hráčů má fotbalový tým na hřišti?", "a": ["9", "10", "11", "12"], "ok": 2},
    {"q": "Která řeka protéká Prahou?", "a": ["Labe", "Morava", "Vltava", "Ohře"], "ok": 2},
    {"q": "Kolik je 7 × 8?", "a": ["54", "56", "58", "64"], "ok": 1},
]
QUIZ_PROMPT = ("Vymysli {n} kvízových otázek česky na téma „{topic}“ pro partu přátel. Každá má 4 možnosti a jednu správnou. "
               "Vrať JEN JSON pole: [{{\"q\": \"…\", \"a\": [\"…\",\"…\",\"…\",\"…\"], \"ok\": index správné}}].")


def parse_quiz(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
    except ValueError:
        return []
    out = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("a"), list) and len(it["a"]) >= 2 and isinstance(it.get("ok"), int) \
                and 0 <= it["ok"] < len(it["a"]) and it.get("q"):
            out.append({"q": str(it["q"])[:200], "a": [str(x)[:80] for x in it["a"][:4]], "ok": int(it["ok"])})
    return out


def music_round(files: list[Path], n: int = 8, rnd: random.Random | None = None) -> list[dict]:
    """Questions from your own music files: a clip plays on the PC, the phones pick the song among four."""
    r = rnd or random.Random()
    songs = [(f, song_name(f)) for f in files]
    if len(songs) < 4:
        return []
    out = []
    for f, name in r.sample(songs, min(n, len(songs))):
        wrong = r.sample([s for _, s in songs if s != name], 3)
        opts = [name, *wrong]
        r.shuffle(opts)
        out.append({"q": "Která je to písnička?", "a": opts, "ok": opts.index(name), "clip": str(f), "start": r.randint(30, 60)})
    return out


def song_name(f: Path) -> str:
    return re.sub(r"^\d+[\s._-]+", "", f.stem).replace("_", " ").strip()


def quiz_create(rt: Any, questions: list[dict], title: str = "Kvíz") -> str:
    tok = pysecrets.token_urlsafe(6)
    data = {"title": title, "q": questions, "i": -1, "players": {}, "answers": {}, "open": False}
    db(rt).exec("INSERT INTO fx_quiz VALUES (?,?,?)", (tok, json.dumps(data, ensure_ascii=False), time.time()))
    return tok


def quiz_get(rt: Any, tok: str) -> dict | None:
    row = db(rt).one("SELECT data FROM fx_quiz WHERE token=?", (tok,))
    return json.loads(row["data"]) if row else None


def quiz_save(rt: Any, tok: str, data: dict) -> None:
    db(rt).exec("UPDATE fx_quiz SET data=? WHERE token=?", (json.dumps(data, ensure_ascii=False), tok))


def quiz_join(rt: Any, tok: str, name: str) -> tuple[str, str]:
    """(the player's name as shown, their key) – the key goes with each answer so nobody answers for someone else."""
    d = quiz_get(rt, tok)
    if d is None:
        raise KeyError(tok)
    if len(d["players"]) >= 60:
        raise ValueError("Kvíz je plný.")
    nm = re.sub(r"\s+", " ", name or "").strip()[:20] or f"Hráč {len(d['players']) + 1}"
    base, n = nm, 2
    while nm in d["players"]:
        nm, n = f"{base} {n}", n + 1
    key = pysecrets.token_urlsafe(8)
    d["players"][nm] = 0
    d.setdefault("keys", {})[nm] = key
    quiz_save(rt, tok, d)
    return nm, key


def quiz_next(rt: Any, tok: str) -> dict:
    """Close the current question (score it) and open the next one."""
    d = quiz_get(rt, tok)
    if d is None:
        raise KeyError(tok)
    quiz_score(d)
    d["i"] += 1
    d["answers"] = {}
    d["open"] = d["i"] < len(d["q"])
    d["opened_at"] = time.time()
    quiz_save(rt, tok, d)
    return d


def quiz_score(d: dict) -> None:
    if 0 <= d["i"] < len(d["q"]) and d.get("open"):
        ok = d["q"][d["i"]]["ok"]
        for who, a in d["answers"].items():
            if a["pick"] == ok:
                fast = max(0.0, 10 - (a["t"] - d.get("opened_at", a["t"])))      # up to 10 points more for being quick
                d["players"][who] = d["players"].get(who, 0) + 100 + round(fast * 10)
        d["open"] = False


def quiz_answer(rt: Any, tok: str, who: str, pick: int, key: str = "") -> bool:
    d = quiz_get(rt, tok)
    if d is None or not d.get("open") or who not in d["players"] or who in d["answers"]:
        return False
    if not pysecrets.compare_digest(str(d.get("keys", {}).get(who, "")), str(key or "")):
        return False
    if not 0 <= pick < len(d["q"][d["i"]]["a"]):
        return False
    d["answers"][who] = {"pick": pick, "t": time.time()}
    quiz_save(rt, tok, d)
    return True


def quiz_public(d: dict, host: bool = False) -> dict:
    cur = d["q"][d["i"]] if 0 <= d["i"] < len(d["q"]) else None
    out: dict[str, Any] = {"title": d["title"], "n": len(d["q"]), "i": d["i"], "open": d["open"],
                           "players": sorted(d["players"].items(), key=lambda x: -x[1]), "answered": sorted(d["answers"])}
    if cur:
        out["q"] = {"q": cur["q"], "a": cur["a"], "music": bool(cur.get("clip"))}
        if not d["open"] or host:
            out["ok"] = cur["ok"] if not d["open"] else None
    out["done"] = d["i"] >= len(d["q"])
    return out


# ------------------------------------------------------------------ (348) podcasts without the sponsor parts
AD_WORDS = re.compile(r"(sponzor|partner(em)? (dnesniho|tohoto) dilu|tento dil (vam )?prinasi|diky (nasemu )?partner|slevov\w* kod|"
                      r"promo ?kod|s kodem|sponsored by|this episode is brought|use (the )?code|promo code|support for this|"
                      r"go to \S+\.com/|link (je )?v popisku|odkaz v popisu)")


def ad_segments(segments: list[dict], pad: float = 2.0, max_len: float = 150) -> list[tuple[float, float]]:
    """Transcript segments ({start, end, text}) → time ranges of sponsor reads: a hit and the hits right after it,
    never longer than max_len seconds."""
    out: list[tuple[float, float]] = []
    i = 0
    while i < len(segments):
        s = segments[i]
        if not AD_WORDS.search(fold(s["text"])):
            i += 1
            continue
        start = max(0.0, s["start"] - pad)
        end = s["end"]
        j = i + 1
        while j < len(segments) and AD_WORDS.search(fold(segments[j]["text"])) and segments[j]["start"] - end < 30 \
                and segments[j]["end"] - start <= max_len:
            end = segments[j]["end"]
            j += 1
        out.append((round(start, 1), round(min(end + pad, start + max_len), 1)))
        i = j
    return merge_ranges(out)


def merge_ranges(rs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(rs):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def keep_ranges(cut: list[tuple[float, float]], total: float) -> list[tuple[float, float]]:
    out, pos = [], 0.0
    for a, b in cut:
        if a > pos:
            out.append((pos, a))
        pos = max(pos, b)
    if pos < total:
        out.append((pos, total))
    return out


def ffmpeg_concat_filter(keep: list[tuple[float, float]], audio_only: bool = True) -> str:
    parts = [f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{i}]" for i, (a, b) in enumerate(keep)]
    return ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(len(keep))) + f"concat=n={len(keep)}:v=0:a=1[out]"


# ------------------------------------------------------------------ (349) a text adventure
ADVENTURE_RULES = ("Jsi vypravěč textové dobrodružné hry v češtině (vlastní originální svět, žádné známé značky ani postavy). "
                   "Piš 3–6 vět, druhá osoba, přítomný čas, napínavě. Hráč může cokoli; když něco nejde, vysvětli proč ve světě hry. "
                   "Na konci každé odpovědi dej na nový řádek STAV: {\"misto\": …, \"inventar\": […], \"zdravi\": 0–10, \"cil\": …} "
                   "a nic za něj.")


def adventure_parse(text: str) -> tuple[str, dict | None]:
    m = re.search(r"STAV:\s*(\{.*\})\s*$", (text or "").strip(), re.S)
    if not m:
        return (text or "").strip(), None
    try:
        st = json.loads(m.group(1))
    except ValueError:
        st = None
    return text[:m.start()].strip(), st if isinstance(st, dict) else None


def adventure_load(rt: Any) -> dict:
    row = db(rt).one("SELECT state, log FROM fx_adventure WHERE id=1")
    if not row:
        return {"state": {}, "log": []}
    return {"state": json.loads(row["state"] or "{}"), "log": json.loads(row["log"] or "[]")}


def adventure_save(rt: Any, state: dict, log: list[dict]) -> None:
    db(rt).exec("INSERT OR REPLACE INTO fx_adventure VALUES (1,?,?)", (json.dumps(state, ensure_ascii=False), json.dumps(log[-30:], ensure_ascii=False)))


# ------------------------------------------------------------------ (350) kids' play timer
def play_start(rt: Any, kid: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    day = dt.date.fromtimestamp(now).isoformat()
    row = db(rt).one("SELECT * FROM fx_play WHERE kid=? AND day=?", (kid, day))
    if row and row["started"]:
        return
    db(rt).exec("INSERT OR REPLACE INTO fx_play VALUES (?,?,?,?,?)", (kid, day, float(row["minutes"]) if row else 0.0, now, 0))


def play_stop(rt: Any, kid: str, now: float | None = None) -> float:
    now = time.time() if now is None else now
    day = dt.date.fromtimestamp(now).isoformat()
    row = db(rt).one("SELECT * FROM fx_play WHERE kid=? AND day=?", (kid, day))
    if not row:
        return 0.0
    m = float(row["minutes"]) + ((now - float(row["started"])) / 60 if row["started"] else 0)
    db(rt).exec("UPDATE fx_play SET minutes=?, started=NULL WHERE kid=? AND day=?", (m, kid, day))
    return round(m, 1)


def play_check(rt: Any, limits: dict[str, int], now: float | None = None) -> list[dict]:
    """[{kid, kind: 'warn'|'over', left}] – five minutes before the limit and at the limit (each once a day)."""
    now = time.time() if now is None else now
    day = dt.date.fromtimestamp(now).isoformat()
    out = []
    for r in db(rt).all("SELECT * FROM fx_play WHERE day=? AND started IS NOT NULL", (day,)):
        limit = limits.get(r["kid"])
        if not limit:
            continue
        used = float(r["minutes"]) + (now - float(r["started"])) / 60
        left = limit - used
        if left <= 0 and r["warned"] < 2:
            db(rt).exec("UPDATE fx_play SET warned=2 WHERE kid=? AND day=?", (r["kid"], day))
            out.append({"kid": r["kid"], "kind": "over", "left": 0})
        elif 0 < left <= 5 and r["warned"] < 1:
            db(rt).exec("UPDATE fx_play SET warned=1 WHERE kid=? AND day=?", (r["kid"], day))
            out.append({"kid": r["kid"], "kind": "warn", "left": math.ceil(left)})
    return out


# ------------------------------------------------------------------ (351) equaliser by genre (Equalizer APO)
EQ = {  # 10 bands: 31 62 125 250 500 1k 2k 4k 8k 16k (dB)
    "rock": [4, 3, 2, 0, -1, 0, 2, 3, 4, 4], "pop": [-1, 1, 3, 4, 3, 1, 0, 1, 2, 2], "jazz": [3, 2, 1, 2, -1, -1, 0, 1, 2, 3],
    "classical": [4, 3, 2, 1, -1, -1, 0, 2, 3, 4], "electronic": [5, 4, 2, 0, -2, 1, 0, 2, 4, 5], "hiphop": [5, 4, 2, 3, -1, -1, 1, 0, 2, 3],
    "metal": [4, 3, 0, -2, -1, 1, 3, 4, 3, 2], "acoustic": [3, 2, 1, 1, 2, 2, 3, 3, 2, 1], "podcast": [-4, -2, 0, 1, 3, 4, 4, 3, 1, 0],
    "flat": [0] * 10,
}
GENRE_MAP = {"rock": "rock", "punk": "rock", "indie": "rock", "pop": "pop", "jazz": "jazz", "blues": "jazz", "soul": "jazz",
             "klasick": "classical", "classical": "classical", "orchest": "classical", "electro": "electronic", "edm": "electronic",
             "house": "electronic", "techno": "electronic", "dance": "electronic", "hip": "hiphop", "rap": "hiphop", "trap": "hiphop",
             "r&b": "hiphop", "metal": "metal", "folk": "acoustic", "country": "acoustic", "acoustic": "acoustic", "podcast": "podcast",
             "mluven": "podcast", "spoken": "podcast"}
BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def eq_for_genre(genre: str) -> str:
    g = fold(genre)
    return next((v for k, v in GENRE_MAP.items() if k in g), "flat")


def eq_apo_text(preset: str) -> str:
    gains = EQ[preset]
    pre = -max(0, max(gains)) - 1
    return (f"# JARVIS: {preset}\nPreamp: {pre} dB\n"
            + "GraphicEQ: " + "; ".join(f"{f} {g}" for f, g in zip(BANDS, gains, strict=True)) + "\n")


def eq_apo_dir() -> Path | None:
    for p in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "EqualizerAPO" / "config",):
        if p.is_dir():
            return p
    return None


def eq_apply(preset: str, cfg_dir: Path | None = None) -> Path:
    d = cfg_dir or eq_apo_dir()
    if d is None:
        raise ValueError("Ekvalizér nastavím přes Equalizer APO (zdarma, sourceforge.net/projects/equalizerapo) – nainstaluj ho pro svůj výstup.")
    f = d / "jarvis-eq.txt"
    f.write_text(eq_apo_text(preset), encoding="utf-8")
    main = d / "config.txt"
    txt = main.read_text(encoding="utf-8", errors="ignore") if main.exists() else ""
    if "jarvis-eq.txt" not in txt:
        main.write_text(txt.rstrip() + "\nInclude: jarvis-eq.txt\n", encoding="utf-8")
    return f


# ------------------------------------------------------------------ (352) photos into albums
def exif_time(p: Path) -> float:
    try:
        from PIL import Image

        with Image.open(p) as im:
            ex = im.getexif()
            raw = ex.get_ifd(0x8769).get(36867) or ex.get(306)
        if raw:
            return dt.datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S").timestamp()
    except Exception:  # noqa: BLE001
        pass
    return p.stat().st_mtime


def photo_events(items: list[tuple[str, float]], gap_h: float = 6) -> list[dict]:
    """Photos (name, time) → events: a new one after a gap of gap_h hours."""
    events: list[dict] = []
    for name, t in sorted(items, key=lambda x: x[1]):
        if not events or t - events[-1]["end"] > gap_h * 3600:
            events.append({"start": t, "end": t, "photos": []})
        events[-1]["end"] = t
        events[-1]["photos"].append(name)
    for e in events:
        a, b = dt.datetime.fromtimestamp(e["start"]), dt.datetime.fromtimestamp(e["end"])
        e["name"] = f"{a:%Y-%m-%d}" + (f" až {b:%d.%m.}" if b.date() != a.date() else "")
    return events


def album_plan(folder: Path, gap_h: float = 6, min_photos: int = 3) -> list[dict]:
    exts = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
    items = [(str(p), exif_time(p)) for p in folder.iterdir() if p.suffix.lower() in exts]
    return [e for e in photo_events(items, gap_h) if len(e["photos"]) >= min_photos]


def album_apply(plan: list[dict], dest: Path) -> int:
    n = 0
    for e in plan:
        d = dest / e["name"]
        d.mkdir(parents=True, exist_ok=True)
        for f in e["photos"]:
            src = Path(f)
            if src.exists() and not (d / src.name).exists():
                shutil.move(str(src), str(d / src.name))
                n += 1
    return n


# ------------------------------------------------------------------ (353) video shortened by voice
def short_segments(duration: float, target: float, pieces: int = 0) -> list[tuple[float, float]]:
    """Evenly spread clips that add up to `target` seconds (skipping the first and last 5 %)."""
    if duration <= target:
        return [(0.0, duration)]
    n = pieces or max(3, min(12, round(target / 6)))
    clip = target / n
    a0, a1 = duration * 0.05, duration * 0.95 - clip
    step = (a1 - a0) / max(1, n - 1)
    return [(round(a0 + i * step, 2), round(a0 + i * step + clip, 2)) for i in range(n)]


def ffmpeg_short_cmd(src: Path, dst: Path, segs: list[tuple[float, float]], music: Path | None = None) -> list[str]:
    v = "".join(f"[0:v]trim={a}:{b},setpts=PTS-STARTPTS[v{i}];[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{i}];"
                for i, (a, b) in enumerate(segs))
    v += "".join(f"[v{i}][a{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[v][a]"
    total = sum(b - a for a, b in segs)
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        v += f";[1:a]volume=0.25,afade=t=out:st={max(0, total - 2):.2f}:d=2[m];[a][m]amix=inputs=2:duration=first[mix]"
        return cmd + ["-filter_complex", v, "-map", "[v]", "-map", "[mix]", "-t", f"{total:.2f}", str(dst)]
    return cmd + ["-filter_complex", v, "-map", "[v]", "-map", "[a]", str(dst)]


def probe_duration(path: Path, runner=subprocess.run) -> float:
    exe = shutil.which("ffprobe")
    if not exe:
        raise ValueError("Na střih potřebuju ffmpeg (ffprobe) v PATH.")
    r = runner([exe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
    return float((r.stdout or "0").strip() or 0)


# ------------------------------------------------------------------ (356) Discord companion
def bot_command(text: str) -> tuple[str, str]:
    """'!kviz historie' → ('quiz', 'historie'); '!hraj <url>' → ('play', url); '!stop', '!skore', '!pomoc'."""
    m = re.match(r"^[!/](\w+)\s*(.*)$", (text or "").strip())
    if not m:
        return "", ""
    cmd = fold(m.group(1))
    return {"kviz": "quiz", "quiz": "quiz", "hraj": "play", "play": "play", "stop": "stop", "skore": "score", "score": "score",
            "odpoved": "answer", "a": "answer", "pomoc": "help", "help": "help", "dalsi": "next", "next": "next"}.get(cmd, ""), m.group(2).strip()


def discord_ready() -> tuple[bool, str]:
    try:
        import discord  # noqa: F401
    except ImportError:
        return False, ("Na společníka v Discordu potřebuju knihovnu discord.py s hlasem (pip install \"discord.py[voice]\") a ffmpeg, "
                       "a token bota (discord.com/developers → New Application → Bot) uložený jako „discord_bot“.")
    from . import secrets

    if not secrets.get("discord_bot"):
        return False, "Ulož token bota jako „discord_bot“ (discord.com/developers → Bot → Reset Token)."
    return True, ""


async def run_discord_bot(rt: Any) -> None:  # pragma: no cover – needs Discord
    import discord

    from . import secrets

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    state: dict[str, Any] = {"quiz": [], "i": -1, "score": {}}

    @client.event
    async def on_message(msg):  # noqa: ANN001
        if msg.author == client.user:
            return
        cmd, arg = bot_command(msg.content)
        if cmd == "help":
            await msg.channel.send("!kviz [téma] · !a 1–4 · !dalsi · !skore · !hraj <odkaz> · !stop")
        elif cmd == "quiz":
            qs = BUILTIN_QUIZ[:]
            if arg:
                try:
                    qs = parse_quiz(await rt.router.complete([{"role": "user", "content": QUIZ_PROMPT.format(n=8, topic=arg)}], fast=True)) or qs
                except Exception:  # noqa: BLE001
                    pass
            random.shuffle(qs)
            state.update(quiz=qs, i=0, score={})
            q = qs[0]
            await msg.channel.send(f"**{q['q']}**\n" + "\n".join(f"{i + 1}. {a}" for i, a in enumerate(q["a"])))
        elif cmd == "answer" and state["quiz"] and 0 <= state["i"] < len(state["quiz"]):
            q = state["quiz"][state["i"]]
            if arg.strip().isdigit() and int(arg) - 1 == q["ok"]:
                state["score"][msg.author.display_name] = state["score"].get(msg.author.display_name, 0) + 1
                state["i"] += 1
                await msg.channel.send(f"✅ {msg.author.display_name}!")
                if state["i"] < len(state["quiz"]):
                    q = state["quiz"][state["i"]]
                    await msg.channel.send(f"**{q['q']}**\n" + "\n".join(f"{i + 1}. {a}" for i, a in enumerate(q["a"])))
        elif cmd == "score":
            await msg.channel.send(", ".join(f"{k}: {v}" for k, v in sorted(state["score"].items(), key=lambda x: -x[1])) or "Zatím nic.")
        elif cmd == "play" and arg.startswith("http") and msg.author.voice:
            vc = msg.guild.voice_client or await msg.author.voice.channel.connect()
            import yt_dlp

            with yt_dlp.YoutubeDL({"format": "bestaudio", "quiet": True}) as y:
                info = y.extract_info(arg, download=False)
            vc.stop()
            vc.play(discord.FFmpegPCMAudio(info["url"], before_options="-reconnect 1 -reconnect_streamed 1"))
            await msg.channel.send(f"▶ {info.get('title', '')}")
        elif cmd == "stop" and msg.guild.voice_client:
            await msg.guild.voice_client.disconnect()

    await client.start(secrets.get("discord_bot"))


# ------------------------------------------------------------------ (357) series (TVmaze, free)
def parse_tvmaze(data: dict) -> dict:
    nxt = (data.get("_embedded") or {}).get("nextepisode") or {}
    return {"id": data.get("id"), "name": data.get("name", ""), "status": data.get("status", ""),
            "next": {"season": nxt.get("season"), "number": nxt.get("number"), "airdate": nxt.get("airdate", ""), "name": nxt.get("name", "")}
            if nxt else None}


def show_add(rt: Any, name: str, tvmaze: int | None = None, season: int = 1, episode: int = 0, next_air: str = "") -> None:
    db(rt).exec("INSERT OR REPLACE INTO fx_shows VALUES (?,?,?,?,?,?)", (name.strip(), tvmaze, season, episode, next_air, ""))


def show_watched(rt: Any, name: str, season: int, episode: int) -> bool:
    row = next((r for r in db(rt).all("SELECT name FROM fx_shows") if fold(name)[:5] in fold(r["name"])), None)
    if not row:
        return False
    db(rt).exec("UPDATE fx_shows SET season=?, episode=? WHERE name=?", (season, episode, row["name"]))
    return True


def shows(rt: Any) -> list[dict]:
    return [dict(r) for r in db(rt).all("SELECT * FROM fx_shows ORDER BY name")]


async def shows_check(rt: Any, today: dt.date, client=None) -> list[str]:
    import httpx

    said = []
    own = client is None
    c = client or httpx.AsyncClient(timeout=15)
    try:
        for s in shows(rt):
            url = (f"https://api.tvmaze.com/shows/{s['tvmaze']}?embed=nextepisode" if s["tvmaze"]
                   else "https://api.tvmaze.com/singlesearch/shows")
            r = await c.get(url, params=None if s["tvmaze"] else {"q": s["name"], "embed": "nextepisode"})
            if r.status_code != 200:
                continue
            info = parse_tvmaze(r.json())
            nxt = info["next"]
            db(rt).exec("UPDATE fx_shows SET tvmaze=?, next_air=? WHERE name=?", (info["id"], (nxt or {}).get("airdate", ""), s["name"]))
            if nxt and nxt["airdate"] and nxt["airdate"] <= today.isoformat() and s["told"] != nxt["airdate"]:
                db(rt).exec("UPDATE fx_shows SET told=? WHERE name=?", (nxt["airdate"], s["name"]))
                said.append(f"{s['name']}: nový díl S{nxt['season']:02d}E{nxt['number']:02d} „{nxt['name']}“ je venku "
                            f"(ty jsi na S{s['season']:02d}E{s['episode']:02d}).")
    finally:
        if own:
            await c.aclose()
    return said


# ------------------------------------------------------------------ (359) concerts (Ticketmaster)
def parse_ticketmaster(data: dict) -> list[dict]:
    out = []
    for e in ((data.get("_embedded") or {}).get("events") or []):
        venue = ((e.get("_embedded") or {}).get("venues") or [{}])[0]
        out.append({"name": e.get("name", ""), "date": ((e.get("dates") or {}).get("start") or {}).get("localDate", ""),
                    "venue": venue.get("name", ""), "city": (venue.get("city") or {}).get("name", ""), "url": e.get("url", "")})
    return out


async def concerts(rt: Any, artists: list[str], country: str = "CZ", client=None) -> list[dict]:
    import httpx

    from . import secrets

    key = secrets.get("ticketmaster")
    if not key:
        raise ValueError("Koncerty hledám přes Ticketmaster (developer.ticketmaster.com, klíč zdarma) – ulož klíč jako „ticketmaster“.")
    out = []
    own = client is None
    c = client or httpx.AsyncClient(timeout=15)
    try:
        for a in artists[:15]:
            r = await c.get("https://app.ticketmaster.com/discovery/v2/events.json",
                            params={"apikey": key, "keyword": a, "countryCode": country, "classificationName": "music", "size": 5})
            if r.status_code == 200:
                out += [{**e, "artist": a} for e in parse_ticketmaster(r.json())]
    finally:
        if own:
            await c.aclose()
    return sorted(out, key=lambda e: e["date"])


# ------------------------------------------------------------------ (360) your own notification sounds
PACKS: dict[str, dict[str, list[tuple]]] = {
    "krystal": {"wake": [(1320, 0, .12), (1760, .08, .25)], "listen": [(1568, 0, .09)], "done": [(1047, 0, .12), (1568, .1, .3)],
                "error": [(392, 0, .16), (330, .12, .25)], "notify": [(1760, 0, .1), (2349, .09, .35)]},
    "marimba": {"wake": [(523, 0, .2), (784, .12, .3)], "listen": [(659, 0, .14)], "done": [(523, 0, .14), (659, .1, .14), (784, .2, .35)],
                "error": [(330, 0, .2), (262, .15, .3)], "notify": [(880, 0, .18), (698, .14, .3)]},
    "scifi": {"wake": [(440, 0, .3, 1760)], "listen": [(2200, 0, .05), (2600, .06, .05)], "done": [(660, 0, .1), (990, .08, .1), (1320, .16, .2)],
              "error": [(220, 0, .3, 110)], "notify": [(1200, 0, .08), (1800, .1, .08), (2400, .2, .15)]},
    "klid": {"wake": [(392, 0, .4), (587, .2, .5)], "listen": [(523, 0, .25)], "done": [(440, 0, .3), (659, .2, .5)],
             "error": [(294, 0, .4)], "notify": [(587, 0, .35), (880, .25, .45)]},
}
FILE_NAMES = {"wake": "probuzeni", "listen": "poslech", "done": "hotovo", "error": "chyba", "notify": "upozorneni"}


HARMONICS: dict[str, list[tuple[float, float]]] = {"krystal": [(1, 1), (2.76, .25), (5.4, .08)], "marimba": [(1, 1), (4, .3), (10, .05)],
                                                  "scifi": [(1, 1), (2, .2)], "klid": [(1, 1), (2, .15), (3, .05)]}


def synth(notes: list[tuple], pack: str, rate: int = 44100) -> bytes:
    """Original tones made here: a soft attack, an exponential decay and a few harmonics (marimba / crystal / sci-fi sweep)."""
    import numpy as np

    total = max(n[1] + n[2] for n in notes) + 0.35
    buf = np.zeros(int(total * rate))
    harm = HARMONICS[pack]
    for note in notes:
        f, start, dur = note[0], note[1], note[2]
        to = note[3] if len(note) > 3 else f
        t = np.arange(int((dur + 0.3) * rate)) / rate
        freq = f + (to - f) * np.minimum(1.0, t / dur)
        phase = np.cumsum(2 * np.pi * freq / rate)
        env = np.minimum(1.0, t / 0.006) * np.exp(-t / (dur * (0.6 if pack == "marimba" else 0.9)))
        wave_ = sum(a * np.sin(phase * k) for k, a in harm) * env
        n0 = int(start * rate)
        seg = buf[n0:n0 + len(wave_)]
        seg += wave_[:len(seg)]
    peak = float(np.abs(buf).max()) or 1.0
    pcm = (buf / peak * 0.85 * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


def ours(p: Path) -> bool:
    marker = p.with_name(".jarvis-pack")
    return marker.exists() and p.name in marker.read_text(encoding="utf-8").split()


def install_pack(pack: str, sounds_dir: Path, overwrite_own: bool = False) -> dict:
    """Writes the pack's five sounds into JARVIS's sounds folder. Your own files there stay unless you say otherwise."""
    if pack not in PACKS:
        raise ValueError("Sady: " + ", ".join(PACKS))
    written, kept = [], []
    for snd, notes in PACKS[pack].items():
        name = FILE_NAMES[snd]
        existing = [p for p in sounds_dir.glob(f"{name}.*")]
        if any(not ours(p) for p in existing) and not overwrite_own:
            kept.append(name)
            continue
        for p in existing:
            p.unlink()
        (sounds_dir / f"{name}.wav").write_bytes(synth(notes, pack))
        written.append(f"{name}.wav")
    marker = sounds_dir / ".jarvis-pack"
    old = set(marker.read_text(encoding="utf-8").split()) if marker.exists() else set()
    marker.write_text(" ".join(sorted(old | set(written))), encoding="utf-8")
    return {"written": written, "kept": kept}


def remove_pack(sounds_dir: Path) -> int:
    marker = sounds_dir / ".jarvis-pack"
    if not marker.exists():
        return 0
    n = 0
    for name in marker.read_text(encoding="utf-8").split():
        p = sounds_dir / name
        if p.exists():
            p.unlink()
            n += 1
    marker.unlink()
    return n


# ------------------------------------------------------------------ daily
async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    from .proactiveplus import due_today

    now = now or dt.datetime.now()
    said: list[str] = []
    c = cfg(rt)
    for e in play_check(rt, c.play_limits, now.timestamp()):
        if e["kind"] == "warn":
            t = f"{e['kid']}: za {e['left']} minut končí dnešní čas na hraní."
        else:
            t = f"{e['kid']}: čas na hraní vypršel."
        rt.notify("Hraní", t, speak=True)
        said.append(t)
    if due_today(rt, "fx_daily", "18:00", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("fx_daily", now.date().isoformat()))
        for fn in (wish_check, ):
            try:
                for t in await fn(rt):
                    rt.notify("Sleva na hru", t)
                    said.append(t)
            except Exception:  # noqa: BLE001 – the service is down; try tomorrow
                pass
        try:
            for t in await shows_check(rt, now.date()):
                rt.notify("Seriály", t)
                said.append(t)
        except Exception:  # noqa: BLE001
            pass
    return said
