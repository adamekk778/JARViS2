// 3.15 Mega animace – the shared motion engine every page uses:
// - the effects tier: ultra / high / eco / off ("auto" picks it from the graphics card, the battery, the load and the
//   system's "reduce motion"; it also steps down by itself when the frame rate drops under 50 fps),
// - one animation clock for the whole page that stops when the page is hidden or a full-screen game runs,
// - springs (natural movement without fixed durations) and page transitions.
// Tier and pause are written on <html data-fx="…" data-fx-paused="1"> so CSS can follow them too.
export type Tier = "ultra" | "high" | "eco" | "off";
const ORDER: Tier[] = ["off", "eco", "high", "ultra"];

let pref: "auto" | Tier = "auto";
let battery = false, heavy = false, reduced = false, paused = false;
let detected: Tier | null = null;
let stepDown = 0;                       // how many steps the frame-rate watch took away (auto only)
const listeners = new Set<(t: Tier) => void>();

/** What the graphics card can do: a discrete card → ultra, integrated → high, software rendering → eco. */
export function tierForRenderer(renderer: string): Tier {
  const r = (renderer || "").toLowerCase();
  if (!r) return "high";
  if (/swiftshader|llvmpipe|basic render|software|microsoft basic/.test(r)) return "eco";
  if (/nvidia|geforce|rtx|gtx|quadro|radeon rx|radeon pro|rx \d{3,4}|arc a\d|arc b\d|apple m\d (pro|max|ultra)/.test(r)) return "ultra";
  return "high";
}

function detect(): Tier {
  if (detected) return detected;
  try {
    const c = document.createElement("canvas");
    const gl = (c.getContext("webgl2") || c.getContext("webgl")) as WebGLRenderingContext | null;
    if (!gl) return (detected = "eco");
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    const name = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : String(gl.getParameter(gl.RENDERER));
    detected = tierForRenderer(name);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  } catch { detected = "high"; }
  return detected;
}

/** The tier for the given situation (pure – the tests call it). */
export function pickTier(o: { pref: "auto" | Tier; gpu: Tier; battery: boolean; heavy: boolean; reduced: boolean; stepDown?: number }): Tier {
  if (o.reduced) return "off";
  if (o.pref !== "auto") return o.pref;
  let t = o.gpu;
  if (o.battery || o.heavy) t = t === "ultra" ? "high" : "eco";
  const i = Math.max(1, ORDER.indexOf(t) - (o.stepDown || 0));     // the watch never goes below eco by itself
  return ORDER[i];
}

let current: Tier = "high";
function apply() {
  const t = pickTier({ pref, gpu: detect(), battery, heavy, reduced, stepDown });
  const root = document.documentElement;
  root.dataset.fx = t;
  root.dataset.fxPaused = paused || document.hidden ? "1" : "0";
  if (t !== current) { current = t; listeners.forEach((f) => f(t)); }
}

export const tier = (): Tier => current;
export const at = (min: Tier): boolean => ORDER.indexOf(current) >= ORDER.indexOf(min);
export const isPaused = (): boolean => paused || document.hidden;
export function onTier(f: (t: Tier) => void): () => void { listeners.add(f); return () => listeners.delete(f); }

let urlPref: Tier | null = null;           // ?fx=… (screenshots, tests) wins over the settings
export function configureMotion(o: { quality?: string; animations?: string; battery?: boolean; heavy?: boolean; paused?: boolean }) {
  if (o.quality !== undefined) pref = (["ultra", "high", "eco", "off"].includes(o.quality) ? o.quality : "auto") as typeof pref;
  if (o.animations === "reduced") pref = "off";
  if (urlPref) pref = urlPref;
  if (o.battery !== undefined) battery = o.battery;
  if (o.heavy !== undefined) heavy = o.heavy;
  if (o.paused !== undefined) paused = o.paused;
  apply();
}

// ------------------------------------------------------------------ one clock for every animation on the page
type Loop = (t: number, dt: number) => void;
const loops = new Set<Loop>();
let raf = 0, last = 0;
let frames = 0, sampleStart = 0, lowFor = 0;
let fps = 60;
export const currentFps = () => Math.round(fps);

function frame(now: number) {
  raf = 0;
  if (isPaused() || !loops.size) { last = 0; return; }
  const dt = last ? Math.min(0.1, (now - last) / 1000) : 1 / 60;
  last = now;
  frames++;
  if (!sampleStart) sampleStart = now;
  if (now - sampleStart >= 1000) {                   // the frame-rate watch: 5 s under 50 fps → one tier down
    fps = (frames * 1000) / (now - sampleStart);
    frames = 0; sampleStart = now;
    if (pref === "auto" && fps < 50 && current !== "eco" && current !== "off") {
      if (++lowFor >= 5) { stepDown++; lowFor = 0; apply(); }
    } else lowFor = 0;
  }
  loops.forEach((f) => { try { f(now, dt); } catch { /* one broken animation must not stop the others */ } });
  kick();
}
function kick() { if (!raf && loops.size && !isPaused()) raf = requestAnimationFrame(frame); }

/** Run `f` every frame while the page is visible and not paused; returns the stop function. */
export function loop(f: Loop): () => void {
  loops.add(f);
  kick();
  return () => { loops.delete(f); };
}

// ------------------------------------------------------------------ springs
export type SpringOpts = { stiffness?: number; damping?: number; mass?: number; precision?: number };

/** One step of a damped spring (semi-implicit Euler) – pure, for tests. */
export function springStep(x: number, v: number, to: number, dt: number, o: SpringOpts = {}): [number, number] {
  const k = o.stiffness ?? 170, c = o.damping ?? 18, m = o.mass ?? 1;
  const a = (-k * (x - to) - c * v) / m;
  const nv = v + a * dt;
  return [x + nv * dt, nv];
}

/** Animate a number from → to with a spring; `on` gets each value. With effects off it jumps straight there. */
export function spring(from: number, to: number, on: (v: number) => void, o: SpringOpts = {}): Promise<void> {
  if (current === "off") { on(to); return Promise.resolve(); }
  const eps = o.precision ?? 0.01;
  let x = from, v = 0;
  return new Promise((done) => {
    const stop = loop((_t, dt) => {
      for (let i = 0; i < 4; i++) [x, v] = springStep(x, v, to, dt / 4, o);
      if (Math.abs(x - to) < eps && Math.abs(v) < eps * 10) { on(to); stop(); done(); return; }
      on(x);
    });
  });
}

/** A page change with the browser's view transition when effects are on. */
export function transition(change: () => void): void {
  const d = document as any;
  if (current === "off" || typeof d.startViewTransition !== "function") { change(); return; }
  try { d.startViewTransition(change); } catch { change(); }
}

// ------------------------------------------------------------------ wiring
let bound = false;
export function initMotion(): void {
  if (bound) return;
  bound = true;
  const mq = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  reduced = !!mq?.matches;
  mq?.addEventListener?.("change", (e) => { reduced = e.matches; apply(); });
  document.addEventListener("visibilitychange", () => { apply(); kick(); });
  const q = new URLSearchParams(location.search).get("fx");       // ?fx=ultra / eco / off – for screenshots and tests
  if (q && ["ultra", "high", "eco", "off"].includes(q)) pref = urlPref = q as Tier;
  apply();
}
