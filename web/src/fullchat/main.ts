// 3.1 full-screen chat ("Otevřít celý chat"): a ChatGPT-style window – recent chats on the left, Chat | Agent on top,
// the greeting and a pill composer in the middle, websites JARVIS builds shown live right in the conversation.
import { applyAppearance } from "../shared/base";
import "./style.css";
import { ChatView, conversationList, miniBlob, sitePreview } from "../shared/chat";
import { fmtTime, h, icon, toast } from "../shared/dom";
import { JarvisClient, localEndpoint } from "../shared/ws";
import { stopButton } from "../shared/taskcard";
import { missingModelCard } from "../shared/localmissing";

const client = new JarvisClient(localEndpoint(), "fullchat", "PC");

const modelChip = h("button", { class: "fc-model", type: "button", title: "AI mozek (změníš v nastavení)",
  onclick: () => openWindow("brain") }, icon("brain"), h("span", {}, "AI"));
const chat = new ChatView(client, {
  greeting: "Ahoj! Dáme se do toho?",
  subtitle: "",
  emptyAvatar: false,
  attachIcon: "plus",
  placeholder: "Zeptej se na cokoli nebo řekni, co mám udělat",
  extraTools: [modelChip],
  suggestions: ["Udělej mi web pro moji kavárnu", "Pusť na YouTube nějakou dobrou hudbu",
    "Co je teď na mé obrazovce?", "Najdi dnešní zprávy z technologií"],
  suggestionIcons: ["globe", "youtube-logo", "monitor", "newspaper"],
});

function openWindow(view: string) {
  if (client.local) client.send("open_window", { view });
  else location.href = `/#${view}`;
}

// ---------- sidebar ----------
const convs = conversationList(client);
const search = h("input", { class: "fc-search", type: "search", placeholder: "Hledat v chatech…", "aria-label": "Hledat v chatech", hidden: true }) as HTMLInputElement;
const filter = () => {
  const q = search.value.trim().toLocaleLowerCase("cs");
  convs.querySelectorAll<HTMLElement>(".conv").forEach((c) => {
    c.hidden = !!q && !(c.textContent || "").toLocaleLowerCase("cs").includes(q);
  });
};
search.addEventListener("input", filter);
new MutationObserver(filter).observe(convs, { childList: true });

const item = (ic: string, label: string, fn: () => void, kbd = "") =>
  h("button", { class: "fc-item", type: "button", onclick: fn }, icon(ic), h("span", {}, label), kbd ? h("kbd", {}, kbd) : null);
const userAvatar = h("span", { class: "fc-avatar" }, "J");
const userName = h("span", { class: "fc-user-name" }, "Ty");
const side = h("aside", { class: "fc-side" },
  h("div", { class: "fc-brand" },
    h("span", { class: "fc-logo" }, miniBlob(true)), h("strong", {}, "JARVIS"),
    h("button", { class: "icon-btn sm fc-collapse", type: "button", title: "Skrýt panel", "aria-label": "Skrýt panel", onclick: () => toggleSide() }, icon("sidebar-simple"))),
  item("note-pencil", "Nový chat", () => newChat(), "Ctrl Shift O"),
  item("magnifying-glass", "Hledat v chatech", () => { search.hidden = !search.hidden; if (!search.hidden) search.focus(); else { search.value = ""; filter(); } }),
  search,
  item("globe", "Moje weby", () => showSites()),
  item("list-checks", "Úkoly", () => openWindow("tasks")),
  item("microphone-stage", "Hlasový režim", () => openWindow("voice-mode")),
  item("circle-notch", "Stark HUD", () => (client.local ? client.send("open_window", { view: "hud" }) : window.open("/hud", "_blank"))),
  h("div", { class: "fc-label" }, "Nedávné"),
  h("div", { class: "fc-convs" }, convs),
  h("button", { class: "fc-user", type: "button", title: "Nastavení", onclick: () => openWindow("general") },
    userAvatar, userName, icon("gear-six")));

function newChat() {
  client.send("new_chat");
  chat.focus();
}

function toggleSide(force?: boolean) {
  const open = force ?? document.body.classList.contains("fc-side-closed");
  document.body.classList.toggle("fc-side-closed", !open);
  try { localStorage.setItem("fc-side", open ? "open" : "closed"); } catch { /* private mode */ }
}

// ---------- top bar ----------
const modeSeg = h("div", { class: "fc-mode", role: "group", "aria-label": "Režim" });
let agentMode = false;
const renderMode = () => modeSeg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", (b.dataset.mode === "agent") === agentMode));
modeSeg.append(
  h("button", { type: "button", "data-mode": "chat", title: "Rychlé odpovědi a akce", onclick: () => setMode(false) }, "Chat"),
  h("button", { type: "button", "data-mode": "agent", title: "Dlouhé úkoly: JARVIS si udělá plán a postupně ho splní", onclick: () => setMode(true) }, "Agent"));
function setMode(v: boolean) {
  if (v === agentMode) return;
  agentMode = v;
  renderMode();
  if (client.local) client.send("settings_set", { patch: { agent: { mode: v } } });
  toast(v ? "Režim Agent: velké úkoly krok za krokem." : "Režim Chat.", "ok", 1800);
}
const stopBtn = stopButton(client);
stopBtn.hidden = true;
const voiceBtn = h("button", { class: "icon-btn", type: "button", title: "Poslech (Hey Jarvis)", "aria-label": "Zapnout nebo vypnout poslech", onclick: () => client.send("voice_toggle") }, icon("waveform"));
const head = h("header", { class: "fc-head" },
  h("button", { class: "icon-btn fc-open-side", type: "button", title: "Zobrazit panel", "aria-label": "Zobrazit panel", onclick: () => toggleSide(true) }, icon("sidebar-simple")),
  h("button", { class: "icon-btn fc-open-side", type: "button", title: "Nový chat", "aria-label": "Nový chat", onclick: () => newChat() }, icon("note-pencil")),
  h("span", { class: "grow" }),
  modeSeg,
  h("span", { class: "grow" }),
  stopBtn, voiceBtn,
  h("button", { class: "icon-btn", type: "button", title: "Malé okno JARVISe", "aria-label": "Malé okno", onclick: () => openWindow("chat") }, icon("arrows-in-simple")));

const mainEl = h("main", { class: "fc-main" }, head, missingModelCard(client), chat.el);
const shell = h("div", { class: "fc" }, side, h("div", { class: "fc-scrim", onclick: () => toggleSide(false) }), mainEl);
document.getElementById("app")!.append(shell);
try { if (localStorage.getItem("fc-side") === "closed" || innerWidth < 860) document.body.classList.add("fc-side-closed"); } catch { /* ignore */ }

// ---------- websites gallery ----------
function showSites() {
  client.send("sites_get");
  const grid = h("div", { class: "fc-sites-grid" }, h("p", { class: "help" }, "Načítám…"));
  const close = () => { dlg.remove(); off(); };
  const dlg = h("div", { class: "fc-dialog", role: "dialog", "aria-modal": "true", "aria-label": "Moje weby", onclick: (e: Event) => { if (e.target === dlg) close(); } },
    h("div", { class: "fc-dialog-box" },
      h("div", { class: "fc-dialog-head" }, h("strong", {}, "Moje weby"),
        h("span", { class: "help" }, "Řekni „udělej mi web pro…“ a JARVIS ho postaví."),
        h("button", { class: "icon-btn sm", type: "button", "aria-label": "Zavřít", onclick: close }, icon("x"))),
      grid));
  dlg.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  const off = client.on("sites", (m) => {
    grid.replaceChildren(...(m.items.length ? m.items.map((s: any) =>
      h("button", { class: "fc-site", type: "button", onclick: () => { close(); openSite(s.url, s.title); } },
        h("span", { class: "fc-site-ico" }, icon("globe-simple")),
        h("span", { class: "fc-site-title" }, s.title), h("span", { class: "fc-site-time" }, fmtTime(s.updated))))
      : [h("p", { class: "help" }, "Zatím žádné weby. Zkus: „Udělej mi web pro moji kavárnu“.")]));
  });
  document.body.append(dlg);
  (dlg.querySelector("button") as HTMLElement | null)?.focus();
}

function openSite(url: string, title: string) {
  const card = sitePreview(client, url, title);
  card.classList.add("max");
  document.body.classList.add("sp-max-open");
  const close = () => { card.remove(); document.body.classList.remove("sp-max-open"); };
  // the card's own full-screen button toggles .max off → treat that as closing this standalone view
  new MutationObserver(() => { if (!card.classList.contains("max")) close(); }).observe(card, { attributes: true, attributeFilter: ["class"] });
  card.tabIndex = -1;
  document.body.append(card);
  card.focus();
}

// ---------- server ----------
const BUSY = ["listening", "thinking", "working", "speaking", "waiting"];
function greet(s: any) {
  const name = s?.general?.address_as || s?.general?.user_name || "";
  chat.setGreeting(name ? `Ahoj, ${name}. Dáme se do toho?` : "Ahoj! Dáme se do toho?");
  const who = s?.general?.user_name || "Ty";
  userName.textContent = who;
  userAvatar.textContent = who.trim().charAt(0).toUpperCase() || "T";
  agentMode = !!s?.agent?.mode;
  renderMode();
}
client.on("welcome", (m) => {
  applyAppearance(m.settings);
  greet(m.settings);
  modelChip.lastChild!.textContent = m.brain ? m.brain[1] : (m.settings?.brain?.chain?.[0] ?? "AI");
  voiceBtn.classList.toggle("on", !!m.voice?.listening);
  voiceBtn.hidden = !m.voice?.available;
  chat.focus();
});
client.on("settings_changed", (m) => { applyAppearance(m.settings); greet(m.settings); });
client.on("brain", (m) => (modelChip.lastChild!.textContent = m.model));
client.on("mood", (m) => (stopBtn.hidden = !BUSY.includes(m.mood)));
client.on("voice_status", (m) => { voiceBtn.classList.toggle("on", !!m.listening); voiceBtn.hidden = !m.available; });
client.onStatus((s) => document.body.classList.toggle("fc-offline", s !== "open"));
client.connect();

window.addEventListener("keydown", (e) => {
  const k = e.key.toLowerCase();
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && k === "o") { e.preventDefault(); newChat(); }
  if ((e.ctrlKey || e.metaKey) && k === "b") { e.preventDefault(); toggleSide(); }
});
matchMedia("(max-width: 860px)").addEventListener("change", (e) => toggleSide(!e.matches));
