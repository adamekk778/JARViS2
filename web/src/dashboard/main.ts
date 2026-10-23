import { applyAppearance } from "../shared/base";
import "./style.css";
import { ChatView, conversationList } from "../shared/chat";
import { h, icon, toast } from "../shared/dom";
import { JarvisClient, localEndpoint } from "../shared/ws";
import { buildSettings, type Section } from "./settings";

const client = new JarvisClient(localEndpoint(), "dashboard", "PC");
const chat = new ChatView(client);

const orb = h("div", { class: "orb", "data-state": "offline" });
const brainChip = h("span", { class: "chip brain-chip", title: "Aktuální AI mozek" }, icon("brain"), "připojuji…");
const voiceBtn = h("button", { class: "icon-btn", type: "button", title: "Poslech (Hey Jarvis)", "aria-label": "Zapnout nebo vypnout poslech", onclick: () => client.send("voice_toggle") }, icon("microphone"));
const newChatBtn = h("button", { class: "btn", type: "button", onclick: () => client.send("new_chat") }, icon("plus"), "Nová konverzace");

type View = "chat" | Section;
const NAV: [View, string, string][] = [
  ["chat", "chat-circle-dots", "Chat"],
  ["general", "user-circle", "Obecné"],
  ["brain", "brain", "Mozek (AI)"],
  ["voice", "waveform", "Hlas"],
  ["notch", "rectangle", "Notch"],
  ["appearance", "palette", "Vzhled"],
  ["hotkeys", "keyboard", "Zkratky"],
  ["tools", "toolbox", "Nástroje"],
  ["integrations", "plugs-connected", "Integrace"],
  ["phone", "device-mobile", "Telefon"],
  ["memory", "database", "Paměť"],
  ["jobs", "calendar-check", "Rutiny"],
  ["backup", "floppy-disk", "Záloha"],
];

const nav = h("nav", { class: "rail", "aria-label": "Sekce" });
const main = h("main", { class: "view" });
const chatView = h("section", { class: "chat-view" },
  h("aside", { class: "sidebar" }, newChatBtn, h("div", { class: "side-title" }, "Konverzace"), conversationList(client)),
  h("div", { class: "chat-wrap" }, chat.el));
const settingsHost = h("section", { class: "settings-view" });
main.append(chatView, settingsHost);

const settingsUI = buildSettings(client, settingsHost);

function go(v: View) {
  nav.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  chatView.hidden = v !== "chat";
  settingsHost.hidden = v === "chat";
  if (v !== "chat") settingsUI.show(v as Section);
  else chat.focus();
  history.replaceState(null, "", `#${v}`);
}

for (const [v, ic, label] of NAV) {
  nav.append(h("button", { type: "button", "data-view": v, title: label, onclick: () => go(v) }, icon(ic), h("span", {}, label)));
  if (v === "chat") nav.append(h("div", { class: "rail-sep" }));
}

const header = h("header", { class: "topbar" },
  h("div", { class: "brand" }, orb, h("strong", {}, "JARVIS")),
  h("div", { class: "top-right" }, brainChip, voiceBtn));

document.getElementById("app")!.append(h("div", { class: "shell" }, header, nav, main));

client.onStatus((s) => {
  if (s !== "open") orb.dataset.state = "offline";
  if (s === "closed") brainChip.lastChild!.textContent = "odpojeno, zkouším znovu…";
});
client.on("welcome", (m) => {
  applyAppearance(m.settings);
  orb.dataset.state = m.busy ? "thinking" : "idle";
  brainChip.lastChild!.textContent = m.brain ? `${m.brain[0]} · ${m.brain[1]}` : (m.settings?.brain?.chain?.[0] ?? "AI");
  voiceBtn.classList.toggle("on", !!m.voice?.listening);
  voiceBtn.hidden = !m.voice?.available;
});
client.on("settings_changed", (m) => applyAppearance(m.settings));
client.on("state", (m) => (orb.dataset.state = m.state));
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
