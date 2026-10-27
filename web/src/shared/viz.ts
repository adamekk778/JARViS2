// OMEGA wave 46: the mission graph and its dry run (192, 755), the live agent map (754), the window map (230), live captions
// (790) and the focus banner (234).
import "./viz.css";
import { h, icon } from "./dom";
import type { JarvisClient } from "./ws";

type SimStep = { n: number; label: string; kind: string; asks: boolean; perm: string; seconds: number };
type Graph = { layers: number[][]; edges: { from: number; to: number }[]; problems: string[]; parallel: number };

/** Columns = what can run at the same time; each step says what it waits for. play() lights them up in order. */
export function missionGraph(sim: SimStep[], graph: Graph, total: number): { el: HTMLElement; play: () => void } {
  const waits = new Map<number, number[]>();
  for (const e of graph.edges) waits.set(e.to, [...(waits.get(e.to) || []), e.from]);
  const nodes = new Map<number, HTMLElement>();
  const cols = graph.layers.map((layer, li) => h("div", { class: "mg-col" }, h("span", { class: "mg-lvl" }, li === 0 ? "Start" : `Fáze ${li + 1}`),
    ...layer.map((i) => {
      const s = sim[i];
      const w = waits.get(i) || [];
      const el = h("div", { class: `mg-node ${s.asks ? "asks" : ""}`, title: s.perm ? `Oprávnění: ${s.perm}` : "" },
        h("b", {}, `${i + 1}`), h("span", {}, s.label),
        h("small", {}, `${s.kind}${s.asks ? " · zeptá se" : ""} · ~${s.seconds} s${w.length ? ` · čeká na ${w.map((x) => x + 1).join(", ")}` : ""}`));
      nodes.set(i, el);
      return el;
    })));
  const n = sim.length;
  const head = h("p", { class: "muted" }, `${n} ${n === 1 ? "krok" : n < 5 ? "kroky" : "kroků"}, nejvíc ${graph.parallel} najednou, odhad ${total} s.`,
    graph.problems.length ? h("span", { class: "mg-bad" }, ` ${graph.problems.join(" ")}`) : "");
  const el = h("div", { class: "mission-graph" }, head, h("div", { class: "mg-cols" }, ...cols));
  const play = () => {
    nodes.forEach((n) => n.classList.remove("lit", "now"));
    let t = 0;
    graph.layers.forEach((layer) => {
      const dur = Math.min(1600, 350 + Math.max(...layer.map((i) => sim[i].seconds)) * 40);
      window.setTimeout(() => layer.forEach((i) => nodes.get(i)?.classList.add("now")), t);
      window.setTimeout(() => layer.forEach((i) => { nodes.get(i)?.classList.remove("now"); nodes.get(i)?.classList.add("lit"); }), t + dur);
      t += dur + 120;
    });
  };
  return { el, play };
}

/** Which specialists are working right now and on what (each pulses when it uses a tool). */
export function agentMap(client: JarvisClient): HTMLElement {
  const agents = new Map<string, { el: HTMLElement; tool: HTMLElement; t: number }>();
  const ring = h("div", { class: "am-ring" });
  const center = h("div", { class: "am-center" }, icon("cpu"), h("span", {}, "JARVIS"));
  const box = h("div", { class: "agent-map", hidden: true }, h("h4", {}, "Agenti teď"), h("div", { class: "am-stage" }, center, ring));
  const layout = () => {
    const list = [...agents.values()];
    box.hidden = !list.length;
    list.forEach((a, i) => {
      const ang = (i / Math.max(1, list.length)) * Math.PI * 2 - Math.PI / 2;
      a.el.style.left = `${50 + Math.cos(ang) * 36}%`;
      a.el.style.top = `${50 + Math.sin(ang) * 36}%`;
    });
  };
  client.on("agent_activity", (m) => {
    let a = agents.get(m.key);
    if (!a) {
      const tool = h("small", {}, "začíná…");
      const el = h("div", { class: "am-agent" }, icon(m.icon || "robot"), h("strong", {}, m.name), tool);
      ring.append(el);
      a = { el, tool, t: Date.now() };
      agents.set(m.key, a);
    }
    a.t = Date.now();
    a.el.classList.remove("pulse");
    void a.el.offsetWidth;
    a.el.classList.add("pulse");
    if (m.state === "tool") a.tool.textContent = m.tool;
    if (m.state === "done") {
      a.tool.textContent = m.ok ? `hotovo (${m.seconds} s)` : "bez výsledku";
      a.el.classList.add(m.ok ? "ok" : "fail");
      const key = m.key;
      window.setTimeout(() => { const x = agents.get(key); if (x && Date.now() - x.t > 7000) { x.el.remove(); agents.delete(key); layout(); } }, 8000);
    }
    layout();
  });
  return box;
}

/** The windows on the screen as a little map: click one to switch to it, arrows move left / right / up / down. */
export function windowMap(client: JarvisClient): { el: HTMLElement; refresh: () => void } {
  const stage = h("div", { class: "wm-stage", tabindex: "0", role: "group", "aria-label": "Mapa oken – šipkami přepínáš" });
  let focused = 0;
  client.on("windows", (m) => {
    focused = m.focused || focused;
    stage.replaceChildren(...(m.items || []).map((w: any) => h("button", {
      class: `wm-win ${w.hwnd === focused ? "on" : ""}`, type: "button", title: w.title,
      style: `left:${w.x * 100}%;top:${w.y * 100}%;width:${w.w * 100}%;height:${w.h * 100}%`,
      onclick: () => { focused = w.hwnd; client.send("window_focus", { hwnd: w.hwnd }); } }, h("span", {}, w.app || w.title))));
  });
  stage.addEventListener("keydown", (e) => {
    const dir = ({ ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" } as Record<string, string>)[e.key];
    if (!dir) return;
    e.preventDefault();
    client.send("window_nav", { dir, from: focused });
  });
  return { el: h("div", { class: "window-map" }, stage), refresh: () => client.send("windows_get") };
}

/** Big, readable captions of what JARVIS says (timed with the speech) and what it heard from you. */
export function captionBar(client: JarvisClient): HTMLElement {
  const who = h("b");
  const line = h("span");
  const bar = h("div", { class: "caption-bar", role: "status", "aria-live": "polite", hidden: true }, who, line);
  let enabled = false;
  let timers: number[] = [];
  const clear = () => { timers.forEach((t) => window.clearTimeout(t)); timers = []; };
  const show = (w: string, text: string, ms: number) => {
    who.textContent = w;
    line.textContent = text;
    bar.hidden = false;
    timers.push(window.setTimeout(() => { bar.hidden = true; }, ms));
  };
  client.on("settings_changed", (m) => { enabled = !!m.settings?.appearance?.captions; if (!enabled) bar.hidden = true; });
  client.on("caption", (m) => {
    if (!enabled) return;
    clear();
    for (const l of m.lines || []) timers.push(window.setTimeout(() => show("JARVIS", l.text, l.duration * 1000 + 400), l.at * 1000));
  });
  client.on("transcript", (m) => { if (enabled && m.text) { clear(); show("Ty", m.text, m.final ? 3500 : 2500); } });
  return bar;
}

/** "Soustředění do 15:40 · čeká 3 upozornění · Ukončit" */
export function focusBanner(client: JarvisClient): HTMLElement {
  const text = h("span");
  const el = h("div", { class: "focus-banner", hidden: true }, icon("moon-stars"), text,
    h("button", { class: "btn ghost sm", type: "button", onclick: () => client.send("focus_set", { minutes: 0 }) }, "Ukončit"));
  client.on("focus", (m) => {
    document.documentElement.dataset.focus = m.active ? "1" : "";
    el.hidden = !m.active;
    if (!m.active) return;
    const until = m.until ? ` do ${new Date(m.until * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}` : "";
    text.textContent = `${m.why && !m.until ? `Ruším méně (${m.why})` : `Soustředění${until}`}${m.waiting ? ` · čeká ${m.waiting} upozornění` : ""}`;
  });
  return el;
}
