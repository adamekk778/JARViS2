// The band on top of each page of the JARVIS window: deep black with the page's colour breathing in a corner,
// particles drifting all the time and moving away from the pointer, and a few little JARVISes walking along its
// floor (they stop, look around, hop, and jump when clicked). Inspired by the Coucou window (MIT).
//
// One loop drives every band; it stops when no band is on screen or the window is hidden, so a hidden window
// costs nothing.
import { h } from "./dom";
import { Blob, type CharacterColor } from "../character/blob";

export interface CastMember { color: CharacterColor; size: number; start: number; glow?: string; sleeps?: boolean }
export interface HeroSpec { color: string; cast: CastMember[] }

interface Walker { blob: Blob; wrap: HTMLElement; start: number; placed: boolean; x: number; dir: 1 | -1; speed: number; pause: number; hop: number; size: number; still: boolean }
interface Band {
  root: HTMLElement; canvas: HTMLCanvasElement; color: [number, number, number];
  dots: { x: number; y: number; vx: number; vy: number; r: number; a: number; white: boolean }[];
  walkers: Walker[]; pointer: { x: number; y: number } | null; w: number; h: number; copy: HTMLElement; minX: number; measured: number;
}

const bands = new Set<Band>();
let raf = 0;
let last = 0;
let lastDraw = 0;
const reduced = () => document.documentElement.dataset.motion === "reduced" || matchMedia("(prefers-reduced-motion: reduce)").matches;

function rgb(hex: string): [number, number, number] {
  const n = parseInt(hex.replace("#", ""), 16);
  return [n >> 16, (n >> 8) & 255, n & 255];
}
const rgba = (c: [number, number, number], a: number) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

function visible(b: Band) {
  if (!b.root.isConnected) return false;
  const r = b.root.getBoundingClientRect();
  return r.bottom > 0 && r.top < innerHeight && r.width > 0;
}

function loop(now: number) {
  raf = 0;
  const live = [...bands].filter(visible);
  if (!live.length || document.hidden) return;
  raf = requestAnimationFrame(loop);
  // ~30 fps is plenty for drifting particles; 12 fps with reduced motion or while you work in another window
  if (now - lastDraw < (reduced() || !document.hasFocus() ? 80 : 32)) return;
  const dt = Math.min(0.06, (now - last) / 1000);
  last = lastDraw = now;
  for (const b of live) draw(b, dt, now / 1000);
}

export function wakeBands() {
  if (!raf && !document.hidden) { last = performance.now(); raf = requestAnimationFrame(loop); }
}
document.addEventListener("visibilitychange", wakeBands);

function fit(b: Band) {
  const dpr = Math.min(2, devicePixelRatio || 1);
  const w = b.canvas.clientWidth, hh = b.canvas.clientHeight;
  if (w !== b.w || hh !== b.h) {
    b.w = w; b.h = hh;
    b.canvas.width = Math.round(w * dpr);
    b.canvas.height = Math.round(hh * dpr);
    const n = Math.round((w * hh) / 2600);
    b.dots = Array.from({ length: n }, () => ({
      x: Math.random() * w, y: Math.random() * hh, vx: (Math.random() - 0.5) * 6, vy: -2 - Math.random() * 5,
      r: 0.5 + Math.random() * 1.3, a: 0.25 + Math.random() * 0.6, white: Math.random() < 0.45,
    }));
  }
  return dpr;
}

function draw(b: Band, dt: number, t: number) {
  const dpr = fit(b);
  const ctx = b.canvas.getContext("2d");
  if (!ctx || !b.w) return;
  const { w, h: hh, color } = b;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, hh);
  const lin = ctx.createLinearGradient(0, 0, w, hh);
  lin.addColorStop(0, "rgba(0,0,0,0)");
  lin.addColorStop(1, rgba(color, 0.1));
  ctx.fillStyle = lin;
  ctx.fillRect(0, 0, w, hh);
  const breath = 0.75 + 0.25 * Math.sin(t * 0.6);
  const rad = ctx.createRadialGradient(w * 0.86, -hh * 0.1, 0, w * 0.86, -hh * 0.1, w * 0.62);
  rad.addColorStop(0, rgba(color, 0.32 * breath));
  rad.addColorStop(0.5, rgba(color, 0.08));
  rad.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = rad;
  ctx.fillRect(0, 0, w, hh);
  for (const d of b.dots) {
    d.x += d.vx * dt; d.y += d.vy * dt;
    if (b.pointer) {
      const dx = d.x - b.pointer.x, dy = d.y - b.pointer.y, q = dx * dx + dy * dy;
      if (q < 3600 && q > 0.01) { const f = (60 - Math.sqrt(q)) * 2.2 * dt; d.x += (dx / Math.sqrt(q)) * f; d.y += (dy / Math.sqrt(q)) * f; }
    }
    if (d.y < -4) { d.y = hh + 4; d.x = Math.random() * w; }
    if (d.x < -4) d.x = w + 4; else if (d.x > w + 4) d.x = -4;
    const tw = 0.6 + 0.4 * Math.sin(t * 1.7 + d.x);
    ctx.fillStyle = d.white ? `rgba(255,255,255,${d.a * tw * 0.7})` : rgba(color, d.a * tw);
    ctx.beginPath(); ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2); ctx.fill();
  }
  walk(b, dt);
}

/** Walkers keep to the right of the title, text and buttons. */
function floorStart(b: Band): number {
  let right = 0;
  for (const el of b.copy.children) right = Math.max(right, (el as HTMLElement).offsetLeft + (el as HTMLElement).offsetWidth);
  return Math.max(b.w * 0.4, b.copy.offsetLeft + right + 36);
}

function walk(b: Band, dt: number) {
  const now = performance.now();
  if (now - b.measured > 1000 || !b.measured) { b.minX = floorStart(b); b.measured = now; }
  const minX = Math.min(b.minX, b.w - 120);
  for (const m of b.walkers) {
    // first time the band has a real width: spread the cast along the floor
    if (!m.placed) { m.x = minX + m.start * Math.max(0, b.w - minX - m.size - 20); m.placed = true; }
    m.x = Math.max(minX, Math.min(m.x, b.w - m.size - 16));
    if (!m.still) {
      if (m.pause > 0) m.pause -= dt;
      else {
        m.x += m.dir * m.speed * dt;
        if (m.x < minX) { m.x = minX; m.dir = 1; m.pause = 1 + Math.random() * 2; }
        if (m.x > b.w - m.size - 16) { m.x = b.w - m.size - 16; m.dir = -1; m.pause = 1 + Math.random() * 2; }
        if (Math.random() < dt * 0.25) m.pause = 1.2 + Math.random() * 3;
        if (Math.random() < dt * 0.08) m.dir = m.dir === 1 ? -1 : 1;
      }
    }
    m.hop = Math.max(0, m.hop - dt * 2.4);
    const lift = Math.sin(m.hop * Math.PI) * m.size * 0.35;
    const step = m.pause > 0 || m.still ? 0 : Math.abs(Math.sin(performance.now() / 140)) * 2;
    m.wrap.style.transform = `translate(${m.x.toFixed(1)}px, ${(-lift - step).toFixed(1)}px)`;
    // eyes look where it walks, and wander when it rests
    m.blob.face(m.pause > 0 || m.still ? 0 : m.dir * 0.7);
  }
}

/** A page band: title, a line under it, optional buttons, and the page's little cast. */
export function hero(spec: HeroSpec, title: string, subtitle: string | null, actions: HTMLElement[] = [], compact = false): HTMLElement {
  const canvas = h("canvas", { class: "hero-bg", "aria-hidden": "true" }) as HTMLCanvasElement;
  const troupe = h("div", { class: "hero-troupe", "aria-hidden": "true" });
  const copy = h("div", { class: "hero-copy" }, h("h1", {}, title), subtitle ? h("p", {}, subtitle) : null,
    actions.length ? h("div", { class: "hero-actions" }, ...actions) : null);
  const root = h("div", { class: `hero ${compact ? "compact" : ""}` }, canvas, troupe, copy);
  root.style.setProperty("--hero-color", spec.color);
  const band: Band = { root, canvas, color: rgb(spec.color), dots: [], walkers: [], pointer: null, w: 0, h: 0, copy, minX: 260, measured: 0 };
  for (const c of spec.cast) {
    const size = compact ? Math.round(c.size * 0.75) : c.size;
    const blob = new Blob({ size, color: c.color, glow: c.glow });
    if (c.sleeps) blob.setMood("sleeping");
    const wrap = h("div", { class: "hero-walker", style: { width: `${size}px` } }, blob.el);
    const m: Walker = { blob, wrap, start: c.start, placed: false, x: 0, dir: Math.random() < 0.5 ? 1 : -1, speed: 14 + Math.random() * 16, pause: Math.random() * 2, hop: 0, size, still: !!c.sleeps };
    wrap.addEventListener("click", () => {
      m.hop = 1;
      if (!m.still) { blob.setMood("joy"); setTimeout(() => blob.setMood("idle"), 1400); }
    });
    band.walkers.push(m);
    troupe.append(wrap);
  }
  root.addEventListener("pointermove", (e) => { const r = canvas.getBoundingClientRect(); band.pointer = { x: e.clientX - r.left, y: e.clientY - r.top }; });
  root.addEventListener("pointerleave", () => (band.pointer = null));
  bands.add(band);
  new IntersectionObserver(() => wakeBands()).observe(root);
  return root;
}

/** Every page's colour and cast (the JARVIS window's palette). */
export const HEROES: Record<string, HeroSpec> = {
  comms: { color: "#f59e0b", cast: [{ color: "amber", size: 56, start: 0.2 }, { color: "white", size: 46, start: 0.65 }, { color: "orange", size: 40, start: 1 }] },
  stark: { color: "#5fd4ff", cast: [{ color: "cyan", size: 58, start: 0.2 }, { color: "black", size: 50, start: 0.6 }, { color: "blue", size: 42, start: 0.95 }] },
  claude: { color: "#e07950", cast: [{ color: "orange", size: 58, start: 0.3 }, { color: "white", size: 48, start: 0.85 }] },
  dictate: { color: "#fb923c", cast: [{ color: "white", size: 62, start: 0.2 }, { color: "orange", size: 50, start: 0.65 }, { color: "rose", size: 42, start: 0.95 }] },
  stats: { color: "#34d399", cast: [{ color: "amber", size: 60, start: 0.3 }, { color: "green", size: 48, start: 0.75 }, { color: "white", size: 40, start: 1 }] },
  notetaker: { color: "#3b9eff", cast: [{ color: "blue", size: 58, start: 0.1 }, { color: "green", size: 48, start: 0.5 }, { color: "violet", size: 44, start: 0.9 }] },
  dictation: { color: "#8e939c", cast: [{ color: "white", size: 56, start: 0.3 }, { color: "black", size: 46, start: 0.95, sleeps: true }] },
  dictionary: { color: "#a78bfa", cast: [{ color: "violet", size: 58, start: 0.2 }, { color: "white", size: 46, start: 0.8 }] },
  chat: { color: "#4f8dff", cast: [{ color: "black", size: 58, start: 0.2 }, { color: "blue", size: 44, start: 0.7 }] },
  tasks: { color: "#34d399", cast: [{ color: "green", size: 52, start: 0.15 }, { color: "black", size: 60, start: 0.55 }, { color: "white", size: 40, start: 0.95 }] },
  "voice-mode": { color: "#f97316", cast: [{ color: "orange", size: 56, start: 0.3 }, { color: "black", size: 46, start: 0.85 }] },
  diagnostics: { color: "#22d3ee", cast: [{ color: "cyan", size: 50, start: 0.2 }, { color: "black", size: 58, start: 0.7 }] },
  general: { color: "#8e939c", cast: [{ color: "white", size: 58, start: 0.35 }, { color: "black", size: 46, start: 0.85 }] },
  brain: { color: "#a78bfa", cast: [{ color: "violet", size: 60, start: 0.2 }, { color: "white", size: 46, start: 0.6 }, { color: "cyan", size: 40, start: 1 }] },
  voice: { color: "#f97316", cast: [{ color: "orange", size: 58, start: 0.3 }, { color: "white", size: 46, start: 0.85 }] },
  notch: { color: "#4f8dff", cast: [{ color: "black", size: 56, start: 0.25 }, { color: "blue", size: 44, start: 0.8 }] },
  appearance: { color: "#f472b6", cast: [{ color: "rose", size: 58, start: 0.2 }, { color: "white", size: 46, start: 0.6 }, { color: "cyan", size: 40, start: 1 }] },
  hotkeys: { color: "#6366f1", cast: [{ color: "midnight", size: 56, start: 0.2 }, { color: "white", size: 44, start: 0.8 }] },
  permissions: { color: "#f7b32b", cast: [{ color: "amber", size: 56, start: 0.25 }, { color: "black", size: 48, start: 0.8 }] },
  tools: { color: "#fb923c", cast: [{ color: "orange", size: 54, start: 0.15 }, { color: "amber", size: 46, start: 0.6 }, { color: "white", size: 40, start: 0.95 }] },
  integrations: { color: "#7c5cff", cast: [{ color: "violet", size: 54, start: 0.15 }, { color: "cyan", size: 46, start: 0.55 }, { color: "amber", size: 42, start: 0.95 }] },
  phone: { color: "#3ddc84", cast: [{ color: "green", size: 56, start: 0.25 }, { color: "white", size: 46, start: 0.8 }] },
  memory: { color: "#3b9eff", cast: [{ color: "blue", size: 58, start: 0.1 }, { color: "green", size: 48, start: 0.5 }, { color: "violet", size: 44, start: 0.9 }] },
  jobs: { color: "#f7b32b", cast: [{ color: "amber", size: 56, start: 0.2 }, { color: "orange", size: 46, start: 0.6 }, { color: "white", size: 40, start: 0.95 }] },
  backup: { color: "#8e939c", cast: [{ color: "white", size: 56, start: 0.3 }, { color: "black", size: 46, start: 0.95, sleeps: true }] },
};
