// 3.2 Stark HUD: a holographic overlay over the whole screen, like the JARVIS of the Iron Man films.
// Arc reactor in the middle (reacts to the voice and to what JARVIS does), live systems, weather, timers,
// today's plan, now playing, a log of what JARVIS did, protocols and a command line. Esc closes it.
import "@fontsource-variable/orbitron";
import "@fontsource/rajdhani/500.css";
import "@fontsource/rajdhani/600.css";
import "@fontsource/rajdhani/700.css";
import { applyAppearance } from "../shared/base";
import "./style.css";
import { h, icon } from "../shared/dom";
import { configureSounds, play } from "../shared/sounds";
import { JarvisClient, localEndpoint } from "../shared/ws";

const client = new JarvisClient(localEndpoint(), "hud", "PC");
const api = () => (window as any).pywebview?.api;
const SVG = "http://www.w3.org/2000/svg";
const svg = (tag: string, attrs: Record<string, string | number> = {}, ...kids: Element[]) => {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
  n.append(...kids);
  return n;
};
const pad = (n: number) => String(n).padStart(2, "0");
const DAYS = ["neděle", "pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota"];
const MOOD: Record<string, string> = {
  idle: "PŘIPRAVEN", joy: "PŘIPRAVEN", listening: "POSLOUCHÁM", thinking: "ANALYZUJI", working: "PRACUJI",
  speaking: "MLUVÍM", waiting: "ČEKÁM NA POTVRZENÍ", error: "PORUCHA", limit: "LIMIT AI", offline: "OFFLINE",
  updating: "AKTUALIZUJI", success: "HOTOVO", focus: "SOUSTŘEDĚNÍ", notify: "ZPRÁVA", sleeping: "POHOTOVOST", dancing: "PŘIPRAVEN",
};

// ---------------------------------------------------------------- arc reactor
function reactor() {
  const C = 260;
  const ring = (r: number, cls: string, attrs: Record<string, string | number> = {}) =>
    svg("circle", { cx: C, cy: C, r, class: cls, ...attrs });
  const seg = (r: number, n: number, gap: number, cls: string) => {
    const len = (2 * Math.PI * r) / n;
    return ring(r, cls, { "stroke-dasharray": `${len - gap} ${gap}` });
  };
  const tri = (r: number) => {
    const p = [0, 120, 240].map((a) => {
      const t = ((a - 90) * Math.PI) / 180;
      return `${C + r * Math.cos(t)},${C + r * Math.sin(t)}`;
    }).join(" ");
    return svg("polygon", { points: p, class: "rx-tri" });
  };
  const defs = svg("defs", {},
    svg("radialGradient", { id: "rx-core" },
      svg("stop", { offset: "0%", "stop-color": "#ffffff" }),
      svg("stop", { offset: "35%", "stop-color": "#c9f4ff" }),
      svg("stop", { offset: "70%", "stop-color": "var(--holo)", "stop-opacity": ".55" }),
      svg("stop", { offset: "100%", "stop-color": "var(--holo)", "stop-opacity": "0" })));
  return h("div", { class: "reactor" }, svg("svg", { viewBox: "0 0 520 520", "aria-hidden": "true" }, defs,
    svg("g", { class: "rx-spin rx-s1" }, seg(248, 120, 4, "rx-ticks")),
    svg("g", { class: "rx-spin rx-s2" }, ring(226, "rx-arc", { "stroke-dasharray": "260 90 60 90 180 740" })),
    svg("g", { class: "rx-spin rx-s3" }, seg(196, 10, 14, "rx-seg")),
    svg("g", { class: "rx-spin rx-s4" }, ring(170, "rx-thin", { "stroke-dasharray": "2 10" }), ring(160, "rx-thin")),
    svg("g", { class: "rx-spin rx-s5" }, seg(136, 3, 30, "rx-bold")),
    svg("g", { class: "rx-core" }, ring(100, "rx-glow", { fill: "url(#rx-core)" }), tri(78), ring(44, "rx-inner"))));
}

// ---------------------------------------------------------------- small widgets
function panel(title: string, ic: string, i: number, ...kids: (Node | null)[]) {
  return h("section", { class: "panel", style: { "--i": String(i) } },
    h("header", {}, icon(ic), h("span", {}, title), h("i", { class: "rule" })), ...kids);
}

function gauge(label: string) {
  const R = 34, L = 2 * Math.PI * R;
  const arc = svg("circle", { cx: 40, cy: 40, r: R, class: "g-val", "stroke-dasharray": `0 ${L}` });
  const val = h("b", {}, "–");
  const el = h("div", { class: "gauge" },
    h("div", { class: "g-ring" }, svg("svg", { viewBox: "0 0 80 80" }, svg("circle", { cx: 40, cy: 40, r: R, class: "g-bg" }), arc), val),
    h("span", {}, label));
  return {
    el,
    set(p: number | null, text?: string) {
      const v = Math.max(0, Math.min(100, p ?? 0));
      arc.setAttribute("stroke-dasharray", `${(v / 100) * L} ${L}`);
      el.classList.toggle("hot", v >= 85);
      val.textContent = text ?? (p == null ? "–" : `${Math.round(v)}%`);
    },
  };
}

function spark(n = 60) {
  const line = svg("polyline", { class: "sp-line", points: "" });
  const area = svg("polygon", { class: "sp-area", points: "" });
  const el = svg("svg", { viewBox: `0 0 ${n - 1} 40`, preserveAspectRatio: "none", class: "spark" }, area, line);
  const data: number[] = [];
  return {
    el,
    push(v: number) {
      data.push(v);
      if (data.length > n) data.shift();
      const off = n - data.length;
      const pts = data.map((d, i) => `${i + off},${(40 - (d / 100) * 38).toFixed(1)}`).join(" ");
      line.setAttribute("points", pts);
      area.setAttribute("points", `${off},40 ${pts} ${n - 1},40`);
    },
  };
}

function typeText(el: HTMLElement, text: string, cps = 90) {
  el.textContent = "";
  let i = 0;
  const step = () => {
    i = Math.min(text.length, i + Math.max(1, Math.round(cps / 30)));
    el.textContent = text.slice(0, i);
    if (i < text.length) setTimeout(step, 33);
  };
  step();
}

// ---------------------------------------------------------------- layout
const greet = h("div", { class: "greet" });
const clock = h("div", { class: "clock" });
const dateEl = h("div", { class: "date" });
const topLeft = h("div", { class: "corner tl" }, clock, dateEl, greet);

const wTemp = h("div", { class: "w-temp" }, "--°");
const wDesc = h("div", { class: "w-desc" }, "Načítám počasí…");
const wDays = h("div", { class: "w-days" });
const topRight = h("div", { class: "corner tr" }, wTemp, wDesc, wDays);

const gCpu = gauge("CPU"), gRam = gauge("RAM"), gDisk = gauge("DISK"), gBat = gauge("BATERIE");
const cpuSpark = spark();
const netEl = h("div", { class: "kv" });
const upEl = h("div", { class: "kv" });
const sysPanel = panel("SYSTÉMY", "cpu", 0,
  h("div", { class: "gauges" }, gCpu.el, gRam.el, gDisk.el, gBat.el),
  h("div", { class: "spark-wrap" }, h("span", { class: "tiny" }, "ZATÍŽENÍ CPU · 90 s"), cpuSpark.el), netEl, upEl);

const logList = h("ol", { class: "log" });
const logPanel = panel("ZÁZNAM", "list-dashes", 2, logList);

const timersBox = h("div", { class: "list" });
const jobsBox = h("div", { class: "list" });
const planPanel = panel("PLÁN A ČASOVAČE", "timer", 1, timersBox, jobsBox);

const mTitle = h("div", { class: "m-title" }, "Nic nehraje");
const mArtist = h("div", { class: "m-artist" });
const mPlay = h("button", { class: "hbtn", type: "button", "aria-label": "Play/pauza", onclick: () => quick("media_control", { action: "play_pause" }) }, icon("play", "ph-fill"));
const mediaPanel = panel("PŘEHRÁVÁ SE", "music-notes", 3,
  h("div", { class: "media" }, h("div", { class: "m-text" }, mTitle, mArtist),
    h("div", { class: "m-btns" },
      h("button", { class: "hbtn", type: "button", "aria-label": "Předchozí", onclick: () => quick("media_control", { action: "previous" }) }, icon("skip-back", "ph-fill")),
      mPlay,
      h("button", { class: "hbtn", type: "button", "aria-label": "Další", onclick: () => quick("media_control", { action: "next" }) }, icon("skip-forward", "ph-fill")))));

const rx = reactor();
const moodEl = h("div", { class: "mood" }, "INICIALIZACE");
const youEl = h("div", { class: "you" });
const answerEl = h("div", { class: "answer" });
const chipsEl = h("div", { class: "chips" });
const centre = h("div", { class: "centre" }, rx, h("div", { class: "name" }, "J.A.R.V.I.S."), moodEl, youEl, chipsEl, answerEl);

const protoRow = h("div", { class: "protocols" });
const input = h("input", { class: "cmd", type: "text", placeholder: "Příkaz pro JARVISe…  (Enter)", "aria-label": "Příkaz pro JARVISe", autocomplete: "off" }) as HTMLInputElement;
const send = () => {
  const text = input.value.trim();
  if (!text) return;
  client.send("user_text", { text, attachments: [] });
  input.value = "";
};
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); send(); }
  if (e.key === "Escape" && input.value) { e.stopPropagation(); input.value = ""; }
});
const bottom = h("div", { class: "bottom" }, protoRow,
  h("div", { class: "cmdbar" },
    h("button", { class: "hbtn", type: "button", title: "Mluvit (Ctrl+Alt+Mezerník)", "aria-label": "Mluvit", onclick: () => client.send("push_to_talk") }, icon("microphone")),
    input,
    h("button", { class: "hbtn", type: "button", title: "Odeslat", "aria-label": "Odeslat", onclick: send }, icon("arrow-right", "ph-bold")),
    h("button", { class: "hbtn", type: "button", title: "Ranní brífink", "aria-label": "Brífink", onclick: () => client.send("user_text", { text: "Brífink", attachments: [] }) }, icon("sun-horizon")),
    h("button", { class: "hbtn", type: "button", title: "Otevřít celý chat", "aria-label": "Celý chat", onclick: () => openChat("full") }, icon("chats-circle"))));

const alertBox = h("div", { class: "alert", hidden: true });
const briefBox = h("div", { class: "brief", hidden: true });
const closeBtn = h("button", { class: "close", type: "button", title: "Zavřít HUD (Esc)", "aria-label": "Zavřít HUD", onclick: () => closeHud() }, icon("x"));
const left = h("div", { class: "col left" }, sysPanel, logPanel);
const right = h("div", { class: "col right" }, planPanel, mediaPanel);
const root = h("div", { class: "hud booting" },
  h("div", { class: "grid" }), h("div", { class: "scan" }), h("div", { class: "vignette" }),
  topLeft, topRight, left, centre, right, bottom, alertBox, briefBox, closeBtn,
  h("i", { class: "br b1" }), h("i", { class: "br b2" }), h("i", { class: "br b3" }), h("i", { class: "br b4" }));
document.getElementById("hud")!.append(root);

// ---------------------------------------------------------------- behaviour
function quick(action: string, args: any = {}) { client.send("quick_action", { action, args }); }
function openChat(view: string) {
  if (api()?.open_chat) api().open_chat(view);
  else window.open(view === "full" ? "/chat" : `/#${view}`, "_blank");
}
function closeHud() {
  if (api()?.close) api().close();
}

let name = "pane";
function tickClock() {
  const d = new Date();
  clock.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  dateEl.textContent = `${DAYS[d.getDay()]} ${d.getDate()}. ${d.getMonth() + 1}. ${d.getFullYear()}`.toUpperCase();
  const hr = d.getHours();
  greet.textContent = `${hr < 5 ? "Dobrou noc" : hr < 10 ? "Dobré ráno" : hr < 18 ? "Dobrý den" : "Dobrý večer"}, ${name}.`;
  for (const t of timers) t.remaining = Math.max(0, t.remaining - 1);
  renderTimers();
}

let timers: any[] = [];
let jobs: any[] = [];
function renderTimers() {
  timersBox.replaceChildren(...timers.slice(0, 4).map((t) => h("div", { class: "row" }, icon("timer"),
    h("span", {}, t.label || "Časovač"), h("b", {}, `${pad(Math.floor(t.remaining / 60))}:${pad(t.remaining % 60)}`))));
  const today = new Date(); today.setHours(23, 59, 59);
  const soon = jobs.filter((j) => j.enabled && j.next_run * 1000 <= today.getTime()).slice(0, 4);
  jobsBox.replaceChildren(...soon.map((j) => {
    const d = new Date(j.next_run * 1000);
    return h("div", { class: "row" }, icon("calendar-check"), h("span", {}, j.title || "Rutina"), h("b", {}, `${pad(d.getHours())}:${pad(d.getMinutes())}`));
  }));
  if (!timers.length && !soon.length) timersBox.replaceChildren(h("div", { class: "muted" }, "Dnes nic naplánováno. „Připomeň mi v 5 …“"));
}

function log(text: string, kind = "") {
  const d = new Date();
  logList.prepend(h("li", { class: kind }, h("time", {}, `${pad(d.getHours())}:${pad(d.getMinutes())}`), h("span", {}, text)));
  while (logList.childElementCount > 9) logList.lastChild!.remove();
}

function renderProtocols(list: any[]) {
  protoRow.replaceChildren(...(list || []).map((p, i) =>
    h("button", { class: "proto", type: "button", style: { "--i": String(i) }, "data-id": p.id, title: `Spustit protokol ${p.name}`,
      onclick: (e: Event) => {
        (e.currentTarget as HTMLElement).classList.add("fire");
        setTimeout(() => (e.currentTarget as HTMLElement)?.classList.remove("fire"), 900);
        client.send("protocol_run", { id: p.id });
      } },
      icon(p.icon || "lightning"), h("span", {}, p.name))));
}

function showAlert(title: string, text: string) {
  alertBox.hidden = false;
  alertBox.replaceChildren(icon("warning", "ph-fill"), h("div", {}, h("strong", {}, title.toUpperCase()), h("span", {}, text)));
  clearTimeout((showAlert as any).t);
  (showAlert as any).t = setTimeout(() => (alertBox.hidden = true), 12000);
}

function showBriefing(text: string) {
  briefBox.hidden = false;
  const body = h("p", {});
  briefBox.replaceChildren(h("header", {}, icon("sun-horizon"), h("span", {}, "RANNÍ BRÍFINK"),
    h("button", { class: "hbtn sm", type: "button", "aria-label": "Zavřít brífink", onclick: () => (briefBox.hidden = true) }, icon("x"))), body);
  typeText(body, text, 120);
}

const plain = (md: string) => md.replace(/```[\s\S]*?```/g, " [kód] ").replace(/[*_#>`|]/g, "").replace(/\s+/g, " ").trim();
let answer = "";

client.on("welcome", (m) => {
  applyAppearance(m.settings);
  configureSounds(m.settings?.appearance);
  name = m.settings?.general?.address_as || m.settings?.general?.user_name || "pane";
  renderProtocols(m.settings?.stark?.protocols);
  timers = (m.timers || []).map((t: any) => ({ ...t }));
  setMedia(m.media || {});
  setMood(m.mood?.mood || "idle");
  refresh(true);
});
client.on("settings_changed", (m) => { applyAppearance(m.settings); renderProtocols(m.settings?.stark?.protocols); });
client.on("system", (s) => {
  gCpu.set(s.cpu_percent); cpuSpark.push(s.cpu_percent || 0);
  gRam.set(s.ram_percent, `${Math.round(s.ram_percent)}%`);
  gDisk.set(s.disk_percent);
  if (s.battery_percent == null) gBat.set(100, "AC"); else gBat.set(s.battery_percent, `${s.battery_percent}%`);
  gBat.el.classList.toggle("hot", s.battery_percent != null && s.battery_percent <= 20 && !s.charging);
  netEl.replaceChildren(icon("arrow-down"), h("span", {}, fmtRate(s.net_down_kbps)), icon("arrow-up"), h("span", {}, fmtRate(s.net_up_kbps)));
  upEl.replaceChildren(icon("clock-counter-clockwise"), h("span", {}, `V provozu ${s.uptime_h} h · ${s.hostname || ""}`));
});
const fmtRate = (k: number) => (k >= 1024 ? `${(k / 1024).toFixed(1)} MB/s` : `${Math.round(k || 0)} kB/s`);
client.on("weather", (w) => {
  wTemp.textContent = `${Math.round(w.temp)}°`;
  wDesc.textContent = `${w.city} · ${w.desc}`.toUpperCase();
  wDays.replaceChildren(...(w.days || []).slice(1, 4).map((d: any) => {
    const day = DAYS[new Date(d.date).getDay()].slice(0, 2).toUpperCase();
    return h("div", { class: "wd" }, h("span", {}, day), h("b", {}, `${Math.round(d.max)}°`), h("i", {}, `${Math.round(d.min)}°`));
  }));
});
client.on("timers", (m) => { timers = m.items.map((t: any) => ({ ...t })); renderTimers(); });
client.on("jobs", (m) => { jobs = m.items || []; renderTimers(); });
client.on("media", (m) => setMedia(m));
function setMedia(m: any) {
  mTitle.textContent = m.title || "Nic nehraje";
  mArtist.textContent = m.artist || "";
  mPlay.replaceChildren(icon(m.playing ? "pause" : "play", "ph-fill"));
  mediaPanel.classList.toggle("on", !!m.playing);
}
function setMood(mood: string) {
  moodEl.textContent = MOOD[mood] || "PŘIPRAVEN";
  root.dataset.mood = mood;
}
client.on("mood", (m) => setMood(m.mood));
let lvlRaf = 0, lvl = 0;
client.on("level", (m) => {
  lvl = Math.max(lvl, Math.min(1, (m.rms || 0) * 9));
  if (!lvlRaf) lvlRaf = requestAnimationFrame(function fade() {
    root.style.setProperty("--lvl", lvl.toFixed(3));
    lvl *= 0.86;
    lvlRaf = lvl > 0.01 ? requestAnimationFrame(fade) : 0;
    if (!lvlRaf) root.style.setProperty("--lvl", "0");
  });
});
client.on("user_message", (m) => {
  youEl.textContent = m.text ? `„${m.text}“` : "";
  answer = ""; answerEl.textContent = ""; chipsEl.replaceChildren();
});
client.on("assistant_delta", (m) => { answer += m.text; answerEl.textContent = plain(answer).slice(-420); });
client.on("assistant_done", (m) => { answer = m.text || answer; answerEl.textContent = plain(answer).slice(0, 420); });
client.on("tool_start", (m) => {
  chipsEl.append(h("span", { class: "chip run", "data-id": m.id }, (m.label || m.name).replace(/^[^\p{L}\p{N}]+/u, "")));
});
client.on("tool_end", (m) => {
  const c = chipsEl.querySelector(`[data-id="${m.id}"]`);
  c?.classList.remove("run"); c?.classList.add(m.ok ? "ok" : "fail");
  if (c) log(`${c.textContent}${m.summary ? " – " + m.summary : ""}`.slice(0, 90), m.ok ? "" : "bad");
});
client.on("protocol", (m) => { log(`Protokol ${m.name} spuštěn`, "lp"); play("wake"); });
client.on("guardian", (m) => { log(m.text, "bad"); showAlert(m.title, m.text); });
client.on("notify", (m) => log(`${m.title}: ${m.body}`.slice(0, 90)));
client.on("briefing", (m) => { showBriefing(m.text); log("Ranní brífink"); });
client.on("error", (m) => log(m.message, "bad"));
client.onStatus((s) => { if (s !== "open") setMood("offline"); });

// ---------------------------------------------------------------- open / close (the desktop shows and hides the window)
let poll = 0, clockT = 0, slow = 0;
function refresh(all = false) {
  client.send("system_get");
  if (all) { client.send("weather_get"); client.send("jobs_get"); client.send("timers_get"); }
}
function open() {
  root.classList.remove("closing");
  root.classList.add("booting");
  void root.offsetWidth;
  setTimeout(() => root.classList.remove("booting"), 1900);
  typeText(moodEl, "INICIALIZACE SYSTÉMŮ…", 60);
  setTimeout(() => setMood(root.dataset.mood || "idle"), 1500);
  play("boot");
  tickClock();
  clearInterval(poll); clearInterval(clockT); clearInterval(slow);
  poll = window.setInterval(() => refresh(), 1500);
  clockT = window.setInterval(tickClock, 1000);
  slow = window.setInterval(() => refresh(true), 10 * 60 * 1000);
  refresh(true);
  setTimeout(() => input.focus(), 400);
}
function close() {
  clearInterval(poll); clearInterval(clockT); clearInterval(slow);
  briefBox.hidden = true;
}
(window as any).__hud = {
  open, close,
  alpha(on: boolean) { document.documentElement.classList.toggle("alpha", on); },
};
window.addEventListener("pywebviewready", () => {
  Promise.resolve(api()?.smooth?.()).then((on) => document.documentElement.classList.toggle("alpha", !!on)).catch(() => {});
});
window.addEventListener("keydown", (e) => { if (e.key === "Escape") closeHud(); });
client.connect();
open();
