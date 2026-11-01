/* 3.12 the living face of the island: two glowing eyes in the black pill when nothing else is going on.
   They blink, look around, look at the mouse over the notch, squint happily when you come near, and show what
   JARVIS is doing (listening, thinking, working, talking, sleeping…). Everything is event driven: a few CSS
   variables change now and then and CSS transitions do the movement – no animation loop running all the time. */
import { h } from "../shared/dom";

type Expr = { c: string; open: number; tilt: number; happy: boolean; anim: string; look?: [number, number] | "up" | "down" | "side" };

const WHITE = "#eaf6ff";
const EXPR: Record<string, Expr> = {
  neutral: { c: WHITE, open: 1, tilt: 0, happy: false, anim: "" },
  hover: { c: WHITE, open: 1, tilt: 0, happy: true, anim: "" },
  listening: { c: "#5ac8fa", open: 1.18, tilt: 0, happy: false, anim: "pulse" },
  thinking: { c: "#bf8cff", open: 0.78, tilt: 0, happy: false, anim: "", look: "up" },
  working: { c: "#ffa53d", open: 0.55, tilt: 0, happy: false, anim: "", look: "down" },
  speaking: { c: "#64d2ff", open: 1, tilt: 0, happy: false, anim: "talk" },
  happy: { c: "#4cd97b", open: 1, tilt: 0, happy: true, anim: "bob" },
  error: { c: "#ff5a5f", open: 0.72, tilt: 14, happy: false, anim: "shake" },
  sleeping: { c: WHITE, open: 0.1, tilt: 0, happy: false, anim: "sleep" },
  notify: { c: "#ffd43b", open: 1.25, tilt: 0, happy: false, anim: "" },
  waiting: { c: "#ffb340", open: 0.9, tilt: 0, happy: false, anim: "", look: "side" },
  annoyed: { c: WHITE, open: 0.35, tilt: -8, happy: false, anim: "" },
  dizzy: { c: "#bf8cff", open: 0.8, tilt: 0, happy: false, anim: "dizzy" },
};
const MOOD_EXPR: Record<string, string> = {
  hover: "hover", expanded: "hover", opening: "hover", listening: "listening", thinking: "thinking", working: "working",
  updating: "working", desktop_interact: "working", speaking: "speaking", success: "happy", joy: "happy", dancing: "happy",
  error: "error", limit: "error", sleeping: "sleeping", offline: "sleeping", notify: "notify", waiting: "waiting",
  annoyed: "annoyed", dizzy: "dizzy",
};

const rnd = (a: number, b: number) => a + Math.random() * (b - a);

export function createFace(reduced: () => boolean) {
  const eye = (side: string) => h("span", { class: `fe ${side}` }, h("span", { class: "fe-lid" }, h("i", { class: "fe-ball" }), h("i", { class: "fe-arc" })));
  const el = h("div", { class: "dy-face", "aria-hidden": "true" },
    h("span", { class: "fe-glow" }), eye("l"), eye("r"),
    h("span", { class: "fe-zz" }, h("i", {}, "z"), h("i", {}, "z"), h("i", {}, "z")));
  let expr = "neutral", visible = false, pointer: [number, number] | null = null, quirk = "";
  let lookT = 0, blinkT = 0, quirkT = 0, sideFlip = 1;

  function set(lx: number, ly: number) {
    // a touch of depth: the eye on the side you look at comes a little closer
    el.style.setProperty("--lx", `${(lx * 8).toFixed(2)}px`);
    el.style.setProperty("--ly", `${(ly * 3.2).toFixed(2)}px`);
    el.style.setProperty("--sl", (1 - lx * 0.07).toFixed(3));
    el.style.setProperty("--sr", (1 + lx * 0.07).toFixed(3));
  }
  function paint() {
    const e = EXPR[quirk || expr] || EXPR.neutral;
    el.dataset.expr = quirk || expr;
    el.dataset.anim = e.anim;
    el.style.setProperty("--c", e.c);
    el.style.setProperty("--open", String(e.open));
    el.style.setProperty("--tilt", `${e.tilt}deg`);
    el.classList.toggle("happy", e.happy);
  }
  function look() {
    window.clearTimeout(lookT);
    const e = EXPR[expr] || EXPR.neutral;
    if (pointer) set(pointer[0], pointer[1]);
    else if (e.look === "up") set(rnd(-0.8, 0.8), -1);
    else if (e.look === "down") set(rnd(-0.3, 0.3), 0.8);
    else if (e.look === "side") { sideFlip = -sideFlip; set(sideFlip * 0.9, 0); }
    else if (expr === "sleeping" || reduced()) set(0, 0);
    else if (Math.random() < 0.42) set(rnd(-0.12, 0.12), rnd(-0.1, 0.1));      // mostly back to the middle
    else set(rnd(-1, 1), rnd(-0.9, 0.6));
    if (!reduced()) lookT = window.setTimeout(look, e.look === "side" ? 1400 : e.look ? rnd(900, 1800) : rnd(1600, 4200));
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
  // every half a minute or so a little something: a happy squint, a quick glance aside, a sleepy moment
  function quirks() {
    window.clearTimeout(quirkT);
    quirkT = window.setTimeout(() => {
      if (visible && expr === "neutral" && !pointer && !reduced()) {
        const q = Math.random();
        if (q < 0.4) { quirk = "hover"; paint(); window.setTimeout(() => { quirk = ""; paint(); }, 1400); }
        else if (q < 0.75) { set(-1, 0); window.setTimeout(() => set(1, 0), 520); window.setTimeout(() => set(0, 0), 1150); }
        else { quirk = "annoyed"; paint(); window.setTimeout(() => { quirk = ""; paint(); blink(); }, 1100); }
      }
      quirks();
    }, rnd(22000, 48000));
  }

  return {
    el,
    /** what JARVIS is doing (the notch's display mood) */
    mood(m: string) {
      const next = MOOD_EXPR[m] || "neutral";
      if (next === expr) return;
      expr = next;
      quirk = "";
      paint();
      look();
    },
    show(on: boolean) {
      if (on === visible) return;
      visible = on;
      el.classList.toggle("on", on);
      if (on) { look(); blink(); quirks(); }
      else { window.clearTimeout(lookT); window.clearTimeout(blinkT); window.clearTimeout(quirkT); }
    },
    /** the mouse over the notch (-1…1 from the middle of the pill), or null when it left */
    pointer(p: [number, number] | null) {
      pointer = p ? [Math.max(-1, Math.min(1, p[0])), Math.max(-1, Math.min(1, p[1]))] : null;
      if (pointer) set(pointer[0], pointer[1]);
      else look();
    },
    /** a short look of joy (a finished task, a new song…) */
    react(kind: "happy" | "notify") {
      quirk = kind;
      paint();
      window.setTimeout(() => { quirk = ""; paint(); }, 1600);
    },
    init() { paint(); set(0, 0); },
  };
}
