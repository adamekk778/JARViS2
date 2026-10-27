import { applyAppearance } from "../shared/base";
import { setApproveGuard } from "../shared/approve";
import "./style.css";
import { ChatView, conversationList } from "../shared/chat";
import { h, icon, toast } from "../shared/dom";
import { Recorder } from "../shared/recorder";
import { JarvisClient } from "../shared/ws";
import { loadPairing, parsePairing, resolveEndpoint, savePairing, type Pairing } from "./connect";
import { native, type PhoneStatus } from "./native";
import { Blob } from "../character/blob";
import { stopButton, TaskCard } from "../shared/taskcard";
import { confirmCommand, guestView, parseCommandLink, pcFilesCard, photoCard, photoRequests, placesCard, scanCommand, sendPhoto } from "./devices";
import { keepVoice, loadOutbox, persistentOutbox } from "./offline";

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
  let waiting = loadOutbox().length;
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
    home: homeView(c),
    more: moreView(c, ep, pairing),
  };
  views.more.prepend(screenCard(c, ep), mochiCard(c));
  document.querySelectorAll(".m-mochi, .m-handoff-layer").forEach((e) => e.remove());
  app.after(mochiHere(c), handoffLayer(c));          // OMEGA 195 / 083
  const tabs = h("nav", { class: "tabs" },
    ...([["chat", "chat-circle-dots", "Chat"], ["control", "game-controller", "Ovládání"], ["home", "house-line", "Domov"], ["more", "dots-three-circle", "Více"]] as const)
      .map(([k, ic, label]) => h("button", { type: "button", "data-tab": k, onclick: () => show(k) }, icon(ic), h("span", {}, label))));
  const show = (k: string) => {
    Object.entries(views).forEach(([n, el]) => (el.hidden = n !== k));
    tabs.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.tab === k));
    native.haptic();
  };
  app.replaceChildren(h("div", { class: "m-shell" }, header, ...Object.values(views), tabs), drawer, scrim);
  show("chat");

  // 3.4 phone link: keep the phone reachable for JARVIS (ring, dial, SMS) and answer his calls
  if (native.phone.available) {
    native.phone.configure({ base: ep.base, token: ep.token, enabled: localStorage.getItem("jarvis.link") !== "0" }).catch(() => {});
    native.phone.onReply(() => { show("chat"); chat.focus(); toast("Řekni nebo napiš JARVISovi odpověď", "ok", 3500); });
    c.on("phone_cmd", async (cmd) => {
      try {
        const r = await native.phone.handle(cmd);
        if (r.state !== "ringing") c.send("phone_ack", { id: cmd.id, state: r.state });
      } catch (e: any) { c.send("phone_ack", { id: cmd.id, state: "error", detail: String(e?.message || e) }); }
    });
  }

  function paintStatus() {
    const s = c.status;
    status.textContent = (s === "open" ? "připojeno k PC" : s === "connecting" ? "připojuji…" : "odpojeno, zkouším znovu…")
      + (waiting ? ` · ${waiting} čeká na odeslání` : "");
  }
  c.onStatus((s) => {
    paintStatus();
    if (s !== "open") face.setMood("offline");
  });
  // OMEGA 725: what is written or said offline waits on the phone (status line shows how much)
  persistentOutbox(c, (n) => {
    if (n > waiting) toast("PC teď není dostupné – pošlu to, až se ozve.", "info", 2500);
    waiting = n;
    paintStatus();
  });
  photoRequests(c, asksBox, () => show("chat"));

  // OMEGA 136 / 722: the home-screen widget follows what JARVIS does, the mission and the pins
  const MOOD_TEXT: Record<string, string> = { idle: "Připraven", listening: "Poslouchá…", thinking: "Přemýšlí…", working: "Pracuje…",
    speaking: "Mluví…", waiting: "Čeká na potvrzení", error: "Něco se nepovedlo", offline: "PC je nedostupné", sleeping: "Odpočívá",
    success: "Hotovo", joy: "Připraven", notify: "Má pro tebe zprávu", focus: "Režim soustředění", dancing: "Hraje hudba", limit: "Limit AI" };
  const widget = { status: "", task: "", pins: "" };
  let widgetTimer = 0;
  const pushWidget = (o: Partial<typeof widget>) => {
    Object.assign(widget, o);
    window.clearTimeout(widgetTimer);
    widgetTimer = window.setTimeout(() => native.widget(widget), 800);
  };
  const pinsText = (items: any[]) => (items || []).slice(0, 3).map((p: any) => `• ${p.text}`).join("\n");
  const taskText = (t: any) => (t && ["running", "paused", "waiting"].includes(t.status) ? `Úkol: ${t.goal || t.title || ""}` : "");
  c.on("pins", (m) => pushWidget({ pins: pinsText(m.items) }));
  c.on("task_update", (m) => pushWidget({ task: taskText(m.task) }));
  c.onStatus((s) => { if (s !== "open") pushWidget({ status: MOOD_TEXT.offline }); });

  // OMEGA 734: on a low battery the app goes quiet – no animations, no haptics, no live audio level from the PC
  native.onBattery((low) => {
    native.lowPower = low;
    document.documentElement.dataset.lowpower = low ? "1" : "";
    if (low) document.documentElement.dataset.motion = "reduced";
    c.send("client_state", { low_power: low });
  });

  // jarvis:// links – the widget, app shortcuts and command QR codes (a command is always shown before it is sent)
  native.onLink((url) => {
    const cmd = parseCommandLink(url);
    if (cmd) { show("chat"); confirmCommand(c, cmd); return; }
    const what = url.replace(/^jarvis:\/\/open\/?/, "");
    if (what === "talk") { show("control"); toast("Podrž mikrofon a mluv", "info", 2500); }
    else if (what === "chat") { show("chat"); chat.focus(); }
    else if (what === "photo") { show("control"); sendPhoto(c, "shelf"); }
    else if (what === "scan") scanCommand(c);
  });
  c.on("welcome", (m) => {
    if (m.guest) { app.replaceChildren(guestView(c, m.guest)); return; }     // OMEGA 727: a temporary guest pairing
    pushWidget({ status: MOOD_TEXT[m.mood?.mood] || "Připraven", task: taskText(m.task), pins: pinsText(m.pins) });
    asks = m.claude_pending || [];
    paintAsks();
    applyAppearance(m.settings);
    face.setMood(m.mood?.mood || "idle", m.mood || {});
    if (m.settings?.character) { face.setColor(m.settings.character.color, m.settings.character.glow || undefined); face.setOutfit(m.settings.character.outfit); face.setCharacter(m.settings.character); }
  });
  c.on("settings_changed", (m) => { applyAppearance(m.settings); if (native.lowPower) document.documentElement.dataset.motion = "reduced"; });
  c.on("mood", (m) => {
    pushWidget({ status: MOOD_TEXT[m.mood] || "Připraven" });
    face.setMood(m.mood, m);
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
    const name = `hlas.${blob.type.includes("mp4") ? "m4a" : "webm"}`;
    if (c.status !== "open") {          // OMEGA 725: no PC right now – keep it on the phone and send it later
      try { await keepVoice(blob, name); toast("PC teď není dostupné – nahrávku pošlu, až se ozve.", "info", 2500); } catch { toast("Nahrávku se nepodařilo uložit", "error"); }
      return;
    }
    try {
      const att = await c.upload(blob, name);
      c.send("voice_upload", { attachment_id: att.id });
      toast("Odesláno", "ok", 1200);
    } catch (e: any) {
      try { await keepVoice(blob, name); toast("Nepodařilo se odeslat – zkusím to znovu, až bude PC dostupné.", "info", 2500); } catch { toast(e.message, "error"); }
    }
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

  // 3.2 protocols: one tap runs "Párty", "Dobrou noc"… on the PC
  const protoBox = h("div", { class: "ctl-grid" });
  const renderProtos = (st: any) => protoBox.replaceChildren(...(st?.stark?.protocols || []).map((p: any) =>
    tile(p.icon || "lightning", p.name, () => { native.haptic(); c.send("protocol_run", { id: p.id }); toast(`Protokol ${p.name}`, "ok", 1400); })));
  c.on("welcome", (m) => renderProtos(m.settings));
  c.on("settings_changed", (m) => renderProtos(m.settings));

  return h("section", { class: "m-view m-control", hidden: true },
    ptt,
    photoCard(c),
    h("div", { class: "card" }, h("h2", {}, "Protokoly"), protoBox),
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

// ---------------- 3.5 Domov: shared lists (shopping in the shop) and the smart home ----------------
function homeView(c: JarvisClient): HTMLElement {
  let lists: Record<string, string[]> = {};
  let current = "nákup";
  const listBox = h("div", { class: "m-list" });
  const addInp = h("input", { class: "input", placeholder: "Přidat na seznam…", enterkeyhint: "done", "aria-label": "Nová položka" }) as HTMLInputElement;
  const add = () => {
    const items = addInp.value.split(",").map((x) => x.trim()).filter(Boolean);
    if (items.length) { c.send("list_update", { list: current, add: items }); addInp.value = ""; native.haptic(); }
  };
  addInp.addEventListener("keydown", (e) => e.key === "Enter" && add());
  const paintLists = () => {
    const names = Array.from(new Set(["nákup", ...Object.keys(lists)]));
    const items = lists[current] || [];
    listBox.replaceChildren(
      h("div", { class: "m-chips" }, ...names.map((n) => h("button", { type: "button", class: `chip ${n === current ? "on" : ""}`,
        onclick: () => { current = n; paintLists(); } }, n, lists[n]?.length ? ` · ${lists[n].length}` : ""))),
      h("ul", { class: "m-items" }, ...(items.length ? items.map((it) => h("li", {}, h("button", { type: "button", class: "m-item",
        onclick: (e: Event) => { (e.currentTarget as HTMLElement).classList.add("done"); native.haptic(); setTimeout(() => c.send("list_update", { list: current, remove: [it] }), 250); } },
        icon("circle"), h("span", {}, it))))
        : [h("li", { class: "muted" }, "Prázdný seznam. Řekni JARVISovi „přidej mléko na nákup“.")])),
      h("div", { class: "inline" }, addInp, h("button", { class: "btn primary", type: "button", "aria-label": "Přidat", onclick: add }, icon("plus"))));
  };
  c.on("lists", (m) => { lists = m.lists || {}; paintLists(); });

  const homeBox = h("div", { class: "ctl-grid" });
  const homeCard = h("div", { class: "card", hidden: true }, h("h2", {}, "Chytrá domácnost"), homeBox);
  const icons: Record<string, string> = { light: "lightbulb", switch: "plug", fan: "fan", scene: "magic-wand", script: "play", input_boolean: "toggle-right", media_player: "speaker-high" };
  c.on("home", (m) => {
    const ds = (m.devices || []).filter((d: any) => icons[d.domain]);
    homeCard.hidden = !m.configured || !ds.length;
    homeBox.replaceChildren(...ds.slice(0, 30).map((d: any) => h("button", { type: "button", class: `ctl ${["on", "playing"].includes(d.state) ? "primary" : ""}`,
      onclick: () => { native.haptic(); c.send("home_action", { id: d.id, action: d.domain === "scene" || d.domain === "script" ? "on" : "toggle" }); } },
      icon(icons[d.domain], ["on", "playing"].includes(d.state) ? "ph-fill" : ""), h("span", {}, d.name))));
  });
  c.on("welcome", (m) => { c.send("lists_get", {}); if (m.settings?.home?.url) c.send("home_get", {}); });
  paintLists();
  return h("section", { class: "m-view m-home", hidden: true },
    h("div", { class: "card" }, h("h2", {}, "Seznamy"), listBox),
    homeCard);
}

// ---------------- 3.4 phone link: JARVIS calls you, dials, SMS, WhatsApp, your messages on the PC ----------------
function phoneCard(c: JarvisClient): HTMLElement {
  if (!native.phone.available) return h("p", { class: "help" }, "Volání, SMS a zprávy z telefonu fungují v aplikaci JARVIS pro Android.");
  const box = h("div", { class: "m-phone" });
  const sw = (on: boolean, fn: (v: boolean) => void, label: string) => {
    const inp = h("input", { type: "checkbox", role: "switch", "aria-label": label }) as HTMLInputElement;
    inp.checked = on;
    inp.onchange = () => fn(inp.checked);
    return h("label", { class: "switch" }, inp, h("span"));
  };
  const step = (ok: boolean, title: string, desc: string, action: string, fn: () => void) =>
    h("div", { class: `row m-step ${ok ? "ok" : ""}` }, icon(ok ? "check-circle" : "circle", ok ? "ph-fill" : ""),
      h("div", { class: "row-text" }, h("strong", {}, title), h("span", {}, desc)),
      ok ? null : h("button", { class: "btn sm", type: "button", onclick: fn }, action));
  const render = (st: PhoneStatus) => box.replaceChildren(
    h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Spojení na pozadí"),
      h("span", {}, st.running ? "Běží – JARVIS ti může zavolat i se zavřenou aplikací." : "Vypnuto – JARVIS tě zastihne, jen když máš aplikaci otevřenou.")),
      sw(st.enabled, async (v) => { localStorage.setItem("jarvis.link", v ? "1" : "0"); render(await native.phone.configure({ enabled: v })); }, "Spojení na pozadí")),
    step(st.phone, "Volání, SMS a kontakty", "„Zavolej mámě“, „pošli SMS…“", "Povolit", async () => render(await native.phone.requestPhone())),
    step(st.fullScreen, "Zvonění přes zamčenou obrazovku", "Aby JARVISův hovor zazvonil jako opravdový.", "Nastavit", () => native.phone.openFullScreen()),
    step(st.overlay, "Volat a ukázat hovor hned", "„Zobrazovat přes jiné aplikace“ – JARVIS vytočí číslo bez klepnutí.", "Povolit", () => native.phone.openOverlay()),
    step(st.battery, "Bez uspávání baterií", "Jinak Android spojení v noci uspí.", "Povolit", () => native.phone.openBattery()),
    h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Zprávy z telefonu na PC"),
      h("span", {}, st.notifAccess ? "JARVIS ti na PC řekne, kdo ti píše (WhatsApp, SMS, Messenger…) a kdo volá."
        : "Vyžaduje povolit „Přístup k oznámením“ pro JARVIS.")),
      st.notifAccess ? sw(st.mirror, async (v) => render(await native.phone.configure({ mirror: v })), "Zprávy z telefonu na PC")
        : h("button", { class: "btn sm", type: "button", onclick: () => native.phone.openNotificationAccess() }, "Povolit")),
    h("div", { class: "btn-row" }, h("button", { class: "btn", type: "button", onclick: () => {
      c.send("quick_action", { action: "call_me", args: { message: "Dobrý den, pane. Tady JARVIS. Zkouška spojení proběhla v pořádku, umím vám zavolat." } });
      toast("JARVIS za chvilku zavolá", "ok");
    } }, icon("phone-call"), "Vyzkoušet hovor od JARVISe")));
  const refresh = () => native.phone.status().then(render).catch(() => {});
  refresh();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });   // back from Android settings
  return box;
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
      phoneCard(c),
      h("p", { class: "help" }, "Tip: v jakékoli aplikaci dej Sdílet → JARVIS a odkaz se otevře na PC, soubor přistane v polici notche. "
        + "Dlouhým podržením ikony JARVIS máš zkratky (Mluvit, Napsat, Fotka na PC) a na plochu si můžeš přidat widget.")),
    pcFilesCard(c),
    placesCard(c),
    h("div", { class: "card" }, h("h2", {}, "O aplikaci"), h("p", { class: "help" }, "JARVIS 2 · nastavení najdeš na PC v okně JARVIS.")));
}


/** OMEGA P9.08: the PC screen, live, while sharing is switched on on the PC (it asks there first). */
function screenCard(c: JarvisClient, ep: { base: string; token: string }): HTMLElement {
  const img = h("img", { class: "m-screen", alt: "Obrazovka PC" }) as HTMLImageElement;
  const note = h("p", { class: "help" }, "Sdílení musíš potvrdit a po čase se samo vypne.");
  const btn = h("button", { class: "btn primary", type: "button" }, icon("monitor"), "Požádat o obrazovku") as HTMLButtonElement;
  let on = false;
  const paint = () => {
    img.hidden = !on;
    btn.replaceChildren(icon(on ? "stop-circle" : "monitor"), on ? "Přestat sdílet" : "Požádat o obrazovku");
    img.src = on ? `${ep.base}/api/screen/stream?token=${encodeURIComponent(ep.token)}&t=${Date.now()}` : "";
  };
  btn.onclick = () => c.send("user_text", { text: on ? "přestaň sdílet obrazovku" : "sdílej obrazovku na telefon na 15 minut", attachments: [] });
  c.on("screen_share", (m) => { on = !!m.active; note.textContent = on ? "Vidíš obrazovku PC. Soukromá okna jsou zakrytá." : "Sdílení musíš potvrdit a po čase se samo vypne."; paint(); });
  paint();
  return h("div", { class: "card" }, h("h2", {}, "Obrazovka PC"), img, note, h("div", { class: "btn-row" }, btn));
}


/** OMEGA 195: Mochi can come over to the phone (and the notch shows an empty seat) – and go back. */
function mochiCard(c: JarvisClient): HTMLElement {
  return h("div", { class: "card" }, h("h2", {}, "Mochi"),
    h("p", { class: "help" }, "Vezmi si postavičku s sebou: na telefonu bude ve stejné náladě, na PC zůstane prázdné místo."),
    h("div", { class: "btn-row" },
      h("button", { class: "btn primary", type: "button", onclick: () => c.send("mochi_move", { to: "phone" }) }, icon("arrow-fat-line-down"), "Mochi na telefon"),
      h("button", { class: "btn", type: "button", onclick: () => c.send("mochi_move", { to: "pc" }) }, icon("desktop"), "Zpátky na PC")),
    oneHandRow());
}

function mochiHere(c: JarvisClient): HTMLElement {
  const blob = new Blob({ size: 72 });
  const box = h("div", { class: "m-mochi", hidden: true, title: "Mochi – ťukni, dvakrát pošle zpátky na PC" }, blob.el);
  let last = 0;
  box.addEventListener("click", () => {
    if (Date.now() - last < 350) { c.send("mochi_move", { to: "pc" }); return; }
    last = Date.now();
    const r = blob.poke();
    if (r) blob.setMood(r);
    native.haptic();
  });
  c.on("mochi_where", (m) => { box.hidden = m.at !== "phone"; if (m.mood) blob.setMood(m.mood); });
  c.on("mood", (m) => { if (!box.hidden && m.mood) blob.setMood(m.mood, m); });
  return box;
}

/** OMEGA 083: what the PC sent flies in from the top (and what you sent to the PC flies up and away). */
function handoffLayer(c: JarvisClient): HTMLElement {
  const layer = h("div", { class: "m-handoff-layer", "aria-live": "polite" });
  c.on("handoff", (m) => {
    const chip = h("div", { class: `m-handoff ${m.to === "phone" ? "in" : "out"}` }, icon(m.kind === "mochi" ? "smiley" : m.kind === "file" ? "file" : "link"),
      h("span", {}, m.to === "phone" ? `Z PC: ${m.label}` : `Na PC: ${m.label}`));
    layer.append(chip);
    native.haptic();
    window.setTimeout(() => chip.remove(), 1800);
  });
  return layer;
}

/** OMEGA 789: one-handed use – everything you tap moves down and towards your thumb. */
function oneHandRow(): HTMLElement {
  const sel = h("select", { class: "input", "aria-label": "Ovládání jednou rukou" },
    h("option", { value: "" }, "Obě ruce"), h("option", { value: "right" }, "Jedna ruka – pravá"), h("option", { value: "left" }, "Jedna ruka – levá")) as HTMLSelectElement;
  const apply = (v: string) => { document.documentElement.dataset.hand = v; try { localStorage.setItem("jarvis.hand", v); } catch { /* private mode */ } };
  try { sel.value = localStorage.getItem("jarvis.hand") || ""; } catch { /* ignore */ }
  apply(sel.value);
  sel.onchange = () => apply(sel.value);
  return h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Ovládání jednou rukou"),
    h("span", {}, "Tlačítka se přesunou dolů k palci, na stranu ruky, kterou držíš telefon.")), sel);
}
