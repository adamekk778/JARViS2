// The desktop pet window: the character, its speech bubble and a right-click menu (spec §6).
import { applyAppearance } from "../shared/base";
import "./style.css";
import { Blob, type Mood } from "../character/blob";
import { h, icon } from "../shared/dom";
import { renderMarkdown } from "../shared/markdown";
import { JarvisClient, localEndpoint } from "../shared/ws";

declare global {
  interface Window { pywebview?: { api: Record<string, (...a: any[]) => Promise<any>> } }
}
const api = (name: string, ...args: any[]) => window.pywebview?.api?.[name]?.(...args).catch(() => {});
const params = new URLSearchParams(location.search);
const demo = params.get("demo");

const client = new JarvisClient(localEndpoint(), "pet", "pet");
const blob = new Blob({ size: 110 });
const body = h("div", { class: "pet-body" }, blob.el);
const answer = h("div", { class: "pet-text md" });
const bubble = h("div", { class: "pet-bubble", hidden: true }, answer);
const menu = h("div", { class: "pet-menu", hidden: true },
  h("button", { type: "button", onclick: () => { hideMenu(); api("open_panel"); } }, icon("layout"), "Otevřít panel"),
  h("button", { type: "button", onclick: () => { hideMenu(); api("open_chat", "chat"); } }, icon("chat-circle-dots"), "Chat"),
  h("button", { type: "button", onclick: () => { hideMenu(); client.send("mood_set", { mood: coreMood === "sleeping" ? null : "sleeping" }); } }, icon("moon-stars"), "Uspat / probudit"),
  h("button", { type: "button", onclick: () => { hideMenu(); api("dock"); } }, icon("arrow-line-up"), "Zpět do notche"));
const root = h("div", { class: "pet" }, bubble, body, menu);
document.getElementById("pet-root")!.append(root);

let coreMood: Mood = "idle";
let action = "idle";
let facing = 1;
let held = false;
let hoverUntil = 0;
let text = "";
let bubbleTimer = 0;

function mood(): Mood {
  if (held) return "dragged";
  if (performance.now() < hoverUntil && (coreMood === "idle" || coreMood === "sleeping")) return "desktop_interact";
  if (action === "sleep" && coreMood === "idle") return "sleeping";
  return coreMood;
}
function update() {
  blob.setMood(mood());
  root.dataset.action = action;
  root.style.setProperty("--facing", String(facing));
  if (action === "walk" || action === "jump") blob.lookAt(innerWidth / 2 + facing * 400, innerHeight - 60);
}

function showBubble(on: boolean) {
  if (on === !bubble.hidden) return;
  bubble.hidden = !on;
  root.classList.toggle("big", on);
  api("bubble", on);
}
function say(t: string, done = false) {
  text = t;
  answer.innerHTML = renderMarkdown(t.length > 420 ? "…" + t.slice(-420) : t);
  answer.scrollTop = answer.scrollHeight;
  showBubble(!!t);
  window.clearTimeout(bubbleTimer);
  if (done) bubbleTimer = window.setTimeout(() => showBubble(false), 7000);
}

// ---------- mouse ----------
let down: { x: number; y: number } | null = null;
let moved = false;
body.addEventListener("pointerdown", (e) => {
  if (e.button !== 0) return;
  down = { x: e.screenX, y: e.screenY };
  moved = false;
  body.setPointerCapture(e.pointerId);
});
body.addEventListener("pointermove", (e) => {
  hoverUntil = performance.now() + 2000;
  if (!down) return;
  if (!moved && Math.hypot(e.screenX - down.x, e.screenY - down.y) > 6) {
    moved = true;
    held = true;
    api("grab");
    update();
  }
  if (moved) api("drag", e.screenX, e.screenY);
});
body.addEventListener("pointerup", async () => {
  const wasDrag = moved;
  down = null;
  moved = false;
  if (wasDrag) {
    held = false;
    await api("release");
    update();
  }
});
body.addEventListener("click", () => { if (!held) client.send("push_to_talk"); });
body.addEventListener("dblclick", () => api("dock"));
body.addEventListener("mouseenter", () => { hoverUntil = performance.now() + 2000; api("hover"); update(); });
root.addEventListener("contextmenu", (e) => { e.preventDefault(); menu.hidden = false; });
function hideMenu() { menu.hidden = true; }
window.addEventListener("blur", hideMenu);
document.addEventListener("pointerdown", (e) => { if (!menu.contains(e.target as Node)) hideMenu(); });
setInterval(update, 500);

// ---------- events ----------
const SIZES: Record<string, number> = { S: 80, M: 110, L: 140 };
function applySize(s?: string) {
  const px = SIZES[s || "M"] ?? 110;
  blob.el.style.setProperty("--blob-size", `${px}px`);
  body.style.width = body.style.height = `${px}px`;
  body.style.left = `${110 - px / 2}px`;
}
client.on("welcome", (m) => {
  applyAppearance(m.settings);
  const ch = m.settings?.character;
  if (ch) { blob.setColor(ch.color, ch.glow || undefined); applySize(ch.size); }
  if (m.mood) coreMood = m.mood.mood;
  update();
});
client.on("settings_changed", (m) => { const ch = m.settings?.character; if (ch) { blob.setColor(ch.color, ch.glow || undefined); applySize(ch.size); } });
client.on("mood", (m) => { coreMood = m.mood; blob.setMood(mood(), { badge: m.badge, progress: m.progress }); update(); });
client.on("pet_state", (m) => { if (m.action !== "open_panel") { action = m.action; facing = m.facing; update(); } });
client.on("level", (m) => blob.setLevel(m.rms || 0));
client.on("transcript", (m) => { if (m.final && m.text) say(`„${m.text}“`); });
client.on("assistant_delta", (m) => say(text.startsWith("„") ? m.text : text + m.text));
client.on("assistant_done", (m) => say(m.text, true));
client.on("confirm_request", (m) => {
  say(`Potřebuji potvrzení: **${m.description}**`);
  answer.append(h("div", { class: "pet-confirm" },
    h("button", { class: "no", type: "button", onclick: () => { client.send("confirm_response", { id: m.id, approved: false }); showBubble(false); } }, "Ne"),
    h("button", { class: "yes", type: "button", onclick: () => { client.send("confirm_response", { id: m.id, approved: true }); showBubble(false); } }, "Ano")));
});
client.on("notify", (m) => say(`**${m.title}**\n\n${m.body}`, true));

if (demo) {
  document.documentElement.classList.add("demo");
  action = demo;
  if (params.get("text")) say(params.get("text")!, false);
  update();
}
client.connect();
