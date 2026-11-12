import { applyAppearance } from "../shared/base";
import { setApproveGuard } from "../shared/approve";
import "./style.css";
import { ChatView, conversationList } from "../shared/chat";
import { h, icon, toast } from "../shared/dom";
import { Recorder } from "../shared/recorder";
import { JarvisClient } from "../shared/ws";
import { loadPairing, parsePairing, refreshLink, resolveEndpoint, savePairing, type Pairing } from "./connect";
import { startUpdateCheck } from "./update";
import { native, type BackupStatus, type PhoneStatus } from "./native";
import { Blob } from "../character/blob";
import { stopButton, TaskCard } from "../shared/taskcard";
import { clipHistoryCard, confirmCommand, guestView, lanSpeedCard, parseCommandLink, pcFilesCard, pcStatusCard, photoCard, photoRequests, placesCard, scanCommand, sendPhoto } from "./devices";
import { keepVoice, loadOutbox, persistentOutbox } from "./offline";
import { soloProvider, soloScreen } from "./solo";
import { flingPad } from "./fling";
import { openRemote } from "./remote";
import { phoneBackground, phoneClock, phoneEyes, phoneLookCard, phoneMusic } from "./phonelook";

const bigFace = (size: number) => { const b = new Blob({ size }); b.setMood("idle"); return b.el; };

const app = document.getElementById("app")!;
let client: JarvisClient | null = null;
let sendToPc: () => void = () => {};           // 3.12 opens the swipe-to-PC sheet (set once the PC is connected)

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
  startUpdateCheck();                                   // 3.12 a newer app → one tap to update
  const p = loadPairing();
  if (!p) return connectScreen();
  app.replaceChildren(h("div", { class: "splash" }, bigFace(96), h("p", {}, "Hledám tvoje PC…")));
  const ep = await resolveEndpoint(p);
  if (!ep) {
    if (soloProvider()) return solo();                 // 3.12 the PC is off: the phone answers by itself
    return connectScreen(p, p.link?.enabled
      ? "PC není dostupné ani přes JARVIS Link. Běží JARVIS na PC a je zapnutý?"
      : "PC není dostupné. Jsi na stejné Wi-Fi? Mimo domov zapni na PC JARVIS Link (Nastavení → Telefon).");
  }
  mainScreen(ep, p);
}

/** 3.12 Zapnout PC z telefonu: the wake packet, then look for the PC for ~2 minutes and connect when it answers. */
let waking = false;
async function wakePc(connect = true) {
  if (waking) return;
  const r = await native.phone.wakePc().catch((e: any) => ({ ok: false, error: String(e?.message || e) } as { ok: boolean; via?: string; relay?: string; error?: string }));
  if (!r.ok) {
    toast(r.error || (r.relay === "ERR nohome" ? "Relay ještě nezná tvůj domov – PC se k němu musí jednou připojit." : "Budicí signál se nepovedlo poslat."), "error", 6000);
    return;
  }
  toast(`Budím PC${r.via?.includes("relay") ? " (i přes relay)" : ""}… za chvilku se připojím`, "ok", 4000);
  native.haptic();
  if (!connect) return;
  waking = true;
  try {
    for (let i = 0; i < 8; i++) {
      await new Promise((ok) => setTimeout(ok, 12000));
      const p = loadPairing();
      const ep = p && (await resolveEndpoint(p));
      if (ep && p) { toast("PC je vzhůru", "ok"); mainScreen(ep, p); return; }
    }
    toast("PC se zatím neozvalo. Na PC v Nastavení → Telefon → Zapnout PC z telefonu zjistíš, co mu chybí.", "info", 7000);
  } finally {
    waking = false;
  }
}

/** 3.12 phone-only mode: a free AI straight from the phone until the PC answers again */
function solo() {
  client?.close();
  client = null;
  soloScreen(app, {
    retry: async () => {
      const p = loadPairing();
      const ep = p && (await resolveEndpoint(p));
      if (!ep || !p) return false;
      toast("PC je zpět – přepínám na plného JARVISe", "ok");
      mainScreen(ep, p);
      return true;
    },
    pair: () => connectScreen(loadPairing()),
    wake: native.phone.available ? () => wakePc(true) : undefined,
  });
}

// ---------------- 3.12 shared clipboard: what you copied on the phone goes to the PC when you open JARVIS ----------------
let clipSync = false;
let clipSent = "";
let clipImgSent = "";
function shareClipboard(c: JarvisClient) {
  c.on("welcome", (m) => { clipSync = !!m.clip_sync; sendClip(); });
  c.on("clip_sync", (m) => { clipSync = !!m.on; });
  const sendClip = async () => {
    if (!clipSync || document.hidden || !native.isNative) return;
    const r = await native.phone.readClipboard().catch(() => null);
    // 3.12 a copied picture → the PC's clipboard (once per picture)
    if (r?.image && r.imageId && r.imageId !== clipImgSent) {
      clipImgSent = r.imageId;
      try {
        const bin = Uint8Array.from(atob(r.image), (ch) => ch.charCodeAt(0));
        const type = r.imageType || "image/png";
        const att = await c.upload(new globalThis.Blob([bin], { type }), `schranka.${type.split("/")[1] || "png"}`);
        c.send("clip_from_phone", { attachment_id: att.id });
        toast("Obrázek je i ve schránce PC", "ok", 1800);
      } catch { /* the PC is not reachable now: next time */ clipImgSent = ""; }
      return;
    }
    const t = (r?.text || "").trim();
    if (!t || t === clipSent || t === (r?.fromPc || "").trim()) return;      // nothing new, or it came from the PC
    clipSent = t;
    c.send("clip_from_phone", { text: t });
    toast("Schránka je i na PC", "ok", 1800);
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) window.setTimeout(sendClip, 400); });
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
    prev && error && native.phone.available ? h("button", { class: "btn primary big", type: "button", onclick: () => wakePc(true) }, icon("power"), "Zapnout PC") : null,
    prev ? h("button", { class: "btn ghost", type: "button", onclick: () => boot() }, icon("arrows-clockwise"), "Zkusit znovu") : null,
    h("div", { class: "solo-entry" },
      h("button", { class: "btn big solo-go", type: "button", onclick: () => solo() }, icon("sparkle", "ph-fill"), "Mluvit bez PC"),
      h("span", {}, "Zdarma přes Groq nebo Gemini, přímo z telefonu"))));
}

// ---------------- main ----------------
function mainScreen(ep: { base: string; token: string }, pairing: Pairing) {
  client?.close();
  const c = new JarvisClient(ep, "mobile", native.deviceName());
  client = c;
  shareClipboard(c);                                 // 3.12 sdílená schránka PC ↔ telefon
  let waiting = loadOutbox().length;
  const chat = new ChatView(c, { compact: true, enterNewline: true, placeholder: "Napiš JARVISovi…" });

  const eyes = phoneEyes();                          // 3.12 the notch's eyes instead of the old orb
  const face = { setMood: (m: string, _x?: unknown) => eyes.set(m), setColor: (..._a: unknown[]) => {}, setOutfit: (_o: unknown) => {}, setCharacter: (_c: unknown) => {} };
  const orb = eyes.el;
  phoneBackground(c);
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
  // 3.12 the swipe-to-PC sheet from the control tab
  views.control.prepend(h("button", { type: "button", class: "fl-entry", onclick: () => sendToPc() },
    h("span", { class: "fl-entry-ico" }, icon("paper-plane-tilt", "ph-fill")),
    h("div", {}, h("strong", {}, "Poslat na PC"), h("span", {}, "Vyber soubor a švihni ho doprava")), icon("caret-right")));
  const clock = phoneClock(c);
  views.home.prepend(clock.el, phoneMusic(c));
  views.more.prepend(phoneLookCard());
  views.more.prepend(screenCard(c, ep), mochiCard(c));
  document.querySelectorAll(".m-mochi, .m-handoff-layer").forEach((e) => e.remove());
  app.after(mochiHere(c), handoffLayer(c));          // OMEGA 195 / 083
  const tabs = h("nav", { class: "tabs" },
    ...([["chat", "chat-circle-dots", "Chat"], ["control", "game-controller", "Ovládání"], ["home", "house-line", "Domov"], ["more", "dots-three-circle", "Více"]] as const)
      .map(([k, ic, label]) => h("button", { type: "button", "data-tab": k, onclick: () => show(k) }, icon(ic), h("span", {}, label))));
  const show = (k: string) => {
    if (k === "home") clock.want();
    Object.entries(views).forEach(([n, el]) => (el.hidden = n !== k));
    tabs.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.tab === k));
    native.haptic();
  };
  app.replaceChildren(h("div", { class: "m-shell" }, header, ...Object.values(views), tabs), drawer, scrim);
  show("chat");

  // 3.4 phone link: keep the phone reachable for JARVIS (ring, dial, SMS) and answer his calls
  if (native.phone.available) {
    native.phone.configure({ base: ep.base, token: ep.token, enabled: localStorage.getItem("jarvis.link") !== "0" }).catch(() => {});
    refreshLink(ep, pairing).then((p) => { pairing = p; });   // 3.12 JARVIS Link: how to reach the PC from outside
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
  let switchTimer = 0;
  c.onStatus((s) => {
    paintStatus();
    if (s !== "open") face.setMood("offline");
    // 3.12 left home (Wi-Fi → mobile data) or came back: after a few seconds offline look for the way that works now
    clearTimeout(switchTimer);
    if (s !== "open") switchTimer = window.setTimeout(async () => {
      if (c.status === "open") return;
      const again = await resolveEndpoint(pairing);
      if (again && again.base !== c.ep.base && (c.status as string) !== "open") mainScreen(again, pairing);
    }, 6000);
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
    try {                                              // 3.12 the phone-only chat knows your name too
      const nm = m.settings?.general?.user_name || "";
      const cfg = JSON.parse(localStorage.getItem("jarvis.solo") || "{}");
      if (nm && cfg.name !== nm) localStorage.setItem("jarvis.solo", JSON.stringify({ ...cfg, name: nm }));
    } catch { /* private */ }
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
  // OMEGA 184: the PC gave this phone its own key – keep it instead of the pairing code (revocable alone)
  c.on("device_token", (m) => {
    if (!m.token) return;
    pairing = { ...pairing, token: m.token };
    savePairing(pairing);
    c.ep.token = m.token;
  });
  c.connect();

  // Re-resolve host when the network changes (Wi-Fi ↔ mobile data)
  native.onResume(async () => {
    if (c.status === "open") return;
    const again = await resolveEndpoint(pairing);
    if (again && again.base !== c.ep.base) mainScreen(again, pairing);
  });

  const fling = flingPad(c);                         // 3.12 "Poslat na PC" by swiping
  sendToPc = () => fling.pick();
  native.onShare(async (ev) => {
    show("chat");
    const urls = ev.texts.filter((t) => /^https?:\/\//.test(t.trim()));
    for (const u of urls) c.send("share", { kind: "url", value: u.trim() });
    const plain = ev.texts.filter((t) => !urls.includes(t));
    if (plain.length) c.send("share", { kind: "text", value: plain.join("\n") });
    // 3.12 shared files wait as cards – swipe them to the right and they fly to the PC
    const got: { blob: globalThis.Blob; name: string }[] = [];
    for (const f of ev.files) {
      try { got.push({ blob: await native.readShared(f), name: f.name }); } catch (e: any) { toast(`${f.name}: ${e.message}`, "error"); }
    }
    if (got.length) fling.add(got);
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
        tile("speaker-simple-high", "Zvuk", () => quick("volume", { action: "unmute" }))),
      pcAudioRow()),
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
        tile("power", "Vypnout", () => danger("system_power", { action: "shutdown" }), "warn"))),
    guardCard(c));
}

// ---------------- 3.12 Zvuk z PC do telefonu ----------------
function pcAudioRow(): HTMLElement | string {
  if (!native.phone.available) return "";
  const btn = h("button", { class: "btn m-pcaudio", type: "button" }) as HTMLButtonElement;
  let on = false;
  const paint = () => btn.replaceChildren(icon(on ? "stop-circle" : "headphones", on ? "ph-fill" : ""),
    on ? "Zastavit zvuk z PC" : "Poslouchat PC v telefonu");
  btn.onclick = async () => {
    native.haptic();
    on = (await native.phone.pcAudio({ on: !on }).catch(() => ({ on: false }))).on;
    paint();
    if (on) toast("Zvuk z PC hraje v telefonu (za pár sekund)", "ok");
  };
  const refresh = () => native.phone.pcAudio({}).then((r) => { on = r.on; paint(); }).catch(() => {});
  paint();
  refresh();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  return h("div", { class: "m-pcaudio-row" }, btn,
    h("p", { class: "help" }, "Hudba, film nebo hra z PC v telefonu a sluchátkách – i v jiné místnosti a mimo domov. Bere se jen zvuk, který PC samo hraje."));
}

// ---------------- 3.12 Hlídání PC: someone uses the PC while you are away → a notice here at once ----------------
function guardCard(c: JarvisClient): HTMLElement {
  const box = h("div", { class: "m-guard" });
  const sw = (on: boolean, fn: (v: boolean) => void, label: string) => {
    const inp = h("input", { type: "checkbox", role: "switch", "aria-label": label }) as HTMLInputElement;
    inp.checked = on;
    inp.onchange = () => fn(inp.checked);
    return h("label", { class: "switch" }, inp, h("span"));
  };
  const time = (t: number) => new Date(t * 1000).toLocaleString("cs-CZ", { weekday: "short", hour: "2-digit", minute: "2-digit" });
  c.on("guard", (g) => {
    if (g.error) toast(g.error, "info");
    const evs: any[] = g.events || [];
    box.replaceChildren(
      h("div", { class: `row m-guard-state ${g.armed ? "on" : ""}` }, icon(g.armed ? "shield-check" : "shield", "ph-fill"),
        h("div", { class: "row-text" }, h("strong", {}, g.armed ? "PC je hlídané" : "Hlídání je vypnuté"),
          h("span", {}, g.armed ? `Od ${time(g.since)}${g.locked ? " · zamčené" : ""}. Když ho někdo odemkne nebo na něj sáhne, hned ti to napíšu.`
            : "Zapni, když od PC odcházíš. Kamera ani mikrofon se nepoužívají.")),
        sw(!!g.armed, (v) => c.send("guard_set", { on: v }), "Hlídat PC")),
      h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Hned znovu zamknout"),
        h("span", {}, "Když někdo hlídané PC odemkne, JARVIS ho okamžitě zase zamkne.")),
        sw(!!g.auto_lock, (v) => c.send("guard_set", { on: !!g.armed, auto_lock: v }), "Hned znovu zamknout")),
      g.armed ? "" : h("button", { class: "btn primary", type: "button", onclick: () => { native.haptic(); c.send("guard_set", { on: true, lock: true }); toast("PC je zamčené a hlídané", "ok"); } },
        icon("lock-key"), "Zamknout a hlídat"),
      ...evs.slice(0, 4).map((e) => h("div", { class: "row m-guard-ev" }, icon("warning-circle", "ph-fill"),
        h("div", { class: "row-text" }, h("strong", {}, e.kind === "unlock" ? "Někdo PC odemkl" : "Někdo PC použil"),
          h("span", {}, `${time(e.t)}${e.locked_again ? " · znovu zamčeno" : ""}`)))));
  });
  c.on("welcome", () => c.send("guard_get", {}));
  return h("div", { class: "card" }, h("h2", {}, "Hlídání PC"), box);
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
    // 3.12 AirDrop-like: knock the phone twice against the monitor (anywhere, also in the gallery) → the newest photo goes
    h("div", { class: "row m-tapdrop" }, h("div", { class: "row-text" }, h("strong", {}, "Ťuk ťuk o monitor → fotka na PC"),
      h("span", {}, st.tapdrop ? (st.photos ? "Zapnuto. Kdekoli (i v galerii) dvakrát ťukni telefonem o monitor a nejnovější fotka nebo screenshot přeskočí na PC."
        : "Povol JARVISovi přístup k fotkám, jinak nemá co poslat.")
        : "Bez otevírání aplikace: dvakrát ťukni telefonem o monitor a poslední fotka přeskočí na PC – jako AirDrop.")),
      st.tapdrop && !st.photos ? h("button", { class: "btn sm", type: "button", onclick: async () => render(await native.phone.requestPhotos()) }, "Povolit fotky")
        : sw(!!st.tapdrop, async (v) => {
          let r = await native.phone.configure({ tapdrop: v, ...(v ? { enabled: true } : {}) });
          if (v) { localStorage.setItem("jarvis.link", "1"); if (!r.photos) r = await native.phone.requestPhotos(); }
          render(r);
        }, "Ťuk o monitor")),
    st.tapdrop && !st.overlay ? h("p", { class: "help" }, "Tip: povol „Zobrazovat přes jiné aplikace“ (výše) a uvidíš i animaci, jak fotka odlétá.") : "",
    // 3.12 Hlas se sluchátky: hold the headphones' button (or "Mluvit" in the notification) → talk → the answer in the headphones
    h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Hlas se sluchátky"),
      h("span", {}, "Podrž tlačítko na sluchátkách (nebo ťukni na „Mluvit“ v oznámení JARVISe), po pípnutí mluv a odpověď uslyšíš ve sluchátkách – i se zamčeným telefonem a mimo domov. Když se Android zeptá, kterou aplikací, vyber JARVIS → Vždy.")),
      h("button", { class: "btn sm", type: "button", onclick: () => native.phone.voiceOpen().catch(() => toast("Nepovedlo se otevřít", "error")) }, icon("headphones"), "Vyzkoušet")),
    // 3.12 Zapnout PC z telefonu
    h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Zapnout PC z telefonu"),
      h("span", {}, st.wake ? "Když je PC vypnuté nebo uspané, ťukni na Zapnout PC – doma vždy, mimo domov přes JARVIS Link s relay serverem. Na PC to musí být povolené (Nastavení → Telefon)."
        : "Otevři aplikaci jednou doma, když PC běží – zapamatuje si, jak ho probudit.")),
      st.wake ? h("button", { class: "btn sm", type: "button", onclick: () => wakePc(false) }, icon("power"), "Zapnout PC") : null),
    // 3.12 the JARVIS tile next to Wi-Fi and the torch: one tap → talk
    h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Dlaždice JARVIS"),
      h("span", {}, "Tlačítko JARVIS ve vysouvací liště (vedle Wi-Fi a baterky): ťukneš a mluvíš – i bez sluchátek a se zamčeným telefonem.")),
      h("button", { class: "btn sm", type: "button", onclick: async () => {
        const r = await native.phone.addTile().catch(() => ({ result: "manual" }));
        if (r.result === "added") toast("Dlaždice JARVIS je ve vysouvací liště", "ok");
        else if (r.result === "manual") toast("Stáhni lištu dolů → ikona tužky → přetáhni dlaždici JARVIS nahoru", "info");
      } }, icon("plus-square"), "Přidat")),
    // 3.12 shared clipboard: copy on the PC → paste on the phone (by itself); copy on the phone → on the PC when you open JARVIS
    h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Sdílená schránka PC ↔ telefon"),
      h("span", {}, "Zkopíruješ na PC, vložíš v telefonu – a naopak (z telefonu se pošle, když otevřeš JARVIS). Text i obrázky a snímky obrazovky, nikdy hesla.")),
      sw(clipSync, (v) => { clipSync = v; c.send("clip_sync_set", { on: v }); if (v) { localStorage.setItem("jarvis.link", "1"); native.phone.configure({ enabled: true }).catch(() => {}); } }, "Sdílená schránka")),
    // 3.12 the notch on the phone: a small island at the top over other apps – what JARVIS does on the PC, a song, a timer
    h("div", { class: "row m-island" }, h("div", { class: "row-text" }, h("strong", {}, "Notch na telefonu"),
      h("span", {}, !st.island ? "Malý ostrůvek nahoře přes ostatní aplikace – jako na PC: co JARVIS dělá, hudba, časovač. Ťuk = otevřít, podržet = mluvit."
        : st.overlay ? "Zapnuto. Když je otevřená aplikace JARVIS, ostrůvek se schová." : "Povol „Zobrazovat přes jiné aplikace“, jinak se nemůže ukázat.")),
      st.island && !st.overlay ? h("button", { class: "btn sm", type: "button", onclick: () => native.phone.openOverlay() }, "Povolit")
        : sw(!!st.island, async (v) => {
          const r = await native.phone.configure({ island: v, ...(v ? { enabled: true } : {}) });
          if (v) { localStorage.setItem("jarvis.link", "1"); if (!r.overlay) native.phone.openOverlay(); }
          render(r);
        }, "Notch na telefonu")),
    h("div", { class: "btn-row" }, h("button", { class: "btn", type: "button", onclick: () => {
      c.send("quick_action", { action: "call_me", args: { message: "Dobrý den, pane. Tady JARVIS. Zkouška spojení proběhla v pořádku, umím vám zavolat." } });
      toast("JARVIS za chvilku zavolá", "ok");
    } }, icon("phone-call"), "Vyzkoušet hovor od JARVISe")));
  const refresh = () => native.phone.status().then(render).catch(() => {});
  refresh();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });   // back from Android settings
  return box;
}

// ---------------- 3.12 Telefon na monitoru PC ----------------
function mirrorCard(): HTMLElement {
  const box = h("div", { class: "m-mirror" });
  let timer = 0;
  const render = (st: { running: boolean; control: boolean }) => {
    clearTimeout(timer);
    if (!document.hidden) timer = window.setTimeout(refresh, st.running ? 3000 : 8000);
    box.replaceChildren(
      h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Telefon na monitoru PC"),
        h("span", {}, st.running ? "Obrazovka se teď zobrazuje na PC. Zastavíš tady nebo v oznámení."
          : "Obrazovka telefonu v okně na PC – klikáš myší, píšeš klávesnicí. Android se pokaždé zeptá.")),
        st.running ? h("button", { class: "btn sm danger", type: "button", onclick: async () => render(await native.phone.mirrorStop()) }, icon("stop"), "Zastavit")
          : h("button", { class: "btn sm primary", type: "button", onclick: () => native.phone.mirrorStart().catch(() => toast("Nepovedlo se spustit", "error")) }, icon("monitor-play"), "Spustit")),
      h("div", { class: `row m-step ${st.control ? "ok" : ""}` }, icon(st.control ? "check-circle" : "circle", st.control ? "ph-fill" : ""),
        h("div", { class: "row-text" }, h("strong", {}, "Ovládání myší z PC"),
          h("span", {}, st.control ? "Povoleno – klikání a psaní z PC funguje, jen když běží Telefon na monitoru."
            : "Jednou povol: Přístupnost → Stažené aplikace → JARVIS – ovládání z PC → Zapnout. Bez toho jde jen sledovat.")),
        st.control ? null : h("button", { class: "btn sm", type: "button", onclick: () => native.phone.openAccessibility() }, "Povolit")));
  };
  const refresh = () => native.phone.mirrorStatus().then(render).catch(() => {});
  refresh();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  return box;
}

// ---------------- 3.12 Ranní souhrn do telefonu ----------------
function morningCard(c: JarvisClient): HTMLElement {
  const box = h("div", { class: "m-morning" });
  const sw = (on: boolean, fn: (v: boolean) => void, label: string) => {
    const inp = h("input", { type: "checkbox", role: "switch", "aria-label": label }) as HTMLInputElement;
    inp.checked = on;
    inp.onchange = () => fn(inp.checked);
    return h("label", { class: "switch" }, inp, h("span"));
  };
  c.on("morning", (m) => {
    if (m.sent === true) toast("Souhrn je v oznámeních telefonu", "ok");
    else if (m.sent === false) toast("Telefon teď není připojený na pozadí – zapni Spojení na pozadí", "info");
    const time = h("input", { class: "input m-time", type: "time", value: m.time || "07:00", "aria-label": "Čas ranního souhrnu" }) as HTMLInputElement;
    time.onchange = () => c.send("morning_set", { time: time.value });
    box.replaceChildren(
      h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Ranní souhrn"),
        h("span", {}, "Každé ráno přijde do telefonu počasí, kalendář, e-maily, plán dne a co se dělo na PC přes noc – s tlačítkem Přehrát.")),
        sw(!!m.on, (v) => { c.send("morning_set", { on: v }); if (v) native.phone.configure({ enabled: true }).catch(() => {}); }, "Ranní souhrn")),
      m.on ? h("div", { class: "m-subrows" },
        h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "V kolik")), time),
        h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Přehrát sám ve sluchátkách"),
          h("span", {}, "Když máš ráno nasazená sluchátka, JARVIS ti souhrn rovnou přečte.")),
          sw(!!m.autoplay, (v) => c.send("morning_set", { autoplay: v }), "Přehrát sám ve sluchátkách")),
        h("div", { class: "btn-row" }, h("button", { class: "btn sm", type: "button", onclick: () => { toast("Připravuji souhrn…", "info"); c.send("morning_test", {}); } },
          icon("sun-horizon"), "Vyzkoušet teď"))) : "");
  });
  c.on("welcome", () => c.send("morning_get", {}));
  return box;
}

// ---------------- 3.12 Záloha fotek z telefonu na PC ----------------
function backupCard(): HTMLElement {
  if (!native.phone.available) return h("span");
  const box = h("div", { class: "m-backup" });
  let choosing = false;
  let timer = 0;
  const sw = (on: boolean, fn: (v: boolean) => void, label: string) => {
    const inp = h("input", { type: "checkbox", role: "switch", "aria-label": label }) as HTMLInputElement;
    inp.checked = on;
    inp.onchange = () => fn(inp.checked);
    return h("label", { class: "switch" }, inp, h("span"));
  };
  const ago = (ms: number) => {
    const m = Math.round((Date.now() - ms) / 60000);
    return m < 1 ? "právě teď" : m < 60 ? `před ${m} min` : m < 1440 ? `před ${Math.round(m / 60)} h` : `před ${Math.round(m / 1440)} dny`;
  };
  const files = (n: number) => `${n} ${n === 1 ? "soubor" : n >= 2 && n <= 4 ? "soubory" : "souborů"}`;
  const say = (b: BackupStatus) => !b.on ? "Nové fotky a videa se samy uloží do PC (Obrázky → JARVIS Telefon), roztříděné po měsících. V telefonu se nic nemaže."
    : !b.perm ? "Povol JARVISovi přístup k fotkám a videím, jinak nemá co zálohovat."
    : b.running ? `Zálohuji na PC… zbývá ${files(Math.max(b.pending, 0))}.`
    : b.state ? `Pozastaveno – ${b.state}.${b.pending > 0 ? ` Čeká ${files(b.pending)}.` : ""}`
    : b.pending > 0 ? `Čeká ${files(b.pending)} – pošlou se ${b.wifi ? "na Wi-Fi" : "samy"}${b.charging ? " při nabíjení" : ""}.`
    : `Vše je na PC${b.lastRun ? ` · kontrola ${ago(b.lastRun)}` : ""}${b.total ? ` · celkem ${files(b.total)}` : ""}.`;
  const set = async (o: Parameters<typeof native.phone.backup>[0]) => {
    try { render(await native.phone.backup(o)); } catch (e: any) { toast(e?.message || "Nepovedlo se", "error"); }
  };
  const render = (b: BackupStatus) => {
    clearTimeout(timer);
    if (b.running && !document.hidden) timer = window.setTimeout(refresh, 2500);
    box.replaceChildren(
      h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Záloha fotek na PC"), h("span", { class: b.running ? "m-live" : "" }, say(b))),
        sw(b.on || choosing, (v) => {
          if (v) { choosing = true; render(b); } else { choosing = false; set({ on: false }); }
        }, "Záloha fotek na PC")),
      choosing ? h("div", { class: "m-choice" },
        h("p", { class: "help" }, "Co poslat na PC? Pak už se budou posílat jen nové."),
        h("div", { class: "btn-row" },
          h("button", { class: "btn primary sm", type: "button", onclick: () => { choosing = false; localStorage.setItem("jarvis.link", "1"); set({ on: true, all: true }); } }, icon("images"), "Všechny fotky"),
          h("button", { class: "btn sm", type: "button", onclick: () => { choosing = false; localStorage.setItem("jarvis.link", "1"); set({ on: true, all: false }); } }, icon("sparkle"), "Jen nové od teď"),
          h("button", { class: "btn ghost sm", type: "button", onclick: () => { choosing = false; render(b); } }, "Zrušit"))) : "",
      b.on && !choosing ? h("div", { class: "m-subrows" },
        h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Jen přes Wi-Fi"), h("span", {}, "Nešetří data – na mobilních datech čeká.")),
          sw(b.wifi, (v) => set({ wifi: v }), "Jen přes Wi-Fi")),
        h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Jen při nabíjení"), h("span", {}, "Šetří baterii – třeba v noci u nabíječky.")),
          sw(b.charging, (v) => set({ charging: v }), "Jen při nabíjení")),
        h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "I videa"), h("span", {}, "Videa jsou velká – na Wi-Fi to nevadí.")),
          sw(b.videos, (v) => set({ videos: v }), "I videa")),
        h("div", { class: "btn-row" }, !b.perm
          ? h("button", { class: "btn sm", type: "button", onclick: () => set({}) }, icon("lock-open"), "Povolit fotky")
          : h("button", { class: "btn sm", type: "button", disabled: b.running, onclick: () => set({ now: true }) }, icon("cloud-arrow-up"), b.running ? "Zálohuji…" : "Zálohovat teď"))) : "");
  };
  const refresh = () => native.phone.backupStatus().then(render).catch(() => {});
  refresh();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
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
      h("p", { class: "help" }, "Mimo domov (i na mobilních datech) se telefon připojí sám přes JARVIS Link – zapneš ho na PC v Nastavení → Telefon."),
      h("div", { class: "btn-row" },
        h("button", { class: "btn", type: "button", onclick: () => location.reload() }, icon("arrows-clockwise"), "Znovu připojit"),
        h("button", { class: "btn danger", type: "button", onclick: () => { if (confirm("Odpojit a zapomenout tohle PC?")) { savePairing(null); c.close(); connectScreen(); } } }, icon("link-break"), "Odpárovat"))),
    h("div", { class: "card" }, h("h2", {}, "Telefon"),
      h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Notifikace z PC"), h("span", {}, "Časovače, připomínky, odpovědi na pozadí")),
        h("label", { class: "switch" }, notif, h("span"))),
      phoneCard(c),
      backupCard(),
      native.phone.available ? morningCard(c) : "",
      native.phone.available ? mirrorCard() : "",
      h("p", { class: "help" }, "Tip: v jakékoli aplikaci dej Sdílet → JARVIS a odkaz se otevře na PC, soubor přistane v polici notche. "
        + "Dlouhým podržením ikony JARVIS máš zkratky (Mluvit, Napsat, Fotka na PC) a na plochu si můžeš přidat widget.")),
    pcStatusCard(c),
    clipHistoryCard(c),
    pcFilesCard(c),
    lanSpeedCard(c),
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
  // 3.12 Vzdálená plocha: see AND drive the PC with a finger (allowed once on the PC)
  let closeRemote: (() => void) | null = null;
  const drive = h("button", { class: "btn", type: "button", onclick: () => c.send("remote_start") }, icon("hand-pointing"), "Ovládat prstem") as HTMLButtonElement;
  c.on("remote_desk", (m) => {
    if (m.error) { toast(m.error, "error", 6000); return; }
    if (m.on && !closeRemote) { closeRemote = openRemote(c, ep); }
    if (!m.on && closeRemote) { closeRemote(); closeRemote = null; }
  });
  return h("div", { class: "card" }, h("h2", {}, "Obrazovka PC"), img, note, h("div", { class: "btn-row" }, btn, drive),
    h("p", { class: "help" }, "Ovládat prstem: ťuk = klik, dva ťuky = dvojklik, podržet = pravé tlačítko, táhnout = přetáhnout, dva prsty = posun. Funguje i mimo domov přes JARVIS Link."));
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
  // an empty data-hand="" still matched html[data-hand] and turned "Obě ruce" into the one-handed layout (3.12)
  const apply = (v: string) => { if (v) document.documentElement.dataset.hand = v; else delete document.documentElement.dataset.hand; try { localStorage.setItem("jarvis.hand", v); } catch { /* private mode */ } };
  try { sel.value = localStorage.getItem("jarvis.hand") || ""; } catch { /* ignore */ }
  apply(sel.value);
  sel.onchange = () => apply(sel.value);
  return h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Ovládání jednou rukou"),
    h("span", {}, "Tlačítka se přesunou dolů k palci, na stranu ruky, kterou držíš telefon.")), sel);
}
