import "./blob.css";
import { BODY_COLORS, EYES, LOOKS, type Accessory, type CharacterColor, type Eye, type Look, type Mood } from "./looks";

export type { Mood, CharacterColor } from "./looks";
export { MOODS, MOOD_LABEL } from "./looks";

const SVG = "http://www.w3.org/2000/svg";
const BODY = "M 10 150 C 10 84 50 40 100 40 C 150 40 190 84 190 150 C 190 168 170 175 100 175 C 30 175 10 168 10 150 Z";
const EYE_X = 27;
const EYE_Y = 116;
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
  glow?: string;          // css colour; default = accent
  trackCursor?: boolean;  // eyes follow the mouse inside this window
}

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

  constructor(opts: BlobOptions = {}) {
    const uid = `b${++uidSeq}`;
    this.el = document.createElement("div");
    this.el.className = "blob";
    this.el.setAttribute("role", "img");
    this.el.setAttribute("aria-label", "JARVIS");
    if (opts.size) this.el.style.setProperty("--blob-size", `${opts.size}px`);

    const svg = el("svg", { viewBox: "0 0 200 200", class: "blob-svg", "aria-hidden": "true" });
    const defs = el("defs");
    const grad = el("radialGradient", { id: `${uid}-g`, cx: "36%", cy: "26%", r: "80%" });
    const s1 = el("stop", { offset: "0%" });
    const s2 = el("stop", { offset: "45%" });
    const s3 = el("stop", { offset: "100%" });
    grad.append(s1, s2, s3);
    this.grads = { light: s1, mid: s2, dark: s3 };
    const blur = el("filter", { id: `${uid}-blur`, x: "-50%", y: "-50%", width: "200%", height: "200%" });
    blur.append(el("feGaussianBlur", { stdDeviation: 6 }));
    const soft = el("filter", { id: `${uid}-soft`, x: "-50%", y: "-50%", width: "200%", height: "200%" });
    soft.append(el("feGaussianBlur", { stdDeviation: 2.2 }));
    defs.append(grad, blur, soft);

    this.shadow = el("ellipse", { cx: 100, cy: 180, rx: 80, ry: 9, class: "blob-shadow", filter: `url(#${uid}-blur)` });
    const halo = el("path", { d: BODY, class: "blob-halo", filter: `url(#${uid}-blur)` });
    const rim = el("path", { d: BODY, class: "blob-rim" });
    const bodyPath = el("path", { d: BODY, fill: `url(#${uid}-g)`, class: "blob-body" });
    const spec = el("ellipse", { cx: 62, cy: 72, rx: 30, ry: 13, transform: "rotate(-24 62 72)", class: "blob-spec", filter: `url(#${uid}-soft)` });
    const spec2 = el("ellipse", { cx: 54, cy: 68, rx: 8, ry: 4, transform: "rotate(-24 54 68)", class: "blob-spec2" });
    this.eyeL = el("path", { class: "blob-eye" });
    this.eyeR = el("path", { class: "blob-eye" });
    this.eyesG = el("g");
    this.eyesG.append(this.eyeL, this.eyeR);
    this.svgBody = el("g", { class: "blob-body-g" });
    this.svgBody.append(halo, rim, bodyPath, spec, spec2, this.eyesG);
    svg.append(defs, this.shadow, this.svgBody);

    this.acc = document.createElement("div");
    this.acc.className = "blob-acc";
    this.el.append(svg, this.acc);

    this.setColor(opts.color ?? "black", opts.glow);
    if (opts.trackCursor !== false) window.addEventListener("pointermove", this.onPointer, { passive: true });
    this.renderAccessories();
    this.raf = requestAnimationFrame(this.frame);
  }

  // ---------- public API ----------
  setMood(m: Mood, extra: { badge?: number; progress?: number | null } = {}) {
    if (extra.badge !== undefined) this.badge = extra.badge;
    if (extra.progress !== undefined) this.progress = extra.progress;
    if (m !== this.mood) {
      this.mood = m;
      this.look = LOOKS[m] ?? LOOKS.idle;
      this.moodStart = performance.now();
      this.el.dataset.mood = m;
      this.renderAccessories();
    } else {
      this.updateDynamic();
    }
  }

  setLevel(rms: number) {
    this.level = Math.max(this.level, clamp(rms * 4, 0, 1));
  }

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
    this.el.style.setProperty("--blob-glow", glow || "var(--accent, #2ee6ff)");
  }

  private onPointer = (e: PointerEvent) => this.lookAt(e.clientX, e.clientY);
  private detachedSince = 0;

  destroy() {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
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
    for (const acc of this.look.accessories as Accessory[]) {
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
        case "notes": add("notes", `<span>${icon("music-note")}</span><span>${icon("music-notes")}</span><span>${icon("music-note")}</span><span>${icon("music-notes-simple")}</span>`); break;
        case "laptop": add("laptop", icon("laptop")); break;
        case "progress": this.progressEl = add("progress", "<b></b>"); break;
        case "sparkles": add("sparkles", `<span>${icon("sparkle")}</span><span>${icon("star-four")}</span><span>${icon("sparkle")}</span><span>${icon("star-four")}</span>`); break;
        case "alert": add("alert", "!"); break;
        case "zzz": add("zzz", "<span>z</span><span>z</span><span>Z</span>"); break;
        case "limit": add("limit", icon("warning")); break;
        case "wifi": add("wifi", icon("wifi-high", "bold")); break;
        case "download": add("download", icon("download-simple", "bold")); break;
        case "bell": this.badgeEl = add("bell", `${icon("bell")}<em></em>`); break;
        case "cursor": add("cursor", icon("cursor")); break;
        case "headphones": add("headphones", "<i></i><i></i>"); break;
        case "clock": add("clock", icon("clock", "bold")); break;
        case "hearts": add("hearts", `<span>${icon("heart")}</span><span>${icon("heart")}</span><span>${icon("heart")}</span>`); break;
        case "ripple": add("ripple", "<i></i><i></i>"); break;
      }
    }
    this.updateDynamic();
  }

  private updateDynamic() {
    if (this.progressEl) {
      const b = this.progressEl.querySelector("b") as HTMLElement;
      const p = this.progress;
      this.progressEl.classList.toggle("indet", p == null);
      b.style.width = p == null ? "35%" : `${Math.round(clamp(p, 0, 1) * 100)}%`;
    }
    if (this.badgeEl) {
      const em = this.badgeEl.querySelector("em") as HTMLElement;
      em.textContent = this.badge > 9 ? "9+" : String(this.badge || "");
      em.hidden = !this.badge;
    }
  }

  // ---------- animation ----------
  private frame = (now: number) => {
    if (!this.el.isConnected) {
      // thrown away by a re-render → stop for good after a moment (lets it be garbage-collected)
      this.detachedSince ||= now;
      if (now - this.detachedSince > 3000) { this.destroy(); return; }
      this.raf = requestAnimationFrame(this.frame);
      return;
    }
    this.detachedSince = 0;
    this.raf = requestAnimationFrame(this.frame);
    if (document.hidden) return;
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    const k = 1 - Math.exp(-dt * 12);
    const look = this.look;
    const reduce = reducedMotion();
    const t = now / 1000;

    // eyes: morph toward the mood's shape, blink, gaze
    const target = EYES[look.eyes];
    for (const key of ["w", "h", "top", "bottom", "tilt"] as const) this.eye[key] = lerp(this.eye[key], target[key], k);
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
    }
    this.gaze.x = lerp(this.gaze.x, gx, k * 0.8);
    this.gaze.y = lerp(this.gaze.y, gy, k * 0.8);

    const e = { ...this.eye, h: this.eye.h * blink };
    const d = eyePath(e);
    this.eyeL.setAttribute("d", d);
    this.eyeR.setAttribute("d", d);
    const ex = this.gaze.x * 9, ey = this.gaze.y * 7;
    this.eyeL.setAttribute("transform", `translate(${100 - EYE_X + ex} ${EYE_Y + ey}) rotate(${this.eye.tilt})`);
    this.eyeR.setAttribute("transform", `translate(${100 + EYE_X + ex} ${EYE_Y + ey}) rotate(${-this.eye.tilt})`);

    // body motion
    this.level *= Math.exp(-dt * 6);
    const since = (now - this.moodStart) / 1000;
    let y = 0, sx = 1, sy = 1, rot = look.tilt;
    if (!reduce) {
      y += Math.sin(t * Math.PI * 2 * look.bobSpeed) * look.bob;
      const breath = 1 + Math.sin(t * Math.PI * 2 * look.bobSpeed) * 0.012;
      sx *= breath;
      sy /= breath;
      if (look.audio) { sy *= 1 + this.level * 0.12; sx *= 1 - this.level * 0.04; }
      if (look.dance) {
        const beat = t * 2; // 120 BPM
        const ph = beat % 1;
        y -= Math.abs(Math.sin(beat * Math.PI)) * 9;
        sy *= ph < 0.15 ? 0.9 : 1;
        sx *= ph < 0.15 ? 1.08 : 1;
        rot += Math.sin(beat * Math.PI) * 8;
      }
      if (look.hop) {
        const ph = (since % 1.3) / 1.3;
        if (ph < 0.4) y -= Math.sin((ph / 0.4) * Math.PI) * 16;
        if (ph > 0.38 && ph < 0.48) { sy *= 0.9; sx *= 1.08; }
      }
      if (look.shake && since < 0.6) rot += Math.sin(since * 40) * 7 * (1 - since / 0.6);
    }
    const sq = look.squash;
    sx *= Math.sqrt(sq);
    sy /= Math.sqrt(sq);
    this.body.bob = lerp(this.body.bob, y, 0.5);
    this.body.squash = lerp(this.body.squash, sx / sy, k);
    this.body.tilt = lerp(this.body.tilt, rot, look.dance || look.shake ? 0.6 : k);
    this.body.glow = lerp(this.body.glow, look.glow + (look.audio ? this.level * 0.3 : 0), k);
    this.body.dim = lerp(this.body.dim, look.dim ?? 0, k);
    this.svgBody.setAttribute("transform",
      `translate(0 ${this.body.bob.toFixed(2)}) rotate(${this.body.tilt.toFixed(2)} 100 172) translate(100 172) scale(${sx.toFixed(3)} ${sy.toFixed(3)}) translate(-100 -172)`);
    this.shadow.setAttribute("rx", String(80 * (1 + Math.min(0, this.body.bob) / 60)));
    this.el.style.setProperty("--blob-glow-a", this.body.glow.toFixed(3));
    this.el.style.setProperty("--blob-dim", this.body.dim.toFixed(3));
    if (look.glowColor) this.el.style.setProperty("--blob-glow", look.glowColor);
    else this.el.style.setProperty("--blob-glow", this.glowColor || "var(--accent, #2ee6ff)");

    // audio bars
    if (this.bars.length) {
      const n = this.bars.length;
      this.bars.forEach((b, i) => {
        const wob = 0.35 + 0.65 * Math.abs(Math.sin(t * 7 + i * 1.3));
        const amp = this.mood === "listening" || this.mood === "speaking" ? Math.max(0.15, this.level) : 0.1;
        const center = n > 9 ? 1 : 1 - Math.abs(i - (n - 1) / 2) / n;
        b.style.transform = `scaleY(${(0.2 + wob * amp * 1.6 * (0.5 + center)).toFixed(3)})`;
      });
    }
  };
}
