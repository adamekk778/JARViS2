import { applyAppearance } from "../shared/base";
import "./style.css";
import { Blob, type Mood } from "../character/blob";
import { h, icon, TOOL_ICON } from "../shared/dom";
import { renderMarkdown } from "../shared/markdown";
import { JarvisClient, localEndpoint } from "../shared/ws";
import { buildPanel } from "./panel";
import { configureSounds, play } from "../shared/sounds";
import { stopButton, type Task } from "../shared/taskcard";

/* Notch modes (spec §4):
   closed  black notch, eyes peeking from the bottom edge
   hover   woke up (mouse over)
   bar     character below the notch + chat / mic / settings buttons
   live    JARVIS is busy: character in its mood + speech bubble
   alert   short notification
   panel   the big panel                                                       */
type Mode = "closed" | "hover" | "bar" | "live" | "alert" | "panel";

declare global {
  interface Window { pywebview?: { api: Record<string, (...a: any[]) => Promise<any>> } }
}

const params = new URLSearchParams(location.search);
const demo = params.get("demo") as Mode | null;
const demoMood = params.get("mood") as Mood | null;
const client = new JarvisClient(localEndpoint(), "notch", "notch");
window.addEventListener("pywebviewready", () => document.documentElement.classList.add("native"));
if (window.pywebview) document.documentElement.classList.add("native");

let cfg = { width: 200, height: 34, expanded_width: 1000, expanded_height: 410, open_delay_ms: 150, close_delay_ms: 400, linger_s: 6 };
let mode: Mode = "closed";
let coreMood: Mood = "idle";
let moodInfo: { badge?: number; progress?: number | null; detail?: string } = {};
let hovering = false;
let pinned = false;
let pendingConfirm: string | null = null;
let petMode = false;
let liveText = "";
let alertTimer = 0, lingerTimer = 0, openTimer = 0, closeTimer = 0, uiMoodTimer = 0;
let uiMood: Mood | null = null; // opening / closing / dragged flashes
let activity = "";
let pinBtn: HTMLElement;
let task: Task | null = null;
let capturing = false;

// ---------- DOM ----------
const blob = new Blob({ size: 64 });
const blobBox = h("div", { class: "n-blob" }, blob.el);
const actText = h("span", { class: "act" });

const barLeft = h("div", { class: "bar-side l" },
  h("button", { class: "n-btn", type: "button", title: "Chat", "aria-label": "Chat", onclick: () => openPanel("chat") }, icon("chat-circle-dots")));
const barStop = stopButton(client, "sm");
const barRight = h("div", { class: "bar-side r" }, barStop,
  h("button", { class: "n-btn", type: "button", title: "Mluvit (Ctrl+Alt+Mezerník)", "aria-label": "Mluvit", onclick: () => client.send("push_to_talk") }, icon("microphone")),
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
  pin: (v) => { pinned = v; if (!v) scheduleClose(); },
  undock: () => client.send("pet_command", { action: "undock" }),
});
const panelHead = h("div", { class: "p-head" },
  h("span", { class: "p-title" }, "J A R V I S"),
  h("div", { class: "p-head-r" },
    h("button", { class: "p-icon", type: "button", title: "Nová konverzace", "aria-label": "Nová konverzace", onclick: () => client.send("new_chat") }, icon("note-pencil")),
    h("button", { class: "p-icon", type: "button", title: "Velké okno chatu", "aria-label": "Velké okno", onclick: () => openChat("chat") }, icon("arrows-out-simple")),
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
const inner = h("div", { class: "n-inner" }, panelWrap, blobBox, actText, barLeft, barRight, bubble, alertBox, capChip, liveStop);
const shape = h("div", { class: "notch", "data-mode": "closed" }, inner);
document.getElementById("notch-root")!.append(shape);

// ---------- window size ----------
const PAD = 28; // keep in sync with desktop/host.py
async function resizeWindow(w: number, hh: number) {
  try { await window.pywebview?.api.resize(Math.round(w), Math.round(hh)); } catch { /* browser preview */ }
}
function openChat(view = "chat") {
  if (window.pywebview) window.pywebview.api.open_chat(view);
  else window.open(`/#${view}`, "_blank");
}

function sizeFor(m: Mode): [number, number] {
  switch (m) {
    case "panel": return [cfg.expanded_width || 1000, Math.max(340, cfg.expanded_height || 390)];
    case "bar": return [360, 96];
    case "hover": return [Math.round(cfg.width * 1.1), Math.round(cfg.height * 1.15)];
    case "alert": return [440, 92];
    case "live": return [560, liveHeight()];
    default: return [activity ? Math.max(cfg.width, 300) : cfg.width, cfg.height];
  }
}
function liveHeight() {
  const kids = [...bubble.children].filter((c) => (c as HTMLElement).textContent) as HTMLElement[];
  const content = kids.reduce((s, k) => s + (k === bubbleAnswer ? Math.min(118, k.scrollHeight) : k.offsetHeight || 20), 0) + Math.max(0, kids.length - 1) * 4;
  return Math.max(96, Math.min(300, content + 34));
}

let lastSize = [0, 0];
function apply(m: Mode) {
  const [w, hh] = sizeFor(m);
  const growing = w > lastSize[0] || hh > lastSize[1];
  window.clearTimeout((apply as any)._t);
  if (growing) resizeWindow(w + PAD * 2, hh + PAD);
  shape.style.setProperty("--w", `${w}px`);
  shape.style.setProperty("--h", `${hh}px`);
  shape.dataset.mode = m;
  if (!growing) {
    (apply as any)._t = window.setTimeout(() => resizeWindow(w + PAD * 2, hh + PAD), 460);
  }
  lastSize = [w, hh];
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
  const calm = coreMood === "idle" || coreMood === "sleeping";
  if (uiMood && calm) return uiMood;
  if (mode === "closed") return calm ? (coreMood === "sleeping" ? "sleeping" : "closed") : coreMood;
  if (mode === "hover" && calm) return "hover";
  if (mode === "bar" && calm) return "expanded";
  return coreMood;
}
function updateBlob() {
  blob.setMood(displayMood(), { badge: moodInfo.badge, progress: moodInfo.progress ?? null });
  shape.dataset.mood = displayMood();
}

function busy() {
  return ["listening", "thinking", "working", "speaking", "waiting"].includes(coreMood) || !!pendingConfirm;
}

function settle(force = false) {
  if (!force && (pinned || dragging)) return;
  if (busy() && mode !== "panel") return setMode("live");
  if (mode === "panel" && !force && hovering) return;
  if (hovering && !force) return setMode("bar");
  setMode("closed");
}

function scheduleClose() {
  window.clearTimeout(closeTimer);
  closeTimer = window.setTimeout(() => {
    if (hovering || pinned) return;
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
shape.addEventListener("mouseenter", () => {
  hovering = true;
  window.clearTimeout(closeTimer);
  window.clearTimeout(openTimer);
  if (mode === "closed" || mode === "alert") {
    setMode("hover");
    openTimer = window.setTimeout(() => hovering && mode === "hover" && setMode("bar"), cfg.open_delay_ms + 220);
  }
});
shape.addEventListener("mouseleave", () => {
  hovering = false;
  window.clearTimeout(openTimer);
  if (mode === "bar" || mode === "hover" || mode === "panel") scheduleClose();
});
blobBox.addEventListener("click", () => {
  if (justDragged) return;
  if (mode === "panel") { if (pinned) setPinned(false); settle(true); }
  else openPanel("chat");
});

// drag the character down out of the notch → desktop pet (spec §4)
let dragging = false, justDragged = false, dragStart: { x: number; y: number } | null = null;
blobBox.addEventListener("pointerdown", (e) => {
  if (petMode || mode === "panel") return;
  dragStart = { x: e.clientX, y: e.clientY };
  blobBox.setPointerCapture(e.pointerId);
});
blobBox.addEventListener("pointermove", (e) => {
  if (!dragStart) return;
  const dy = e.clientY - dragStart.y;
  if (dy > 8) {
    dragging = true;
    blobBox.style.transform = `translateY(${Math.min(dy, 80)}px)`;
    blob.setMood("dragged");
  }
  if (dy > 60) {
    dragStart = null;
    dragging = false;
    justDragged = true;
    setTimeout(() => (justDragged = false), 300);
    blobBox.style.transform = "";
    client.send("pet_command", { action: "undock" });
  }
});
const endDrag = () => {
  if (dragging) { justDragged = true; setTimeout(() => (justDragged = false), 300); }
  dragStart = null;
  dragging = false;
  blobBox.style.transform = "";
  updateBlob();
};
blobBox.addEventListener("pointerup", endDrag);
blobBox.addEventListener("pointercancel", endDrag);

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
window.addEventListener("keydown", (e) => { if (e.key === "Escape" && mode === "panel") { if (pinned) setPinned(false); settle(true); } });

// ---------- live bubble ----------
const STATE_LABEL: Partial<Record<Mood, string>> = { listening: "Poslouchám…", thinking: "Přemýšlím…", working: "Pracuji…", waiting: "Potřebuji potvrzení" };
function renderLive() {
  bubbleState.textContent = STATE_LABEL[coreMood] ?? "";
  const activeTask = task && ["running", "paused", "waiting"].includes(task.status) ? task : null;
  if (activeTask && activeTask.total) {
    const cur = activeTask.steps.find((s) => s.status === "running") || activeTask.steps[Math.min(activeTask.done, activeTask.total - 1)];
    bubbleTask.replaceChildren(icon("list-checks"), ` Krok ${Math.min(activeTask.done + 1, activeTask.total)}/${activeTask.total}`,
      cur ? h("span", { class: "muted" }, ` · ${cur.title}`) : "", activeTask.status === "paused" ? h("span", { class: "muted" }, " (pozastaveno)") : "");
  } else bubbleTask.replaceChildren();
  liveStop.hidden = !busy();
  barStop.hidden = !busy();
  const text = liveText.length > 600 ? "…" + liveText.slice(-600) : liveText;
  bubbleAnswer.innerHTML = text ? renderMarkdown(text) : "";
  bubbleAnswer.scrollTop = bubbleAnswer.scrollHeight;
  if (mode === "live") apply("live");
}

function onMood(m: any) {
  const prev = coreMood;
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

// ---------- activity (closed notch) ----------
let timers: any[] = [];
let media: any = {};
function updateActivity() {
  if (timers.length) {
    const r = Math.max(0, Math.round(timers[0].ends_at - Date.now() / 1000));
    activity = `${Math.floor(r / 60)}:${String(r % 60).padStart(2, "0")}`;
    actText.replaceChildren(icon("timer"), " ", activity);
  } else if (media?.playing && media.title) {
    activity = media.title;
    actText.replaceChildren(icon("music-notes"), " ", activity);
  } else {
    activity = "";
    actText.replaceChildren();
  }
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
  cfg = { ...cfg, ...(m.settings?.notch || {}) };
  if (!m.settings?.notch?.expanded_width || m.settings.notch.expanded_width < 900) { cfg.expanded_width = 1000; cfg.expanded_height = 410; }
  const ch = m.settings?.character;
  if (ch) blob.setColor(ch.color, ch.glow || undefined);
  petMode = !!m.pet_mode;
  shape.classList.toggle("pet-away", petMode);
  media = m.media || {};
  timers = m.timers || [];
  pendingConfirm = m.pending_confirm || null;
  onMood(m.mood || { mood: m.busy ? "thinking" : "idle" });
  if (m.settings?.notch?.pinned) { setPinned(true, false); openPanel(); } else settle();
});
client.on("settings_changed", (m) => {
  applyAppearance(m.settings);
  configureSounds(m.settings?.appearance);
  const ch = m.settings?.character;
  if (ch) blob.setColor(ch.color, ch.glow || undefined);
  petMode = !!ch?.pet_mode;
  shape.classList.toggle("pet-away", petMode);
});
client.on("mood", onMood);
client.on("level", (m) => blob.setLevel(m.rms || 0));
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
client.on("confirm_resolved", (m) => { if (pendingConfirm === m.id) { pendingConfirm = null; bubbleConfirm.replaceChildren(); renderLive(); if (!busy()) settle(); } });
client.on("confirm_timeout", (m) => { if (pendingConfirm === m.id) { pendingConfirm = null; bubbleConfirm.replaceChildren(); settle(); } });
client.on("notify", (m) => { showAlert(m.title, m.body); play("notify"); });
client.on("task_update", (m) => {
  const prevStatus = task?.id === m.task?.id ? task?.status : null;
  task = m.task;
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
