import { applyAppearance } from "../shared/base";
import "./style.css";
import { h, icon, TOOL_ICON } from "../shared/dom";
import { renderMarkdown } from "../shared/markdown";
import type { AgentState, Attachment } from "../shared/protocol";
import { JarvisClient, localEndpoint } from "../shared/ws";
import { buildTiles, type TileCtx } from "./tiles";

/* Notch modes:
   idle   collapsed black notch (+ tiny live activity)
   open   hovered: panel with tiles
   live   JARVIS is listening / thinking / speaking: waves, transcript, answer
   alert  short notification pop                                              */
type Mode = "idle" | "open" | "live" | "alert";

declare global {
  interface Window { pywebview?: { api: Record<string, (...a: any[]) => Promise<any>> } }
}

const params = new URLSearchParams(location.search);
window.addEventListener("pywebviewready", () => document.documentElement.classList.add("native"));
if (window.pywebview) document.documentElement.classList.add("native");
const demo = params.get("demo") as Mode | null;
const client = new JarvisClient(localEndpoint(), "notch", "notch");

let cfg = { width: 200, height: 32, expanded_width: 680, expanded_height: 240, open_delay_ms: 150, close_delay_ms: 400, linger_s: 6, tiles: ["ask", "media", "shelf", "quick", "timers", "system", "weather", "phone"] };
let mode: Mode = "idle";
let agentState: AgentState = "idle";
let hovering = false;
let pinned = false; // typing or confirming keeps it open
let openTimer = 0, closeTimer = 0, lingerTimer = 0, alertTimer = 0;
let level = 0;
let smooth = 0;
let liveText = "";
let pendingConfirm: string | null = null;
let activity: { icon: string; text: string } | null = null;

// ---------- DOM ----------
const orb = h("div", { class: "orb", "data-state": "offline" });
const actIcon = h("i", { class: "ph ph-music-notes act-icon" });
const actText = h("span", { class: "act-text" });
const collapsed = h("div", { class: "n-collapsed" }, orb, h("div", { class: "act" }, actIcon, actText));

const waves = h("canvas", { class: "waves", width: 120, height: 40 }) as HTMLCanvasElement;
const liveState = h("div", { class: "live-state" });
const liveTranscript = h("div", { class: "live-transcript" });
const liveTool = h("div", { class: "live-tool" });
const liveAnswer = h("div", { class: "live-answer md" });
const liveConfirm = h("div", { class: "live-confirm" });
const live = h("div", { class: "n-live" },
  h("div", { class: "live-head" }, h("div", { class: "orb", "data-state": "listening" }), liveState, waves),
  liveTranscript, liveTool, liveAnswer, liveConfirm);

const alertTitle = h("strong");
const alertBody = h("span");
const alertBox = h("div", { class: "n-alert" }, h("i", { class: "ph ph-bell-ringing alert-icon" }), h("div", { class: "alert-text" }, alertTitle, alertBody));

const clock = h("span", { class: "clock" });
const brainLbl = h("span", { class: "brain-lbl" });
const header = h("div", { class: "n-header" },
  h("div", { class: "orb", "data-state": "idle" }), h("strong", {}, "JARVIS"), clock, brainLbl,
  h("div", { class: "spacer" }),
  h("button", { class: "n-btn", type: "button", title: "Chat (Ctrl+Alt+J)", "aria-label": "Otevřít chat", onclick: () => openChat("chat") }, icon("chat-circle-dots")),
  h("button", { class: "n-btn", type: "button", title: "Nastavení", "aria-label": "Nastavení", onclick: () => openChat("general") }, icon("gear-six")),
  h("button", { class: "n-btn", type: "button", title: "Připnout otevřený", "aria-label": "Připnout", onclick: (e: Event) => { pinned = !pinned; (e.currentTarget as HTMLElement).classList.toggle("on", pinned); } }, icon("push-pin")));
const strip = h("div", { class: "n-strip" });
strip.addEventListener("scroll", () => strip.classList.toggle("at-end", strip.scrollLeft + strip.clientWidth >= strip.scrollWidth - 4));
strip.addEventListener("wheel", (e) => { if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) { strip.scrollLeft += e.deltaY; e.preventDefault(); } }, { passive: false });
const panel = h("div", { class: "n-panel" }, header, strip);

const shape = h("div", { class: "notch", "data-mode": "idle" }, collapsed, live, alertBox, panel);
const dropHint = h("div", { class: "drop-hint" }, icon("tray-arrow-down"), "Pusť soubory do police");
shape.append(dropHint);
document.getElementById("notch-root")!.append(shape);

// ---------- tiles ----------
const tileCtx: TileCtx = {
  client,
  pin: (v) => { pinned = v; if (!v) scheduleClose(); },
  openChat,
  shelf: [] as Attachment[],
};
const tiles = buildTiles(tileCtx);
function renderTiles() {
  strip.replaceChildren(...cfg.tiles.filter((t) => tiles[t]).map((t) => tiles[t].el));
}

// ---------- window sizing (pywebview) ----------
async function resizeWindow(w: number, hgt: number) {
  try { await window.pywebview?.api.resize(Math.round(w), Math.round(hgt)); } catch { /* browser preview */ }
}
function openChat(view = "chat") {
  if (window.pywebview) window.pywebview.api.open_chat(view);
  else window.open(`/#${view}`, "_blank");
}

const PAD = 28; // room for shadow
function sizeFor(m: Mode): [number, number] {
  switch (m) {
    case "open": return [cfg.expanded_width, cfg.expanded_height];
    case "live": return [Math.max(460, Math.min(560, cfg.expanded_width)), liveHeight()];
    case "alert": return [420, 64];
    default: return [activity ? Math.max(cfg.width, 300) : cfg.width, cfg.height];
  }
}
function liveHeight() {
  const base = 62;
  const extra = (liveTranscript.textContent ? 24 : 0) + (liveTool.textContent ? 24 : 0) + (liveAnswer.textContent ? Math.min(110, 6 + liveAnswer.scrollHeight) : 0) + (pendingConfirm ? 44 : 0);
  return Math.min(260, base + extra);
}

let lastSize = [0, 0];
function apply(m: Mode) {
  const [w, hgt] = sizeFor(m);
  const growing = w > lastSize[0] || hgt > lastSize[1];
  if (growing) resizeWindow(w + PAD * 2, hgt + PAD);
  shape.style.setProperty("--w", `${w}px`);
  shape.style.setProperty("--h", `${hgt}px`);
  shape.dataset.mode = m;
  if (!growing) {
    window.clearTimeout((apply as any)._t);
    (apply as any)._t = window.setTimeout(() => resizeWindow(w + PAD * 2, hgt + PAD), 420);
  }
  lastSize = [w, hgt];
}

function setMode(m: Mode) {
  if (demo) m = demo;
  mode = m;
  apply(m);
}

function settle() {
  // decide the resting mode after something ends
  if (pendingConfirm || agentState !== "idle") return setMode("live");
  if (hovering || pinned) return setMode("open");
  setMode("idle");
}

function scheduleClose() {
  window.clearTimeout(closeTimer);
  closeTimer = window.setTimeout(() => {
    if (!hovering && !pinned && mode === "open") settle();
  }, cfg.close_delay_ms);
}

shape.addEventListener("mouseenter", () => {
  hovering = true;
  window.clearTimeout(closeTimer);
  window.clearTimeout(openTimer);
  if (mode === "idle" || mode === "alert") openTimer = window.setTimeout(() => hovering && setMode("open"), cfg.open_delay_ms);
});
shape.addEventListener("mouseleave", () => {
  hovering = false;
  window.clearTimeout(openTimer);
  if (mode === "open") scheduleClose();
});
shape.addEventListener("click", (e) => {
  if (mode === "idle") { setMode("open"); e.stopPropagation(); }
  if (mode === "live" && agentState === "idle" && !pendingConfirm) setMode("open");
});

// drag & drop to shelf
let dragDepth = 0;
window.addEventListener("dragenter", (e) => {
  if (!e.dataTransfer?.types.includes("Files")) return;
  dragDepth++;
  shape.classList.add("dragging");
  if (mode !== "open") setMode("open");
});
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; shape.classList.remove("dragging"); } });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", async (e) => {
  e.preventDefault();
  dragDepth = 0;
  shape.classList.remove("dragging");
  const target = (e.target as HTMLElement).closest("[data-tile]") as HTMLElement | null;
  for (const f of [...(e.dataTransfer?.files || [])]) {
    const att = await client.upload(f, f.name);
    if (target?.dataset.tile === "ask") tiles.ask.attach?.(att);
    else client.send("shelf_add", { attachment_id: att.id });
  }
});

// ---------- live mode ----------
const STATE_LABEL: Record<string, string> = { listening: "Poslouchám…", thinking: "Přemýšlím…", acting: "Pracuji…", speaking: "", waiting: "Potřebuji potvrzení", idle: "" };
function setAgentState(s: AgentState) {
  agentState = s;
  orb.dataset.state = s;
  live.querySelector(".orb")!.setAttribute("data-state", s);
  header.querySelector(".orb")!.setAttribute("data-state", s);
  liveState.textContent = STATE_LABEL[s] ?? "";
  if (s === "listening") {
    liveText = "";
    liveAnswer.textContent = "";
    liveTranscript.textContent = "";
    liveTool.textContent = "";
  }
  if (s !== "idle") {
    window.clearTimeout(lingerTimer);
    if (mode !== "open" || s === "listening") setMode("live");
  } else if (mode === "live") {
    window.clearTimeout(lingerTimer);
    lingerTimer = window.setTimeout(() => { if (agentState === "idle" && !pendingConfirm) settle(); }, cfg.linger_s * 1000);
  }
}

function drawWaves() {
  const ctx = waves.getContext("2d")!;
  const w = waves.width, hh = waves.height;
  ctx.clearRect(0, 0, w, hh);
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#2ee6ff";
  const t = performance.now() / 1000;
  const active = agentState === "listening" || agentState === "speaking";
  smooth += (level - smooth) * 0.2;
  const amp = active ? Math.max(0.18, Math.min(1, smooth * 5)) : agentState === "idle" ? 0.06 : 0.14;
  const bars = 18;
  for (let i = 0; i < bars; i++) {
    const x = (i + 0.5) * (w / bars);
    const env = Math.sin((i / (bars - 1)) * Math.PI);
    const v = (0.35 + 0.65 * Math.abs(Math.sin(t * 5 + i * 0.7))) * amp * env;
    const bh = Math.max(3, v * hh);
    ctx.fillStyle = accent;
    ctx.globalAlpha = 0.55 + 0.45 * env;
    const bw = w / bars - 3;
    ctx.beginPath();
    ctx.roundRect(x - bw / 2, (hh - bh) / 2, bw, bh, bw / 2);
    ctx.fill();
  }
  level *= 0.94;
  requestAnimationFrame(drawWaves);
}
requestAnimationFrame(drawWaves);

function renderLiveAnswer() {
  const text = liveText.length > 600 ? "…" + liveText.slice(-600) : liveText;
  liveAnswer.innerHTML = renderMarkdown(text);
  liveAnswer.scrollTop = liveAnswer.scrollHeight;
  if (mode === "live") apply("live");
}

// ---------- activity (collapsed live activity) ----------
function updateActivity() {
  const timers = tiles.timers?.state?.() as any[] | undefined;
  const media = tiles.media?.state?.() as any;
  if (timers?.length) {
    const t = timers[0];
    const r = Math.max(0, Math.round(t.ends_at - Date.now() / 1000));
    activity = { icon: "timer", text: `${Math.floor(r / 60)}:${String(r % 60).padStart(2, "0")}` };
  } else if (media?.playing && media.title) {
    activity = { icon: "music-notes", text: media.title };
  } else {
    activity = null;
  }
  shape.classList.toggle("has-act", !!activity);
  if (activity) {
    actIcon.className = `ph ph-${activity.icon} act-icon`;
    actText.textContent = activity.text;
  }
  if (mode === "idle") apply("idle");
}
setInterval(() => {
  clock.textContent = new Date().toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  updateActivity();
}, 1000);

// ---------- events ----------
client.onStatus((s) => { if (s !== "open") orb.dataset.state = "offline"; });
client.on("welcome", (m) => {
  applyAppearance(m.settings);
  cfg = { ...cfg, ...(m.settings?.notch || {}) };
  if (m.brain) brainLbl.textContent = m.brain[0];
  tileCtx.shelf = m.shelf || [];
  renderTiles();
  tiles.media?.update?.(m.media);
  tiles.timers?.update?.(m.timers);
  tiles.shelf?.update?.(m.shelf);
  pendingConfirm = m.pending_confirm || null;
  setAgentState(m.busy ? "thinking" : "idle");
  settle();
});
client.on("settings_changed", (m) => {
  applyAppearance(m.settings);
  cfg = { ...cfg, ...(m.settings?.notch || {}) };
  renderTiles();
  apply(mode);
});
client.on("state", (m) => setAgentState(m.state));
client.on("level", (m) => (level = Math.max(level, m.rms || 0)));
client.on("transcript", (m) => { liveTranscript.textContent = m.text ? `„${m.text}“` : ""; if (mode === "live") apply("live"); });
client.on("user_message", (m) => { if (!liveTranscript.textContent && m.source !== "notch") liveTranscript.textContent = `„${m.text}“`; liveText = ""; });
client.on("assistant_delta", (m) => { liveText += m.text; renderLiveAnswer(); tiles.ask?.delta?.(m.text); });
client.on("assistant_done", (m) => { liveText = m.text; renderLiveAnswer(); liveTool.textContent = ""; tiles.ask?.done?.(m.text); });
client.on("tool_start", (m) => {
  liveTool.replaceChildren(icon(TOOL_ICON[m.name] || "gear-six"), " ", String(m.label || m.name).replace(/^[^\p{L}\p{N}]+/u, ""));
  if (mode === "live") apply("live");
});
client.on("tool_end", (m) => { if (!m.ok) liveTool.append(h("span", { class: "fail" }, ` · ${m.summary}`)); });
client.on("brain", (m) => (brainLbl.textContent = m.provider));
client.on("confirm_request", (m) => {
  pendingConfirm = m.id;
  const answer = (ok: boolean) => { client.send("confirm_response", { id: m.id, approved: ok }); pendingConfirm = null; liveConfirm.replaceChildren(); apply(mode); };
  liveConfirm.replaceChildren(
    h("span", {}, icon("shield-warning", "ph-fill"), " ", String(m.description).replace(/^[^\p{L}\p{N}]+/u, "")),
    h("button", { class: "n-pill no", type: "button", onclick: () => answer(false) }, "Ne"),
    h("button", { class: "n-pill yes", type: "button", onclick: () => answer(true) }, "Ano"));
  setMode("live");
});
client.on("confirm_timeout", (m) => { if (pendingConfirm === m.id) { pendingConfirm = null; liveConfirm.replaceChildren(); settle(); } });
client.on("notify", (m) => {
  alertTitle.textContent = m.title;
  alertBody.textContent = m.body;
  if (mode === "idle" || mode === "alert") {
    setMode("alert");
    window.clearTimeout(alertTimer);
    alertTimer = window.setTimeout(() => mode === "alert" && settle(), 5000);
  }
});
client.on("media", (m) => { tiles.media?.update?.(m); updateActivity(); });
client.on("timers", (m) => { tiles.timers?.update?.(m.items); updateActivity(); });
client.on("shelf", (m) => tiles.shelf?.update?.(m.items));
client.on("*", (m) => { for (const t of Object.values(tiles)) t.on?.(m); });

// timers change whenever a tool touches them
client.on("tool_end", () => client.send("timers_get"));

if (demo) {
  document.documentElement.classList.add("demo");
  cfg.tiles = cfg.tiles;
  renderTiles();
  if (demo === "live") {
    liveTranscript.textContent = "„Pusť na YouTube trailer na Avengers“";
    liveTool.replaceChildren(icon("youtube-logo"), " Pouštím YouTube: Avengers trailer");
    liveText = "Pouštím **Avengers: Endgame**, oficiální trailer.";
    renderLiveAnswer();
    agentState = "speaking";
    level = 0.4;
    setInterval(() => (level = 0.15 + Math.random() * 0.25), 120);
  }
  if (demo === "alert") { alertTitle.textContent = "Časovač"; alertBody.textContent = "Pizza je hotová!"; }
  setMode(demo);
}
client.connect();
