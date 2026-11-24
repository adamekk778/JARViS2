import "./blob.css";
import { OUTFIT_SVG, resolveOutfit } from "./outfits";
import { BODY_COLORS, EYES, LOOKS, type Accessory, type CharacterColor, type Eye, type Look, type Mood } from "./looks";
import { PERSONALITY_ENERGY, ambientExtra, reactionPhases, type Ambient, type Phase, type Reaction } from "./reactions";
import { at, onTier, tier } from "../shared/motion";

export type { Mood, CharacterColor } from "./looks";
export { MOODS, MOOD_LABEL } from "./looks";

const SVG = "http://www.w3.org/2000/svg";
// gumdrop: a near-circular ellipse (rx 90, ry 86) cut flat at the bottom, soft corners
const BODY = "M 36 175 Q 22 175 17.8 166 A 90 86 0 1 1 182.2 166 Q 178 175 164 175 Z";
const EYE_X = 35;
const EYE_Y = 133;
export const DEFAULT_GLOW = "#4f8dff";
let uidSeq = 0;

const el = <K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number> = {}) => {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
  return n;
};
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

function eyePath(e: Eye): string {
  const { w, h, top, bottom } = e;
  const f = (n: number) => n.toFixed(2);
  return `M ${f(-w)} 0 C ${f(-w)} ${f(-h * top)} ${f(w)} ${f(-h * top)} ${f(w)} 0 C ${f(w)} ${f(h * bottom)} ${f(-w)} ${f(h * bottom)} ${f(-w)} 0 Z`;
}

const prefersReduced = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;
function reducedMotion(): boolean {
  return document.documentElement.dataset.motion === "reduced" || !!prefersReduced?.matches;
}

export interface BlobOptions {
  size?: number;          // px
  color?: CharacterColor;
  glow?: string;          // css colour; default = JARVIS blue
  trackCursor?: boolean;  // eyes follow the mouse inside this window
}

export interface MoodExtra {
  badge?: number;
  progress?: number | null;
  reaction?: Reaction | null;   // a one-off reaction to play over the mood (played once per id)
  secondary?: Mood | null;      // a second feeling blended into the eyes
  ambient?: Ambient;            // time of day / weather props
  [k: string]: unknown;         // the whole "mood" message can be passed as is
}

const CALM = new Set<Mood>(["idle", "closed", "hover", "expanded", "focus"]);

export class Blob {
  el: HTMLElement;
  mood: Mood = "idle";
  private look: Look = LOOKS.idle;
  private eye: Eye = { ...EYES.open };
  private body = { bob: 0, squash: 1, tilt: 0, glow: 0.45, dim: 0 };
  private gaze = { x: 0, y: 0 };
  private cursor: { x: number; y: number; t: number } | null = null;
  private glance = { x: 0, y: 0, until: 0, next: performance.now() + 5000 };
  private blinkUntil = 0;
  private nextBlink = performance.now() + 2500;
  private moodStart = performance.now();
  private level = 0;
  private progress: number | null = null;
  private badge = 0;
  private raf = 0;
  private last = performance.now();
  private svgBody: SVGGElement;
  private outfitG!: SVGGElement;
  outfit = "none";
  private eyeL: SVGPathElement;
  private eyeR: SVGPathElement;
  private eyesG: SVGGElement;
  private shadow: SVGEllipseElement;
  private acc: HTMLElement;
  private bars: HTMLElement[] = [];
  private progressEl: HTMLElement | null = null;
  private badgeEl: HTMLElement | null = null;
  private grads: { light: SVGStopElement; mid: SVGStopElement; dark: SVGStopElement };
  private glowColor = "";
  private cuts: { cut: SVGEllipseElement; side: 1 | -1 }[] = [];
  private fx: HTMLElement;
  private reaction: { phases: Phase[]; start: number; idx: number } | null = null;
  private lastReaction = -1;
  private secondary: Mood | null = null;
  private ambient: Ambient | undefined;
  private ambientOn = true;
  private energy = 1;
  private fxHtml = "";
  // OMEGA 743: soft body – a damped spring on the squash (x > 0 = wide and short), kicked by landings, pokes and mood changes
  private jelly = { x: 0, v: 0 };
  private lastLand = -1;
  /** Kick the soft body (positive = flatten, negative = stretch up). */
  wobble(strength = 1.5) { this.jelly.v += strength; }
  // 3.15 Mega animace: liquid metal, the real voice wave, the jobs orbiting him, the beat, feelings of his own
  private liquidG!: SVGGElement;
  private liquidF!: { turb: SVGElement; disp: SVGElement; chrome: SVGElement; chromeG: SVGElement };
  private liquidOn = false;
  private levelHist: number[] = new Array(16).fill(0);
  private orbitG!: SVGGElement;
  private orbit: (number | null)[] = [];
  private beatAt = -1e9;
  private tempo = 120;
  private localReaction = -1;
  private nextLife = performance.now() + 45000;
  private offTier: () => void = () => {};
  /** A beat of the music: a small hop in time with it (the dance follows the measured tempo). */
  beat(bpm?: number) {
    this.beatAt = performance.now();
    if (bpm && bpm >= 60 && bpm <= 200) this.tempo = bpm;
    if (this.mood === "dancing") this.wobble(-0.9);
    this.kick();
  }
  /** Jobs running (downloads, missions, steps): each a small moon orbiting him, filled with its progress (null = unknown). */
  private orbitKey = "";
  setOrbit(items: (number | null)[]) {
    const list = items.slice(0, 4);
    const key = list.map((p) => (p == null ? "n" : Math.round(clamp(p, 0, 1) * 100))).join(",");
    if (key === this.orbitKey) return;                 // the notch calls this often: only real changes redraw
    this.orbitKey = key;
    this.orbit = list;
    this.renderOrbit();
    this.kick();
  }
  /** One of his own little reactions (not from the PC). */
  private feel(name: string) {
    if (tier() === "off") return;
    this.play({ name, id: this.localReaction-- });
  }

  constructor(opts: BlobOptions = {}) {
    const uid = `b${++uidSeq}`;
    this.el = document.createElement("div");
    this.el.className = "blob";
    this.el.setAttribute("role", "img");
    this.el.setAttribute("aria-label", "JARVIS");
    if (opts.size) this.el.style.setProperty("--blob-size", `${opts.size}px`);

    const svg = el("svg", { viewBox: "0 0 200 200", class: "blob-svg", "aria-hidden": "true" });
    const defs = el("defs");
    const grad = el("radialGradient", { id: `${uid}-g`, cx: "42%", cy: "18%", r: "85%" });
    const s1 = el("stop", { offset: "0%" });
    const s2 = el("stop", { offset: "50%" });
    const s3 = el("stop", { offset: "100%" });
    grad.append(s1, s2, s3);
    this.grads = { light: s1, mid: s2, dark: s3 };
    const blur = el("filter", { id: `${uid}-blur`, x: "-50%", y: "-50%", width: "200%", height: "200%" });
    blur.append(el("feGaussianBlur", { stdDeviation: 6 }));
    const soft = el("filter", { id: `${uid}-soft`, x: "-50%", y: "-50%", width: "200%", height: "200%" });
    soft.append(el("feGaussianBlur", { stdDeviation: 2.2 }));
    // rim light: bright along the top edge, fading out toward the base
    const rimGrad = el("linearGradient", { id: `${uid}-r`, x1: 0, y1: 0, x2: 0, y2: 1 });
    rimGrad.append(el("stop", { offset: "0%", class: "blob-rim-a" }), el("stop", { offset: "55%", class: "blob-rim-b" }),
      el("stop", { offset: "100%", class: "blob-rim-c" }));
    const clip = el("clipPath", { id: `${uid}-c` });
    clip.append(el("path", { d: BODY }));
    const floor = el("radialGradient", { id: `${uid}-f` });
    floor.append(el("stop", { offset: "0%", class: "blob-floor-a" }), el("stop", { offset: "55%", class: "blob-floor-b" }),
      el("stop", { offset: "100%", class: "blob-floor-c" }));
    // crescent eyes: each eye is masked by a black ellipse biting in from its inner side
    const masks = ([1, -1] as const).map((side, i) => {
      const m = el("mask", { id: `${uid}-m${i}`, maskUnits: "userSpaceOnUse", maskContentUnits: "userSpaceOnUse", x: -60, y: -60, width: 120, height: 120 });
      const cut = el("ellipse", { cx: 0, cy: 0, rx: 0, ry: 0, fill: "#000" });
      m.append(el("rect", { x: -60, y: -60, width: 120, height: 120, fill: "#fff" }), cut);
      return { m, cut, side };
    });
    this.cuts = masks;
    // 3.15 liquid metal: the outline ripples softly (turbulence → displacement) and a chrome reflection slides over him
    const liquid = el("filter", { id: `${uid}-liq`, x: "-20%", y: "-20%", width: "140%", height: "140%" });
    const turb = el("feTurbulence", { type: "fractalNoise", baseFrequency: "0.011", numOctaves: 2, seed: 3, result: "n" });
    const disp = el("feDisplacementMap", { in: "SourceGraphic", in2: "n", scale: 0, xChannelSelector: "R", yChannelSelector: "G" });
    liquid.append(turb, disp);
    const chromeGrad = el("linearGradient", { id: `${uid}-ch`, x1: 0, y1: 0, x2: 1, y2: 1, gradientUnits: "objectBoundingBox" });
    for (const [o, a] of [[0, 0], [0.32, 0], [0.4, 0.55], [0.47, 0.05], [0.58, 0.35], [0.66, 0], [1, 0]] as const) {
      chromeGrad.append(el("stop", { offset: o, "stop-color": "#ffffff", "stop-opacity": a }));
    }
    defs.append(liquid, chromeGrad);
    defs.append(grad, rimGrad, floor, clip, blur, soft, ...masks.map((x) => x.m));

    // floor: blue light spilling out from under the body + dark contact shadow
    this.shadow = el("ellipse", { cx: 100, cy: 175, rx: 130, ry: 4.5, fill: `url(#${uid}-f)`, class: "blob-shadow", filter: `url(#${uid}-soft)` });
    const contact = el("ellipse", { cx: 100, cy: 177, rx: 78, ry: 4, class: "blob-contact", filter: `url(#${uid}-soft)` });
    const halo = el("path", { d: BODY, class: "blob-halo", stroke: `url(#${uid}-r)`, filter: `url(#${uid}-blur)` });
    const bodyPath = el("path", { d: BODY, fill: `url(#${uid}-g)`, class: "blob-body" });
    // inner edge light (stroke clipped to the inside of the body) + soft sheen on the crown
    const rim = el("path", { d: BODY, class: "blob-rim", stroke: `url(#${uid}-r)`, "clip-path": `url(#${uid}-c)` });
    const rimSoft = el("path", { d: BODY, class: "blob-rim-soft", stroke: `url(#${uid}-r)`, "clip-path": `url(#${uid}-c)`, filter: `url(#${uid}-soft)` });
    const spec = el("ellipse", { cx: 90, cy: 66, rx: 52, ry: 16, transform: "rotate(-8 90 66)", class: "blob-spec", filter: `url(#${uid}-blur)`, "clip-path": `url(#${uid}-c)` });
    this.eyeL = el("path", { class: "blob-eye", mask: `url(#${uid}-m0)` });
    this.eyeR = el("path", { class: "blob-eye", mask: `url(#${uid}-m1)` });
    this.eyesG = el("g");
    // glow is filtered on a wrapper so it follows the masked (crescent) shape
    for (const eye of [this.eyeL, this.eyeR]) {
      const wrap = el("g", { class: "blob-eye-glow" });
      wrap.append(eye);
      this.eyesG.append(wrap);
    }
    this.svgBody = el("g", { class: "blob-body-g" });
    this.outfitG = el("g", { class: "blob-outfit" });
    const chrome = el("path", { d: BODY, fill: `url(#${uid}-ch)`, class: "blob-chrome", "clip-path": `url(#${uid}-c)` });
    const chromeG = el("g", { class: "blob-chrome-g" });
    chromeG.append(chrome);
    this.liquidG = el("g", { class: "blob-liquid" });
    this.liquidG.append(halo, bodyPath, chromeG, spec, rimSoft, rim);
    this.liquidF = { turb, disp, chrome, chromeG };
    this.svgBody.append(this.liquidG, this.eyesG, this.outfitG);
    this.orbitG = el("g", { class: "blob-orbit" });
    svg.append(defs, this.shadow, contact, this.svgBody, this.orbitG);
    this.liquidUid = uid;

    this.acc = document.createElement("div");
    this.acc.className = "blob-acc";
    this.fx = document.createElement("div");
    this.fx.className = "blob-acc blob-fx";
    this.el.append(svg, this.acc, this.fx);

    this.setColor(opts.color ?? "black", opts.glow);
    if (opts.trackCursor !== false) window.addEventListener("pointermove", this.onPointer, { passive: true });
    this.renderAccessories();
    // only animate while it can be seen: a hidden page, a closed panel or another tab costs nothing
    this.io = new IntersectionObserver((es) => { this.seen = es[es.length - 1].isIntersecting; if (this.seen) this.kick(); });
    this.io.observe(this.el);
    document.addEventListener("visibilitychange", this.onVis);
    this.raf = requestAnimationFrame(this.frame);
    this.setLiquid(at("high"));
    this.offTier = onTier(() => this.setLiquid(at("high")));
  }
  private io: IntersectionObserver;
  private liquidUid = "";
  /** 3.15 the liquid-metal look (high / ultra tier; the plain glossy blob otherwise). */
  setLiquid(on: boolean) {
    this.liquidOn = on;
    if (on) this.liquidG.setAttribute("filter", `url(#${this.liquidUid}-liq)`);
    else this.liquidG.removeAttribute("filter");
    this.liquidF.chromeG.style.display = on ? "" : "none";
    this.el.classList.toggle("liquid", on);
    this.kick();
  }
  private renderOrbit() {
    const g = this.orbitG;
    while (g.firstChild) g.firstChild.remove();
    this.orbit.forEach((p, i) => {
      const moon = el("g", { class: `blob-moon ${p == null ? "indet" : ""}`, "data-i": i });
      moon.append(el("circle", { r: 11, class: "moon-track" }),
        el("circle", { r: 11, class: "moon-arc", pathLength: 100, "stroke-dasharray": p == null ? "30 70" : `${Math.round(clamp(p, 0, 1) * 100)} 100`,
          transform: "rotate(-90)" }), el("circle", { r: 4.2, class: "moon-core" }));
      g.append(moon);
    });
  }
  private seen = true;
  private timer = 0;
  private onVis = () => { if (!document.hidden) this.kick(); };
  /** Draw the next frame now (a mood change, the cursor moved, it came into view) instead of after the calm pause. */
  private kick() {
    if (this.timer) { clearTimeout(this.timer); this.timer = 0; }
    if (!this.raf && this.seen && !document.hidden) this.raf = requestAnimationFrame(this.frame);
  }

  // ---------- public API ----------
  setMood(m: Mood, extra: MoodExtra = {}) {
    if (extra.badge !== undefined) this.badge = extra.badge;
    if (extra.progress !== undefined) this.progress = extra.progress;
    if (extra.secondary !== undefined) this.secondary = extra.secondary && extra.secondary in LOOKS ? extra.secondary : null;
    if (extra.ambient !== undefined) this.ambient = extra.ambient;
    if (extra.reaction && extra.reaction.id !== this.lastReaction) this.play(extra.reaction);
    if (m !== this.mood || extra.reaction) this.kick();
    if (m !== this.mood) {
      if (this.renderedFrames) this.wobble(m === "success" || m === "joy" ? -1.6 : 0.9);
      // 3.15 feelings of his own: he stretches after sleep, is proud after a long job, startled by a sudden notice
      const was = this.mood, long = performance.now() - this.moodStart;
      if (this.renderedFrames && !extra.reaction) {
        if (was === "sleeping" && m !== "closed") setTimeout(() => this.feel("stretch"), 0);
        else if (m === "success" && (was === "working" || was === "thinking") && long > 15000) setTimeout(() => this.feel("proud"), 0);
        else if (m === "notify" && CALM.has(was)) setTimeout(() => this.feel("surprised"), 0);
      }
      this.mood = m;
      this.look = LOOKS[m] ?? LOOKS.idle;
      this.moodStart = performance.now();
      this.el.dataset.mood = m;
      this.renderAccessories();
    } else {
      this.updateDynamic();
    }
    this.renderFx();
  }

  /** Play a one-off reaction over the current mood (OMEGA 72 / 73 / 74 / 81 / 738 / 746 / 747 / 749 / 750). */
  play(r: Reaction) {
    this.kick();
    this.lastReaction = r.id;
    const phases = reactionPhases(r);
    if (!phases.length) return;
    this.reaction = { phases, start: performance.now(), idx: 0 };
    this.el.dataset.reaction = r.name;
    this.renderAccessories();
    this.renderFx();
  }

  /** How lively he is (OMEGA 242) and whether he wears weather / time-of-day props (739 / 740 / 741). */
  setCharacter(o: { personality?: string; ambient?: boolean }) {
    if (o.personality !== undefined) this.energy = PERSONALITY_ENERGY[o.personality] ?? 1;
    if (o.ambient !== undefined) this.ambientOn = o.ambient;
    this.renderFx();
  }

  /** The look in effect right now: the mood, or the running reaction's phase over it. */
  private current(now: number): Look & { spin?: boolean } {
    const r = this.reaction;
    if (!r) return this.look;
    const since = (now - r.start) / 1000;
    let idx = r.phases.findIndex((p) => since < p.until);
    if (idx < 0) {
      this.reaction = null;
      delete this.el.dataset.reaction;
      this.renderAccessories();
      this.renderFx();
      return this.look;
    }
    if (idx !== r.idx) {
      r.idx = idx;
      this.renderAccessories();
      this.renderFx();
    }
    return this.phaseLook();
  }

  private phaseLook(): Look & { spin?: boolean } {
    const ph = this.reaction?.phases[this.reaction.idx]?.look;
    return ph ? { ...this.look, ...ph, accessories: ph.accessories ?? this.look.accessories } : this.look;
  }

  /** The reaction's own prop, or the ambient props while he is calm. */
  private renderFx() {
    let html = "", cls = "";
    if (this.reaction) {
      html = this.reaction.phases[this.reaction.idx]?.extra ?? "";
      cls = `fx-${this.el.dataset.reaction}`;
    } else if (this.ambientOn && CALM.has(this.mood)) {
      html = ambientExtra(this.ambient);
      cls = "fx-ambient";
    }
    const key = cls + html;
    if (key === this.fxHtml) return;
    this.fxHtml = key;
    this.fx.className = `blob-acc blob-fx ${cls}`;
    this.fx.innerHTML = html ? `<div class="acc fx">${html}</div>` : "";
  }

  setLevel(rms: number) {
    this.level = Math.max(this.level, clamp(rms * 4, 0, 1));
  }

  /** Dress him up: an outfit name or "auto" (the season decides). */
  setOutfit(o: string | undefined) {
    const name = resolveOutfit(o);
    if (name === this.outfit) return;
    this.outfit = name;
    this.outfitG.innerHTML = name === "none" ? "" : OUTFIT_SVG[name];
    this.el.dataset.outfit = name;
  }

  private pokes: number[] = [];
  /** A poke (click): the 3rd quick one annoys him, the 6th makes his head spin. Returns the reaction, if any. */
  poke(): "annoyed" | "dizzy" | null {
    const now = performance.now();
    this.pokes = this.pokes.filter((t) => now - t < 4000);
    this.pokes.push(now);
    this.wobble(2.4);
    if (this.pokes.length >= 6) { this.pokes = []; return "dizzy"; }
    if (this.pokes.length >= 3) return "annoyed";
    return null;
  }

  /** Rest the eyes towards a direction (-1..1) without counting as pointer movement, so the frame cap stays low. */
  face(x: number, y = 0) {
    this.facing = { x: clamp(x, -1, 1), y: clamp(y, -1, 1) };
  }
  private facing = { x: 0, y: 0 };

  /** Point the eyes at a position in this window's client coordinates. */
  lookAt(x: number, y: number) {
    this.cursor = { x, y, t: performance.now() };
  }

  setColor(c: CharacterColor, glow?: string) {
    const col = BODY_COLORS[c] ?? BODY_COLORS.black;
    this.grads.light.setAttribute("stop-color", col.light);
    this.grads.mid.setAttribute("stop-color", col.mid);
    this.grads.dark.setAttribute("stop-color", col.dark);
    this.el.style.setProperty("--blob-eye", col.eye);
    this.el.style.setProperty("--blob-rim", col.rim);
    this.el.dataset.color = c;
    this.glowColor = glow || "";
    this.el.style.setProperty("--blob-glow", glow || DEFAULT_GLOW);
  }

  private onPointer = (e: PointerEvent) => { this.lookAt(e.clientX, e.clientY); if (this.timer) this.kick(); };
  /** Frames actually drawn (for the performance check in the dev gallery). */
  renderedFrames = 0;
  private lastRender = 0;

  /** Idle animation is cheap (spec §8): ≤20 fps when calm and the cursor is still, ≤10 fps with reduced motion. */
  private fpsCap(now: number): number {
    if (reducedMotion()) return 10;
    const calm = this.mood === "idle" || this.mood === "closed" || this.mood === "sleeping" || this.mood === "focus";
    const pointerStill = !this.cursor || now - this.cursor.t > 3000;
    return calm && pointerStill && !this.reaction && !this.jelly.v ? 20 : 0;
  }

  destroy() {
    this.offTier();
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    clearTimeout(this.timer);
    this.timer = 0;
    this.io.disconnect();
    document.removeEventListener("visibilitychange", this.onVis);
    window.removeEventListener("pointermove", this.onPointer);
    this.el.remove();
  }

  // ---------- accessories ----------
  private renderAccessories() {
    const a = this.acc;
    a.replaceChildren();
    this.bars = [];
    this.progressEl = null;
    this.badgeEl = null;
    const add = (cls: string, html = "") => {
      const d = document.createElement("div");
      d.className = `acc acc-${cls}`;
      d.innerHTML = html;
      a.append(d);
      return d;
    };
    const icon = (name: string, weight = "fill") => `<i class="ph${weight === "fill" ? "-fill" : weight === "bold" ? "-bold" : ""} ph-${name}"></i>`;
    const look = this.phaseLook();
    for (const acc of look.accessories as Accessory[]) {
      switch (acc) {
        case "waves":
          for (const side of ["l", "r"]) {
            const g = add(`waves ${side}`);
            for (let i = 0; i < 5; i++) {
              const b = document.createElement("i");
              g.append(b);
              this.bars.push(b);
            }
          }
          break;
        case "voice": {
          const g = add("voice");
          for (let i = 0; i < 9; i++) {
            const b = document.createElement("i");
            g.append(b);
            this.bars.push(b);
          }
          break;
        }
        case "dots": add("dots", "<i></i><i></i><i></i>"); break;
        case "wait": add("dots wait", "<i></i><i></i><i></i>"); break;
        case "notes": add("notes", `<span>${icon("music-note")}</span><span>${icon("music-notes")}</span><span>${icon("music-note")}</span><span>${icon("music-note-simple")}</span>`); break;
        case "laptop": add("laptop", icon("laptop")); break;
        case "check": add("check", icon("check-circle", "bold")); break;
        case "warn": add("warn", icon("warning-circle", "bold")); break;
        case "limit": add("limit", icon("warning", "bold")); break;
        case "cloud": add("cloud", icon("cloud-slash", "bold")); break;
        case "spinner": this.progressEl = add("spinner", '<svg viewBox="0 0 40 40"><circle class="track" cx="20" cy="20" r="15"/><circle class="arc" cx="20" cy="20" r="15" pathLength="100"/></svg>'); break;
        case "zzz": add("zzz", "<span>z</span><span>z</span><span>Z</span>"); break;
        case "bell": this.badgeEl = add("bell", `${icon("bell")}<em></em>`); break;
        case "cursor": add("cursor", icon("cursor")); break;
        case "dragbox": add("dragbox", `<b></b><span>${icon("cursor")}<u>${icon("plus-circle")}</u></span>`); break;
        case "minus": add("minus", icon("minus-circle", "bold")); break;
        case "stars": add("stars", `<span>${icon("star-four")}</span><span>${icon("star-four")}</span><span>${icon("star-four")}</span><span>${icon("star-four")}</span>`); break;
        case "heart": add("heart", icon("heart")); break;
        case "spiral": {
          const sp = '<svg viewBox="-10 -10 20 20"><path d="M0 0 m0 -1.5 a1.5 1.5 0 1 1 -1.5 1.5 a3 3 0 1 1 3 3 a4.5 4.5 0 1 1 -4.5 -4.5 a6 6 0 1 1 6 6" /></svg>';
          add("spiral", `<span>${sp}</span><span>${sp}</span>`);
          break;
        }
        case "anger": add("anger", icon("lightning", "fill")); break;
      }
    }
    this.updateDynamic();
  }

  private updateDynamic() {
    if (this.progressEl) {
      // ring: spins while the size is unknown, otherwise fills up with the progress
      const arc = this.progressEl.querySelector(".arc") as SVGCircleElement;
      const p = this.progress;
      this.progressEl.classList.toggle("indet", p == null);
      arc.style.strokeDasharray = p == null ? "" : `${Math.round(clamp(p, 0, 1) * 100)} 100`;
    }
    if (this.badgeEl) {
      const em = this.badgeEl.querySelector("em") as HTMLElement;
      em.textContent = this.badge > 9 ? "9+" : this.badge > 1 ? String(this.badge) : "";
    }
  }

  // ---------- animation ----------
  private frame = (now: number) => {
    this.raf = 0;
    // out of sight (another page, a closed panel, a hidden window, thrown away by a re-render): sleep until it shows
    if (!this.el.isConnected || !this.seen || document.hidden) return;
    const cap = this.fpsCap(now);
    if (cap) {
      const wait = 1000 / cap - (now - this.lastRender);
      if (wait > 2) { this.timer = window.setTimeout(() => { this.timer = 0; this.raf = requestAnimationFrame(this.frame); }, wait); return; }
      this.timer = window.setTimeout(() => { this.timer = 0; this.raf = requestAnimationFrame(this.frame); }, 1000 / cap);
    } else this.raf = requestAnimationFrame(this.frame);
    this.lastRender = now;
    this.renderedFrames++;
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    const k = 1 - Math.exp(-dt * 12);
    const look = this.current(now);
    const reduce = reducedMotion();
    const t = now / 1000;

    // eyes: morph toward the mood's shape, blink, gaze
    // OMEGA 736: a second feeling tints the eyes a little (unless a reaction is playing)
    const target = EYES[look.eyes];
    const sec = !this.reaction && this.secondary && this.secondary !== this.mood ? EYES[LOOKS[this.secondary].eyes] : null;
    for (const key of ["w", "h", "top", "bottom", "tilt", "cut"] as const) {
      this.eye[key] = lerp(this.eye[key], sec ? lerp(target[key], sec[key], 0.3) : target[key], k);
    }
    if (look.blink && now > this.nextBlink && !reduce) {
      this.blinkUntil = now + 130;
      this.nextBlink = now + 2800 + Math.random() * 4500 + (Math.random() < 0.15 ? -2600 : 0); // sometimes double-blink
    }
    const blink = now < this.blinkUntil ? 0.12 : 1;

    let gx = look.gaze[0], gy = look.gaze[1];
    const cur = this.cursor;
    if (cur && now - cur.t < 4000 && look.gaze[0] === 0 && look.gaze[1] === 0) {
      const r = this.el.getBoundingClientRect();
      gx = clamp((cur.x - (r.left + r.width / 2)) / 260, -1, 1);
      gy = clamp((cur.y - (r.top + r.height * 0.55)) / 220, -1, 1);
    } else if (look.blink && !reduce) {
      if (now > this.glance.next) {
        this.glance = { x: (Math.random() * 2 - 1) * 0.8, y: (Math.random() - 0.6) * 0.5, until: now + 1300, next: now + 4000 + Math.random() * 6000 };
      }
      if (now < this.glance.until) { gx = this.glance.x; gy = this.glance.y; }
      else if (look.gaze[0] === 0 && look.gaze[1] === 0) { gx = this.facing.x; gy = this.facing.y; }
    }
    this.gaze.x = lerp(this.gaze.x, gx, k * 0.8);
    this.gaze.y = lerp(this.gaze.y, gy, k * 0.8);

    const e = { ...this.eye, h: this.eye.h * blink };
    const d = eyePath(e);
    this.eyeL.setAttribute("d", d);
    this.eyeR.setAttribute("d", (look as { wink?: boolean }).wink ? eyePath({ ...e, h: e.h * 0.08 }) : d);
    const ex = this.gaze.x * 9, ey = this.gaze.y * 7;
    this.eyeL.setAttribute("transform", `translate(${100 - EYE_X + ex} ${EYE_Y + ey}) rotate(${this.eye.tilt})`);
    this.eyeR.setAttribute("transform", `translate(${100 + EYE_X + ex} ${EYE_Y + ey}) rotate(${-this.eye.tilt})`);
    const c = Math.max(0, this.eye.cut);  // the lerp can overshoot below 0 after a long frame
    for (const { cut, side } of this.cuts) {
      cut.setAttribute("cx", (side * e.w * 0.9).toFixed(2));
      cut.setAttribute("cy", (-e.h * 0.04).toFixed(2));
      cut.setAttribute("rx", (e.w * 1.2 * c).toFixed(2));
      cut.setAttribute("ry", (e.h * 0.72 * c).toFixed(2));
    }

    // body motion
    this.level *= Math.exp(-dt * 6);
    const since = (now - (this.reaction ? this.reaction.start : this.moodStart)) / 1000;
    const en = this.energy;
    let y = 0, sx = 1, sy = 1, rot = look.tilt, spin = 0;
    if (!reduce) {
      y += Math.sin(t * Math.PI * 2 * look.bobSpeed) * look.bob * Math.min(1.3, en);
      const breath = 1 + Math.sin(t * Math.PI * 2 * look.bobSpeed) * 0.012;
      sx *= breath;
      sy /= breath;
      if (look.audio) { sy *= 1 + this.level * 0.12; sx *= 1 - this.level * 0.04; }
      if (look.dance) {
        const beat = t * (this.tempo / 60); // 3.15 the measured tempo of the music (120 BPM until known)
        const ph = beat % 1;
        y -= Math.abs(Math.sin(beat * Math.PI)) * 9 * Math.max(0.5, en);
        sy *= ph < 0.15 ? 0.9 : 1;
        sx *= ph < 0.15 ? 1.08 : 1;
        rot += Math.sin(beat * Math.PI) * 8;
      }
      if (look.hop) {
        const ph = (since % 1.3) / 1.3;
        if (ph < 0.4) y -= Math.sin((ph / 0.4) * Math.PI) * 16 * Math.max(0.5, en);
        const cycle = Math.floor(since / 1.3);
        if (ph >= 0.4 && cycle !== this.lastLand) { this.lastLand = cycle; this.wobble(1.8 * Math.max(0.5, en)); }
      }
      if (look.shake && since < 0.6) rot += Math.sin(since * 40) * 7 * (1 - since / 0.6);
      if (now - this.beatAt < 180 && this.mood === "dancing") y -= (1 - (now - this.beatAt) / 180) * 5;
      if (look.wobble) { rot += Math.sin(t * 5) * 9; y += Math.sin(t * 10) * 1.5; }
      if (look.spin) spin = clamp(since / 1.2, 0, 1) * 360;
      // soft body: under-damped spring, so a landing squashes, overshoots and settles in a few wobbles
      const j = this.jelly;
      j.v += (-170 * j.x - 7.5 * j.v) * dt;
      j.x = clamp(j.x + j.v * dt, -0.18, 0.22);
      if (Math.abs(j.x) < 0.0005 && Math.abs(j.v) < 0.005) j.x = j.v = 0;
      sx *= 1 + j.x * 0.6;
      sy /= 1 + j.x;
    } else {
      this.jelly.x = this.jelly.v = 0;
    }
    const sq = look.squash;
    sx *= Math.sqrt(sq);
    sy /= Math.sqrt(sq);
    this.body.bob = lerp(this.body.bob, y, 0.5);
    this.body.squash = lerp(this.body.squash, sx / sy, k);
    this.body.tilt = lerp(this.body.tilt, rot, look.dance || look.shake ? 0.6 : k);
    // OMEGA 740: softer glow at night while he is calm
    const night = this.ambientOn && this.ambient?.part === "night" && CALM.has(this.mood) && !this.reaction ? 0.75 : 1;
    this.body.glow = lerp(this.body.glow, look.glow * night + (look.audio ? this.level * 0.3 : 0), k);
    this.body.dim = lerp(this.body.dim, look.dim ?? 0, k);
    this.svgBody.setAttribute("transform",
      `${spin ? `rotate(${spin.toFixed(1)} 100 112) ` : ""}translate(0 ${this.body.bob.toFixed(2)}) rotate(${this.body.tilt.toFixed(2)} 100 175) translate(100 175) scale(${sx.toFixed(3)} ${sy.toFixed(3)}) translate(-100 -175)`);
    this.shadow.setAttribute("rx", String(130 * (1 + Math.min(0, this.body.bob) / 60)));
    this.eyesG.style.opacity = look.noEyes ? "0" : "1";
    this.el.style.setProperty("--blob-glow-a", this.body.glow.toFixed(3));
    this.el.style.setProperty("--blob-dim", this.body.dim.toFixed(3));
    if (look.glowColor) this.el.style.setProperty("--blob-glow", look.glowColor);
    else this.el.style.setProperty("--blob-glow", this.glowColor || DEFAULT_GLOW);

    // audio bars – 3.15: the real voice: the middle bar is now, the outer ones a moment ago (the level history)
    this.levelHist.unshift(this.level);
    this.levelHist.length = 16;
    if (this.bars.length) {
      const n = this.bars.length;
      const live = this.mood === "listening" || this.mood === "speaking";
      this.bars.forEach((b, i) => {
        const fromMid = Math.round(Math.abs(i - (n - 1) / 2));
        const hist = this.levelHist[Math.min(15, fromMid * 2)] || 0;
        const wob = 0.35 + 0.65 * Math.abs(Math.sin(t * 7 + i * 1.3));
        const amp = live ? Math.max(0.12, hist) : 0.1;
        const center = n > 9 ? 1 : 1 - Math.abs(i - (n - 1) / 2) / n;
        const v = live && hist > 0.05 ? 0.2 + hist * 1.5 * (0.6 + center) : 0.2 + wob * amp * 1.6 * (0.5 + center);
        b.style.transform = `scaleY(${v.toFixed(3)})`;
      });
    }
    // 3.15 liquid metal: the outline breathes with the voice and the bounce, the reflection follows the gaze
    if (this.liquidOn && !reduce) {
      const lf = this.liquidF;
      lf.turb.setAttribute("baseFrequency", (0.011 + 0.003 * Math.sin(t * 0.7)).toFixed(4));
      lf.disp.setAttribute("scale", (2.2 + this.level * 7 + Math.abs(this.jelly.x) * 40).toFixed(2));
      lf.chromeG.setAttribute("transform", `translate(${(this.gaze.x * -14 + Math.sin(t * 0.4) * 6).toFixed(1)} ${(this.gaze.y * -8).toFixed(1)})`);
    }
    // 3.15 the jobs orbiting him on a tilted ring (behind him on the far side, in front on the near side)
    if (this.orbit.length) {
      const moons = this.orbitG.children;
      for (let i = 0; i < moons.length; i++) {
        const a = t * 0.9 + (i * Math.PI * 2) / moons.length;
        const x = 100 + Math.cos(a) * 96, y2 = 118 + Math.sin(a) * 30 + this.body.bob;
        const m = moons[i] as SVGGElement;
        m.setAttribute("transform", `translate(${x.toFixed(1)} ${y2.toFixed(1)}) scale(${(0.8 + 0.2 * Math.sin(a)).toFixed(2)})`);
        m.style.opacity = Math.sin(a) < -0.2 ? "0.35" : "1";
      }
    }
    // 3.15 a life of his own while calm: a yawn late at night, now and then a wink at you
    if (!reduce && !this.reaction && CALM.has(this.mood) && now > this.nextLife) {
      const hr = new Date().getHours();
      const night = hr >= 23 || hr < 5 || this.ambient?.part === "night";
      this.nextLife = now + (60000 + Math.random() * 90000) / Math.max(0.4, this.energy);
      if (night) this.feel("yawn");
      else if (Math.random() < 0.35 * this.energy) this.feel("wink");
    }
  };
}
