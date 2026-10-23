import { applyAppearance } from "../shared/base";
import "./style.css";
import { ChatView, conversationList } from "../shared/chat";
import { Blob } from "../character/blob";
import { h, icon, toast } from "../shared/dom";
import { JarvisClient, localEndpoint } from "../shared/ws";
import { buildSettings, type Section } from "./settings";
import { stopButton } from "../shared/taskcard";
import { buildTasks } from "./tasks";
import { buildVoiceMode } from "./voice-mode";
import { buildDiagnostics } from "./diagnostics";

const client = new JarvisClient(localEndpoint(), "dashboard", "PC");
const chat = new ChatView(client);

const face = new Blob({ size: 34 });
face.setMood("offline");
const orb = face.el;
const brainChip = h("span", { class: "chip brain-chip", title: "Aktuální AI mozek" }, icon("brain"), "připojuji…");
const voiceBtn = h("button", { class: "icon-btn", type: "button", title: "Poslech (Hey Jarvis)", "aria-label": "Zapnout nebo vypnout poslech", onclick: () => client.send("voice_toggle") }, icon("microphone"));
const stopBtn = stopButton(client);
stopBtn.hidden = true;
const BUSY = ["listening", "thinking", "working", "speaking", "waiting"];
const newChatBtn = h("button", { class: "btn", type: "button", onclick: () => client.send("new_chat") }, icon("plus"), "Nová konverzace");

type Page = "tasks" | "voice-mode" | "diagnostics";
type View = "chat" | Page | Section;
const NAV: [View, string, string][] = [
  ["chat", "chat-circle-dots", "Chat"],
  ["tasks", "list-checks", "Úkoly"],
  ["voice-mode", "microphone-stage", "Hlasový režim"],
  ["general", "user-circle", "Obecné"],
  ["brain", "brain", "Mozek (AI)"],
  ["voice", "waveform", "Hlas"],
  ["notch", "rectangle", "Notch"],
  ["appearance", "palette", "Vzhled"],
  ["hotkeys", "keyboard", "Zkratky"],
  ["permissions", "shield-check", "Oprávnění"],
  ["tools", "toolbox", "Nástroje"],
  ["integrations", "plugs-connected", "Integrace"],
  ["phone", "device-mobile", "Telefon"],
  ["memory", "database", "Paměť"],
  ["jobs", "calendar-check", "Rutiny"],
  ["backup", "floppy-disk", "Záloha"],
  ["diagnostics", "pulse", "Diagnostika"],
];

const nav = h("nav", { class: "rail", "aria-label": "Sekce" });
const main = h("main", { class: "view" });
const chatView = h("section", { class: "chat-view" },
  h("aside", { class: "sidebar" }, newChatBtn, h("div", { class: "side-title" }, "Konverzace"), conversationList(client)),
  h("div", { class: "chat-wrap" }, chat.el));
const settingsHost = h("section", { class: "settings-view" });
const tasks = buildTasks(client);
const pages: Record<Page, { el: HTMLElement; show?: () => void; hide?: () => void }> = {
  tasks,
  "voice-mode": buildVoiceMode(client),
  diagnostics: buildDiagnostics(client, (text) => { go("chat"); client.send("user_text", { text, attachments: [] }); }),
};
main.append(chatView, settingsHost, ...Object.values(pages).map((p) => p.el));

const settingsUI = buildSettings(client, settingsHost);

function go(v: View) {
  nav.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  const page = pages[v as Page];
  chatView.hidden = v !== "chat";
  settingsHost.hidden = v === "chat" || !!page;
  for (const [k, p] of Object.entries(pages)) { if (k !== v && !p.el.hidden) p.hide?.(); p.el.hidden = k !== v; }
  if (page) page.show?.();
  else if (v !== "chat") settingsUI.show(v as Section);
  else chat.focus();
  history.replaceState(null, "", `#${v}`);
}

for (const [v, ic, label] of NAV) {
  nav.append(h("button", { type: "button", "data-view": v, title: label, onclick: () => go(v) }, icon(ic), h("span", {}, label)));
  if (v === "voice-mode" || v === "backup") nav.append(h("div", { class: "rail-sep" }));
}

const header = h("header", { class: "topbar" },
  h("div", { class: "brand" }, orb, h("strong", {}, "JARVIS")),
  h("div", { class: "top-right" }, stopBtn, brainChip, voiceBtn));

document.getElementById("app")!.append(h("div", { class: "shell" }, header, nav, main));

client.onStatus((s) => {
  if (s !== "open") face.setMood("offline");
  if (s === "closed") brainChip.lastChild!.textContent = "odpojeno, zkouším znovu…";
});
client.on("welcome", (m) => {
  applyAppearance(m.settings);
  face.setMood(m.mood?.mood || "idle");
  if (m.settings?.character) face.setColor(m.settings.character.color, m.settings.character.glow || undefined);
  brainChip.lastChild!.textContent = m.brain ? `${m.brain[0]} · ${m.brain[1]}` : (m.settings?.brain?.chain?.[0] ?? "AI");
  voiceBtn.classList.toggle("on", !!m.voice?.listening);
  voiceBtn.hidden = !m.voice?.available;
});
client.on("settings_changed", (m) => { applyAppearance(m.settings); if (m.settings?.character) face.setColor(m.settings.character.color, m.settings.character.glow || undefined); });
client.on("mood", (m) => { face.setMood(m.mood, { badge: m.badge, progress: m.progress }); stopBtn.hidden = !BUSY.includes(m.mood); });
client.on("stopped", () => toast("Zastaveno.", "ok"));
client.on("level", (m) => face.setLevel(m.rms || 0));
client.on("brain", (m) => (brainChip.lastChild!.textContent = `${m.provider} · ${m.model}`));
client.on("voice_status", (m) => { voiceBtn.classList.toggle("on", !!m.listening); voiceBtn.hidden = !m.available; });
client.on("notify", (m) => toast(`${m.title}: ${m.body}`, "info", 6000));
client.connect();

window.addEventListener("hashchange", () => {
  const v = location.hash.slice(1) as View;
  if (NAV.some(([n]) => n === v)) go(v);
});

const initial = (location.hash.slice(1) || "chat") as View;
go(NAV.some(([v]) => v === initial) ? initial : "chat");
