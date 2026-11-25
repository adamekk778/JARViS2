// 3.15 Mega animace v HUD (návrhy 2, 11–17, 43): the cinematic start, the parallax depth, the live telemetry, the
// tools orbiting the reactor while JARVIS works, the red alert, the protocol sequence, the kiosk screensaver and the
// HUD's voice commands. Everything follows the effects tier (eco = calm, off = none) and stops with the page.
import { h, icon } from "../shared/dom";
import { at, loop, tier } from "../shared/motion";
import { play } from "../shared/sounds";

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ 2: the cinematic start
export type BootInfo = { ai: string; voice: boolean; online: boolean; name: string };

export function bootLines(i: BootInfo): [string, string][] {
  return [["JÁDRO J.A.R.V.I.S.", "ONLINE"], ["NEURONOVÁ SÍŤ", i.ai ? i.ai.toUpperCase() : "PŘIPRAVENA"],
    ["HLASOVÝ MODUL", i.voice ? "AKTIVNÍ" : "TICHÝ REŽIM"], ["SENZORY A TELEMETRIE", "KALIBROVÁNO"],
    ["SPOJENÍ", i.online ? "ŠIFROVANÉ" : "OFFLINE"], ["PROTOKOLY", "NAČTENY"]];
}

export async function bootSequence(root: HTMLElement, info: BootInfo): Promise<void> {
  if (!at("high")) return;                          // eco / off: just the short fade the CSS already does
  const lines = bootLines(info);
  const list = h("ol", { class: "boot-lines" });
  const sweep = h("i", { class: "boot-sweep" });
  const title = h("div", { class: "boot-title" });
  const el = h("div", { class: "boot-seq", "aria-hidden": "true" }, sweep, title, list);
  root.append(el);
  play("boot");
  for (const [k, v] of lines) {
    const li = h("li", {}, h("span", {}, k), h("i", {}), h("b", {}, ""));
    list.append(li);
    await wait(150);
    (li.lastChild as HTMLElement).textContent = v;
    li.classList.add("ok");
  }
  title.textContent = "VŠECHNY SYSTÉMY ONLINE";
  el.classList.add("done");
  play("done");
  await wait(650);
  el.classList.add("out");
  await wait(500);
  el.remove();
}

// ------------------------------------------------------------------ 11: parallax depth + the hologram grain
export function parallax(root: HTMLElement): () => void {
  let tx = 0, ty = 0, x = 0, y = 0;
  const move = (e: PointerEvent) => { tx = (e.clientX / window.innerWidth) * 2 - 1; ty = (e.clientY / window.innerHeight) * 2 - 1; };
  window.addEventListener("pointermove", move);
  const stop = loop((_t, dt) => {
    if (!at("high")) { if (x || y) { x = y = 0; root.style.setProperty("--px", "0"); root.style.setProperty("--py", "0"); } return; }
    x += (tx - x) * Math.min(1, dt * 4); y += (ty - y) * Math.min(1, dt * 4);
    root.style.setProperty("--px", x.toFixed(3));
    root.style.setProperty("--py", y.toFixed(3));
  });
  return () => { stop(); window.removeEventListener("pointermove", move); };
}

// ------------------------------------------------------------------ 12: live telemetry curves
export function trace(label: string, color = "var(--holo)", n = 90) {
  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("class", "tr-line");
  line.setAttribute("style", `stroke:${color}`);
  const svgEl = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svgEl.setAttribute("viewBox", `0 0 ${n - 1} 30`);
  svgEl.setAttribute("preserveAspectRatio", "none");
  svgEl.setAttribute("class", "trace");
  svgEl.append(line);
  const val = h("b", {}, "–");
  const el = h("div", { class: "tr" }, h("span", {}, label), val, svgEl);
  const data: number[] = [];
  let shown: number[] = [];
  // the curve glides between samples (one per 1.5 s) instead of jumping
  const stop = loop((_t, dt) => {
    if (!data.length) return;
    if (shown.length !== data.length) shown = data.slice();
    let moved = false;
    for (let i = 0; i < data.length; i++) {
      const d = data[i] - shown[i];
      if (Math.abs(d) > 0.05) { shown[i] += d * Math.min(1, dt * 6); moved = true; }
    }
    if (!moved) return;
    const off = n - shown.length;
    line.setAttribute("points", shown.map((v, i) => `${i + off},${(29 - (v / 100) * 28).toFixed(1)}`).join(" "));
  });
  return {
    el, stop,
    push(v: number, text: string) {
      data.push(Math.max(0, Math.min(100, v)));
      if (data.length > n) { data.shift(); shown.shift(); }
      val.textContent = text;
    },
  };
}

/** Network speed (kB/s) on a log scale 0–100 for the curve. */
export const netScale = (kbps: number) => Math.min(100, (Math.log10(1 + Math.max(0, kbps)) / 5) * 100);

/** A column of real numbers running past, like the telemetry in the film (ultra only). */
export function telemetry(get: () => number[]): HTMLElement {
  const el = h("pre", { class: "telemetry", "aria-hidden": "true" });
  const rows: string[] = [];
  let acc = 0;
  loop((_t, dt) => {
    if (!at("ultra")) { if (rows.length) { rows.length = 0; el.textContent = ""; } return; }
    acc += dt;
    if (acc < 0.12) return;
    acc = 0;
    const v = get();
    const hex = (n: number) => Math.max(0, Math.round(n)).toString(16).toUpperCase().padStart(4, "0");
    rows.push(`${hex(v[0] * 655)} ${hex(v[1] * 655)} ${hex(v[2])} ${(v[0] / 100).toFixed(3)} ${hex(performance.now() % 65535)}`);
    if (rows.length > 18) rows.shift();
    el.textContent = rows.join("\n");
  });
  return el;
}

// ------------------------------------------------------------------ 14: the tools orbiting the reactor
export function toolOrbit(host: HTMLElement) {
  const ring = h("div", { class: "orbit", "aria-hidden": "true" });
  host.append(ring);
  const nodes = new Map<string, HTMLElement>();
  let spin = 0;
  const layout = () => {
    const list = [...nodes.values()];
    list.forEach((n, i) => n.style.setProperty("--a", `${(360 / Math.max(1, list.length)) * i}deg`));
  };
  loop((_t, dt) => {
    if (!nodes.size) return;
    spin = (spin + dt * (at("high") ? 14 : 0)) % 360;
    ring.style.setProperty("--spin", `${spin}deg`);
  });
  return {
    start(id: string, label: string) {
      const n = h("div", { class: "orb-node" }, h("i", { class: "orb-line" }), h("span", {}, label.replace(/^[^\p{L}\p{N}]+/u, "").slice(0, 26)));
      nodes.set(id, n);
      ring.append(n);
      layout();
      if (at("high")) play("holo");
    },
    end(id: string, ok: boolean) {
      const n = nodes.get(id);
      if (!n) return;
      n.classList.add(ok ? "ok" : "fail");
      setTimeout(() => { n.classList.add("gone"); setTimeout(() => { n.remove(); nodes.delete(id); layout(); }, 450); }, 1200);
    },
    clear() { nodes.forEach((n) => n.remove()); nodes.clear(); },
  };
}

// ------------------------------------------------------------------ 15: the red alert
export function redAlert(root: HTMLElement, ms = 3600): void {
  if (tier() === "off") return;
  root.classList.remove("red-alert");
  void root.offsetWidth;
  root.classList.add("red-alert");
  play("alert");
  clearTimeout((redAlert as any).t);
  (redAlert as any).t = setTimeout(() => root.classList.remove("red-alert"), ms);
}

// ------------------------------------------------------------------ 16: a protocol as a sequence
export function protocolRun(root: HTMLElement) {
  let el: HTMLElement | null = null, steps: HTMLElement[] = [], done = 0, timer = 0;
  const finish = () => {
    if (!el) return;
    steps.forEach((s) => s.classList.add("ok"));
    el.classList.add("done");
    const old = el;
    setTimeout(() => { old.classList.add("out"); setTimeout(() => old.remove(), 500); }, 1400);
    el = null;
  };
  return {
    async start(name: string, ic: string, labels: string[]) {
      el?.remove();
      done = 0;
      const count = h("b", { class: "pr-count" }, "");
      steps = (labels.length ? labels : ["Spouštím"]).map((l) => h("li", {}, icon("circle"), h("span", {}, l)));
      el = h("div", { class: "proto-run", role: "status", "aria-live": "polite" },
        h("header", {}, icon(ic || "lightning", "ph-fill"), h("span", {}, `PROTOKOL ${name.toUpperCase()}`), count), h("ol", {}, ...steps));
      root.append(el);
      play("whoosh");
      if (at("high")) for (const n of ["3", "2", "1"]) { count.textContent = n; play("holo"); await wait(220); }
      count.textContent = "▶";
      steps[0]?.classList.add("run");
      clearTimeout(timer);
      timer = window.setTimeout(finish, 25000);
    },
    step() {
      if (!el) return;
      const cur = steps[done];
      if (cur) { cur.classList.remove("run"); cur.classList.add("ok"); }
      done++;
      if (done >= steps.length) { play("done"); clearTimeout(timer); finish(); } else steps[done]?.classList.add("run");
    },
    end() { if (el) { clearTimeout(timer); play("done"); finish(); } },
    active: () => !!el,
  };
}

// ------------------------------------------------------------------ 17: the wall display's screensaver
export function screensaver(root: HTMLElement, mountGlobeInto: (host: HTMLElement) => Promise<{ dispose(): void } | null>) {
  let el: HTMLElement | null = null, g: { dispose(): void } | null = null;
  const clock = h("div", { class: "ss-clock" });
  const tick = () => { const d = new Date(); clock.textContent = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
  let t = 0;
  return {
    async show() {
      if (el) return;
      const gh = h("div", { class: "ss-globe" });
      el = h("div", { class: "screensaver", "aria-hidden": "true" }, gh, clock);
      root.append(el);
      tick();
      t = window.setInterval(tick, 10000);
      g = await mountGlobeInto(gh);
    },
    hide() {
      if (!el) return;
      clearInterval(t);
      g?.dispose(); g = null;
      el.classList.add("out");
      const old = el;
      setTimeout(() => old.remove(), 700);
      el = null;
      play("wake");
    },
    get on() { return !!el; },
  };
}

// ------------------------------------------------------------------ 43: the HUD's voice commands
export const HUD_ACTIONS = ["map", "globe", "flat", "zoom_in", "zoom_out", "radar_play", "close_map", "full", "minimal", "focus",
  "presentation", "hide_panels", "show_panels", "systems", "close"] as const;
