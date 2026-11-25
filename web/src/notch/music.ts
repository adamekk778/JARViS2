/* 3.12 the music screen of the notch (a click on the player on the main screen): big album art with its colours
   behind everything, the song, a progress bar you can drag, play / pause / previous / next, and the lyrics beside it –
   the line being sung lights up word by word and the text scrolls with the song; a click on a line jumps there.
   Runs its frame loop only while it is on screen. */
import { brandEl, mediaBrand } from "../shared/brands";
import { h, icon } from "../shared/dom";
import { fmtShift, isAutoShift, lyricShift, setLyricShift } from "../shared/lyricsync";

type Line = { t: number; text: string };
type Ctx = { quick: (action: string, args?: any) => void; back: () => void; lyricsOn: () => boolean; onlineOn?: () => void;
  karaoke?: () => void };

const mmss = (s: number) => `${Math.floor(Math.max(0, s) / 60)}:${String(Math.floor(Math.max(0, s)) % 60).padStart(2, "0")}`;

export function createMusicView(ctx: Ctx) {
  let media: any = {};
  let lyr: { title: string; artist?: string; synced: boolean; lines: Line[]; plain: string; reason?: string; tr?: string[] } = { title: "", synced: false, lines: [], plain: "" };
  let visible = false, raf = 0, cur = -2, dragging = false, art = "";

  const bg = h("img", { class: "mu-bg", alt: "", "aria-hidden": "true" }) as HTMLImageElement;
  const cover = h("img", { class: "mu-cover-img", alt: "" }) as HTMLImageElement;
  const coverBox = h("div", { class: "mu-cover" }, cover, h("span", { class: "mu-cover-none" }, icon("music-notes", "ph-fill")));
  const src = h("div", { class: "mu-src" });
  const title = h("strong", { class: "mu-title" });
  const artist = h("span", { class: "mu-artist" });
  const fill = h("i", { class: "mu-fill" }), knob = h("i", { class: "mu-knob" });
  const track = h("div", { class: "mu-track" }, fill, knob);
  const bar = h("div", { class: "mu-bar", role: "slider", "aria-label": "Průběh písně", tabindex: "0" }, track);
  const t0 = h("span", {}), t1 = h("span", {});
  const playIco = h("span", {});
  const btn = (ic: string | null, label: string, fn: () => void, cls = "") => h("button", { class: `mu-btn ${cls}`, type: "button", "aria-label": label, title: label,
    onclick: (e: Event) => { (e.currentTarget as HTMLElement).animate([{ transform: "scale(.86)" }, { transform: "scale(1)" }], { duration: 260, easing: "cubic-bezier(.3,1.6,.5,1)" }); fn(); } },
    ic ? icon(ic, "ph-fill") : playIco);
  const lyrList = h("div", { class: "mu-lines" });
  // 3.12 the text running late or early: move it by a quarter of a second (kept for this song and the next ones)
  const shiftVal = h("button", { class: "mu-sync-v", type: "button", title: "Vrátit posun na nulu", onclick: () => nudge(null) });
  const nudge = (d: number | null) => {
    const v = setLyricShift(media?.title, media?.artist, d === null ? 0 : lyricShift(media?.title, media?.artist) + d);
    shiftVal.textContent = fmtShift(v);
    cur = -2;
  };
  const sync = h("div", { class: "mu-sync", role: "group", "aria-label": "Posun textu" },
    h("button", { type: "button", title: "Text jde pozadu – posunout dřív", onclick: () => nudge(0.25) }, icon("rewind", "ph-fill"), "Text pozadu"),
    shiftVal,
    h("button", { type: "button", title: "Text jde napřed – posunout později", onclick: () => nudge(-0.25) }, "Text napřed", icon("fast-forward", "ph-fill")),
    // 3.14 the words belong to another song (or version): never show this text for it again, try another one
    h("button", { type: "button", class: "mu-wrong", title: "Tohle není text téhle písně – zkusit jiný", onclick: () => ctx.quick("lyrics_wrong") },
      icon("swap", "ph-fill"), "Jiný text"),
    ctx.karaoke ? h("button", { type: "button", title: "Karaoke přes celou obrazovku", onclick: () => ctx.karaoke?.() },
      icon("microphone-stage", "ph-fill"), "Karaoke") : "");
  const lyrBox = h("div", { class: "mu-lyrics" }, lyrList);
  const lyrWrap = h("div", { class: "mu-lyr-wrap" }, lyrBox, sync);       // outside the faded edges of the lyrics
  const back = h("button", { class: "mu-back", type: "button", title: "Zpět", "aria-label": "Zpět na hlavní obrazovku", onclick: () => ctx.back() }, icon("caret-left"));
  const el = h("div", { class: "mu" },
    h("div", { class: "mu-glow", "aria-hidden": "true" }, bg),
    h("div", { class: "mu-left" }, back, coverBox,
      h("div", { class: "mu-meta" }, src, title, artist),
      h("div", { class: "mu-time" }, bar, h("div", { class: "mu-times" }, t0, t1)),
      h("div", { class: "mu-ctl" },
        btn("skip-back", "Předchozí", () => ctx.quick("media_control", { action: "previous" })),
        btn(null, "Přehrát / pauza", () => ctx.quick("media_control", { action: "play_pause" }), "main"),
        btn("skip-forward", "Další", () => ctx.quick("media_control", { action: "next" })))),
    lyrWrap);

  // ---- where we are in the song ----
  const dur = () => Number(media?.duration) || 0;
  const pos = () => {
    if (typeof media?.position !== "number") return -1;
    return Math.min(dur() || 1e9, media.position + (media.playing ? Math.max(0, Date.now() / 1000 - (media.at || Date.now() / 1000)) : 0));
  };
  function seek(sec: number) {
    if (!(dur() > 0)) return;
    const s = Math.max(0, Math.min(dur() - 1, sec));
    media = { ...media, position: s, at: Date.now() / 1000 };   // moves at once; the player confirms
    cur = -2;
    ctx.quick("media_seek", { seconds: Math.round(s * 10) / 10 });
  }
  // the bar: click or drag to a place in the song
  const fracAt = (x: number) => { const r = track.getBoundingClientRect(); return Math.max(0, Math.min(1, (x - r.left) / r.width)); };
  bar.addEventListener("pointerdown", (e) => {
    if (!(dur() > 0)) return;
    dragging = true;
    bar.setPointerCapture(e.pointerId);
    el.classList.add("scrub");
    paintBar(fracAt(e.clientX) * dur());
  });
  bar.addEventListener("pointermove", (e) => { if (dragging) paintBar(fracAt(e.clientX) * dur()); });
  bar.addEventListener("pointerup", (e) => {
    if (!dragging) return;
    dragging = false;
    el.classList.remove("scrub");
    seek(fracAt(e.clientX) * dur());
  });
  bar.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") seek(pos() + 5);
    if (e.key === "ArrowLeft") seek(pos() - 5);
  });
  function paintBar(p: number) {
    const d = dur();
    const f = d > 0 ? Math.max(0, Math.min(1, p / d)) : 0;
    // 3.12 only what changed: "left" re-lays the notch out, so it moves in 0.1 % steps (the fill is a cheap transform)
    const sx = f.toFixed(4), kl = `${(f * 100).toFixed(1)}%`;
    if (fill.dataset.f !== sx) { fill.dataset.f = sx; fill.style.transform = `scaleX(${sx})`; }
    if (knob.style.left !== kl) knob.style.left = kl;
    if (t0.textContent !== mmss(p)) t0.textContent = mmss(p);
    const rest = `-${mmss(d - p)}`;
    if (t1.textContent !== rest) t1.textContent = rest;
  }

  // ---- lyrics ----
  function buildLyrics() {
    cur = -2;
    lyrList.style.transform = "";
    // 3.14 the same title is not enough (two songs called "Stay"): the artist has to match too
    const same = lyr.title && media?.title && lyr.title === media.title && (lyr.artist ?? "") === String(media.artist || "");
    el.classList.toggle("no-lyrics", !(same && (lyr.lines.length || lyr.plain)));
    if (!media?.title) { lyrList.replaceChildren(h("div", { class: "mu-empty" }, icon("music-notes-simple"), h("strong", {}, "Nic nehraje"), h("span", {}, "Pusť si hudbu – text uvidíš tady."))); return; }
    if (!ctx.lyricsOn()) { lyrList.replaceChildren(h("div", { class: "mu-empty" }, icon("text-aa"), h("strong", {}, "Texty jsou vypnuté"), h("span", {}, "Zapneš je v Nastavení → Notch → Texty písní."))); return; }
    // 3.12 why there is no text, said plainly (it used to stay on "Hledám text…" for ever)
    if (same && lyr.reason === "offline") {
      lyrList.replaceChildren(h("div", { class: "mu-empty" }, icon("wifi-slash"), h("strong", {}, "Je zapnutý režim „Jen offline“"),
        h("span", {}, "V něm JARVIS nic nestahuje z internetu – ani texty a obaly písní, ani AI."),
        ctx.onlineOn ? h("button", { type: "button", class: "mu-go", onclick: () => ctx.onlineOn?.() }, icon("wifi-high"), "Vypnout Jen offline") : ""));
      return;
    }
    if (same && lyr.reason && !lyr.lines.length && !lyr.plain) {
      lyrList.replaceChildren(h("div", { class: "mu-empty" }, icon("warning-circle"), h("strong", {}, "Text se nepodařilo stáhnout"),
        h("span", {}, `${lyr.reason} – zkusím to znovu u další písně. Diagnostika → Zkontrolovat řekne víc.`)));
      return;
    }
    if (!same || (!lyr.lines.length && !lyr.plain)) {
      lyrList.replaceChildren(h("div", { class: "mu-empty" }, icon("microphone-stage"), h("strong", {}, same ? "Text jsme nenašli" : "Hledám text…"),
        h("span", {}, same ? "Pro tuhle píseň není v databázi LRCLIB žádný text." : "Chvilku – hledám slova k téhle písni.")));
      return;
    }
    if (lyr.synced && lyr.lines.length) {
      lyrList.replaceChildren(...lyr.lines.map((l, i) => {
        const words = l.text ? l.text.split(/(\s+)/).map((w) => (/\s+/.test(w) ? w : h("span", { class: "w" }, w))) : [h("span", { class: "mu-dots" }, "• • •")];
        const tr = lyr.tr?.[i];             // 3.12 the Czech translation, small under the line
        return h("p", { class: "mu-line", "data-i": String(i), title: `Přetočit na ${mmss(l.t)}`, onclick: () => seek(l.t) }, ...words,
          tr && l.text ? h("span", { class: "mu-tr" }, tr) : "");
      }));
    } else {
      lyrList.replaceChildren(h("div", { class: "mu-plain-note" }, "Text bez časování – nepohybuje se se zpěvem"),
        ...lyr.plain.split(/\n/).map((t) => h("p", { class: "mu-line plain" }, t || " ")));
    }
  }
  function lineAt(p: number): number {
    const L = lyr.lines;
    let lo = 0, hi = L.length - 1, ans = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (L[mid].t <= p + 0.15) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
    return ans;
  }
  function paintLyrics(p: number) {
    if (!lyr.synced || !lyr.lines.length || el.classList.contains("no-lyrics")) return;
    const i = lineAt(p);
    const lines = lyrList.children;
    if (i !== cur) {
      const prev = cur;
      cur = i;
      for (let k = 0; k < lines.length; k++) {
        const ln = lines[k] as HTMLElement;
        ln.classList.toggle("past", k < i);
        ln.classList.toggle("now", k === i);
        if (k !== i) ln.style.removeProperty("--fill");
        if (k === prev && k !== i) ln.querySelectorAll(".w").forEach((w) => { (w as HTMLElement).style.removeProperty("--w"); (w as any)._w = ""; });
      }
      // keep the sung line a little above the middle; the list glides there
      const target = lines[Math.max(0, i)] as HTMLElement | undefined;
      if (target) {
        const y = target.offsetTop - lyrBox.clientHeight * 0.36 + target.offsetHeight / 2;
        lyrList.style.transform = `translateY(${-Math.max(0, y)}px)`;
      }
    }
    // the words of the sung line fill up one after another
    if (i >= 0) {
      const ln = lines[i] as HTMLElement;
      const start = lyr.lines[i].t, end = lyr.lines[i + 1]?.t ?? start + 4;
      const f = Math.max(0, Math.min(1, (p - start) / Math.max(0.5, Math.min(end - start, 8))));
      const ws = ((ln as any)._ws ??= [...ln.querySelectorAll(".w")]) as HTMLElement[];
      const lens = ((ln as any)._lens ??= ws.map((w) => (w.textContent || "").length)) as number[];
      const total = lens.reduce((a, n) => a + n, 0) || 1;
      let acc = 0;
      ws.forEach((w, k) => {
        const len = lens[k] || 1;
        const wf = Math.max(0, Math.min(1, (f * total - acc) / len));
        acc += len;
        const v = `${Math.round(wf * 100)}%`;
        if ((w as any)._w !== v) { (w as any)._w = v; w.style.setProperty("--w", v); }
      });
    }
  }

  let painted = 0;
  function frame(ts = performance.now()) {
    raf = 0;
    if (!visible) return;
    if (ts - painted < 21) { raf = requestAnimationFrame(frame); return; }   // ~45 frames a second is plenty
    painted = ts;
    const p = pos();
    if (!dragging && p >= 0) paintBar(p);
    if (p >= 0) paintLyrics(p + lyricShift(media?.title, media?.artist));
    raf = requestAnimationFrame(frame);
  }
  function paintMeta() {
    const has = !!media?.title;
    el.classList.toggle("empty", !has);
    el.classList.toggle("playing", !!media?.playing);
    const thumb = has && media.thumb ? String(media.thumb) : "";
    if (thumb !== art) {
      art = thumb;
      coverBox.classList.toggle("has", !!thumb);
      if (thumb) {
        cover.src = thumb; bg.src = thumb;
        cover.animate([{ opacity: 0, transform: "scale(.94)" }, { opacity: 1, transform: "none" }], { duration: 450, easing: "cubic-bezier(.2,.9,.25,1)" });
      } else { cover.removeAttribute("src"); bg.removeAttribute("src"); }
    }
    title.textContent = has ? media.title : "Nic nehraje";
    shiftVal.textContent = fmtShift(lyricShift(media?.title, media?.artist)) + (isAutoShift(media?.title, media?.artist) ? " · auto" : "");
    artist.textContent = has ? media.artist || "" : "";
    const b = mediaBrand(media?.source || "");
    src.replaceChildren(...(b && b.id !== "browser" ? [brandEl(b), h("span", {}, b.name)] : []));
    const want = media?.playing ? "pause" : "play";
    if (playIco.dataset.i !== want) { playIco.dataset.i = want; playIco.replaceChildren(icon(want, "ph-fill")); }
    el.classList.toggle("no-time", !(dur() > 0));
  }

  return {
    el,
    setMedia(m: any) {
      const newSong = m?.title !== media?.title;
      media = m || {};
      paintMeta();
      if (newSong) buildLyrics();
      cur = -2;
    },
    setLyrics(m: any) {
      lyr = { title: String(m?.title || ""), artist: String(m?.artist || ""), synced: !!m?.synced, lines: Array.isArray(m?.lines) ? m.lines : [], plain: String(m?.plain || ""),
        reason: m?.reason ? String(m.reason) : "", tr: Array.isArray(m?.tr) ? m.tr.map(String) : [] };
      buildLyrics();
    },
    show(on: boolean) {
      visible = on;
      if (on) { paintMeta(); buildLyrics(); if (!raf) raf = requestAnimationFrame(frame); }
      else if (raf) { cancelAnimationFrame(raf); raf = 0; }
    },
  };
}
