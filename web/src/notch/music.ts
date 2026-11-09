/* 3.12 the music screen of the notch (a click on the player on the main screen): big album art with its colours
   behind everything, the song, a progress bar you can drag, play / pause / previous / next, and the lyrics beside it –
   the line being sung lights up word by word and the text scrolls with the song; a click on a line jumps there.
   Runs its frame loop only while it is on screen. */
import { brandEl, mediaBrand } from "../shared/brands";
import { h, icon } from "../shared/dom";

type Line = { t: number; text: string };
type Ctx = { quick: (action: string, args?: any) => void; back: () => void; lyricsOn: () => boolean };

const mmss = (s: number) => `${Math.floor(Math.max(0, s) / 60)}:${String(Math.floor(Math.max(0, s)) % 60).padStart(2, "0")}`;

export function createMusicView(ctx: Ctx) {
  let media: any = {};
  let lyr: { title: string; synced: boolean; lines: Line[]; plain: string } = { title: "", synced: false, lines: [], plain: "" };
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
  const lyrBox = h("div", { class: "mu-lyrics" }, lyrList);
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
    lyrBox);

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
    fill.style.transform = `scaleX(${f.toFixed(4)})`;
    knob.style.left = `${(f * 100).toFixed(2)}%`;
    if (t0.textContent !== mmss(p)) t0.textContent = mmss(p);
    const rest = `-${mmss(d - p)}`;
    if (t1.textContent !== rest) t1.textContent = rest;
  }

  // ---- lyrics ----
  function buildLyrics() {
    cur = -2;
    lyrList.style.transform = "";
    const same = lyr.title && media?.title && lyr.title === media.title;
    el.classList.toggle("no-lyrics", !(same && (lyr.lines.length || lyr.plain)));
    if (!media?.title) { lyrList.replaceChildren(h("div", { class: "mu-empty" }, icon("music-notes-simple"), h("strong", {}, "Nic nehraje"), h("span", {}, "Pusť si hudbu – text uvidíš tady."))); return; }
    if (!ctx.lyricsOn()) { lyrList.replaceChildren(h("div", { class: "mu-empty" }, icon("text-aa"), h("strong", {}, "Texty jsou vypnuté"), h("span", {}, "Zapneš je v Nastavení → Notch → Texty písní."))); return; }
    if (!same || (!lyr.lines.length && !lyr.plain)) {
      lyrList.replaceChildren(h("div", { class: "mu-empty" }, icon("microphone-stage"), h("strong", {}, same ? "Text jsme nenašli" : "Hledám text…"),
        h("span", {}, same ? "Pro tuhle píseň není v databázi LRCLIB žádný text." : "Chvilku – hledám slova k téhle písni.")));
      return;
    }
    if (lyr.synced && lyr.lines.length) {
      lyrList.replaceChildren(...lyr.lines.map((l, i) => {
        const words = l.text ? l.text.split(/(\s+)/).map((w) => (/\s+/.test(w) ? w : h("span", { class: "w" }, w))) : [h("span", { class: "mu-dots" }, "• • •")];
        return h("p", { class: "mu-line", "data-i": String(i), title: `Přetočit na ${mmss(l.t)}`, onclick: () => seek(l.t) }, ...words);
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
        if (k === prev && k !== i) ln.querySelectorAll(".w").forEach((w) => (w as HTMLElement).style.removeProperty("--w"));
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
      const ws = ln.querySelectorAll(".w") as NodeListOf<HTMLElement>;
      const total = [...ws].reduce((a, w) => a + w.textContent!.length, 0) || 1;
      let acc = 0;
      ws.forEach((w) => {
        const len = w.textContent!.length;
        const wf = Math.max(0, Math.min(1, (f * total - acc) / len));
        acc += len;
        w.style.setProperty("--w", `${Math.round(wf * 100)}%`);
      });
    }
  }

  function frame() {
    raf = 0;
    if (!visible) return;
    const p = pos();
    if (!dragging && p >= 0) paintBar(p);
    if (p >= 0) paintLyrics(p);
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
      lyr = { title: String(m?.title || ""), synced: !!m?.synced, lines: Array.isArray(m?.lines) ? m.lines : [], plain: String(m?.plain || "") };
      buildLyrics();
    },
    show(on: boolean) {
      visible = on;
      if (on) { paintMeta(); buildLyrics(); if (!raf) raf = requestAnimationFrame(frame); }
      else if (raf) { cancelAnimationFrame(raf); raf = 0; }
    },
  };
}
