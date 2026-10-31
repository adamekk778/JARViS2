import { applyAppearance } from "../shared/base";
import "./style.css";
import { Blob, type Mood } from "../character/blob";
import { h, icon, TOOL_ICON } from "../shared/dom";
import { renderMarkdown } from "../shared/markdown";
import { JarvisClient, localEndpoint } from "../shared/ws";
import { buildPanel } from "./panel";
import { configureSounds, panFor, play, setAnchorPan, setCustomSounds } from "../shared/sounds";
import { stopButton, type Task } from "../shared/taskcard";
import { notchOutline, regionSender } from "../shared/region";
import { radialActions, renderRadial, type UiAction } from "./radial";
import { brandEl, brandOf, BRANDS } from "../shared/brands";

/* Notch modes (spec §4):
   closed  black notch, eyes peeking from the bottom edge
   hover   woke up (mouse over)
   bar     character below the notch + chat / mic / settings buttons
   live    JARVIS is busy: character in its mood + speech bubble
   alert   short notification
   panel   the big panel
   radial  right-click on the character: a ring of actions around him (3.10)    */
type Mode = "closed" | "hover" | "bar" | "live" | "alert" | "panel" | "radial";

declare global {
  interface Window { pywebview?: { api: Record<string, (...a: any[]) => Promise<any>> } }
}

const params = new URLSearchParams(location.search);
const demo = params.get("demo") as Mode | null;
const demoMood = params.get("mood") as Mood | null;
const client = new JarvisClient(localEndpoint(), "notch", "notch");
window.addEventListener("pywebviewready", () => {
  document.documentElement.classList.add("native");
  Promise.resolve((window as any).pywebview?.api?.smooth?.()).then((on) => on && setAlpha(true)).catch(() => {});
});
// 3.1: the host made the window per-pixel transparent → paint only the shape, anti-aliased against the desktop
let regionPad = 0;
function setAlpha(on: boolean) {
  document.documentElement.classList.toggle("alpha", on);
  regionPad = on ? 2 : 0;
  syncRegion();
}
(window as any).__notchAlpha = setAlpha;
if (window.pywebview) document.documentElement.classList.add("native");

let cfg = { width: 200, height: 34, expanded_width: 1000, expanded_height: 410, open_delay_ms: 150, close_delay_ms: 400, linger_s: 6, monitor: 0, offset_x: 0,
  open_on: "hover", tuck_minutes: 10 };
let mode: Mode = "closed";
let coreMood: Mood = "idle";
let moodInfo: { badge?: number; progress?: number | null; detail?: string; reaction?: any; secondary?: any; ambient?: any } = {};
let hovering = false;
let pinned = false;      // the pin button (stays open, also after a restart)
let holding = false;     // you are writing in the panel's chat
let pendingConfirm: string | null = null;
let liveText = "";
let alertTimer = 0, lingerTimer = 0, openTimer = 0, closeTimer = 0, uiMoodTimer = 0;
let selAsk: any = null, selTimer = 0;   // 3.3 selected-text menu (Ctrl+Alt+E)
let uiMood: Mood | null = null; // opening / closing / dragged flashes
let activity = "";
let pinBtn: HTMLElement;
let task: Task | null = null;
let capturing = false;

// ---------- DOM ----------
const blob = new Blob({ size: 64 });
const blobBox = h("div", { class: "n-blob" }, blob.el);
const actText = h("span", { class: "act" });
const glow = h("div", { class: "n-glow", "aria-hidden": "true" });
const progressBar = h("b");
const progress = h("div", { class: "n-progress", "aria-hidden": "true" }, progressBar);
const clock = h("b");
const weatherText = h("span");
const barTop = h("div", { class: "bar-top" }, clock, weatherText);

const barLeft = h("div", { class: "bar-side l" },
  h("button", { class: "n-btn", type: "button", title: "Chat", "aria-label": "Chat", onclick: () => openPanel("chat") }, icon("chat-circle-dots")));
const barStop = stopButton(client, "sm");
const barRight = h("div", { class: "bar-side r" }, barStop,
  h("button", { class: "n-btn", type: "button", title: "Mluvit (Ctrl+Alt+Mezerník)", "aria-label": "Mluvit", onclick: () => client.send("push_to_talk") }, icon("microphone")),
  h("button", { class: "n-btn", type: "button", title: "Stark HUD (Ctrl+Alt+H)", "aria-label": "Stark HUD", onclick: () => openChat("hud") }, icon("circle-notch")),
  h("button", { class: "n-btn", type: "button", title: "Nastavení", "aria-label": "Nastavení", onclick: () => openPanel("settings") }, icon("gear-six")));

const bubbleState = h("div", { class: "b-state" });
const bubbleTranscript = h("div", { class: "b-transcript" });
const bubbleTool = h("div", { class: "b-tool" });
const bubbleAnswer = h("div", { class: "b-answer md" });
const bubbleConfirm = h("div", { class: "b-confirm" });
const bubbleTask = h("div", { class: "b-task" });
const liveStop = stopButton(client, "sm");
const bubble = h("div", { class: "n-bubble" }, bubbleState, bubbleTask, bubbleTranscript, bubbleTool, bubbleAnswer, bubbleConfirm);
const capChip = h("span", { class: "n-capture", hidden: true, title: "JARVIS se právě dívá na obrazovku" }, h("i", { class: "dot" }), "Vidím obrazovku");

const panel = buildPanel({
  client,
  openChat,
  pin: (v) => { holding = v; if (!v && !hovering) scheduleClose(); },
});
const panelHead = h("div", { class: "p-head" },
  h("span", { class: "p-title" }, "J A R V I S"), panel.dateEl,
  h("div", { class: "p-head-r" },
    h("button", { class: "p-icon", type: "button", title: "Nová konverzace", "aria-label": "Nová konverzace", onclick: () => client.send("new_chat") }, icon("note-pencil")),
    h("button", { class: "p-icon", type: "button", title: "Otevřít celý chat", "aria-label": "Otevřít celý chat", onclick: () => { openChat("full"); settle(true); } }, icon("arrows-out-simple")),
    (pinBtn = h("button", { class: "p-icon pin", type: "button", title: "Připnout (zůstane otevřený i po restartu)", "aria-label": "Připnout", onclick: () => setPinned(!pinned) }, icon("push-pin"))),
    h("button", { class: "p-icon", type: "button", title: "Zavřít", "aria-label": "Zavřít panel", onclick: () => { if (pinned) setPinned(false); settle(true); } }, icon("minus"))));
const panelWrap = h("div", { class: "n-panel" }, panelHead, panel.el);
function setPinned(v: boolean, save = true) {
  pinned = v;
  pinBtn.classList.toggle("on", v);
  if (save) client.send("settings_set", { patch: { notch: { pinned: v } } });
  if (!v) scheduleClose();
}

const alertTitle = h("strong");
const alertBody = h("span");
const alertBox = h("div", { class: "n-alert-text" }, alertTitle, alertBody);
const radialBox = h("div", { class: "n-radial", role: "menu", "aria-label": "Akce" });
// OMEGA P12.02: little bars at the right edge of the closed notch that move with the music (only while something plays)
const musicBars = h("div", { class: "n-music", "aria-hidden": "true" }, ...Array.from({ length: 7 }, () => h("i")));
let musicOff = 0;
// 3.11 island look: just two glowing eyes instead of the whole character, live info on the left and the right
const eyes = h("div", { class: "n-eyes", "aria-hidden": "true" }, h("i"), h("i"));
const lead = h("div", { class: "n-lead" });
const trail = h("div", { class: "n-trail" });
const volBar = h("div", { class: "n-vol", "aria-hidden": "true" }, h("b"));
const brandBadge = h("div", { class: "n-brand" });            // which AI answers, in the live bubble
const inner = h("div", { class: "n-inner" }, glow, panelWrap, barTop, radialBox, blobBox, eyes, lead, trail, volBar, brandBadge, actText, barLeft, barRight, bubble, alertBox, capChip, liveStop, progress, musicBars);
const shape = h("div", { class: "notch", "data-mode": "closed" }, inner);
document.getElementById("notch-root")!.append(shape);

// ---------- window size ----------
const PAD = 28; // keep in sync with desktop/host.py
async function resizeWindow(w: number, hh: number) {
  try { await window.pywebview?.api.resize(Math.round(w), Math.round(hh)); } catch { /* browser preview */ }
}
/** One window big enough for every mode. The window region is the visible shape, so the window itself never has
 *  to change size while the notch opens or closes – resizing it at the start and end of every animation made
 *  the notch jump. Same formula as notch_window_size() in desktop/host.py; changes only with the settings. */
/** Notch settings from the core. A panel narrower than 760 px has no room for its three columns: such a value
 *  (the old default was 600) means the default 1000 × 410, like notch_window_size() in desktop/host.py. */
function takeNotchSettings(n: any) {
  if (!n) return;
  cfg = { ...cfg, ...n };
  if (!(cfg.expanded_width >= 760)) { cfg.expanded_width = 1000; cfg.expanded_height = 410; }
}
function windowSize(): [number, number] {
  const w = Math.max(cfg.expanded_width || 1000, 560, Math.round(cfg.width * 1.1), Math.max(cfg.width, 300));
  const hh = Math.max(340, cfg.expanded_height || 390, Math.round(cfg.height * 1.15), cfg.height);
  return [w + PAD * 2, hh + PAD];
}
let windowKey = "";
function ensureWindow() {
  if (!window.pywebview?.api?.resize) return;
  const [w, hh] = windowSize();
  const key = `${w}x${hh}@${cfg.monitor}:${cfg.offset_x}`;   // monitor / offset: the host places the window again
  if (key === windowKey) return;
  windowKey = key;
  resizeWindow(w, hh).then(() => window.setTimeout(() => syncRegion(true), 30));
}
function openChat(view = "chat") {
  if (window.pywebview) window.pywebview.api.open_chat(view);
  else window.open(view === "full" ? "/chat" : view === "hud" ? "/hud" : `/#${view}`, "_blank");
}

function sizeFor(m: Mode): [number, number] {
  switch (m) {
    case "panel": return [cfg.expanded_width || 1000, Math.max(340, cfg.expanded_height || 390)];
    case "bar": return [400, 104];
    case "hover": return [Math.round(cfg.width * 1.1), Math.round(cfg.height * 1.15)];
    case "alert": return [440, 92];
    case "radial": return [340, 320];
    case "live": return [560, liveHeight()];
    default: {
      const kind = island() ? shape.dataset.island || "" : "";
      if (kind === "volume") return [Math.max(cfg.width, 420), cfg.height];
      return [activity || kind ? Math.max(cfg.width, island() ? 380 : 300) : cfg.width, cfg.height];
    }
  }
}
function liveHeight() {
  const kids = [...bubble.children].filter((c) => (c as HTMLElement).textContent) as HTMLElement[];
  const content = kids.reduce((s, k) => s + (k === bubbleAnswer ? Math.min(118, k.scrollHeight) : k.offsetHeight || 20), 0) + Math.max(0, kids.length - 1) * 4;
  return Math.max(96, Math.min(300, content + 34));
}

// ---------- shape animation (3.0.x): one spring drives the visible shape AND the window region in the same frame ----------
// The box (.notch) jumps to the bigger of the old/new size, the visible shape is a clip-path that springs from the
// old size to the new one, and the window region follows those exact numbers. Nothing is laid out per frame, so
// even the big panel opens and closes smoothly; after the animation the box and the window shrink to fit.
const sendRegion = regionSender();
const RADIUS: Record<string, number> = { closed: 18, hover: 18, bar: 26, live: 26, alert: 26, panel: 26, radial: 60 };
const S = { w: 200, h: 34, r: 18, vw: 0, vh: 0, vr: 0, tw: 200, th: 34, tr: 18, raf: 0, last: 0, grow: true };
let boxW = 0, boxH = 0;
const reducedMotion = () => document.documentElement.dataset.motion === "reduced" || matchMedia("(prefers-reduced-motion: reduce)").matches;

function paintShape() {
  shape.style.setProperty("--cw", `${S.w.toFixed(2)}px`);
  shape.style.setProperty("--ch", `${S.h.toFixed(2)}px`);
  shape.style.setProperty("--r", `${Math.max(0, S.r).toFixed(2)}px`);
  syncRegion();
}
function syncRegion(force = false) {
  if (!window.pywebview) return;
  const box = shape.getBoundingClientRect();
  const cx = box.left + box.width / 2;
  const r = { left: cx - S.w / 2, right: cx + S.w / 2, top: box.top, bottom: box.top + S.h } as DOMRect;
  sendRegion([notchOutline(r, Math.max(0, S.r), 14, window.devicePixelRatio || 1, regionPad)], force);
}
function setBox(w: number, hh: number) {
  if (w === boxW && hh === boxH) return;
  boxW = w; boxH = hh;
  shape.style.setProperty("--w", `${w}px`);
  shape.style.setProperty("--h", `${hh}px`);
}
function springStep(now: number) {
  const dt = Math.min(0.034, (now - S.last) / 1000 || 0.016);
  S.last = now;
  // growing: lively with a little overshoot; shrinking: quicker and without bounce
  const k = S.grow ? 340 : 520, c = S.grow ? 27 : 46;
  let moving = false;
  for (const [x, v, t] of [["w", "vw", "tw"], ["h", "vh", "th"], ["r", "vr", "tr"]] as const) {
    const a = k * (S[t] - S[x]) - c * S[v];
    S[v] += a * dt;
    S[x] += S[v] * dt;
    if (Math.abs(S[t] - S[x]) > 0.3 || Math.abs(S[v]) > 4) moving = true;
  }
  if (!moving) { S.w = S.tw; S.h = S.th; S.r = S.tr; S.vw = S.vh = S.vr = 0; }
  paintShape();
  if (moving) S.raf = requestAnimationFrame(springStep);
  else { S.raf = 0; settleBox(); }
}
function settleBox() {
  // after the animation the box fits the shape exactly (the window keeps its size, see windowSize)
  setBox(S.tw, S.th);
  syncRegion(true);
}
function animateShape(w: number, hh: number, r: number) {
  S.grow = w >= S.w && hh >= S.h;
  S.tw = w; S.th = hh; S.tr = r;
  // the box is never smaller than what is on screen during the move
  const bw = Math.max(w, Math.ceil(S.w)), bh = Math.max(hh, Math.ceil(S.h));
  ensureWindow();
  setBox(Math.max(bw, boxW), Math.max(bh, boxH));
  if (reducedMotion()) { S.w = w; S.h = hh; S.r = r; paintShape(); settleBox(); return; }
  if (!S.raf) { S.last = performance.now(); S.raf = requestAnimationFrame(springStep); }
}
window.addEventListener("pywebviewready", () => { ensureWindow(); syncRegion(); window.setTimeout(() => syncRegion(true), 500); });
window.addEventListener("resize", () => window.setTimeout(syncRegion, 30));
// keep the region honest: if Windows ever drops it (DPI change, display change, a failed first send), it comes
// back within 2 s – sent even unchanged, the host only re-applies it when it is really missing
window.setInterval(() => { if (!S.raf) syncRegion(true); }, 2000);

/** Ask Windows where the cursor really is (WebView2 can fire mouseleave when the window moves under a still cursor). */
async function cursorInside(): Promise<boolean> {
  try { return !!(await window.pywebview?.api.cursor_inside?.()); } catch { return false; }
}

function apply(m: Mode) {
  const [w, hh] = sizeFor(m);
  shape.dataset.mode = m;
  animateShape(w, hh, RADIUS[m] ?? 26);
  updateBlob();
}

function setMode(m: Mode) {
  if (demo) m = demo;
  const prev = mode;
  mode = m;
  // little transition moods (opening / closing) like the reference frames 4 and 6
  if ((m === "bar" || m === "panel") && (prev === "closed" || prev === "hover")) flashUi("opening", 420);
  if (m === "closed" && (prev === "bar" || prev === "panel" || prev === "hover")) flashUi("closing", 450);
  apply(m);
}

function flashUi(mood: Mood, ms: number) {
  uiMood = mood;
  window.clearTimeout(uiMoodTimer);
  uiMoodTimer = window.setTimeout(() => { uiMood = null; updateBlob(); }, ms);
}

/** Which mood the character shows: core mood, layered with UI-only moods (spec §3). */
function displayMood(): Mood {
  if (demoMood) return demoMood;
  if (dict.state === "listening") return "listening";
  if (dict.state === "transcribing") return "thinking";
  const calm = coreMood === "idle" || coreMood === "sleeping";
  if (uiMood && calm) return uiMood;
  if (mode === "closed") return calm ? (coreMood === "sleeping" ? "sleeping" : "closed") : coreMood;
  if (mode === "hover" && calm) return "hover";
  if (mode === "bar" && calm) return "expanded";
  return coreMood;
}
function updateBlob() {
  blob.setMood(displayMood(), { badge: moodInfo.badge, progress: moodInfo.progress ?? null, reaction: moodInfo.reaction,
    secondary: moodInfo.secondary ?? null, ambient: moodInfo.ambient });
  shape.dataset.mood = displayMood();
}

/** JARVIS itself is doing something (STOP makes sense). */
function jarvisBusy() {
  return ["listening", "thinking", "working", "speaking", "waiting"].includes(coreMood) || !!pendingConfirm;
}
/** Something needs the live bubble open: JARVIS at work or Claude Code waiting for an answer. */
function busy() {
  return jarvisBusy() || claudeAsks.length > 0 || !!selAsk;
}

function settle(force = false) {
  if (!force && (pinned || holding || dragging)) return;
  if (busy() && mode !== "panel") return setMode("live");
  if (mode === "panel" && !force && hovering) return;
  if (hovering && !force) return setMode("bar");
  setMode("closed");
}

function scheduleClose() {
  window.clearTimeout(closeTimer);
  closeTimer = window.setTimeout(async () => {
    if (hovering || pinned || holding) return;
    if (window.pywebview && await cursorInside()) { scheduleClose(); return; }
    if (busy()) setMode("live");
    else settle(true);
  }, cfg.close_delay_ms);
}

function openPanel(section?: Parameters<typeof panel.show>[0]) {
  setMode("panel");
  panel.show(section || panel.section);
  client.send("mood_set", { clear: "notify" });
}

// ---------- mouse ----------
let leaveCheck = 0;
shape.addEventListener("mouseenter", () => {
  window.clearTimeout(leaveCheck);
  hovering = true;
  window.clearTimeout(closeTimer);
  window.clearTimeout(openTimer);
  stir();
  if (mode === "closed" || mode === "alert") {
    // straight from the closed notch to the bar: no half-open step in between; OMEGA 092: locked = only wakes up, a click opens it
    const next: Mode = cfg.open_on === "click" ? "hover" : "bar";
    openTimer = window.setTimeout(() => hovering && (mode === "closed" || mode === "alert") && setMode(next), cfg.open_delay_ms);
  }
});
function leave() {
  hovering = false;
  window.clearTimeout(openTimer);
  if (mode === "bar" || mode === "hover" || mode === "panel" || mode === "radial") scheduleClose();
}
shape.addEventListener("click", (e) => {
  if (cfg.open_on === "click" && (mode === "hover" || mode === "closed") && !(e.target as HTMLElement).closest(".n-blob")) setMode("bar");
});
shape.addEventListener("mouseleave", async () => {
  if (window.pywebview && await cursorInside()) {
    // spurious leave: keep it open and keep checking until the cursor really goes away
    const recheck = async () => { if (await cursorInside()) leaveCheck = window.setTimeout(recheck, 300); else leave(); };
    window.clearTimeout(leaveCheck);
    leaveCheck = window.setTimeout(recheck, 300);
    return;
  }
  leave();
});
blobBox.addEventListener("click", () => {
  if (justDragged) return;
  if (mode === "radial") { settle(true); return; }
  const poked = blob.poke();      // 3 quick pokes annoy him, 6 make his head spin
  if (poked) { flashUi(poked, poked === "dizzy" ? 3200 : 1600); updateBlob(); return; }
  if (mode === "panel") { if (pinned) setPinned(false); settle(true); }
  else openPanel("chat");
});

// 3.1: the character always stays in the notch (the desktop pet was removed)
const dragging = false, justDragged = false;

// files dropped on the notch go to the shelf (or to the chat when the chat is visible)
let dragDepth = 0;
window.addEventListener("dragenter", (e) => {
  if (!e.dataTransfer?.types.includes("Files")) return;
  dragDepth++;
  shape.classList.add("dropping");
  if (mode !== "panel") openPanel("files");
});
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; shape.classList.remove("dropping"); } });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", async (e) => {
  if ((e.target as HTMLElement).closest(".chat")) return; // ChatView handles its own drop
  e.preventDefault();
  dragDepth = 0;
  shape.classList.remove("dropping");
  for (const f of [...(e.dataTransfer?.files || [])]) client.send("shelf_add", { attachment_id: (await client.upload(f, f.name)).id });
});
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && mode === "panel") { if (pinned) setPinned(false); settle(true); }
  if (e.key === "Escape" && mode === "radial") settle(true);
});

// ---------- 3.10: the ring of actions (OMEGA 751) for the app in front (089) and the moment (094) ----------
let appCtx: { app: string; actions: UiAction[]; suggestions?: UiAction[] } = { app: "", actions: [] };
function paintRadial() {
  renderRadial(radialBox, radialActions(appCtx.actions || [], appCtx.suggestions || []), appCtx.app, runAction);
}
function openRadial() {
  client.send("notch_context_get");
  paintRadial();
  setMode("radial");
}
function runAction(a: UiAction) {
  if (a.text) client.send("user_text", { text: a.text, attachments: [] });
  else if (a.quick) client.send("quick_action", { action: a.quick, args: a.args || {} });
  else if (a.pin) client.send("pin_done", { id: a.pin });
  else if (a.open === "talk") client.send("push_to_talk");
  else if (a.open === "play") openChat("play");
  else if (a.open === "chat" || a.open === "workspaces" || a.open === "settings") { openPanel(a.open); return; }
  settle(true);
}
blobBox.addEventListener("contextmenu", (e) => { e.preventDefault(); if (mode === "radial") settle(true); else openRadial(); });
client.on("app_context", (m) => {
  appCtx = { app: m.app || "", actions: m.actions || [], suggestions: m.suggestions ?? appCtx.suggestions };
  if (mode === "radial") paintRadial();
});

// ---------- 3.10: after a long quiet spell he hides behind the edge and now and then peeks out (OMEGA 078) ----------
let lastStir = Date.now();
function stir() {
  lastStir = Date.now();
  shape.classList.remove("tucked", "peek");
}
window.setInterval(() => {
  const quiet = mode === "closed" && (coreMood === "idle" || coreMood === "sleeping") && !activity;
  if (!quiet || !cfg.tuck_minutes) { if (shape.classList.contains("tucked")) stir(); return; }
  if (Date.now() - lastStir < cfg.tuck_minutes * 60000) return;
  shape.classList.add("tucked");
  if (!shape.classList.contains("peek") && Math.random() < 0.08) {
    shape.classList.add("peek");
    blob.face(Math.random() < 0.5 ? -0.8 : 0.8, 0.4);
    window.setTimeout(() => { shape.classList.remove("peek"); blob.face(0, 0); }, 2600);
  }
}, 5000);

// ---------- live bubble ----------
const STATE_LABEL: Partial<Record<Mood, string>> = { listening: "Poslouchám…", thinking: "Přemýšlím…", working: "Pracuji…", waiting: "Potřebuji potvrzení" };
function renderLive() {
  bubbleState.textContent = selAsk ? `Označený text${selAsk.app ? " · " + selAsk.app : ""} – co s ním?`
    : claudeAsks.length && !pendingConfirm ? `Claude Code · ${claudeAsks[0].project} čeká na tebe` : STATE_LABEL[coreMood] ?? "";
  const activeTask = task && ["running", "paused", "waiting"].includes(task.status) ? task : null;
  if (activeTask && activeTask.total) {
    const cur = activeTask.steps.find((s) => s.status === "running") || activeTask.steps[Math.min(activeTask.done, activeTask.total - 1)];
    bubbleTask.replaceChildren(icon("list-checks"), ` Krok ${Math.min(activeTask.done + 1, activeTask.total)}/${activeTask.total}`,
      cur ? h("span", { class: "muted" }, ` · ${cur.title}`) : "", activeTask.status === "paused" ? h("span", { class: "muted" }, " (pozastaveno)") : "");
  } else bubbleTask.replaceChildren();
  liveStop.hidden = !jarvisBusy();
  barStop.hidden = !jarvisBusy();
  const text = liveText.length > 600 ? "…" + liveText.slice(-600) : liveText;
  bubbleAnswer.innerHTML = text ? renderMarkdown(text) : "";
  bubbleAnswer.scrollTop = bubbleAnswer.scrollHeight;
  if (mode === "live") apply("live");
}

function onMood(m: any) {
  const prev = coreMood;
  if (m.mood !== "idle" && m.mood !== "sleeping") stir();
  coreMood = m.mood;
  moodInfo = m;
  if (m.mood !== prev) {
    if (m.mood === "listening") play(prev === "idle" || prev === "sleeping" || prev === "closed" ? "wake" : "listen");
    else if (m.mood === "error" || m.mood === "limit") play("error");
  }
  if (m.mood === "listening" && prev !== "listening") {
    liveText = "";
    bubbleTranscript.textContent = "";
    bubbleTool.textContent = "";
  }
  if ((m.mood === "error" || m.mood === "limit") && m.detail && mode !== "panel" && mode !== "live") {
    showAlert(m.mood === "limit" ? "Dosažen limit" : "Něco se nepovedlo", m.mood === "limit"
      ? "Všichni AI poskytovatelé teď hlásí limit. Počkej chvilku nebo přidej dalšího v Nastavení → Mozek." : m.detail);
  }
  if (busy()) {
    window.clearTimeout(lingerTimer);
    if (mode !== "panel") setMode("live");
  } else if (mode === "live") {
    window.clearTimeout(lingerTimer);
    lingerTimer = window.setTimeout(() => { if (!busy()) settle(); }, (liveText ? cfg.linger_s : 1.2) * 1000);
  }
  renderLive();
  updateBlob();
}

function showAlert(title: string, body: string) {
  alertTitle.textContent = title;
  alertBody.textContent = body;
  if (mode === "closed" || mode === "alert" || mode === "hover") {
    setMode("alert");
    window.clearTimeout(alertTimer);
    alertTimer = window.setTimeout(() => mode === "alert" && settle(), 5000);
  }
}

// ---------- a new version waits (3.0): JARVIS turns blue and the capsule says so ----------
let upd: any = null;
let charColor: [any, string | undefined] = ["black", undefined];
function paintUpdate() {
  const waiting = upd?.available && upd.state !== "error";
  if (waiting) blob.setColor("blue", charColor[1]);
  else blob.setColor(charColor[0], charColor[1]);
}

// ---------- Claude Code (3.0): live step in the capsule, Allow / Deny in the live bubble ----------
let claudeSessions: any[] = [];
let claudeAsks: any[] = [];
function renderClaudeAsk() {
  const a = claudeAsks[0];
  if (!a) { if (!pendingConfirm) bubbleConfirm.replaceChildren(); return; }
  if (pendingConfirm) return;      // JARVIS's own question first
  const answer = (decision: string) => { client.send("claude_decision", { id: a.id, decision }); };
  bubbleState.textContent = `Claude Code · ${a.project} čeká na tebe`;
  bubbleConfirm.replaceChildren(
    h("span", { title: (a.details || []).join("\n") }, icon("terminal-window", "ph-fill"), " ", String(a.label)),
    h("button", { class: "n-pill no", type: "button", onclick: () => answer("deny") }, "Zamítnout"),
    h("button", { class: "n-pill", type: "button", title: `Vždy povolit ${a.tool}`, onclick: () => answer("always") }, "Vždy"),
    h("button", { class: "n-pill yes", type: "button", onclick: () => answer("allow") }, "Povolit"));
  if (mode !== "panel") setMode("live");
}
function claudeActivity(): boolean {
  const s = claudeSessions.find((x) => x.state === "working" || x.state === "thinking" || x.state === "waiting");
  if (!s) return false;
  activity = s.step || "Claude Code";
  actText.replaceChildren(icon("terminal-window"), " ", s.state === "waiting" ? `${s.project} · čeká` : activity);
  return true;
}

// ---------- 3.3 selected text anywhere (Ctrl+Alt+E): fix, translate, explain… ----------
function closeSelection() {
  selAsk = null;
  window.clearTimeout(selTimer);
  bubbleConfirm.replaceChildren();
  bubbleTranscript.textContent = "";
  renderLive();
  if (!busy()) settle();
}
client.on("selection", (m) => {
  if (!m.text) return;
  selAsk = m;
  liveText = "";
  bubbleTool.textContent = "";
  const short = m.text.length > 150 ? m.text.slice(0, 150) + "…" : m.text;
  bubbleTranscript.textContent = `„${short.replace(/\s+/g, " ")}“`;
  // OMEGA 759: the data lens – money, units, dates, numbers, IČO / IBAN at a glance, before any AI
  const lensRow = (m.lens || []).length ? h("div", { class: "n-lens" }, ...(m.lens as any[]).slice(0, 4).map((l) =>
    h("span", { class: "n-lens-chip", title: l.note || l.kind }, l.color ? h("i", { class: "sw", style: `background:${l.color}` }) : "", h("b", {}, l.text), ` ${l.value}`))) : "";
  bubbleConfirm.replaceChildren(lensRow,
    ...(m.actions || []).map((a: any) => h("button", { class: `n-pill ${a.replace ? "yes" : ""}`, type: "button",
      title: a.replace ? "Výsledek se vloží místo označeného textu" : "Výsledek ukážu tady",
      onclick: () => {
        client.send("selection_action", { action: a.key });
        bubbleConfirm.replaceChildren(h("span", { class: "muted" }, `${a.label}…`));
        window.clearTimeout(selTimer);
      } }, a.label)),
    h("button", { class: "n-pill no", type: "button", "aria-label": "Zavřít", onclick: closeSelection }, icon("x")));
  play("listen");
  renderLive();
  if (mode !== "panel") setMode("live");
  window.clearTimeout(selTimer);
  selTimer = window.setTimeout(closeSelection, 25000);
});
client.on("selection_result", (m) => {
  selAsk = null;
  window.clearTimeout(selTimer);
  bubbleConfirm.replaceChildren();
  bubbleTranscript.textContent = "";
  if (!m.ok) { renderLive(); showAlert("Označený text", m.text); play("error"); return; }
  play("done");
  if (m.replaced) { renderLive(); settle(); showAlert(m.label, "Hotovo – text jsem nahradil."); return; }
  liveText = m.text;
  renderLive();
  if (mode !== "panel") setMode("live");
  window.clearTimeout(lingerTimer);
  lingerTimer = window.setTimeout(() => { if (!busy()) settle(); }, Math.max(cfg.linger_s, 12) * 1000);
});

// ---------- activity (closed notch) ----------
let timers: any[] = [];
let media: any = {};
// dictation anywhere: listening (with a level meter), transcribing, then a short "pasted" note
let dict: { state: string; level: number; text: string; until: number } = { state: "idle", level: 0, text: "", until: 0 };
const dictBars = h("span", { class: "dbars" }, ...Array.from({ length: 5 }, () => h("i")));
function dictActivity(): boolean {
  if (dict.state === "listening") {
    const lv = dict.level;
    [...dictBars.children].forEach((b, i) => ((b as HTMLElement).style.transform = `scaleY(${Math.max(0.2, Math.min(1, lv * (1.6 - Math.abs(i - 2) * 0.35)))})`));
    activity = "Poslouchám";
    actText.replaceChildren(dictBars, " ", dict.text || "Poslouchám");
    return true;
  }
  if (dict.state === "transcribing") {
    activity = "Přepisuji";
    actText.replaceChildren(icon("waveform"), " Přepisuji…");
    return true;
  }
  if (dict.until > Date.now()) {
    activity = dict.text;
    actText.replaceChildren(icon(dict.state === "done" ? "check" : "x"), " ", dict.text);
    return true;
  }
  return false;
}
function island() { return document.documentElement.dataset.nstyle !== "mochi"; }
/** A ring that empties as the timer runs (the focus timer in the closed island). */
function ring(frac: number) {
  const c = 2 * Math.PI * 7;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 18 18");
  svg.setAttribute("class", "n-ring");
  svg.innerHTML = `<circle cx="9" cy="9" r="7" fill="none" stroke="currentColor" stroke-opacity=".25" stroke-width="2.5"/>`
    + `<circle cx="9" cy="9" r="7" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" `
    + `stroke-dasharray="${c.toFixed(2)}" stroke-dashoffset="${(c * (1 - Math.max(0, Math.min(1, frac)))).toFixed(2)}" transform="rotate(-90 9 9)"/>`;
  return svg;
}
const CLAUDE_SHORT: Record<string, string> = { working: "Pracuje", thinking: "Přemýšlí", waiting: "Čeká na tebe" };
const AI_WORD: Record<string, string> = { listening: "Poslouchá", thinking: "Přemýšlí", working: "Pracuje", speaking: "Mluví", waiting: "Čeká na tebe" };
// the AI that answers now (the core says which provider + model once the first words arrive)
let brain: { provider: string; model: string } | null = null;
const team = new Map<string, { icon: string; name: string; since: number }>();   // specialists at work right now
client.on("agent_activity", (m) => {
  if (m.state === "start") team.set(m.key, { icon: m.icon || "robot", name: m.name, since: team.get(m.key)?.since || Date.now() });
  if (m.state === "done") team.delete(m.key);
  updateActivity();
});
let vol: { level: number; muted: boolean } | null = null, volUntil = 0;
client.on("brain", (m) => { brain = { provider: m.provider || "", model: m.model || "" }; renderBrand(); updateActivity(); });
client.on("volume", (m) => {
  vol = { level: Number(m.level) || 0, muted: !!m.muted };
  volUntil = Date.now() + 1600;
  updateActivity();
  window.setTimeout(updateActivity, 1700);
});
function renderBrand() {
  if (!brain || !jarvisBusy()) { brandBadge.replaceChildren(); return; }
  const b = brandOf(brain.provider, brain.model);
  brandBadge.replaceChildren(brandEl(b), h("span", {}, b.name));
  shape.style.setProperty("--brand", b.color);
}
/** What the closed island shows on its left and right (the same priority as the activity text). */
function islandActivity(t: any) {
  let kind = "", l: (Node | string)[] = [], r: (Node | string)[] = [];
  const cc = claudeSessions.find((x) => ["working", "thinking", "waiting"].includes(x.state));
  if (vol && Date.now() < volUntil) {
    kind = "volume";
    l = [icon(vol.muted || vol.level === 0 ? "speaker-slash" : vol.level < 34 ? "speaker-low" : "speaker-high", "ph-fill")];
    (volBar.firstChild as HTMLElement).style.width = `${vol.muted ? 0 : vol.level}%`;
  } else if (team.size) {
    const all = [...team.values()];
    const secs = Math.round((Date.now() - Math.min(...all.map((a) => a.since))) / 1000);
    kind = "team";
    l = [h("span", { class: "n-team" }, ...all.slice(0, 4).map((a) => h("i", { title: a.name }, icon(a.icon, "ph-fill")))),
         h("span", {}, all.length === 1 ? all[0].name : `Tým · ${all.length}`)];
    r = [`${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`];
  } else if (jarvisBusy() && brain && coreMood !== "listening") {
    const b = brandOf(brain.provider, brain.model);
    kind = "ai"; l = [brandEl(b), h("span", {}, AI_WORD[coreMood] || "Pracuje")]; r = [b.name];
    shape.style.setProperty("--brand", b.color);
  } else if (dict.state === "listening" || dict.state === "transcribing") {
    kind = "dict"; l = [icon("microphone", "ph-fill"), h("span", {}, dict.state === "listening" ? "Poslouchám" : "Přepisuji")]; r = [dictBars];
  } else if (cc) {
    const secs = Math.max(0, Math.round(Date.now() / 1000 - (cc.started || Date.now() / 1000)));
    kind = "claude"; l = [brandEl(BRANDS.claude), h("span", {}, CLAUDE_SHORT[cc.state] || "Pracuje")];
    shape.style.setProperty("--brand", BRANDS.claude.color);
    r = [`${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`];
  } else if (timers.length) {
    const tm = timers[0], left = Math.max(0, Math.round(tm.ends_at - Date.now() / 1000));
    kind = "focus"; l = [ring(tm.seconds ? left / tm.seconds : 1)]; r = [`${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`];
  } else if (t && t.total) {
    kind = "task"; l = [icon("list-checks"), h("span", {}, `Krok ${Math.min(t.done + 1, t.total)}/${t.total}`)];
    r = [`${Math.round((t.done / t.total) * 100)} %`];
  } else if (upd?.available && upd.state !== "error") {
    kind = "update"; l = [icon("arrow-circle-up"), h("span", {}, upd.state === "downloading" ? "Stahuji" : `Verze ${upd.latest}`)];
    r = upd.state === "downloading" ? [`${Math.round((upd.progress || 0) * 100)} %`] : [];
  } else if (media?.playing && media.title) {
    kind = "music"; l = [media.thumb ? h("img", { class: "n-art", src: media.thumb, alt: "" }) : h("span", { class: "n-art" }, icon("music-notes", "ph-fill"))];
  }
  lead.replaceChildren(...l);
  trail.replaceChildren(...r);
  shape.dataset.island = kind;
}
function updateActivity() {
  const t = task && ["running", "paused", "waiting"].includes(task.status) ? task : null;
  shape.classList.toggle("has-task", !!(t && t.total));
  progressBar.style.width = t && t.total ? `${Math.round((t.done / t.total) * 100)}%` : "0";
  const now = new Date();
  clock.textContent = now.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  if (!weatherText.dataset.w) weatherText.textContent = now.toLocaleDateString("cs-CZ", { weekday: "short", day: "numeric", month: "numeric" });
  if (dictActivity()) {
    // dictation wins while it runs
  } else if (claudeActivity()) {
    // a Claude Code session at work
  } else if (timers.length) {
    const r = Math.max(0, Math.round(timers[0].ends_at - Date.now() / 1000));
    activity = `${Math.floor(r / 60)}:${String(r % 60).padStart(2, "0")}`;
    actText.replaceChildren(icon("timer"), " ", activity);
  } else if (t && t.total) {
    activity = `Krok ${Math.min(t.done + 1, t.total)}/${t.total}`;
    actText.replaceChildren(icon("list-checks"), " ", activity);
  } else if (upd?.available && upd.state !== "error") {
    activity = upd.state === "downloading" ? `Stahuji ${Math.round((upd.progress || 0) * 100)} %` : `Nová verze ${upd.latest}`;
    actText.replaceChildren(icon("arrow-circle-up"), " ", activity);
  } else if (media?.playing && media.title) {
    activity = media.title;
    actText.replaceChildren(icon("music-notes"), " ", activity);
  } else {
    activity = "";
    actText.replaceChildren();
  }
  islandActivity(t);
  shape.classList.toggle("has-act", !!activity);
  if (mode === "closed") apply("closed");
}
setInterval(updateActivity, 1000);

// ---------- server events ----------
client.onStatus((s) => { if (s !== "open") { coreMood = "offline"; updateBlob(); } });
client.on("welcome", (m) => {
  applyAppearance(m.settings);
  configureSounds(m.settings?.appearance);
  task = m.task || null;
  takeNotchSettings(m.settings?.notch);
  document.documentElement.dataset.nstyle = m.settings?.notch?.style || "island";
  const ch = m.settings?.character;
  if (ch) { charColor = [ch.color, ch.glow || undefined]; blob.setColor(ch.color, ch.glow || undefined); blob.setOutfit(ch.outfit); blob.setCharacter(ch); }
  upd = m.update;
  paintUpdate();
  media = m.media || {};
  timers = m.timers || [];
  pendingConfirm = m.pending_confirm || null;
  claudeSessions = m.claude_sessions || [];
  setCustomSounds(m.sounds);
  claudeAsks = m.claude_pending || [];
  onMood(m.mood || { mood: m.busy ? "thinking" : "idle" });
  renderClaudeAsk();
  ensureWindow();
  if (m.settings?.notch?.pinned) { setPinned(true, false); openPanel(); } else settle();
});
client.on("settings_changed", (m) => {
  applyAppearance(m.settings);
  configureSounds(m.settings?.appearance);
  const ch = m.settings?.character;
  if (ch) { charColor = [ch.color, ch.glow || undefined]; paintUpdate(); blob.setOutfit(ch.outfit); blob.setCharacter(ch); }
  if (m.settings?.notch) {        // every size and timing setting takes effect right away, without a restart
    takeNotchSettings(m.settings.notch);
    document.documentElement.dataset.nstyle = m.settings.notch.style || "island";
    ensureWindow();
    apply(mode);
  }

});
client.on("mood", onMood);
client.on("mood", () => renderBrand());
client.on("level", (m) => blob.setLevel(m.rms || 0));
// OMEGA 083: something goes to the phone (flies off to the right) or comes from it (flies into the notch)
const HANDOFF_ICON: Record<string, string> = { link: "link", text: "text-aa", file: "file", url: "link", mochi: "smiley", photo: "image" };
client.on("handoff", (m) => {
  const chip = h("div", { class: `n-handoff ${m.to === "phone" ? "out" : "in"}` }, icon(HANDOFF_ICON[m.kind] || "paper-plane-tilt"), h("span", {}, String(m.label || "")));
  inner.append(chip);
  flashUi(m.to === "phone" ? "success" : "notify", 1200);
  play(m.to === "phone" ? "done" : "notify", panFor("phone"));
  window.setTimeout(() => chip.remove(), 1500);
});
// OMEGA 195: Mochi went to the phone – an empty seat and a way to call him back
const away = h("button", { class: "n-away", type: "button", title: "Mochi je na telefonu – klikni a vrátí se", "aria-label": "Vrátit Mochiho na PC",
  onclick: (e: Event) => { e.stopPropagation(); client.send("mochi_move", { to: "pc" }); } }, icon("device-mobile"));
blobBox.append(away);
client.on("mochi_where", (m) => { shape.classList.toggle("mochi-away", m.at === "phone"); });
// OMEGA 752 / 084: JARVIS works in a window → the notch moved above it; sounds come from that side
client.on("anchor", (m) => { setAnchorPan(m.cx ?? null); shape.classList.toggle("anchored", m.cx != null); });
// OMEGA 079: each specialist agent splits off as a little Mochi next to the big one and merges back when done
const minis = new Map<string, HTMLElement>();
client.on("agent_activity", (m) => {
  let el = minis.get(m.key);
  if (m.state === "start" && !el) {
    el = h("div", { class: "n-mini", title: m.name }, h("i"), h("i"));
    el.style.setProperty("--k", String(minis.size));
    blobBox.append(el);
    minis.set(m.key, el);
  }
  if (el && m.state === "tool") { el.classList.remove("hop"); void el.offsetWidth; el.classList.add("hop"); }
  if (el && m.state === "done") {
    el.classList.add("merge");
    const key = m.key;
    window.setTimeout(() => { minis.get(key)?.remove(); minis.delete(key); }, 700);
  }
});
blobBox.addEventListener("dblclick", (e) => {      // a playful split into three and back
  e.preventDefault();
  const trio = [0, 1, 2].map((k) => { const x = h("div", { class: "n-mini play" }, h("i"), h("i")); x.style.setProperty("--k", String(k)); return x; });
  blobBox.append(...trio);
  flashUi("joy", 1600);
  window.setTimeout(() => trio.forEach((x) => x.classList.add("merge")), 1100);
  window.setTimeout(() => trio.forEach((x) => x.remove()), 1800);
});
// OMEGA 247: after a long quiet spell Mochi runs along the screen edge for a few seconds (click = he jumps and hides)
let edgePlay = true;
let lastNudge = Date.now();
["pointermove", "keydown"].forEach((ev) => window.addEventListener(ev, () => { lastNudge = Date.now(); }, { passive: true }));
window.setInterval(() => {
  if (!edgePlay || mode !== "closed" || busy() || document.documentElement.dataset.focus === "1" || document.documentElement.dataset.motion === "reduced") return;
  if (Date.now() - lastNudge < 8 * 60_000 || shape.classList.contains("edge-play")) return;
  lastNudge = Date.now();
  shape.classList.add("edge-play");
  window.setTimeout(() => shape.classList.remove("edge-play"), 7000);
}, 20_000);
blobBox.addEventListener("pointerdown", () => { if (shape.classList.contains("edge-play")) { shape.classList.remove("edge-play"); flashUi("joy", 900); } });
client.on("settings_changed", (m) => { edgePlay = m.settings?.notch?.edge_play !== false; });

client.on("focus", (m) => { document.documentElement.dataset.focus = m.active ? "1" : ""; });   // OMEGA 234: quieter, see-through notch
client.on("music_level", (m) => {
  const b: number[] = Array.isArray(m.bars) ? m.bars : [];
  const on = b.some((v) => v > 0.05);
  musicBars.classList.toggle("on", on);
  [...musicBars.children].forEach((el, i) => { (el as HTMLElement).style.transform = `scaleY(${Math.max(0.08, b[i] || 0)})`; });
  window.clearTimeout(musicOff);
  if (on) musicOff = window.setTimeout(() => musicBars.classList.remove("on"), 1500);
});
client.on("transcript", (m) => { bubbleTranscript.textContent = m.text ? `„${m.text}“` : ""; renderLive(); });
client.on("user_message", (m) => { if (m.source !== "notch") bubbleTranscript.textContent = m.text ? `„${m.text}“` : ""; liveText = ""; renderLive(); });
client.on("assistant_delta", (m) => { liveText += m.text; renderLive(); });
client.on("assistant_done", (m) => { liveText = m.text; bubbleTool.textContent = ""; renderLive(); client.send("timers_get"); });
client.on("tool_start", (m) => {
  bubbleTool.replaceChildren(icon(TOOL_ICON[m.name] || "gear-six"), " ", String(m.label || m.name));
  renderLive();
});
client.on("tool_end", (m) => { if (!m.ok) bubbleTool.append(h("span", { class: "fail" }, ` · ${m.summary}`)); });
client.on("confirm_request", (m) => {
  pendingConfirm = m.id;
  const answer = (ok: boolean) => { client.send("confirm_response", { id: m.id, approved: ok }); pendingConfirm = null; bubbleConfirm.replaceChildren(); renderLive(); };
  bubbleConfirm.replaceChildren(
    h("span", {}, icon("shield-warning", "ph-fill"), " ", String(m.description),
      (m.details || []).length ? h("span", { class: "muted", title: (m.details as string[]).join("\n") }, ` (${(m.details as string[]).length}× – detail v panelu)`) : ""),
    h("button", { class: "n-pill no", type: "button", onclick: () => answer(false) }, "Ne"),
    h("button", { class: "n-pill yes", type: "button", onclick: () => answer(true) }, "Ano"));
  if (mode !== "panel") setMode("live");
  renderLive();
});
client.on("confirm_resolved", (m) => { if (pendingConfirm === m.id) { pendingConfirm = null; bubbleConfirm.replaceChildren(); renderClaudeAsk(); renderLive(); if (!busy()) settle(); } });
client.on("confirm_timeout", (m) => { if (pendingConfirm === m.id) { pendingConfirm = null; bubbleConfirm.replaceChildren(); settle(); } });
client.on("notify", (m) => { showAlert(m.title, m.body); play("notify", panFor(m.target === "mobile" ? "phone" : /mail|e-mail/i.test(m.title || "") ? "mail" : /telefon/i.test(m.title || "") ? "phone" : "notch")); });
client.on("sounds", (m) => setCustomSounds(m.files));
client.on("update_status", (m) => { upd = m; paintUpdate(); updateActivity(); });
client.on("claude_sessions", (m) => { claudeSessions = m.items || []; updateActivity(); });
client.on("claude_permission", (m) => { claudeAsks.push(m); play("notify"); renderClaudeAsk(); renderLive(); });
client.on("claude_permission_resolved", (m) => {
  claudeAsks = claudeAsks.filter((a) => a.id !== m.id);
  renderClaudeAsk();
  renderLive();
  if (!busy()) settle();
});
client.on("task_update", (m) => {
  const prevStatus = task?.id === m.task?.id ? task?.status : null;
  task = m.task;
  updateActivity();
  if (prevStatus && prevStatus !== "done" && task?.status === "done" && (task?.total || 0) > 1) play("done");
  renderLive();
});
client.on("screen_capture", (m) => {
  capturing = !!m.active;
  capChip.hidden = !capturing;
  shape.classList.toggle("capturing", capturing);
});
client.on("stopped", () => { task = null; pendingConfirm = null; bubbleConfirm.replaceChildren(); renderLive(); showAlert("Zastaveno", "Všechno jsem zastavil."); });
client.on("media", (m) => { media = m; updateActivity(); });
client.on("dictation", (m) => {
  const was = dict.state;
  if (m.state === "listening") dict = { state: "listening", level: m.level ?? 0, text: m.hands_free ? "Diktuji · ťukni pro vložení" : "Poslouchám", until: 0 };
  else if (m.state === "transcribing") dict = { ...dict, state: "transcribing" };
  else if (m.state === "done") dict = { state: "done", level: 0, text: `Vloženo · ${m.words} ${m.words === 1 ? "slovo" : m.words < 5 ? "slova" : "slov"}`, until: Date.now() + 2500 };
  else if (m.state === "error" || (m.state === "cancelled" && m.message)) dict = { state: "error", level: 0, text: m.message || "Zrušeno", until: Date.now() + 3000 };
  else dict = { state: "idle", level: 0, text: "", until: 0 };
  if (was !== dict.state) { updateBlob(); if (dict.state === "listening") play("listen"); else if (dict.state === "done") play("done"); }
  updateActivity();
});
let weatherAsked = 0;
client.on("weather", (m) => {
  if (m.error) return;
  weatherText.dataset.w = "1";
  weatherText.textContent = `${Math.round(m.temp)}° · ${m.city}`;
});
shape.addEventListener("mouseenter", () => {
  if (Date.now() - weatherAsked > 30 * 60_000) { weatherAsked = Date.now(); client.send("weather_get"); }
});
client.on("timers", (m) => { timers = m.items || []; updateActivity(); });
client.on("quick_result", (m) => { if (/timer/.test(m.action)) client.send("timers_get"); });
client.on("pet_state", (m) => { if (m.action === "open_panel") setTimeout(() => openPanel("chat"), 300); });

// ---------- demo (screenshots / browser preview) ----------
if (demo) {
  document.documentElement.classList.add("demo");
  if (demo === "live") {
    coreMood = demoMood || "speaking";
    bubbleTranscript.textContent = "„Pusť na YouTube trailer na Avengers“";
    bubbleTool.replaceChildren(icon("youtube-logo"), " Pouštím YouTube: avengers trailer");
    liveText = "Pouštím **Avengers: Endgame**, oficiální trailer.";
    setInterval(() => blob.setLevel(0.05 + Math.random() * 0.12), 100);
  }
  if (demo === "alert") { alertTitle.textContent = "Časovač"; alertBody.textContent = "Pizza je hotová!"; }
  renderLive();
  setMode(demo);
}
client.connect();
