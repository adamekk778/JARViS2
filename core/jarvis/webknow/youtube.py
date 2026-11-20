"""Spec 2026-11-20 §5.12: the videos you watch (from the browser's history, or ones JARVIS played) are kept by their
subtitles – Czech, Slovak or English, written by hand before automatic ones – so "o čem bylo to video?" has an answer.
Only the metadata and the subtitles are fetched (yt-dlp, no video, no sound); at most 30 videos a day; no AI when
storing – the AI summarises only when you ask."""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import logging
import re
import urllib.request
from urllib.parse import parse_qs, urlparse

from .store import Doc

log = logging.getLogger("jarvis.webknow")
PER_DAY = 30
LANGS = ("cs", "sk", "en")
YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_id(url: str) -> str | None:
    p = urlparse(url or "")
    host = (p.hostname or "").lower()
    cand = ""
    if host in ("youtu.be", "www.youtu.be"):
        cand = p.path.strip("/").split("/")[0]
    elif host in YT_HOSTS:
        if p.path == "/watch":
            cand = (parse_qs(p.query).get("v") or [""])[0]
        else:
            m = re.match(r"^/(shorts|live|embed)/([^/?#]+)", p.path)
            cand = m.group(2) if m else ""
    return cand if ID.match(cand or "") else None


def vtt_to_text(vtt: str) -> str:
    out: list[str] = []
    for line in (vtt or "").splitlines():
        s = line.strip()
        if not s or s == "WEBVTT" or "-->" in s or re.match(r"^(Kind|Language|NOTE|STYLE)\b", s) or s.isdigit():
            continue
        s = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()
        if s and (not out or out[-1] != s):
            out.append(s)
    return " ".join(out)


def _pick(tracks: dict) -> str:
    for lang in LANGS:
        for key, fmts in (tracks or {}).items():
            if key == lang or key.startswith(lang + "-"):
                for f in fmts or []:
                    if f.get("ext") == "vtt" and f.get("url"):
                        return f["url"]
    return ""


def fetch_info(url: str) -> dict:
    """Blocking: the title, channel, length, description and the subtitles as plain text ("" when there are none)."""
    import yt_dlp

    opts = {"skip_download": True, "quiet": True, "no_warnings": True, "noplaylist": True, "writesubtitles": True,
            "writeautomaticsub": True, "subtitleslangs": list(LANGS)}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    sub_url = _pick(info.get("subtitles")) or _pick(info.get("automatic_captions"))
    subs = ""
    if sub_url:
        with urllib.request.urlopen(sub_url, timeout=10) as r:   # noqa: S310 – a https URL yt-dlp got from YouTube
            subs = vtt_to_text(r.read(4 * 2 ** 20).decode("utf-8", errors="replace"))
    return {"title": info.get("title") or "", "channel": info.get("channel") or info.get("uploader") or "",
            "duration": info.get("duration"), "description": info.get("description") or "", "subtitles": subs}


def _day(rt, today: str) -> int:
    row = rt.db.one("SELECT v FROM kv WHERE k='webknow_yt_day'")
    day, _, n = (row["v"] if row else "").partition(":")
    return int(n or 0) if day == today else 0


async def learn_video(rt, url: str) -> int | None:
    vid = video_id(url)
    if not vid or not rt.cfg.webknow.youtube or rt.memory.private:
        return None
    canonical = f"https://www.youtube.com/watch?v={vid}"
    if rt.db.one("SELECT 1 FROM web_docs WHERE url=?", (canonical,)):
        return None
    today = dt.date.today().isoformat()
    n = _day(rt, today)
    if n >= PER_DAY:
        return None
    try:
        info = await asyncio.to_thread(fetch_info, canonical)
    except Exception as e:  # noqa: BLE001 – a private / removed video, YouTube said no
        log.debug("youtube %s: %s", vid, e)
        return None
    desc = info.get("description") or ""
    did = rt.webknow.add(Doc(url=canonical, title=info.get("title") or canonical, kind="video", source=info.get("channel") or "",
                             snippet=desc[:400], text=(info.get("subtitles") or desc)[:15000]))
    if did is not None:
        rt.db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES ('webknow_yt_day', ?)", (f"{today}:{n + 1}",))
    return did
