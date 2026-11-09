/* 3.12 the living face of the island: two glowing eyes. They blink, look around, follow the mouse over the notch and
   change shape with what is going on – hearts, stars, ? when Claude asks, ! when something needs a yes, a flame when
   you start focusing, X X when every AI is at its limit… (EXPR below, about 40 looks). Event driven: a few CSS variables
   change now and then and CSS transitions do the movement – no animation loop running all the time. */
import { h } from "../shared/dom";

// ---- eye shapes (SVG, drawn in the eye's colour) ----
const S20 = (body: string, stroke = false) =>
  `<svg viewBox="0 0 20 20" aria-hidden="true" ${stroke ? 'fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"' : 'fill="currentColor"'}>${body}</svg>`;
const T20 = (ch: string, size = 17) => `<svg viewBox="0 0 20 20" aria-hidden="true"><text x="10" y="16.2" text-anchor="middle" font-size="${size}" font-weight="900" font-family="system-ui, sans-serif" fill="currentColor">${ch}</text></svg>`;
const GLYPH: Record<string, string> = {
  arc: S20('<path d="M3 13.5Q10 2 17 13.5"/>', true),
  u: S20('<path d="M3 7Q10 18 17 7"/>', true),
  heart: '<svg viewBox="0 0 24 22" aria-hidden="true" fill="currentColor"><path d="M12 21.2S2.2 15 1.1 8.9A5.6 5.6 0 0 1 12 5a5.6 5.6 0 0 1 10.9 3.9C21.8 15 12 21.2 12 21.2z"/></svg>',
  star: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M12 1.5l2.9 6.6 7.1.7-5.4 4.8 1.6 7-6.2-3.7-6.2 3.7 1.6-7L2 8.8l7.1-.7z"/></svg>',
  ring: S20('<circle cx="10" cy="10" r="6.2"/>', true),
  dot: S20('<circle cx="10" cy="10" r="3.4"/>'),
  x: S20('<path d="M4.5 4.5l11 11M15.5 4.5l-11 11"/>', true),
  gt: S20('<path d="M5.5 4l9 6-9 6"/>', true),
  lt: S20('<path d="M14.5 4l-9 6 9 6"/>', true),
  line: S20('<path d="M3 10.5h14"/>', true),
  spiral: S20('<path d="M10 10m0-1.6a1.6 1.6 0 1 1-1.6 1.6 3.2 3.2 0 1 1 3.2 3.2 4.8 4.8 0 1 1-4.8-4.8 6.4 6.4 0 1 1 6.4 6.4" stroke-width="2"/>', true),
  sparkle: S20('<path d="M10 1c.9 6.6 2.4 8.1 9 9-6.6.9-8.1 2.4-9 9-.9-6.6-2.4-8.1-9-9 6.6-.9 8.1-2.4 9-9z"/>'),
  ask: T20("?"),
  bang: T20("!"),
  note: S20('<path d="M8.2 15.6a2.7 2.7 0 1 1-1.7-2.5V3.4l8.4-1.9v10.9a2.7 2.7 0 1 1-1.7-2.5V5.5L8.2 6.7z"/>'),
  check: S20('<path d="M3.5 10.5L8 15l8.5-10"/>', true),
  flame: S20('<path d="M10 1.2c1.2 3.7 5.4 5.8 5.4 10.6A5.4 5.4 0 0 1 4.6 12c0-2.8 1.7-4.2 2.6-5.8.4 1.7 1.3 2.6 2.2 2.8C10.1 6.6 9.6 3.8 10 1.2z"/>'),
  moon: S20('<path d="M13.6 2.2a8 8 0 1 0 4.4 14.4A6.4 6.4 0 0 1 13.6 2.2z"/>'),
  sun: S20('<circle cx="10" cy="10" r="4.2"/><path d="M10 .8v2.6M10 16.6v2.6M.8 10h2.6M16.6 10h2.6M3.5 3.5l1.8 1.8M14.7 14.7l1.8 1.8M3.5 16.5l1.8-1.8M14.7 5.3l1.8-1.8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'),
  square: S20('<rect x="3.5" y="3.5" width="13" height="13" rx="2.5"/>'),
  diamond: S20('<path d="M10 1.5L18.5 10 10 18.5 1.5 10z"/>'),
  down: S20('<path d="M10 3v12M4.5 9.8L10 15.3l5.5-5.5"/>', true),
  bolt: S20('<path d="M11.6 1L3.8 11.2h5.6L8.4 19l7.8-10.2h-5.6z"/>'),
  plus: S20('<path d="M10 3.5v13M3.5 10h13"/>', true),
  zero: S20('<ellipse cx="10" cy="10" rx="5" ry="7.5"/>', true),
};

type Expr = { c: string; l?: string; r?: string; open?: number; anim?: string; look?: "up" | "down" | "side" | "fixed"; brow?: "angry" | "sad"; tear?: boolean };
const WHITE = "#eaf6ff";
/** every look of the eyes; l / r = the shape of each eye (none = the glowing capsule) */
export const EXPR: Record<string, Expr> = {
  neutral: { c: WHITE },
  hover: { c: WHITE, l: "arc", r: "arc" },
  happy: { c: "#4cd97b", l: "arc", r: "arc", anim: "bob" },
  content: { c: WHITE, l: "u", r: "u", anim: "breathe" },
  love: { c: "#ff5c8a", l: "heart", r: "heart", anim: "beat" },
  kiss: { c: "#ff5c8a", l: "arc", r: "heart", anim: "beat" },
  star: { c: "#ffd60a", l: "star", r: "star", anim: "twinkle" },
  starwink: { c: "#ffd60a", l: "star", r: "arc", anim: "twinkle" },
  party: { c: "#ff5cd6", l: "star", r: "star", anim: "party" },
  wink: { c: WHITE, r: "arc" },
  laugh: { c: "#4cd97b", l: "gt", r: "lt", anim: "bob" },
  squeeze: { c: WHITE, l: "gt", r: "lt", anim: "shake" },
  surprised: { c: WHITE, l: "ring", r: "ring", open: 1 },
  shocked: { c: "#ffd43b", l: "dot", r: "dot" },
  wow: { c: "#5ac8fa", l: "zero", r: "zero" },
  curious: { c: WHITE, l: "ring", anim: "tilt" },
  skeptical: { c: WHITE, l: "line" },
  bored: { c: "#9aa3ae", l: "line", r: "line" },
  annoyed: { c: WHITE, open: 0.35 },
  focus: { c: "#ffb340", open: 0.62, look: "fixed" },
  determined: { c: "#ff9f0a", l: "flame", r: "flame", anim: "flicker" },
  angry: { c: "#ff453a", open: 0.9, brow: "angry", anim: "shake" },
  sad: { c: "#ff5a5f", open: 0.85, brow: "sad", anim: "shake" },
  cry: { c: "#64d2ff", open: 0.8, brow: "sad", tear: true },
  ko: { c: "#ff453a", l: "x", r: "x" },
  dizzy: { c: "#bf8cff", l: "spiral", r: "spiral", anim: "spin" },
  listening: { c: "#5ac8fa", open: 1.18, anim: "pulse" },
  thinking: { c: "#bf8cff", open: 0.78, look: "up" },
  working: { c: "#ffa53d", open: 0.55, look: "down" },
  speaking: { c: "#64d2ff", anim: "talk" },
  sleeping: { c: WHITE, open: 0.1, anim: "sleep" },
  notify: { c: "#ffd43b", open: 1.25, look: "down" },
  alert: { c: "#ffd43b", l: "bang", r: "bang", anim: "bounce" },
  ask: { c: "#ffb340", l: "ask", r: "ask", anim: "bounce" },
  waiting: { c: "#ffb340", open: 0.9, look: "side" },
  music: { c: "#ff6fa8", l: "note", r: "note", anim: "groove" },
  sparkle: { c: "#7fe7ff", l: "sparkle", r: "sparkle", anim: "twinkle" },
  done: { c: "#4cd97b", l: "check", r: "check", anim: "pop" },
  download: { c: "#0a84ff", l: "down", r: "down", anim: "bounce" },
  charge: { c: "#ffd60a", l: "bolt", r: "bolt", anim: "flicker" },
  robot: { c: "#7fe7ff", l: "square", r: "square", anim: "glitch" },
  diamond: { c: "#bf8cff", l: "diamond", r: "diamond", anim: "twinkle" },
  moon: { c: "#c9d6ff", l: "moon", r: "moon", anim: "breathe" },
  sun: { c: "#ffcc4d", l: "sun", r: "sun", anim: "spin-slow" },
  heal: { c: "#4cd97b", l: "plus", r: "plus", anim: "pulse" },
};
const MOOD_EXPR: Record<string, string> = {
  hover: "hover", expanded: "hover", opening: "hover", listening: "listening", thinking: "thinking", working: "working",
  updating: "download", desktop_interact: "robot", speaking: "speaking", success: "star", joy: "love", dancing: "music",
  error: "sad", limit: "ko", sleeping: "sleeping", offline: "bored", notify: "notify", waiting: "ask",
  annoyed: "annoyed", dizzy: "dizzy", focus: "focus", personalize: "sparkle", dragged: "squeeze",
};

const rnd = (a: number, b: number) => a + Math.random() * (b - a);
const pick = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)];

export function createFace(reduced: () => boolean) {
  const eye = (side: string) => h("span", { class: `fe ${side}` }, h("i", { class: "fe-brow" }),
    h("span", { class: "fe-lid" }, h("i", { class: "fe-ball" }), h("i", { class: "fe-g" })), h("i", { class: "fe-tear" }));
  const L = eye("l"), R = eye("r");
  const el = h("div", { class: "dy-face", "aria-hidden": "true" },
    h("span", { class: "fe-glow" }), L, R,
    h("span", { class: "fe-zz" }, h("i", {}, "z"), h("i", {}, "z"), h("i", {}, "z")));
  let expr = "neutral", situation = "", visible = false, pointer: [number, number] | null = null, quirk = "", focusOn = false;
  let lookT = 0, blinkT = 0, quirkT = 0, quirkEnd = 0, loveT = 0, sideFlip = 1;

  function set(lx: number, ly: number) {
    // a touch of depth: the eye on the side you look at comes a little closer
    el.style.setProperty("--lx", `${(lx * 8).toFixed(2)}px`);
    el.style.setProperty("--ly", `${(ly * 3.2).toFixed(2)}px`);
    el.style.setProperty("--sl", (1 - lx * 0.07).toFixed(3));
    el.style.setProperty("--sr", (1 + lx * 0.07).toFixed(3));
  }
  const base = () => situation || (expr === "neutral" && focusOn ? "focus" : expr);
  function glyph(e: HTMLElement, shape: string | undefined) {
    const g = e.querySelector(".fe-g") as HTMLElement;
    const key = shape || "";
    if (g.dataset.s === key) return;
    g.dataset.s = key;
    g.innerHTML = key ? GLYPH[key] || "" : "";
    e.classList.toggle("has-g", !!key);
    // a soft morph: the new shape comes out of a blur while the capsule melts away (no pop, no spin)
    if (key && !reduced()) g.animate([{ transform: "scale(.55)", opacity: 0, filter: "blur(5px)" }, { transform: "none", opacity: 1, filter: "blur(0)" }],
      { duration: 340, easing: "cubic-bezier(.2,.8,.2,1)" });
  }
  function paint() {
    const name = quirk || base();
    const e = EXPR[name] || EXPR.neutral;
    el.dataset.expr = name;
    el.dataset.anim = e.anim || "";
    el.dataset.brow = e.brow || "";
    el.classList.toggle("tears", !!e.tear);
    el.style.setProperty("--c", e.c);
    el.style.setProperty("--open", String(e.open ?? 1));
    glyph(L, e.l);
    glyph(R, e.r);
  }
  /** a look for a moment, then back to what JARVIS is doing */
  function flash(name: string, ms: number) {
    if (!EXPR[name]) return;
    quirk = name;
    paint();
    window.clearTimeout(quirkEnd);
    quirkEnd = window.setTimeout(() => { quirk = ""; paint(); }, ms);
  }
  function look() {
    window.clearTimeout(lookT);
    const e = EXPR[base()] || EXPR.neutral;
    if (pointer) set(pointer[0], pointer[1]);
    else if (e.look === "up") set(rnd(-0.8, 0.8), -1);
    else if (e.look === "down") set(rnd(-0.3, 0.3), 0.8);
    else if (e.look === "side") { sideFlip = -sideFlip; set(sideFlip * 0.9, 0); }
    else if (e.look === "fixed") set(rnd(-0.08, 0.08), 0.1);                         // focus: steady, straight ahead
    else if (expr === "sleeping" || reduced()) set(0, 0);
    else if (Math.random() < 0.42) set(rnd(-0.12, 0.12), rnd(-0.1, 0.1));      // mostly back to the middle
    else set(rnd(-1, 1), rnd(-0.9, 0.6));
    if (!reduced()) lookT = window.setTimeout(look, e.look === "side" ? 1400 : e.look === "fixed" ? rnd(4000, 7000) : e.look ? rnd(900, 1800) : rnd(1600, 4200));
  }
  function blink() {
    window.clearTimeout(blinkT);
    if (visible && expr !== "sleeping" && !reduced()) {
      el.classList.remove("blink");
      void el.offsetWidth;                                                         // restart the animation
      el.classList.add("blink");
      window.setTimeout(() => el.classList.remove("blink"), 180);
      if (Math.random() < 0.2) window.setTimeout(blink, 260);                       // now and then a double blink
    }
    blinkT = window.setTimeout(blink, rnd(2400, 6200));
  }
  // every so often a little something: hearts, a wink, a laugh, a glance aside, an eye roll, at night a moon…
  function quirks() {
    window.clearTimeout(quirkT);
    quirkT = window.setTimeout(() => {
      if (visible && expr === "neutral" && !situation && !focusOn && !pointer && !quirk && !reduced()) {
        const hr = new Date().getHours();
        const q = Math.random();
        if (q < 0.12) flash("wink", 700);
        else if (q < 0.24) { set(-1, 0); window.setTimeout(() => set(1, 0), 520); window.setTimeout(() => set(0, 0), 1150); }
        else if (q < 0.33) {                                                         // an eye roll
          set(-1, -0.6); window.setTimeout(() => set(0, -1), 260); window.setTimeout(() => set(1, -0.6), 520);
          window.setTimeout(() => set(0, 0), 900);
        } else if (q < 0.45 && (hr >= 22 || hr < 5)) flash("moon", 2600);
        else if (q < 0.45 && hr >= 6 && hr < 10) flash("sun", 2400);
        else flash(pick(["hover", "content", "content", "love", "curious", "skeptical", "starwink", "surprised"]), 1500);
      }
      quirks();
    }, rnd(22000, 50000));
  }

  return {
    el,
    /** what JARVIS is doing (the notch's display mood) */
    mood(m: string) {
      const next = MOOD_EXPR[m] || "neutral";
      if (next === expr) return;
      expr = next;
      if (quirk !== "angry") quirk = "";
      paint();
      look();
    },
    /** something that wins over the mood: "ask" (Claude asks), "alert" (a yes / no waits)… or "" */
    situation(name: string) {
      const n = EXPR[name] ? name : "";
      if (n === situation) return;
      situation = n;
      paint();
      look();
    },
    /** the focus mode is on: steady, determined eyes (a flame when it starts) */
    focus(on: boolean) {
      if (on === focusOn) return;
      focusOn = on;
      if (on) flash("determined", 2200);
      else flash("party", 2000);
      paint();
      look();
    },
    show(on: boolean) {
      if (on === visible) return;
      visible = on;
      el.classList.toggle("on", on);
      if (on) {
        el.classList.remove("wake"); void el.offsetWidth; el.classList.add("wake");   // eyes open as the face appears
        look(); blink(); quirks();
      } else { window.clearTimeout(lookT); window.clearTimeout(blinkT); window.clearTimeout(quirkT); }
    },
    /** the mouse over the notch (-1…1 from the middle of the pill), or null when it left */
    pointer(p: [number, number] | null) {
      const was = pointer;
      pointer = p ? [Math.max(-1, Math.min(1, p[0])), Math.max(-1, Math.min(1, p[1]))] : null;
      if (pointer) set(pointer[0], pointer[1]);
      else look();
      // stay a moment over the notch and the eyes fall in love
      if (pointer && !was) { window.clearTimeout(loveT); loveT = window.setTimeout(() => { if (pointer && !reduced()) flash("love", 2400); }, 1800); }
      if (!pointer) window.clearTimeout(loveT);
    },
    /** a short look (any name from EXPR) */
    react(kind: string, ms = 1800) { flash(kind, ms); },
    init() { paint(); set(0, 0); },
  };
}
