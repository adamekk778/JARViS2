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
import { buildDictation, buildStats, dictKey, recapOverlay } from "./dictation";
import { buildNotetaker } from "./notetaker";
import { buildClaude } from "./claude";
import { buildStark } from "./stark";
import { whatsNewOverlay } from "../shared/whatsnew";
import { missingModelCard } from "../shared/localmissing";
import { commandPalette } from "./palette";

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
const fullBtn = h("button", { class: "btn", type: "button", title: "Otevřít chat přes celou obrazovku",
  onclick: () => (client.local ? client.send("open_window", { view: "full" }) : window.open("/chat", "_blank")) }, icon("arrows-out-simple"), "Celý chat");
const newChatBtn = h("button", { class: "btn", type: "button", onclick: () => client.send("new_chat") }, icon("plus"), "Nová konverzace");

type Page = "tasks" | "voice-mode" | "diagnostics" | "dictate" | "stats" | "notetaker" | "claude" | "stark";
type View = "chat" | Page | Section;
const GROUPS: [string, View[]][] = [
  ["Hlavní", ["chat", "stark", "tasks", "voice-mode", "claude"]],
  ["Diktování", ["dictate", "notetaker", "stats", "dictionary", "dictation"]],
  ["Nastavení", ["general", "brain", "voice", "notch", "appearance", "hotkeys", "permissions", "tools", "integrations", "phone", "memory", "jobs", "backup"]],
  ["Systém", ["diagnostics"]],
];
const NAV: [View, string, string][] = [
  ["chat", "chat-circle-dots", "Chat"],
  ["stark", "circle-notch", "Stark"],
  ["tasks", "list-checks", "Úkoly"],
  ["voice-mode", "microphone-stage", "Hlasový režim"],
  ["claude", "terminal-window", "Claude Code"],
  ["dictate", "microphone", "Diktování"],
  ["notetaker", "record", "Nahrávání hovorů"],
  ["stats", "chart-bar", "Statistiky"],
  ["dictionary", "book-open", "Slovník a zkratky"],
  ["dictation", "sliders", "Nastavení diktování"],
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
  h("div", { class: "chat-wrap" },
    h("header", { class: "chat-head" }, h("span", { class: "chat-head-title" }, "Chat"), brainChip, h("span", { class: "grow" }), stopBtn, voiceBtn, fullBtn),
    missingModelCard(client), chat.el));
const settingsHost = h("section", { class: "settings-view" });
const tasks = buildTasks(client);
const pages: Record<Page, { el: HTMLElement; show?: () => void; hide?: () => void }> = {
  tasks,
  "voice-mode": buildVoiceMode(client),
  diagnostics: buildDiagnostics(client, (text) => { go("chat"); client.send("user_text", { text, attachments: [] }); }),
  dictate: buildDictation(client, (v) => go(v as View)),
  stats: buildStats(client),
  notetaker: buildNotetaker(client),
  claude: buildClaude(client),
  stark: buildStark(client),
};
recapOverlay(client);
whatsNewOverlay(client);
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

for (const [group, views] of GROUPS) {
  nav.append(h("div", { class: "rail-group" }, group));
  for (const v of views) {
    const [, ic, label] = NAV.find(([n]) => n === v)!;
    nav.append(h("button", { type: "button", "data-view": v, title: label, onclick: () => go(v) }, icon(ic), h("span", {}, label)));
  }
}

const MOOD_TEXT: Record<string, string> = {
  idle: "Připraven", listening: "Poslouchám…", thinking: "Přemýšlím…", working: "Pracuji…", speaking: "Mluvím…",
  waiting: "Čekám na tvé potvrzení", error: "Něco se pokazilo", limit: "Dosažen limit AI", updating: "Aktualizuji…",
  success: "Hotovo", offline: "Nepřipojeno", focus: "Režim soustředění", notify: "Mám pro tebe zprávu",
  dancing: "Tančím", joy: "Připraven", sleeping: "Odpočívám",
};
const statusText = h("span", { class: "brand-status" }, "Připojuji…");
let lastSettings: any = null;
let lastMood = "idle";
function moodText(mood: string) {
  lastMood = mood;
  if ((mood === "idle" || mood === "joy") && lastSettings?.dictation?.enabled !== false) return `Připraven · drž ${dictKey(lastSettings)}`;
  return MOOD_TEXT[mood] || "Připraven";
}
const palette = commandPalette({
  nav: NAV.map(([v, ic, label]) => ({ icon: ic, label, run: () => go(v) })),
  actions: [
    { icon: "plus", label: "Nová konverzace", run: () => { go("chat"); client.send("new_chat"); } },
    { icon: "arrows-out-simple", label: "Otevřít celý chat", run: () => fullBtn.click() },
    { icon: "circle-notch", label: "Otevřít Stark HUD", run: () => client.send("open_window", { view: "hud" }) },
    { icon: "sun-horizon", label: "Ranní brífink", run: () => { go("chat"); client.send("user_text", { text: "Brífink", attachments: [] }); } },
    { icon: "stop-circle", label: "Zastavit vše (STOP)", run: () => client.send("stop_all") },
    { icon: "microphone", label: "Zapnout / vypnout poslech", run: () => client.send("voice_toggle") },
  ],
  search: (q) => { go("general"); settingsUI.search(q); },
});
const paletteBtn = h("button", { class: "palette-btn", type: "button", title: "Rychlé hledání (Ctrl+K)", onclick: () => palette.open() },
  icon("magnifying-glass"), h("span", {}, "Hledat…"), h("kbd", {}, "Ctrl K"));

const versionText = h("div", { class: "side-version" });
const side = h("aside", { class: "side" },
  h("div", { class: "brand" }, orb, h("strong", {}, "JARVIS")),
  paletteBtn,
  nav,
  h("div", { class: "side-status" }, statusText),
  versionText);

function greet(name?: string) {
  const hr = new Date().getHours();
  const hello = hr < 5 ? "Dobrou noc" : hr < 10 ? "Dobré ráno" : hr < 12 ? "Dobré dopoledne" : hr < 18 ? "Dobré odpoledne" : "Dobrý večer";
  chat.setGreeting(name ? `${hello}, ${name}` : hello);
}
greet();

document.getElementById("app")!.append(h("div", { class: "shell" }, side, main));

client.onStatus((s) => {
  if (s !== "open") { face.setMood("offline"); statusText.textContent = s === "closed" ? "Odpojeno, zkouším znovu…" : "Připojuji…"; }
  if (s === "closed") brainChip.lastChild!.textContent = "odpojeno, zkouším znovu…";
});
client.on("welcome", (m) => {
  applyAppearance(m.settings);
  face.setMood(m.mood?.mood || "idle");
  lastSettings = m.settings;
  statusText.textContent = moodText(m.mood?.mood || "idle");
  versionText.textContent = m.version ? `JARVIS ${m.version}` : "";
  greet(m.settings?.general?.address_as || m.settings?.general?.user_name);
  if (m.settings?.character) { face.setColor(m.settings.character.color, m.settings.character.glow || undefined); face.setOutfit(m.settings.character.outfit); }
  brainChip.lastChild!.textContent = m.brain ? `${m.brain[0]} · ${m.brain[1]}` : (m.settings?.brain?.chain?.[0] ?? "AI");
  voiceBtn.classList.toggle("on", !!m.voice?.listening);
  voiceBtn.hidden = !m.voice?.available;
});
client.on("settings_changed", (m) => { lastSettings = m.settings; statusText.textContent = moodText(lastMood); applyAppearance(m.settings); if (m.settings?.character) { face.setColor(m.settings.character.color, m.settings.character.glow || undefined); face.setOutfit(m.settings.character.outfit); } });
client.on("mood", (m) => {
  face.setMood(m.mood, { badge: m.badge, progress: m.progress });
  stopBtn.hidden = !BUSY.includes(m.mood);
  statusText.textContent = moodText(m.mood);
  statusText.dataset.busy = String(BUSY.includes(m.mood));
});
client.on("stopped", () => toast("Zastaveno.", "ok"));
client.on("level", (m) => face.setLevel(m.rms || 0));
client.on("brain", (m) => (brainChip.lastChild!.textContent = `${m.provider} · ${m.model}`));
client.on("voice_status", (m) => { voiceBtn.classList.toggle("on", !!m.listening); voiceBtn.hidden = !m.available; });
client.on("notify", (m) => toast(`${m.title}: ${m.body}`, "info", 6000));
client.connect();

window.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); palette.open(); }
});

window.addEventListener("hashchange", () => {
  const v = location.hash.slice(1) as View;
  if (NAV.some(([n]) => n === v)) go(v);
});

const initial = (location.hash.slice(1) || "chat") as View;
go(NAV.some(([v]) => v === initial) ? initial : "chat");
