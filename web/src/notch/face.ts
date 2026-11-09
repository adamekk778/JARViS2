/* 3.12 the living face of the island: two glowing eyes in the black pill when nothing else is going on.
   They blink, look around, look at the mouse over the notch, squint happily when you come near, turn into hearts or
   stars, wink, and show what JARVIS is doing (listening, thinking, working, talking, sleeping, focus…). Everything is
   event driven: a few CSS variables change now and then and CSS transitions do the movement – no animation loop. */
import { h } from "../shared/dom";

type Shape = "ball" | "arc" | "heart" | "star" | "angry" | "sad";
type Expr = { c: string; open: number; shape: Shape; anim: string; look?: "up" | "down" | "side" | "fixed" };

const WHITE = "#eaf6ff";
const EXPR: Record<string, Expr> = {
  neutral: { c: WHITE, open: 1, shape: "ball", anim: "" },
  hover: { c: WHITE, open: 1, shape: "arc", anim: "" },
  listening: { c: "#5ac8fa", open: 1.18, shape: "ball", anim: "pulse" },
  thinking: { c: "#bf8cff", open: 0.78, shape: "ball", anim: "", look: "up" },
  working: { c: "#ffa53d", open: 0.55, shape: "ball", anim: "", look: "down" },
  speaking: { c: "#64d2ff", open: 1, shape: "ball", anim: "talk" },
  happy: { c: "#4cd97b", open: 1, shape: "arc", anim: "bob" },
  love: { c: "#ff5c8a", open: 1, shape: "heart", anim: "beat" },
  star: { c: "#ffd60a", open: 1, shape: "star", anim: "twinkle" },
  focus: { c: "#ffb340", open: 0.62, shape: "ball", anim: "", look: "fixed" },
  angry: { c: "#ff453a", open: 0.9, shape: "angry", anim: "shake" },
  error: { c: "#ff5a5f", open: 0.85, shape: "sad", anim: "shake" },
  sleeping: { c: WHITE, open: 0.1, shape: "ball", anim: "sleep" },
  notify: { c: "#ffd43b", open: 1.25, shape: "ball", anim: "", look: "down" },
  waiting: { c: "#ffb340", open: 0.9, shape: "ball", anim: "", look: "side" },
  annoyed: { c: WHITE, open: 0.35, shape: "ball", anim: "" },
  dizzy: { c: "#bf8cff", open: 0.8, shape: "ball", anim: "dizzy" },
};
const MOOD_EXPR: Record<string, string> = {
  hover: "hover", expanded: "hover", opening: "hover", listening: "listening", thinking: "thinking", working: "working",
  updating: "working", desktop_interact: "working", speaking: "speaking", success: "star", joy: "love", dancing: "love",
  error: "error", limit: "error", sleeping: "sleeping", offline: "sleeping", notify: "notify", waiting: "waiting",
  annoyed: "annoyed", dizzy: "dizzy", focus: "focus",
};

const rnd = (a: number, b: number) => a + Math.random() * (b - a);
const HEART = '<svg viewBox="0 0 24 22" aria-hidden="true"><path d="M12 21.2S2.2 15 1.1 8.9A5.6 5.6 0 0 1 12 5a5.6 5.6 0 0 1 10.9 3.9C21.8 15 12 21.2 12 21.2z"/></svg>';
const STAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1.5l2.9 6.6 7.1.7-5.4 4.8 1.6 7-6.2-3.7-6.2 3.7 1.6-7L2 8.8l7.1-.7z"/></svg>';

export function createFace(reduced: () => boolean) {
  const eye = (side: string) => {
    const heart = h("i", { class: "fe-heart" }); heart.innerHTML = HEART;
    const star = h("i", { class: "fe-star" }); star.innerHTML = STAR;
    return h("span", { class: `fe ${side}` }, h("i", { class: "fe-brow" }), h("span", { class: "fe-lid" }, h("i", { class: "fe-ball" }), h("i", { class: "fe-arc" }), heart, star));
  };
  const el = h("div", { class: "dy-face", "aria-hidden": "true" },
    h("span", { class: "fe-glow" }), eye("l"), eye("r"),
    h("span", { class: "fe-zz" }, h("i", {}, "z"), h("i", {}, "z"), h("i", {}, "z")));
  let expr = "neutral", visible = false, pointer: [number, number] | null = null, quirk = "", focusOn = false;
  let lookT = 0, blinkT = 0, quirkT = 0, quirkEnd = 0, loveT = 0, sideFlip = 1;

  function set(lx: number, ly: number) {
    // a touch of depth: the eye on the side you look at comes a little closer
    el.style.setProperty("--lx", `${(lx * 8).toFixed(2)}px`);
    el.style.setProperty("--ly", `${(ly * 3.2).toFixed(2)}px`);
    el.style.setProperty("--sl", (1 - lx * 0.07).toFixed(3));
    el.style.setProperty("--sr", (1 + lx * 0.07).toFixed(3));
  }
  const base = () => (expr === "neutral" && focusOn ? "focus" : expr);
  function paint() {
    const name = quirk || base();
    const e = EXPR[name] || EXPR.neutral;
    el.dataset.expr = name;
    el.dataset.anim = e.anim;
    el.dataset.shape = e.shape;
    el.style.setProperty("--c", e.c);
    el.style.setProperty("--open", String(e.open));
  }
  /** a look for a moment, then back to what JARVIS is doing */
  function flash(name: string, ms: number) {
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
  // every half a minute or so a little something: hearts, a wink, a happy squint, a glance aside, an eye roll…
  function quirks() {
    window.clearTimeout(quirkT);
    quirkT = window.setTimeout(() => {
      if (visible && expr === "neutral" && !focusOn && !pointer && !quirk && !reduced()) {
        const q = Math.random();
        if (q < 0.2) flash("love", 2200);
        else if (q < 0.38) { el.classList.add("wink"); window.setTimeout(() => el.classList.remove("wink"), 650); }
        else if (q < 0.55) flash("hover", 1400);
        else if (q < 0.72) { set(-1, 0); window.setTimeout(() => set(1, 0), 520); window.setTimeout(() => set(0, 0), 1150); }
        else if (q < 0.86) {                                                         // an eye roll
          set(-1, -0.6); window.setTimeout(() => set(0, -1), 260); window.setTimeout(() => set(1, -0.6), 520);
          window.setTimeout(() => set(0, 0), 900);
        } else { flash("annoyed", 1100); window.setTimeout(blink, 1150); }
      }
      quirks();
    }, rnd(18000, 40000));
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
    /** the focus mode is on: steady, determined eyes */
    focus(on: boolean) {
      if (on === focusOn) return;
      focusOn = on;
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
    /** a short look: hearts, stars, a frown… */
    react(kind: "love" | "star" | "happy" | "notify" | "angry", ms = 1800) { flash(kind, ms); },
    init() { paint(); set(0, 0); },
  };
}
