/* 3.12 the phone in the same look as the PC: the notch's eyes in the header, a big clock with the date and the weather,
   the song playing on the PC with its art and controls, and your own background (black, the colours of the music or a
   photo) with how dark and blurred it is. Kept on this phone. */
import { h, icon, toast } from "../shared/dom";
import { type Look, loadLook, loadPhoto, onLookChange, saveLook, savePhoto, shrinkPhoto } from "../shared/lookstore";
import type { JarvisClient } from "../shared/ws";
import { native } from "./native";
import "./phonelook.css";

const COLORS = ["#ffffff", "#0a84ff", "#ff9f0a", "#ff375f", "#30d158", "#bf5af2", "#64d2ff", "#ffd60a"];
const getColor = () => { try { return localStorage.getItem("jarvis.clock.color") || "#ffffff"; } catch { return "#ffffff"; } };
const setColor = (c: string) => { try { localStorage.setItem("jarvis.clock.color", c); } catch { /* private */ } window.dispatchEvent(new CustomEvent("jarvis-look")); };
const pad = (n: number) => String(n).padStart(2, "0");
const mmss = (s: number) => `${Math.floor(Math.max(0, s) / 60)}:${pad(Math.floor(Math.max(0, s)) % 60)}`;

/** the notch's eyes: colour and motion follow what JARVIS does */
export function phoneEyes() {
  const el = h("div", { class: "pe-eyes", "aria-hidden": "true", "data-s": "offline" }, h("i"), h("i"));
  return { el, set(state: string) { el.dataset.s = state; } };
}

/** the background layer behind the whole app */
let album = "";
const layer = h("div", { class: "pe-bg", "aria-hidden": "true" });
function applyBg() {
  const look = loadLook(), photo = loadPhoto();
  const src = look.bg === "photo" ? photo : look.bg === "album" ? album : "";
  document.documentElement.dataset.phbg = src ? look.bg : "";
  if (!src) delete document.documentElement.dataset.phbg;
  layer.style.backgroundImage = src ? `url("${src}")` : "";
  layer.style.setProperty("--dim", String(look.dim / 100));
  layer.style.setProperty("--blur", `${look.bg === "album" ? Math.max(look.blur, 28) : look.blur}px`);
}
export function phoneBackground(c: JarvisClient) {
  if (!layer.isConnected) document.body.prepend(layer);
  c.on("media", (m) => { const t = m?.thumb ? String(m.thumb) : ""; if (t !== album) { album = t; applyBg(); } });
  c.on("welcome", (m) => { const t = m.media?.thumb ? String(m.media.thumb) : ""; if (t !== album) { album = t; applyBg(); } });
  onLookChange(applyBg);
  applyBg();
}

/** the clock on top of "Domov": time, date, the weather */
export function phoneClock(c: JarvisClient) {
  const time = h("strong", { class: "pe-time" }), date = h("span", { class: "pe-date" }), wx = h("span", { class: "pe-wx" });
  const el = h("button", { type: "button", class: "pe-clock", title: "Klepni pro jinou barvu", onclick: () => {
    const cur = getColor(); setColor(COLORS[(COLORS.indexOf(cur) + 1) % COLORS.length]); paintColor(); native.haptic();
  } }, time, h("div", { class: "pe-sub" }, date, wx));
  const paintColor = () => el.style.setProperty("--ck", getColor());
  let last = "";
  const tick = () => {
    if (!el.isConnected && last) return;
    const d = new Date(), k = `${d.getHours()}:${pad(d.getMinutes())}`;
    if (k !== last) {
      last = k;
      time.textContent = k;
      const s = d.toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" });
      date.textContent = s.charAt(0).toUpperCase() + s.slice(1);
    }
  };
  tick();
  window.setInterval(tick, 5000);
  onLookChange(paintColor);
  paintColor();
  let asked = 0;
  const want = () => { if (Date.now() - asked > 30 * 60000 && c.status === "open") { asked = Date.now(); c.send("weather_get"); } };
  c.onStatus((s) => s === "open" && want());
  c.on("weather", (m) => {
    if (!m || m.error || typeof m.temp !== "number") { wx.replaceChildren(); return; }
    const d = String(m.desc || "");
    const ic = /bouř/i.test(d) ? "cloud-lightning" : /sníh|sněž/i.test(d) ? "snowflake" : /déšť|přeháň|mrhol/i.test(d) ? "cloud-rain"
      : /mlh/i.test(d) ? "cloud-fog" : /zataž|oblač/i.test(d) ? "cloud" : new Date().getHours() >= 19 || new Date().getHours() < 6 ? "moon" : "sun";
    wx.replaceChildren(icon(ic, "ph-fill"), h("b", {}, `${Math.round(m.temp)}°`), m.city ? h("span", {}, m.city) : "");
  });
  return { el, want };
}

/** the song playing on the PC: art, title, progress, controls */
export function phoneMusic(c: JarvisClient) {
  let media: any = {}, raf = 0;
  const quick = (action: string, args: any = {}) => { native.haptic(); c.send("quick_action", { action, args }); };
  const art = h("img", { class: "pe-art", alt: "" }) as HTMLImageElement;
  const glow = h("img", { class: "pe-glow", alt: "", "aria-hidden": "true" }) as HTMLImageElement;
  const title = h("strong", {}), artist = h("span", {});
  const fill = h("i"), t0 = h("span", {}), t1 = h("span", {});
  const playIco = h("span", {});
  const b = (ic: string | null, label: string, fn: () => void, cls = "") => h("button", { type: "button", class: `pe-btn ${cls}`, "aria-label": label, onclick: fn },
    ic ? icon(ic, "ph-fill") : playIco);
  const bar = h("div", { class: "pe-bar" }, fill);
  bar.addEventListener("click", (e) => {
    const d = Number(media.duration) || 0;
    if (!(d > 0)) return;
    const r = bar.getBoundingClientRect();
    const s = Math.max(0, Math.min(d - 1, ((e.clientX - r.left) / r.width) * d));
    media = { ...media, position: s, at: Date.now() / 1000 };
    quick("media_seek", { seconds: Math.round(s) });
  });
  const el = h("div", { class: "pe-music", hidden: true }, glow,
    h("div", { class: "pe-mrow" }, h("div", { class: "pe-artbox" }, art, icon("music-notes", "ph-fill")),
      h("div", { class: "pe-meta" }, title, artist)),
    h("div", { class: "pe-time-row" }, bar, h("div", { class: "pe-times" }, t0, t1)),
    h("div", { class: "pe-ctl" },
      b("skip-back", "Předchozí", () => quick("media_control", { action: "previous" })),
      b(null, "Přehrát / pauza", () => { media = { ...media, playing: !media.playing, position: pos(), at: Date.now() / 1000 }; paint(); quick("media_control", { action: "play_pause" }); }, "main"),
      b("skip-forward", "Další", () => quick("media_control", { action: "next" }))));
  const pos = () => typeof media.position === "number"
    ? Math.min(Number(media.duration) || 1e9, media.position + (media.playing ? Math.max(0, Date.now() / 1000 - (media.at || Date.now() / 1000)) : 0)) : -1;
  const frame = () => {
    raf = 0;
    const d = Number(media.duration) || 0, p = pos();
    el.classList.toggle("no-time", !(d > 0 && p >= 0));
    if (d > 0 && p >= 0) {
      fill.style.transform = `scaleX(${Math.min(1, p / d).toFixed(4)})`;
      t0.textContent = mmss(p); t1.textContent = `-${mmss(d - p)}`;
    }
    if (media.playing && el.isConnected && !el.hidden && document.visibilityState === "visible") raf = window.setTimeout(frame, 500) as unknown as number;
  };
  const paint = () => {
    el.hidden = !media?.title;
    title.textContent = media.title || "";
    artist.textContent = media.artist || "";
    const th = media.thumb ? String(media.thumb) : "";
    if (art.getAttribute("src") !== th) { if (th) { art.src = th; glow.src = th; } else { art.removeAttribute("src"); glow.removeAttribute("src"); } }
    el.classList.toggle("has-art", !!th);
    el.classList.toggle("playing", !!media.playing);
    const want = media.playing ? "pause" : "play";
    if (playIco.dataset.i !== want) { playIco.dataset.i = want; playIco.replaceChildren(icon(want, "ph-fill")); }
    if (raf) window.clearTimeout(raf);
    frame();
  };
  c.on("welcome", (m) => { media = m.media || {}; paint(); });
  c.on("media", (m) => { media = m || {}; paint(); });
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") frame(); });
  return el;
}

/** Více → "Vzhled telefonu" */
export function phoneLookCard() {
  const file = h("input", { type: "file", accept: "image/*", hidden: true }) as HTMLInputElement;
  const box = h("div", { class: "pe-look" });
  const card = h("div", { class: "card" }, h("h2", {}, "Vzhled telefonu"), box, file);
  file.onchange = async () => {
    const f = file.files?.[0]; file.value = "";
    if (!f) return;
    try {
      if (!savePhoto(await shrinkPhoto(f))) { toast("Fotka je moc velká – zkus menší", "error"); return; }
      saveLook({ ...loadLook(), bg: "photo" }); paint();
    } catch (e: any) { toast(e.message || "Fotku se nepodařilo načíst", "error"); }
  };
  const paint = () => {
    const look = loadLook(), photo = loadPhoto(), col = getColor();
    const opt = (k: Look["bg"], label: string, prev: Node) => h("button", { type: "button", class: `pe-opt ${look.bg === k ? "on" : ""}`,
      onclick: () => { if (k === "photo" && !photo) { file.click(); return; } saveLook({ ...look, bg: k }); paint(); native.haptic(); } }, prev, h("span", {}, label));
    const range = (k: "dim" | "blur", label: string, max: number) => {
      const r = h("input", { type: "range", min: 0, max, value: look[k], "aria-label": label }) as HTMLInputElement;
      r.oninput = () => saveLook({ ...loadLook(), [k]: Number(r.value) });
      return h("label", { class: "pe-range" }, h("span", {}, label), r);
    };
    box.replaceChildren(
      h("div", { class: "pe-opts" },
        opt("none", "Černé", h("i", { class: "pe-prev black" })),
        opt("album", "Barvy hudby", h("i", { class: "pe-prev album" })),
        opt("photo", "Moje fotka", photo ? h("i", { class: "pe-prev", style: { backgroundImage: `url("${photo}")` } }) : h("i", { class: "pe-prev add" }, icon("plus")))),
      photo ? h("button", { type: "button", class: "btn", onclick: () => file.click() }, icon("image"), "Vybrat jinou fotku") : "",
      look.bg !== "none" ? h("div", { class: "pe-ranges" }, range("dim", "Ztmavení", 85), range("blur", "Rozmazání", 30)) : "",
      h("div", { class: "pe-colors" }, h("span", {}, "Barva hodin"),
        h("div", {}, ...COLORS.map((cc) => h("button", { type: "button", class: `pe-sw ${cc === col ? "on" : ""}`, style: { background: cc }, "aria-label": `Barva ${cc}`,
          onclick: () => { setColor(cc); paint(); } })))));
  };
  paint();
  return card;
}
