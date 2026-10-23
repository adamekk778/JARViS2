import { applyAppearance } from "../shared/base";
import { setApproveGuard } from "../shared/approve";
import "./style.css";
import { ChatView, conversationList } from "../shared/chat";
import { h, icon, toast } from "../shared/dom";
import { Recorder } from "../shared/recorder";
import { JarvisClient } from "../shared/ws";
import { loadPairing, parsePairing, resolveEndpoint, savePairing, type Pairing } from "./connect";
import { native } from "./native";
import { Blob } from "../character/blob";
import { stopButton, TaskCard } from "../shared/taskcard";

const bigFace = (size: number) => { const b = new Blob({ size }); b.setMood("idle"); return b.el; };

const app = document.getElementById("app")!;
let client: JarvisClient | null = null;

// A QR opened in a normal phone browser lands on /mobile#token=...
const fromUrl = parsePairing(location.href);
if (fromUrl) {
  if (!fromUrl.hosts.length) fromUrl.hosts = [location.hostname];
  savePairing(fromUrl);
  history.replaceState(null, "", location.pathname);
}

window.addEventListener("hashchange", () => {
  const p = parsePairing(location.href);
  if (p) {
    savePairing(p);
    history.replaceState(null, "", location.pathname);
    boot();
  }
});

boot();

async function boot() {
  const p = loadPairing();
  if (!p) return connectScreen();
  app.replaceChildren(h("div", { class: "splash" }, bigFace(96), h("p", {}, "Hledám tvoje PC…")));
  const ep = await resolveEndpoint(p);
  if (!ep) return connectScreen(p, "PC není dostupné. Běží JARVIS na PC? Jsi na stejné Wi-Fi nebo máš zapnutý Tailscale?");
  mainScreen(ep, p);
}

// ---------------- connect ----------------
function connectScreen(prev?: Pairing | null, error?: string) {
  const manual = h("input", { class: "input", placeholder: "192.168.1.20:8765 TOKEN nebo odkaz z PC", autocomplete: "off" }) as HTMLInputElement;
  const tryPairing = async (p: Pairing | null) => {
    if (!p) return toast("Tohle není platný párovací kód", "error");
    savePairing(p);
    boot();
  };
  const scan = async () => {
    try {
      const text = await native.scanQr();
      if (text) tryPairing(parsePairing(text));
    } catch (e: any) {
      toast(e.message || "Skenování se nepodařilo", "error");
    }
  };
  app.replaceChildren(h("div", { class: "connect" },
    bigFace(110),
    h("h1", {}, "JARVIS"),
    h("p", { class: "lead" }, "Spáruj telefon s počítačem. Na PC otevři JARVIS → Telefon a naskenuj QR kód."),
    error ? h("div", { class: "readonly-note" }, icon("warning"), " ", error) : null,
    native.isNative ? h("button", { class: "btn primary big", type: "button", onclick: scan }, icon("qr-code"), "Naskenovat QR kód") : null,
    h("details", { class: "manual", open: !native.isNative || undefined },
      h("summary", {}, "Zadat ručně"),
      h("div", { class: "manual-body" }, manual, h("button", { class: "btn", type: "button", onclick: () => tryPairing(parsePairing(manual.value)) }, "Připojit"))),
    prev ? h("button", { class: "btn ghost", type: "button", onclick: () => boot() }, icon("arrows-clockwise"), "Zkusit znovu") : null));
}

// ---------------- main ----------------
function mainScreen(ep: { base: string; token: string }, pairing: Pairing) {
  client?.close();
  const c = new JarvisClient(ep, "mobile", native.deviceName());
  client = c;
  const chat = new ChatView(c, { compact: true, placeholder: "Napiš JARVISovi…" });

  const face = new Blob({ size: 34 });
  face.setMood("offline");
  const orb = face.el;
  const status = h("span", { class: "m-status" }, "připojuji…");
  const drawer = h("aside", { class: "drawer", "aria-label": "Konverzace" },
    h("div", { class: "drawer-head" }, h("strong", {}, "Konverzace"),
      h("button", { class: "btn", type: "button", onclick: () => { c.send("new_chat"); closeDrawer(); } }, icon("plus"), "Nová")),
    conversationList(c, () => closeDrawer()));
  const scrim = h("div", { class: "scrim", onclick: () => closeDrawer() });
  const openDrawer = () => document.body.classList.add("drawer-open");
  const closeDrawer = () => document.body.classList.remove("drawer-open");

  const stop = stopButton(c, "sm");
  stop.hidden = true;
  const taskCard = new TaskCard(c, { compact: true, hideWhenIdle: true });
  // Claude Code on the PC waiting for an answer (3.0): Povolit needs the fingerprint
  setApproveGuard((reason) => native.verify(reason));
  let asks: any[] = [];
  const asksBox = h("div", { class: "m-asks" });
  const decideClaude = async (id: string, decision: string, label = "") => {
    if ((decision === "allow" || decision === "always") && !(await native.verify(`Claude Code: ${label}`))) return;
    c.send("claude_decision", { id, decision });
    native.haptic();
  };
  const paintAsks = () => asksBox.replaceChildren(...asks.map((a) => h("div", { class: "card m-ask" },
    h("div", { class: "m-ask-head" }, icon("terminal-window", "ph-fill"), h("div", {}, h("strong", {}, `${a.project} chce:`), h("span", {}, a.label))),
    h("div", { class: "btn-row" },
      h("button", { class: "btn danger", type: "button", onclick: () => decideClaude(a.id, "deny") }, "Zamítnout"),
      h("button", { class: "btn primary", type: "button", onclick: () => decideClaude(a.id, "allow", a.label) }, icon("fingerprint"), "Povolit")))));
  const header = h("header", { class: "m-head" },
    h("button", { class: "icon-btn", type: "button", "aria-label": "Konverzace", onclick: openDrawer }, icon("list")),
    h("div", { class: "m-title" }, orb, h("div", {}, h("strong", {}, "JARVIS"), status)),
    stop,
    h("button", { class: "icon-btn", type: "button", "aria-label": "Nová konverzace", onclick: () => c.send("new_chat") }, icon("note-pencil")));

  const views: Record<string, HTMLElement> = {
    chat: h("section", { class: "m-view m-chat" }, asksBox, taskCard.el, chat.el),
    control: controlView(c),
    more: moreView(c, ep, pairing),
  };
  const tabs = h("nav", { class: "tabs" },
    ...([["chat", "chat-circle-dots", "Chat"], ["control", "game-controller", "Ovládání"], ["more", "dots-three-circle", "Více"]] as const)
      .map(([k, ic, label]) => h("button", { type: "button", "data-tab": k, onclick: () => show(k) }, icon(ic), h("span", {}, label))));
  const show = (k: string) => {
    Object.entries(views).forEach(([n, el]) => (el.hidden = n !== k));
    tabs.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.tab === k));
    native.haptic();
  };
  app.replaceChildren(h("div", { class: "m-shell" }, header, ...Object.values(views), tabs), drawer, scrim);
  show("chat");

  c.onStatus((s) => {
    status.textContent = s === "open" ? "připojeno k PC" : s === "connecting" ? "připojuji…" : "odpojeno, zkouším znovu…";
    if (s !== "open") face.setMood("offline");
  });
  c.on("welcome", (m) => {
    asks = m.claude_pending || [];
    paintAsks();
    applyAppearance(m.settings);
    face.setMood(m.mood?.mood || "idle");
    if (m.settings?.character) { face.setColor(m.settings.character.color, m.settings.character.glow || undefined); face.setOutfit(m.settings.character.outfit); }
  });
  c.on("settings_changed", (m) => applyAppearance(m.settings));
  c.on("mood", (m) => {
    face.setMood(m.mood, { badge: m.badge, progress: m.progress });
    stop.hidden = !["listening", "thinking", "working", "speaking", "waiting"].includes(m.mood);
  });
  c.on("stopped", () => { toast("Zastaveno.", "ok"); native.haptic(); });
  c.on("notify", (m) => {
    if (document.hidden) native.notify(m.title, m.body);
    else toast(`${m.title}: ${m.body}`, "info", 6000);
    native.haptic();
  });
  c.on("assistant_done", (m) => { if (document.hidden) native.notify("JARVIS", String(m.text).slice(0, 180)); });
  c.on("confirm_request", (m) => { if (document.hidden) native.notifyApproval("JARVIS potřebuje potvrzení", m.description, { kind: "jarvis", id: m.id, label: m.description }); native.haptic(); });
  c.on("claude_permission", (m) => {
    asks.push(m); paintAsks(); show("chat"); native.haptic();
    if (document.hidden) native.notifyApproval(`Claude Code · ${m.project} čeká`, m.label, { kind: "claude", id: m.id, label: m.label });
  });
  c.on("claude_permission_resolved", (m) => { asks = asks.filter((a) => a.id !== m.id); paintAsks(); });
  native.onApprovalAction(async (action, extra) => {
    if (action !== "allow" && action !== "deny") return;
    if (extra.kind === "claude") return decideClaude(extra.id, action, extra.label);
    if (action === "allow" && !(await native.verify(extra.label || "Potvrdit akci"))) return;
    c.send("confirm_response", { id: extra.id, approved: action === "allow" });
  });
  c.on("error", (m) => {
    if (m.auth) { savePairing(null); connectScreen(null, "Token už neplatí. Spáruj telefon znovu."); }
  });
  c.connect();

  // Re-resolve host when the network changes (Wi-Fi ↔ mobile data)
  native.onResume(async () => {
    if (c.status === "open") return;
    const again = await resolveEndpoint(pairing);
    if (again && again.base !== c.ep.base) mainScreen(again, pairing);
  });

  native.onShare(async (ev) => {
    show("chat");
    const urls = ev.texts.filter((t) => /^https?:\/\//.test(t.trim()));
    for (const u of urls) c.send("share", { kind: "url", value: u.trim() });
    const plain = ev.texts.filter((t) => !urls.includes(t));
    if (plain.length) c.send("share", { kind: "text", value: plain.join("\n") });
    for (const f of ev.files) {
      try {
        const blob = await native.readShared(f);
        const att = await c.upload(blob, f.name);
        c.send("share", { kind: "file", attachment_id: att.id });
      } catch (e: any) {
        toast(`${f.name}: ${e.message}`, "error");
      }
    }
  });
}

// ---------------- control tab ----------------
function controlView(c: JarvisClient): HTMLElement {
  const quick = (action: string, args: any = {}, confirmed = false) => { native.haptic(); c.send("quick_action", { action, args, confirmed }); };
  c.on("quick_result", (m) => {
    if (m.needs_confirm && confirm(`${m.summary}: ${m.action}?`)) quick(m.action, lastArgs[m.action] || {}, true);
  });
  const lastArgs: Record<string, any> = {};
  const danger = (action: string, args: any) => { lastArgs[action] = args; quick(action, args); };

  const vol = h("input", { type: "range", min: 0, max: 100, value: 50, "aria-label": "Hlasitost PC" }) as HTMLInputElement;
  vol.onchange = () => quick("volume", { action: "set", level: Number(vol.value) });

  // push-to-talk: hold to record, release to send
  const rec = new Recorder();
  const ptt = h("button", { class: "ptt", type: "button", "aria-label": "Podrž a mluv" }, icon("microphone", "ph-fill"), h("span", {}, "Podrž a mluv"));
  const start = async (e: Event) => {
    e.preventDefault();
    try { await rec.start(); ptt.classList.add("rec"); native.haptic(); } catch { toast("Nemám přístup k mikrofonu", "error"); }
  };
  const stop = async () => {
    if (!rec.active) return;
    ptt.classList.remove("rec");
    const blob = await rec.stop();
    if (!blob || blob.size < 1500) return;
    try {
      const att = await c.upload(blob, `hlas.${blob.type.includes("mp4") ? "m4a" : "webm"}`);
      c.send("voice_upload", { attachment_id: att.id });
      toast("Odesláno", "ok", 1200);
    } catch (e: any) { toast(e.message, "error"); }
  };
  ptt.addEventListener("pointerdown", start);
  ptt.addEventListener("pointerup", stop);
  ptt.addEventListener("pointerleave", stop);
  ptt.addEventListener("contextmenu", (e) => e.preventDefault());

  const yt = h("input", { class: "input", placeholder: "Co pustit na YouTube?", enterkeyhint: "go" }) as HTMLInputElement;
  const playYt = () => { if (yt.value.trim()) { quick("youtube_play", { query: yt.value.trim() }); yt.value = ""; } };
  yt.addEventListener("keydown", (e) => e.key === "Enter" && playYt());
  const app_ = h("input", { class: "input", placeholder: "Otevřít aplikaci na PC (Spotify, Discord…)", enterkeyhint: "go" }) as HTMLInputElement;
  app_.addEventListener("keydown", (e) => { if (e.key === "Enter" && app_.value.trim()) { quick("open_app", { name: app_.value.trim() }); app_.value = ""; } });

  const tile = (ic: string, label: string, fn: () => void, cls = "") =>
    h("button", { class: `ctl ${cls}`, type: "button", onclick: fn }, icon(ic), h("span", {}, label));

  return h("section", { class: "m-view m-control", hidden: true },
    ptt,
    h("div", { class: "card" }, h("h2", {}, "Média"),
      h("div", { class: "media-row" },
        tile("skip-back", "Předchozí", () => quick("media_control", { action: "previous" })),
        tile("play-pause", "Play / pauza", () => quick("media_control", { action: "play_pause" }), "primary"),
        tile("skip-forward", "Další", () => quick("media_control", { action: "next" }))),
      h("div", { class: "vol" }, icon("speaker-low"), vol, icon("speaker-high")),
      h("div", { class: "media-row" },
        tile("speaker-slash", "Ztlumit", () => quick("volume", { action: "mute" })),
        tile("speaker-simple-high", "Zvuk", () => quick("volume", { action: "unmute" })))),
    h("div", { class: "card" }, h("h2", {}, "Pustit a otevřít"),
      h("div", { class: "inline" }, yt, h("button", { class: "btn primary", type: "button", onclick: playYt }, icon("youtube-logo"))),
      app_),
    h("div", { class: "card" }, h("h2", {}, "Počítač"),
      h("div", { class: "ctl-grid" },
        tile("camera", "Screenshot", () => c.send("user_text", { text: "Pošli mi screenshot obrazovky", attachments: [] })),
        tile("lock", "Zamknout", () => quick("system_power", { action: "lock" })),
        tile("moon", "Tmavý režim", () => quick("set_dark_mode", { dark: true })),
        tile("sun", "Světlý režim", () => quick("set_dark_mode", { dark: false })),
        tile("browsers", "Plocha", () => quick("window_control", { action: "minimize_all" })),
        tile("timer", "Minutka 10 min", () => quick("set_timer", { seconds: 600, label: "10 min" })),
        tile("moon-stars", "Uspat", () => danger("system_power", { action: "sleep" }), "warn"),
        tile("power", "Vypnout", () => danger("system_power", { action: "shutdown" }), "warn"))));
}

// ---------------- more tab ----------------
function moreView(c: JarvisClient, ep: { base: string }, p: Pairing): HTMLElement {
  const notif = h("input", { type: "checkbox", role: "switch", "aria-label": "Notifikace" }) as HTMLInputElement;
  notif.checked = localStorage.getItem("jarvis.notify") !== "0";
  notif.onchange = async () => {
    localStorage.setItem("jarvis.notify", notif.checked ? "1" : "0");
    if (notif.checked) await native.askNotifyPermission();
  };
  return h("section", { class: "m-view m-more", hidden: true },
    h("div", { class: "card" }, h("h2", {}, "Připojení"),
      h("div", { class: "kv" }, h("span", {}, "PC"), h("b", { class: "mono" }, ep.base.replace("http://", ""))),
      h("div", { class: "kv" }, h("span", {}, "Známé adresy"), h("b", { class: "mono" }, p.hosts.join(", "))),
      h("p", { class: "help" }, "Mimo domov se připojíš přes Tailscale (zdarma). Nainstaluj ho na PC i telefon a přihlas se stejným účtem."),
      h("div", { class: "btn-row" },
        h("button", { class: "btn", type: "button", onclick: () => location.reload() }, icon("arrows-clockwise"), "Znovu připojit"),
        h("button", { class: "btn danger", type: "button", onclick: () => { if (confirm("Odpojit a zapomenout tohle PC?")) { savePairing(null); c.close(); connectScreen(); } } }, icon("link-break"), "Odpárovat"))),
    h("div", { class: "card" }, h("h2", {}, "Telefon"),
      h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Notifikace z PC"), h("span", {}, "Časovače, připomínky, odpovědi na pozadí")),
        h("label", { class: "switch" }, notif, h("span"))),
      h("p", { class: "help" }, "Tip: v jakékoli aplikaci dej Sdílet → JARVIS a odkaz se otevře na PC, soubor přistane v polici notche.")),
    h("div", { class: "card" }, h("h2", {}, "O aplikaci"), h("p", { class: "help" }, "JARVIS 2 · nastavení najdeš na PC v okně JARVIS.")));
}
