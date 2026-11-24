// 3.14 Karaoke přes celou obrazovku: the line being sung big in the middle, its words lit as they are sung (the exact
// word times when the lyrics have them, otherwise shared by length), the lines before and after dimmed, the Czech
// translation under it, the album art blurred behind. On the PC it opens from the notch (Hudba → Karaoke) or by
// voice ("pusť karaoke"); on a TV or tablet at home: http://<PC>:8765/karaoke?token=<the phone's key>.
import { applyAppearance } from "../shared/base";
import { h, icon } from "../shared/dom";
import { lyricShift } from "../shared/lyricsync";
import { JarvisClient, localEndpoint } from "../shared/ws";
import "./style.css";

type Word = { t: number; c: number; text: string };
type Line = { t: number; text: string; words?: Word[] };

const q = new URLSearchParams(location.search);
const ep = localEndpoint();
if (q.get("token")) ep.token = String(q.get("token"));
const client = new JarvisClient(ep, "karaoke", "PC");
applyAppearance({});

let media: any = {};
let lyr: { title: string; artist: string; synced: boolean; lines: Line[]; tr: string[]; plain: string } =
  { title: "", artist: "", synced: false, lines: [], tr: [], plain: "" };
let cur = -2;

const bg = h("div", { class: "k-bg" });
const prev = h("p", { class: "k-line k-prev" });
const now = h("p", { class: "k-line k-now" });
const tr = h("p", { class: "k-tr" });
const next1 = h("p", { class: "k-line k-next" });
const next2 = h("p", { class: "k-line k-next k-next2" });
const title = h("strong", {}), artist = h("span", {});
const cover = h("img", { class: "k-cover", alt: "" }) as HTMLImageElement;
const fill = h("i", {});
const note = h("p", { class: "k-note" });
const closeBtn = h("button", { class: "k-btn", type: "button", title: "Zavřít (Esc)", "aria-label": "Zavřít karaoke", onclick: () => close() }, icon("x"));
const fsBtn = h("button", { class: "k-btn", type: "button", title: "Celá obrazovka (F)", "aria-label": "Celá obrazovka",
  onclick: () => toggleFs() }, icon("arrows-out"));
const root = h("main", { class: "k" }, bg,
  h("header", { class: "k-head" }, cover, h("div", { class: "k-meta" }, title, artist), h("span", { class: "grow" }), fsBtn, closeBtn),
  h("section", { class: "k-stage", "aria-live": "polite" }, prev, now, tr, next1, next2, note),
  h("footer", { class: "k-foot" }, h("div", { class: "k-bar" }, fill)));
document.getElementById("karaoke")!.replaceWith(root);

function close() {
  if (client.local) client.send("open_window", { view: "karaoke-close" });
  else if (history.length > 1) history.back();
}
function toggleFs() {
  if (document.fullscreenElement) void document.exitFullscreen();
  else void document.documentElement.requestFullscreen?.().catch(() => undefined);
}
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !document.fullscreenElement) close();
  if (e.key.toLowerCase() === "f") toggleFs();
});

const pos = () => {
  if (typeof media.position !== "number") return -1;
  return media.position + (media.playing ? Math.max(0, Date.now() / 1000 - (media.at || Date.now() / 1000)) : 0);
};
const same = () => !!media.title && lyr.title === media.title && lyr.artist === String(media.artist || "");

/** a line as words that light up: each word a span whose --f (0–1) says how much of it is sung */
function wordsOf(line: Line | undefined): HTMLElement[] {
  if (!line || !line.text) return [h("span", { class: "k-dots" }, "♪ ♪ ♪")];
  return line.text.split(/(\s+)/).map((w) => (/^\s+$/.test(w) ? document.createTextNode(w) as unknown as HTMLElement : h("span", { class: "k-w" }, w)));
}

function paint() {
  if (!same() || !lyr.synced || !lyr.lines.length) {
    const msg = !media.title ? "Pusť si písničku – text se objeví tady." : !same() ? "Hledám text…"
      : lyr.plain ? "Text bez časování – nepohybuje se se zpěvem." : "Pro tuhle píseň text nemáme.";
    note.textContent = msg;
    note.hidden = false;
    if (lyr.plain && same()) { now.textContent = ""; prev.textContent = ""; next1.textContent = ""; next2.textContent = ""; tr.textContent = "";
      note.replaceChildren(h("span", {}, msg), h("pre", { class: "k-plain" }, lyr.plain)); }
    cur = -2;
    return;
  }
  note.hidden = true;
  const p = pos() + lyricShift(media.title, media.artist);
  const L = lyr.lines;
  let i = -1;
  for (let k = 0; k < L.length && L[k].t <= p + 0.05; k++) i = k;
  if (i !== cur) {
    cur = i;
    prev.replaceChildren(...(i > 0 ? wordsOf(L[i - 1]) : []));
    now.replaceChildren(...(i >= 0 ? wordsOf(L[i]) : [h("span", { class: "k-dots" }, `♪ ${lyr.title}`)]));
    tr.textContent = i >= 0 && L[i].text ? (lyr.tr[i] || "") : "";
    next1.replaceChildren(...wordsOf(L[i + 1]));
    next2.replaceChildren(...wordsOf(L[i + 2]));
    now.animate([{ opacity: 0.2, transform: "translateY(18px) scale(.98)" }, { opacity: 1, transform: "none" }], { duration: 320, easing: "cubic-bezier(.2,.9,.25,1)" });
  }
  if (i < 0) return;
  const line = L[i], end = L[i + 1]?.t ?? line.t + 4;
  const spans = [...now.querySelectorAll<HTMLElement>(".k-w")];
  if (line.words && line.words.length) {                     // exact word times
    let at = 0;
    spans.forEach((sp) => {
      const text = sp.textContent || "";
      const c = line.text.indexOf(text, at);
      at = c + text.length;
      const w = line.words!.filter((x) => x.c >= c && x.c < c + text.length);
      const t0 = w.length ? w[0].t : line.t, t1 = w.length ? (line.words![line.words!.indexOf(w[w.length - 1]) + 1]?.t ?? Math.min(end, w[w.length - 1].t + 0.6)) : end;
      sp.style.setProperty("--f", String(Math.max(0, Math.min(1, (p - t0) / Math.max(0.05, t1 - t0)))));
    });
  } else {                                                   // shared by length over the line's time
    const total = spans.reduce((a, sp) => a + (sp.textContent || "").length, 0) || 1;
    const f = Math.max(0, Math.min(1, (p - line.t) / Math.max(0.6, Math.min(end - line.t, 8)))) * total;
    let acc = 0;
    spans.forEach((sp) => {
      const len = (sp.textContent || "").length || 1;
      sp.style.setProperty("--f", String(Math.max(0, Math.min(1, (f - acc) / len))));
      acc += len;
    });
  }
}

function paintMeta() {
  title.textContent = media.title || "Nic nehraje";
  artist.textContent = media.artist || "";
  const art = media.thumb || "";
  if (art && cover.src !== art) { cover.src = art; bg.style.backgroundImage = `url("${art}")`; }
  cover.hidden = !art;
  root.classList.toggle("paused", !media.playing);
}

function frame() {
  const d = Number(media.duration) || 0;
  if (d > 0) fill.style.width = `${Math.max(0, Math.min(100, (pos() / d) * 100))}%`;
  paint();
  requestAnimationFrame(frame);
}

client.on("welcome", (m: any) => {
  if (m.media) { media = { ...m.media, at: m.media.at || Date.now() / 1000 }; paintMeta(); }
  if (m.lyrics?.lines) setLyrics(m.lyrics);
  client.send("lyrics_get");
});
client.on("media", (m: any) => { media = { ...m }; paintMeta(); cur = -2; });
function setLyrics(m: any) {
  lyr = { title: String(m.title || ""), artist: String(m.artist || ""), synced: !!m.synced, lines: Array.isArray(m.lines) ? m.lines : [],
    tr: Array.isArray(m.tr) ? m.tr.map(String) : [], plain: String(m.plain || "") };
  cur = -2;
}
client.on("lyrics", (m: any) => setLyrics(m));
client.connect();
requestAnimationFrame(frame);
