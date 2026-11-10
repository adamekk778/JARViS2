// The big notch panel (spec §5): content, right column (chat), tab bar at the bottom. "Domů" = three live cards.
import { createFocusStats } from "./focusstats";
import { createAskAi } from "./askai";
import { createClock } from "./clock";
import { createMusicView } from "./music";
import { Blob, type CharacterColor } from "../character/blob";
import { ChatView } from "../shared/chat";
import { fmtSize, h, icon, KIND_ICON, toast } from "../shared/dom";
import type { Attachment } from "../shared/protocol";
import type { JarvisClient } from "../shared/ws";
import { TaskCard } from "../shared/taskcard";
import { missingModelCard } from "../shared/localmissing";
import { windowMap } from "../shared/viz";
import { brandEl, brandOf, BRANDS, mediaBrand } from "../shared/brands";

export type Section = "home" | "music" | "chat" | "quick" | "system" | "files" | "workspaces" | "tools" | "settings" | "more" | "activity";

const NAV: [Section, string, string][] = [
  ["home", "house", "Domů"],
  ["chat", "chat-circle-dots", "Chat"],
  ["quick", "squares-four", "Akce"],
  ["system", "gear-six", "Systém"],
  ["files", "folder-simple", "Soubory"],
  ["workspaces", "browsers", "Plochy"],
  ["tools", "wrench", "Nástroje"],
  ["settings", "sliders-horizontal", "Nastavení"],
  ["more", "dots-three-circle", "Více"],
  ["activity", "pulse", "Průběh"],
];
// 3.12 Dynamic Island: five tabs in the head; the rest sits behind "Více"
const EXTRA: Section[] = ["files", "workspaces", "tools", "settings", "activity"];

export interface PanelCtx {
  client: JarvisClient;
  openChat: (view?: string) => void;
  pin: (v: boolean) => void;
}

export function buildPanel(ctx: PanelCtx) {
  const { client } = ctx;
  const quick = (action: string, args: any = {}) => client.send("quick_action", { action, args });
  let settings: any = null;
  let shelf: Attachment[] = [];
  let media: any = {};
  let update: any = null;
  let current: Section = "home";
  let sessions: any[] = [];
  let moodDetail = "";
  let brain: { provider: string; model: string } | null = null;
  let volume: { level: number; muted: boolean } | null = null;
  let agentBtn: HTMLElement | undefined;
  let mood = "idle";

  // ---------- chat (centre) ----------
  const chat = new ChatView(client, {
    compact: true, emptyAvatar: false, suggestions: [],
    greeting: "Ahoj! Jak ti dnes můžu pomoct?", subtitle: "Mám pro tebe nápady, odpovědi i řešení.",
    placeholder: "Napiš mi něco…",
  });
  // the panel stays open while you are writing something (not merely because the box has focus)
  const typing = () => !!(chat.el.querySelector("textarea") as HTMLTextAreaElement | null)?.value.trim();
  chat.el.addEventListener("input", () => ctx.pin(typing()));
  chat.el.addEventListener("focusout", () => ctx.pin(typing()));

  // ---------- right column ----------
  const card = (ic: string, title: string, sub: string, fn: () => void) =>
    h("button", { class: "qcard", type: "button", onclick: fn }, icon(ic), h("strong", {}, title), h("span", {}, sub));
  const mediaCard = h("div", { class: "media-card", hidden: true });
  const renderMedia = () => {
    mediaCard.hidden = !media?.title;
    if (!media?.title) return;
    mediaCard.replaceChildren(
      h("div", { class: "mc-art" }, media.thumb ? h("img", { src: media.thumb, alt: "" }) : icon("music-notes")),
      h("div", { class: "mc-meta" }, h("strong", {}, media.title), h("span", {}, media.artist || "")),
      h("div", { class: "mc-ctl" },
        h("button", { class: "p-icon", type: "button", "aria-label": "Předchozí", onclick: () => quick("media_control", { action: "previous" }) }, icon("skip-back", "ph-fill")),
        h("button", { class: "p-icon big", type: "button", "aria-label": "Play/pauza", onclick: () => quick("media_control", { action: "play_pause" }) }, icon(media.playing ? "pause" : "play", "ph-fill")),
        h("button", { class: "p-icon", type: "button", "aria-label": "Další", onclick: () => quick("media_control", { action: "next" }) }, icon("skip-forward", "ph-fill"))));
  };
  const taskCard = new TaskCard(client, { compact: true, hideWhenIdle: true });

  // 3.10: what fits the app in front (OMEGA 089) and the moment (094)
  let ctxInfo: any = { app: "", actions: [], suggestions: [] };
  const ctxCard = h("div", { class: "p-card ctx-card", hidden: true });
  const runCtx = (a: any) => {
    if (a.text) { show("chat"); client.send("user_text", { text: a.text, attachments: [] }); }
    else if (a.quick) quick(a.quick, a.args || {});
    else if (a.pin) client.send("pin_done", { id: a.pin });
  };
  const renderCtx = () => {
    const acts = [...(ctxInfo.suggestions || []), ...(ctxInfo.actions || [])].slice(0, 6);
    ctxCard.hidden = !acts.length;
    ctxCard.replaceChildren(h("div", { class: "p-card-head" }, h("span", {}, ctxInfo.app ? `Pro ${ctxInfo.app}` : "Teď se hodí")),
      h("div", { class: "ctx-list" }, ...acts.map((a: any) => h("button", { class: "p-pill", type: "button", title: a.label, onclick: () => runCtx(a) }, icon(a.icon), " ", a.label))));
  };

  // 3.10: small pinned to-dos (OMEGA 093)
  let pins: any[] = [];
  const pinsList = h("div", { class: "pins" });
  const pinInput = h("input", { class: "p-input", type: "text", placeholder: "Připnout… (např. zavolat Petrovi v 15:00)", "aria-label": "Nový připnutý úkol" }) as HTMLInputElement;
  pinInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && pinInput.value.trim()) { client.send("pin_add", { text: pinInput.value.trim() }); pinInput.value = ""; }
  });
  pinInput.addEventListener("focus", () => ctx.pin(true));
  pinInput.addEventListener("blur", () => ctx.pin(false));
  const fmtDue = (ts: number) => {
    const d = new Date(ts * 1000), now = new Date();
    const hm = d.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
    return d.toDateString() === now.toDateString() ? hm : `${d.getDate()}. ${d.getMonth() + 1}. ${hm}`;
  };
  const renderPins = () => {
    pinsList.replaceChildren(...pins.map((p) => {
      const c = h("input", { type: "checkbox", "aria-label": `Hotovo: ${p.text}` }) as HTMLInputElement;
      c.checked = !!p.done;
      c.onchange = () => client.send("pin_done", { id: p.id, done: c.checked });
      const late = p.due && p.due * 1000 < Date.now();
      return h("label", { class: `pin ${late ? "late" : ""}` }, c, h("span", {}, p.text),
        p.due ? h("em", {}, fmtDue(p.due)) : null,
        h("button", { class: "p-icon sm", type: "button", "aria-label": "Odepnout", onclick: (e: Event) => { e.preventDefault(); client.send("pin_remove", { id: p.id }); } }, icon("x")));
    }));
  };
  const pinsCard = h("div", { class: "p-card pins-card" },
    h("div", { class: "p-card-head" }, h("span", {}, icon("push-pin"), " Připnuté")), pinsList, pinInput);

  const right = h("aside", { class: "p-right" },
    missingModelCard(client, "compact"),
    taskCard.el,
    ctxCard,
    pinsCard,
    mediaCard,
    h("div", { class: "p-card qa-card" },
      h("div", { class: "p-card-head" }, h("span", {}, "Rychlé akce"), h("button", { class: "p-icon sm", type: "button", "aria-label": "Všechny akce", onclick: () => show("quick") }, icon("squares-four"))),
      h("div", { class: "qgrid" },
        card("squares-four", "Otevřít aplikaci", "Spustit program", () => { show("chat"); chat.prefill("Otevři "); }),
        card("magnifying-glass", "Hledat soubory", "Najít na počítači", () => { show("chat"); chat.prefill("Najdi soubor "); }),
        card("article", "Shrnout text", "Získat přehled", () => { show("chat"); client.send("user_text", { text: "Shrň mi text, který mám ve schránce.", attachments: [] }); }),
        card("image", "Analyzovat obrázek", "Popsat a vysvětlit", () => { show("chat"); chat.prefill("Co je na tomhle obrázku? ", true); }))));

  // Akce (3.12 redesign): a real player strip with volume, STOP, mode switches that show their state, the computer's
  // one-tap actions as chips, then the clipboard and the timer
  const pop = (e: Event) => (e.currentTarget as HTMLElement).animate([{ transform: "scale(.94)" }, { transform: "scale(1)" }], { duration: 260, easing: "cubic-bezier(.3,1.6,.5,1)" });
  const akArt = h("img", { class: "ak-art-img", alt: "" }) as HTMLImageElement;
  const akArtBox = h("div", { class: "ak-art" }, akArt, icon("music-notes", "ph-fill"));
  const akTitle = h("strong", { class: "ak-title" }), akArtist = h("span", { class: "ak-artist" });
  const akPlayIco = h("span", {});
  const akBtn = (ic: string | null, label: string, fn: () => void, cls = "") => h("button", { class: `ak-btn ${cls}`, type: "button", "aria-label": label, title: label,
    onclick: (e: Event) => { pop(e); fn(); } }, ic ? icon(ic, "ph-fill") : akPlayIco);
  const akVolIco = h("button", { class: "ak-vol-ico", type: "button", "aria-label": "Ztlumit / zrušit ztlumení", onclick: () => quick("volume", { action: volume?.muted ? "unmute" : "mute" }) });
  const akVol = h("input", { type: "range", min: 0, max: 100, step: 1, class: "dock-range ak-range", "aria-label": "Hlasitost" }) as HTMLInputElement;
  let akVolAt = -1e9;
  akVol.oninput = () => { akVol.style.setProperty("--v", `${akVol.value}%`); if (performance.now() - akVolAt > 80) { akVolAt = performance.now(); quick("volume", { action: "set", level: Number(akVol.value) }); } };
  akVol.onchange = () => quick("volume", { action: "set", level: Number(akVol.value) });
  const akPlayer = h("div", { class: "ak-card ak-player" },
    h("div", { class: "ak-now" }, akArtBox, h("div", { class: "ak-meta" }, akTitle, akArtist)),
    h("div", { class: "ak-ctl" },
      akBtn("skip-back", "Předchozí", () => quick("media_control", { action: "previous" })),
      akBtn(null, "Přehrát / pauza", () => quick("media_control", { action: "play_pause" }), "main"),
      akBtn("skip-forward", "Další", () => quick("media_control", { action: "next" }))),
    h("div", { class: "ak-vol" }, akVolIco, akVol));
  const akStop = h("button", { class: "ak-stop", type: "button", onclick: (e: Event) => { pop(e); client.send("stop_all"); } },
    icon("hand-palm", "ph-fill"), h("strong", {}, "STOP"), h("span", {}, "zastavit vše"));
  // modes: a tile with a switch that shows whether it is on
  const mode = (ic: string, label: string, sub: string, color: string, fn: () => void, toggle = true) => {
    const state = h("span", { class: "ak-mode-sub" }, sub);
    const el = h("button", { class: `ak-mode ${toggle ? "toggle" : ""}`, type: "button", onclick: (e: Event) => { pop(e); fn(); } },
      h("span", { class: "ak-mode-ico" }, icon(ic, "ph-fill")), toggle ? h("i", { class: "ak-sw", "aria-hidden": "true" }) : "",
      h("strong", {}, label), state);
    el.style.setProperty("--mc", color);
    return { el, set: (on: boolean, text: string) => { el.classList.toggle("on", on); state.textContent = text; } };
  };
  const mFocus = mode("headphones", "Fokus", "Vypnuto", "#bf8cff", () => client.send("mood_set", { mood: mood === "focus" ? null : "focus" }));
  const mAgent = mode("robot", "Režim Agent", "Vypnuto", "#3ee0cc", () => client.send("settings_set", { patch: { agent: { mode: !settings?.agent?.mode } } }));
  const mDark = mode("moon", "Tmavý režim", "Přepnout Windows", "#8b93ff", () => quick("set_dark_mode", { dark: true }), false);
  const mVoice = mode("microphone-stage", "Hlasový režim", "Mluv s JARVISem", "#4ade80", () => ctx.openChat("voice-mode"), false);
  agentBtn = mAgent.el;
  const chip = (ic: string, label: string, fn: () => void) => h("button", { class: "ak-chip", type: "button", onclick: (e: Event) => { pop(e); fn(); } }, icon(ic, "ph-fill"), h("span", {}, label));
  const quickView = h("div", { class: "p-sec p-quick ak" },
    h("div", { class: "ak-top" }, akPlayer, akStop),
    h("div", { class: "ak-modes" }, mFocus.el, mAgent.el, mDark.el, mVoice.el),
    h("div", { class: "ak-chips" },
      chip("camera", "Snímek obrazovky", () => client.send("user_text", { text: "Udělej screenshot", attachments: [] })),
      chip("lock-simple", "Zamknout PC", () => quick("system_power", { action: "lock" })),
      chip("moon-stars", "Uspat JARVISe", () => client.send("mood_set", { mood: "sleeping" })),
      chip("bell-slash", "Přečteno", () => client.send("mood_set", { clear: "notify" }))),
    h("div", { class: "qrows" },
      h("div", { class: "qrow" }, h("span", { class: "qr-title" }, icon("clipboard-text", "ph-fill"), "Schránka"),
        ...([["Shrň", "Shrň stručně text, který mám ve schránce."], ["Přelož", "Přelož text ze schránky (česky ↔ anglicky)."],
          ["Vysvětli", "Vysvětli mi jednoduše text, který mám ve schránce."]] as const).map(([label, text]) =>
          h("button", { class: "qpill", type: "button", onclick: () => { show("chat"); client.send("user_text", { text, attachments: [] }); } }, label))),
      h("div", { class: "qrow" }, h("span", { class: "qr-title" }, icon("timer", "ph-fill"), "Minutka"),
        ...[1, 5, 10, 25].map((m) => h("button", { class: "qpill", type: "button", onclick: () => quick("set_timer", { seconds: m * 60, label: `${m} min` }) }, `${m} min`)))));
  let akArtSrc = "";
  function paintQuick() {
    const has = !!media?.title;
    akPlayer.classList.toggle("empty", !has);
    const th = has && media.thumb ? String(media.thumb) : "";
    if (th !== akArtSrc) { akArtSrc = th; akArtBox.classList.toggle("has", !!th); if (th) akArt.src = th; else akArt.removeAttribute("src"); }
    if (akTitle.textContent !== (has ? media.title : "Nic nehraje")) akTitle.textContent = has ? media.title : "Nic nehraje";
    const ar = has ? media.artist || "" : "Pusť si hudbu nebo video";
    if (akArtist.textContent !== ar) akArtist.textContent = ar;
    const pi = media?.playing ? "pause" : "play";
    if (akPlayIco.dataset.i !== pi) { akPlayIco.dataset.i = pi; akPlayIco.replaceChildren(icon(pi, "ph-fill")); }
    const lv = volume ? (volume.muted ? 0 : volume.level) : 50;
    const vi = volume?.muted || lv === 0 ? "speaker-slash" : lv < 34 ? "speaker-low" : "speaker-high";
    if (akVolIco.dataset.i !== vi) { akVolIco.dataset.i = vi; akVolIco.replaceChildren(icon(vi, "ph-fill")); }
    if (document.activeElement !== akVol) { akVol.value = String(lv); akVol.style.setProperty("--v", `${lv}%`); }
    mFocus.set(mood === "focus", mood === "focus" ? "Zapnuto" : "Vypnuto");
    mAgent.set(!!settings?.agent?.mode, settings?.agent?.mode ? "Zapnuto" : "Vypnuto");
  }
  const syncAgent = () => agentBtn?.classList.toggle("accent", !!settings?.agent?.mode);
  // Systém (3.12 redesign): one "Výkon" card with three rings inside each other (CPU, RAM, disk) and a legend with bars,
  // beside it the weather, the battery and the network, the version below
  const sysVals: Record<string, HTMLElement> = {};
  const sysRings: Record<string, SVGCircleElement> = {};
  const sysBars: Record<string, HTMLElement> = {};
  const RINGS: Record<string, number> = { cpu: 64, ram: 50, disk: 36 };
  const circ = (r: number) => 2 * Math.PI * r;
  const ringsSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  ringsSvg.setAttribute("viewBox", "0 0 160 160");
  ringsSvg.setAttribute("class", "sy-rings");
  for (const [k, r] of Object.entries(RINGS)) {
    const bg = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    const arc = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    for (const el of [bg, arc]) { el.setAttribute("cx", "80"); el.setAttribute("cy", "80"); el.setAttribute("r", String(r)); }
    bg.setAttribute("class", `sy-bg sy-${k}`);
    arc.setAttribute("class", `sy-arc sy-${k}`);
    arc.style.strokeDasharray = `${circ(r)}`;
    arc.style.strokeDashoffset = `${circ(r)}`;
    ringsSvg.append(bg, arc);
    sysRings[k] = arc;
  }
  const legend = (k: string, label: string) => h("div", { class: `sy-leg sy-${k}` },
    h("i", { class: "sy-dot" }), h("span", { class: "sy-lbl" }, label), (sysVals[k] = h("b", {}, "–")),
    h("div", { class: "sy-bar" }, (sysBars[k] = h("i", {}))));
  const mini = (k: string, ic: string, label: string) => h("div", { class: `sy-mini sy-${k}` },
    h("span", { class: "sy-mini-ico" }, icon(ic, "ph-fill")), h("div", {}, (sysVals[k] = h("b", {}, "–")), h("span", {}, label)));
  const setGauge = (k: string, pct: number | null) => {
    const p = pct == null ? 0 : Math.max(0, Math.min(100, pct));
    const arc = sysRings[k];
    if (arc) arc.style.strokeDashoffset = `${(circ(RINGS[k]) * (1 - p / 100)).toFixed(2)}`;
    if (sysBars[k]) sysBars[k].style.transform = `scaleX(${(p / 100).toFixed(3)})`;
    const hot = ["cpu", "ram", "disk"].includes(k) && p >= 85;      // only load can be "too much"
    sysVals[k]?.closest(".sy-leg")?.classList.toggle("hot", hot);
  };
  const weatherBox = h("div", { class: "weather" }, h("span", { class: "muted" }, "Počasí se načítá…"));
  const updateBox = h("div", { class: "update" });
  const renderUpdate = () => {
    const u = update;
    const ver = h("span", { class: "muted" }, `Verze ${u?.current ?? "?"}`);
    if (!u?.available) {
      updateBox.replaceChildren(ver, h("button", { class: "p-pill", type: "button", onclick: () => { client.send("update_check"); toast("Hledám aktualizace…"); } }, icon("arrows-clockwise"), " Zkontrolovat"));
      return;
    }
    const btn = u.state === "downloading"
      ? h("span", { class: "p-progress" }, h("b", { style: { width: `${Math.round((u.progress || 0) * 100)}%` } }))
      : h("button", { class: "p-pill accent", type: "button", onclick: () => { if (confirm(`Nainstalovat JARVIS ${u.latest}? JARVIS se na chvíli zavře.`)) client.send("update_install"); } }, icon("download-simple"), ` Aktualizovat na ${u.latest}`);
    // a failed download / install says why, right next to the button (it stays there for another try)
    const err = u.state === "error" && u.error ? h("span", { class: "p-update-err", title: u.error }, `Nepovedlo se: ${u.error}`) : "";
    updateBox.replaceChildren(ver, btn, err);
  };
  const systemView = h("div", { class: "p-sec p-system sy" },
    h("div", { class: "sy-perf" },
      h("div", { class: "sy-head" }, h("strong", {}, "Výkon"), h("span", {}, "teď")),
      h("div", { class: "sy-body" }, h("div", { class: "sy-ring-box" }, ringsSvg),
        h("div", { class: "sy-legend" }, legend("cpu", "Procesor"), legend("ram", "Paměť"), legend("disk", "Disk")))),
    h("div", { class: "sy-side" }, weatherBox,
      h("div", { class: "sy-minis" }, mini("bat", "battery-high", "Baterie"), mini("net", "wifi-high", "Síť"))),
    updateBox);

  const shelfList = h("div", { class: "shelf" });
  const renderShelf = () => {
    shelfList.replaceChildren(...(shelf.length ? shelf.map((a) =>
      h("div", { class: "shelf-item", title: `${a.name} (${fmtSize(a.size)})` },
        a.thumb ? h("img", { src: client.url(a.thumb), alt: "" }) : icon(KIND_ICON[a.kind] || "file"),
        h("span", { class: "shelf-name" }, a.name),
        h("button", { class: "p-icon sm", type: "button", title: "Otevřít", "aria-label": "Otevřít", onclick: () => quick("save_attachment", { id: a.id, open: true }) }, icon("arrow-square-out")),
        h("button", { class: "p-icon sm", type: "button", title: "Zeptat se", "aria-label": "Zeptat se", onclick: () => { show("chat"); client.send("user_text", { text: "Co je v tomhle souboru?", attachments: [a.id] }); } }, icon("sparkle")),
        h("button", { class: "p-icon sm", type: "button", title: "Na telefon", "aria-label": "Na telefon", onclick: () => quick("send_to_phone", { text: a.name, title: "Soubor z PC", url: client.url(a.url, true) }) }, icon("device-mobile")),
        h("button", { class: "p-icon sm", type: "button", title: "Odebrat", "aria-label": "Odebrat", onclick: () => client.send("shelf_remove", { attachment_id: a.id }) }, icon("x"))))
      : [h("div", { class: "shelf-empty" }, icon("tray-arrow-down"), h("span", {}, "Přetáhni sem soubory. Můžeš se na ně zeptat, otevřít je nebo poslat na telefon."))]));
  };
  const fileInput = h("input", { type: "file", multiple: true, hidden: true }) as HTMLInputElement;
  fileInput.onchange = async () => {
    for (const f of [...(fileInput.files || [])]) client.send("shelf_add", { attachment_id: (await client.upload(f, f.name)).id });
    fileInput.value = "";
  };
  const filesView = h("div", { class: "p-sec p-files" }, shelfList,
    h("button", { class: "p-pill", type: "button", onclick: () => fileInput.click() }, icon("plus"), " Přidat soubory"), fileInput);

  // 3.10: workspaces – the windows of a piece of work, saved and back in one click (OMEGA 091)
  const wsList = h("div", { class: "ws-list" });
  const wsName = h("input", { class: "p-input", type: "text", placeholder: "Název (např. Účetnictví)", "aria-label": "Název plochy" }) as HTMLInputElement;
  wsName.addEventListener("focus", () => ctx.pin(true));
  wsName.addEventListener("blur", () => ctx.pin(false));
  const wmap = windowMap(client);         // OMEGA 230: the windows on the screen as a map (click / arrows)
  const wsView = h("div", { class: "p-sec p-ws" },
    h("h4", {}, "Okna teď"), wmap.el,
    h("p", { class: "muted" }, "Plocha si zapamatuje otevřené programy a kde má každý okno. Obnovení spustí jen to, co v ní bylo, a okna rozmístí."),
    h("div", { class: "ws-save" }, wsName,
      h("button", { class: "p-pill accent", type: "button", onclick: () => { client.send("workspace_save", { name: wsName.value.trim() }); wsName.value = ""; } }, icon("floppy-disk"), " Uložit současná okna")),
    wsList);
  const renderWs = (items: any[]) => {
    wsList.replaceChildren(...(items.length ? items.map((w) => h("div", { class: "ws-item" },
      icon("squares-four"), h("strong", {}, w.name), h("span", { class: "muted" }, `${w.windows} oken · ${new Date(w.updated * 1000).toLocaleDateString("cs-CZ")}`),
      h("button", { class: "p-pill", type: "button", onclick: () => { client.send("workspace_restore", { name: w.name }); toast(`Obnovuji ${w.name}…`); } }, icon("play"), " Obnovit"),
      h("button", { class: "p-icon sm", type: "button", "aria-label": `Smazat ${w.name}`, onclick: () => { if (confirm(`Smazat plochu ${w.name}?`)) client.send("workspace_delete", { name: w.name }); } }, icon("trash"))))
      : [h("span", { class: "muted" }, "Zatím žádná uložená plocha.")]));
  };

  const toolsBox = h("div", { class: "tool-cats" });
  const skillsBox = h("div", { class: "skills" });
  const mcpBox = h("div", { class: "mcps" });
  const toolsView = h("div", { class: "p-sec p-tools" }, toolsBox, h("h4", {}, "Naučené dovednosti"), skillsBox, h("h4", {}, "Integrace (MCP)"), mcpBox);

  const settingsView = h("div", { class: "p-sec p-settings" });
  let previewBlob: Blob | null = null;
  const renderSettings = () => {
    if (!settings) return;
    const sw = (path: string, label: string) => {
      const [sec, key] = path.split(".");
      const inp = h("input", { type: "checkbox", role: "switch", "aria-label": label }) as HTMLInputElement;
      inp.checked = !!settings[sec]?.[key];
      inp.onchange = () => client.send("settings_set", { patch: { [sec]: { [key]: inp.checked } } });
      return h("label", { class: "p-row" }, h("span", {}, label), h("span", { class: "switch" }, inp, h("span")));
    };
    const colors: CharacterColor[] = ["black", "midnight", "violet", "rose", "white"];
    const preview = (previewBlob ??= new Blob({ size: 64 }));
    preview.setMood("personalize");
    preview.setColor(settings.character?.color || "black", settings.character?.glow || undefined);
    preview.setOutfit(settings.character?.outfit);
    settingsView.replaceChildren(
      h("div", { class: "p-col" },
        sw("voice.enabled", "Hlasové ovládání"), sw("voice.wake_word", "Probouzení „Hey Jarvis“"),
        h("label", { class: "p-row" }, h("span", {}, "Mluvit nahlas"),
          (() => {
            const sel = h("select", { class: "p-select" }, h("option", { value: "voice" }, "Jen u hlasu"), h("option", { value: "always" }, "Vždy"), h("option", { value: "never" }, "Nikdy")) as HTMLSelectElement;
            sel.value = settings.voice?.speak_mode || "voice";
            sel.onchange = () => client.send("settings_set", { patch: { voice: { speak_mode: sel.value } } });
            return sel;
          })()),
        h("label", { class: "p-row" }, h("span", {}, "Animace"),
          (() => {
            const sel = h("select", { class: "p-select" }, h("option", { value: "full" }, "Plné"), h("option", { value: "reduced" }, "Omezené")) as HTMLSelectElement;
            sel.value = settings.appearance?.animations || "full";
            sel.onchange = () => client.send("settings_set", { patch: { appearance: { animations: sel.value } } });
            return sel;
          })()),
        h("button", { class: "p-pill", type: "button", onclick: () => ctx.openChat("general") }, icon("arrow-square-out"), " Celé nastavení")),
      h("div", { class: "p-col char" }, preview.el,
        h("div", { class: "swatches" }, ...colors.map((c) => h("button", {
          class: `swatch sw-${c} ${settings.character?.color === c ? "on" : ""}`, type: "button", "aria-label": c,
          onclick: () => client.send("settings_set", { patch: { character: { color: c } } }),
        }))),
        h("div", { class: "sizes" }, ...(["S", "M", "L"] as const).map((s) => h("button", {
          class: `p-pill ${settings.character?.size === s ? "accent" : ""}`, type: "button",
          onclick: () => client.send("settings_set", { patch: { character: { size: s } } }),
        }, s)))));
  };

  // ---------- home (3.12): a real "now playing" card, JARVIS / Claude and a focus ring beside it, a dock below ----------
  // Built once and only updated in place (a text, a width, a class) – nothing is rebuilt every second, so the
  // album art never reloads and nothing flickers; the song progress runs on requestAnimationFrame.
  const MOOD_WORD: Record<string, string> = { idle: "Připraven", listening: "Poslouchám", thinking: "Přemýšlím", working: "Pracuji",
    speaking: "Mluvím", waiting: "Čekám na tebe", success: "Hotovo", error: "Chyba", offline: "Offline", sleeping: "Odpočívám", notify: "Novinka" };
  const CLAUDE_WORD: Record<string, string> = { working: "Pracuje", thinking: "Přemýšlí", waiting: "Čeká na tebe", done: "Hotovo", idle: "Hotovo" };
  const homeDate = h("div", { class: "home-date" });          // shown in the panel head
  const setText = (el: Element, t: string) => { if (el.textContent !== t) el.textContent = t; };
  const mmss = (s: number) => `${Math.floor(Math.max(0, s) / 60)}:${String(Math.floor(Math.max(0, s)) % 60).padStart(2, "0")}`;

  // now playing
  const npBg = h("img", { class: "np-bg", alt: "", "aria-hidden": "true" }) as HTMLImageElement;
  const npArt = h("img", { class: "np-art-img", alt: "" }) as HTMLImageElement;
  const npArtBox = h("div", { class: "np-art" }, npArt, h("span", { class: "np-art-none" }, icon("music-notes", "ph-fill")));
  const npSrc = h("span", { class: "np-src" });
  const npTitle = h("strong", { class: "np-title" });
  const npArtist = h("span", { class: "np-artist" });
  const npFill = h("i", { class: "np-fill" });
  const npKnob = h("i", { class: "np-knob" });
  const npBar = h("div", { class: "np-bar" }, h("div", { class: "np-track" }, npFill, npKnob));
  const npT0 = h("span", {}), npT1 = h("span", {});
  const npPlayIco = h("span", { class: "np-play-ico" });
  const ctl = (ic: string, label: string, action: string, cls = "") => h("button", { class: `np-btn ${cls}`, type: "button", "aria-label": label,
    onclick: (e: Event) => { (e.currentTarget as HTMLElement).animate([{ transform: "scale(.86)" }, { transform: "scale(1)" }], { duration: 260, easing: "cubic-bezier(.3,1.6,.5,1)" }); quick("media_control", { action }); } },
    ic ? icon(ic, "ph-fill") : npPlayIco);
  const npCard = h("div", { class: "np", role: "group", "aria-label": "Právě hraje" },
    h("div", { class: "np-glow", "aria-hidden": "true" }, npBg),
    h("div", { class: "np-top" }, npArtBox, h("div", { class: "np-meta" }, npSrc, npTitle, npArtist)),
    h("div", { class: "np-time" }, npBar, h("div", { class: "np-times" }, npT0, npT1)),
    h("div", { class: "np-ctl" }, ctl("skip-back", "Předchozí", "previous"), ctl("", "Přehrát / pauza", "play_pause", "main"), ctl("skip-forward", "Další", "next")));
  let artSrc = "", playIco = "";
  function paintNowPlaying() {
    const has = !!media?.title, playing = !!media?.playing;
    npCard.classList.toggle("empty", !has);
    npCard.classList.toggle("playing", playing);
    const thumb = has && media.thumb ? String(media.thumb) : "";
    if (thumb !== artSrc) {                       // only a new cover is decoded (and it fades in)
      artSrc = thumb;
      npArtBox.classList.toggle("has", !!thumb);
      if (thumb) { npArt.src = thumb; npBg.src = thumb; npArt.animate([{ opacity: 0, transform: "scale(.94)" }, { opacity: 1, transform: "scale(1)" }], { duration: 420, easing: "cubic-bezier(.2,.9,.25,1)" }); }
      else { npArt.removeAttribute("src"); npBg.removeAttribute("src"); }
    }
    setText(npTitle, has ? media.title : "Nic nehraje");
    setText(npArtist, has ? (media.artist || (playing ? "hraje" : "pozastaveno")) : "Pusť si hudbu nebo video – uvidíš to tady");
    const src = mediaBrand(media?.source || "");
    const srcKey = src ? src.id : "";
    if (npSrc.dataset.k !== srcKey) { npSrc.dataset.k = srcKey; npSrc.replaceChildren(...(src && src.id !== "browser" ? [brandEl(src), h("span", {}, src.name)] : [])); }
    const want = playing ? "pause" : "play";
    if (want !== playIco) { playIco = want; npPlayIco.replaceChildren(icon(want, "ph-fill")); }
  }
  function songNow(): [number, number] {
    const dur = Number(media?.duration) || 0;
    if (!dur || typeof media?.position !== "number") return [0, 0];
    const pos = media.position + (media.playing ? Math.max(0, Date.now() / 1000 - (media.at || Date.now() / 1000)) : 0);
    return [Math.min(pos, dur), dur];
  }
  function npLoop() {
    if (current === "home" && !npCard.classList.contains("empty")) {
      const [pos, dur] = songNow();
      npCard.classList.toggle("no-time", !dur);
      if (dur) {
        const p = Math.min(1, pos / dur);
        npFill.style.transform = `scaleX(${p.toFixed(4)})`;
        npKnob.style.left = `${(p * 100).toFixed(2)}%`;
        setText(npT0, mmss(pos));
        setText(npT1, `-${mmss(dur - pos)}`);
      }
    }
    requestAnimationFrame(npLoop);
  }
  requestAnimationFrame(npLoop);

  // JARVIS / Claude Code
  const aiLogo = h("span", { class: "ai-logo" });
  const aiName = h("span", { class: "ai-name" }), aiWord = h("strong", { class: "ai-word" }), aiSub = h("span", { class: "ai-sub" });
  // 3.12 the logos of your AIs on the card: a click asks that one AI (askai.ts); the sheet is made on first use
  let ask: ReturnType<typeof createAskAi> | null = null;
  const askAi = () => (ask ??= createAskAi(() => el.parentElement || el, client, () => show("chat")));
  const aiChipsBox = h("div", { class: "aa-chips-slot" });
  const cardAi = h("div", { class: "tile ai", role: "button", tabindex: "0",
    onclick: (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest(".aa-chips-slot")) return;
      show(sessions.some((x) => x.state !== "idle" || (x.changes || []).length) || jChanges.length ? "activity" : "chat");
    },
    onkeydown: (e: KeyboardEvent) => { if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) { e.preventDefault(); (e.currentTarget as HTMLElement).click(); } } },
    h("div", { class: "tile-head" }, aiLogo, aiName, h("i", { class: "ai-dot", "aria-hidden": "true" })), aiWord, aiSub, aiChipsBox);
  const paintAiChips = () => {
    const a = askAi();
    if (!aiChipsBox.firstChild) aiChipsBox.append(a.chips);
    a.paintChips(settings);
  };
  // focus timer with a ring
  const RING = 2 * Math.PI * 22;
  const ringArc = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  const ringSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  ringSvg.setAttribute("viewBox", "0 0 52 52");
  ringSvg.setAttribute("class", "fx-ring");
  ringSvg.innerHTML = '<circle cx="26" cy="26" r="22" class="fx-ring-bg"/>';
  for (const [k, v] of [["cx", "26"], ["cy", "26"], ["r", "22"], ["class", "fx-ring-arc"]]) ringArc.setAttribute(k, v);
  ringArc.style.strokeDasharray = `${RING}`;
  ringSvg.append(ringArc);
  // 3.12 the focus mode itself (notifications wait, the notch watches YouTube & co.): 25 or 50 minutes, today's total
  const fxTime = h("strong", { class: "fx-time" }), fxLabel = h("span", { class: "fx-label" }), fxToday = h("span", { class: "fx-today" });
  const fxBtnIco = h("span", {});
  let focusState: any = {};
  const startFocus = (min: number) => quick("focus_mode", { minutes: min });
  const fxChip = (min: number) => h("button", { class: "fx-chip", type: "button", title: `Soustředit se ${min} minut`,
    onclick: (e: Event) => { e.stopPropagation(); startFocus(min); } }, `${min}`);
  let stats: ReturnType<typeof createFocusStats> | null = null;     // 3.12 the week of focus (made on first open)
  const fxChips = h("div", { class: "fx-chips" }, fxChip(25), fxChip(50),
    h("button", { class: "fx-stats", type: "button", title: "Týden soustředění", "aria-label": "Týden soustředění",
      onclick: (e: Event) => { e.stopPropagation(); (stats ??= createFocusStats(el.parentElement || el, client)).open(); } }, icon("chart-bar", "ph-fill")));
  const cardFocus = h("div", { class: "tile focus", role: "button", tabindex: "0", "aria-label": "Soustředění",
    onclick: () => (focusState.active ? quick("focus_mode", { minutes: 0 }) : startFocus(25)),
    onkeydown: (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (e.currentTarget as HTMLElement).click(); } } },
    h("div", { class: "fx-ring-box" }, ringSvg, h("span", { class: "fx-ico" }, fxBtnIco)),
    h("div", { class: "fx-text" }, fxTime, fxLabel, fxToday), fxChips);
  let fxIco = "";
  const dur = (sec: number) => { const m = Math.round(sec / 60); return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`; };

  // dock: volume (live while dragging) and round quick buttons
  const homeVolIcon = h("button", { class: "dock-vol-ico", type: "button", "aria-label": "Ztlumit / zrušit ztlumení",
    onclick: () => quick("volume", { action: volume?.muted ? "unmute" : "mute" }) });
  const homeVol = h("input", { type: "range", min: 0, max: 100, step: 1, class: "dock-range", "aria-label": "Hlasitost" }) as HTMLInputElement;
  const homeVolNum = h("span", { class: "dock-vol-num" });
  let volSentAt = -1e9, volTimer = 0;
  const sendVol = () => { volSentAt = performance.now(); quick("volume", { action: "set", level: Number(homeVol.value) }); };
  homeVol.oninput = () => {                       // the PC volume follows the finger, at most ~12× a second
    homeVol.style.setProperty("--v", `${homeVol.value}%`);
    setText(homeVolNum, homeVol.value);
    window.clearTimeout(volTimer);
    if (performance.now() - volSentAt > 80) sendVol(); else volTimer = window.setTimeout(sendVol, 80);
  };
  homeVol.onchange = sendVol;
  const dockBtn = (ic: string, label: string, fn: () => void, cls = "") => h("button", { class: `dock-btn ${cls}`, type: "button", title: label, "aria-label": label,
    onclick: (e: Event) => { (e.currentTarget as HTMLElement).animate([{ transform: "scale(.86)" }, { transform: "scale(1)" }], { duration: 280, easing: "cubic-bezier(.3,1.6,.5,1)" }); fn(); } },
    icon(ic, "ph-fill"), h("span", { class: "dock-tip" }, label));
  const homeRow = h("div", { class: "dock" },
    h("div", { class: "dock-vol" }, homeVolIcon, homeVol, homeVolNum),
    h("div", { class: "dock-btns" },
      dockBtn("microphone", "Mluvit", () => client.send("push_to_talk")),
      dockBtn("camera", "Snímek obrazovky", () => client.send("user_text", { text: "Udělej screenshot", attachments: [] })),
      dockBtn("headphones", "Fokus", () => client.send("mood_set", { mood: mood === "focus" ? null : "focus" })),
      dockBtn("lock-simple", "Zamknout PC", () => quick("system_power", { action: "lock" })),
      dockBtn("hand-palm", "STOP – zastavit vše", () => client.send("stop_all"), "stop")));
  // 3.12 a big clock on the left: six looks, a click changes the colour (see clock.ts)
  const clock = createClock();
  window.setInterval(() => { if (current === "home" && !document.hidden) clock.paint(); }, 1000);
  // 3.12 "what's next" under the clock: the next event in today's calendar, else the soonest pinned task
  let agendaAt = 0, events: any[] = [];
  const wantAgenda = () => { if (Date.now() - agendaAt > 10 * 60000) { agendaAt = Date.now(); client.send("calendar_get", { days: 1 }); } paintAgenda(); };
  const hhmm = (ts: number) => new Date(ts * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  const paintAgenda = () => {
    const now = Date.now() / 1000, end = new Date(); end.setHours(23, 59, 59, 999);
    const ev = events.find((e) => !e.all_day && e.end > now && e.start < end.getTime() / 1000);
    if (ev) { clock.agenda({ ic: "calendar-dots", time: ev.start <= now ? "teď" : hhmm(ev.start), text: ev.title }); return; }
    const pin = pins.filter((p) => !p.done).sort((a, b) => (a.due || 9e12) - (b.due || 9e12))[0];
    clock.agenda(pin ? { ic: "push-pin", time: pin.due ? hhmm(pin.due) : "", text: pin.text } : null);
  };
  client.on("calendar", (m) => { events = m.items || []; paintAgenda(); });
  let weatherAt = 0;                        // the clock shows the weather; asked for now and then while home is open
  const wantWeather = () => { if (Date.now() - weatherAt > 30 * 60000) { weatherAt = Date.now(); client.send("weather_get"); } };
  const homeView = h("div", { class: "home home2" },
    h("div", { class: "home-grid three" }, clock.el, npCard, h("div", { class: "home-side" }, cardAi, cardFocus)), homeRow);

  let aiKey = "";
  function renderHome() {
    if (current === "quick") paintQuick();
    if (current === "more") paintMore();
    const now = new Date();
    if (!homeDate.querySelector(".hd-time")) homeDate.append(h("span", { class: "hd-day" }), h("strong", { class: "hd-time" }));
    const hr = now.getHours(), who = settings?.general?.user_name ? `, ${settings.general.user_name}` : "";
    const hello = hr < 5 ? "Dobrou noc" : hr < 10 ? "Dobré ráno" : hr < 12 ? "Dobré dopoledne" : hr < 18 ? "Dobré odpoledne" : "Dobrý večer";
    homeDate.classList.toggle("greet", current === "home");
    setText(homeDate.querySelector(".hd-day")!, current === "home" ? hello : now.toLocaleDateString("cs-CZ", { weekday: "short", day: "numeric", month: "numeric" }));
    homeDate.dataset.who = current === "home" ? who.replace(/^, /, "") : "";
    setText(homeDate.querySelector(".hd-time")!, now.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" }));
    if (current !== "home") return;
    wantWeather();
    wantAgenda();
    paintNowPlaying();
    const cc = sessions.find((s) => ["working", "thinking", "waiting"].includes(s.state)) || sessions[0];
    const b = cc ? BRANDS.claude : brain ? brandOf(brain.provider, brain.model) : null;
    const busy = cc ? ["working", "thinking"].includes(cc.state) : ["thinking", "working", "speaking", "listening"].includes(mood);
    const key = `${cc ? "cc" : ""}|${b?.id || ""}`;
    if (key !== aiKey) {
      aiKey = key;
      aiLogo.replaceChildren(b ? brandEl(b) : icon("sparkle", "ph-fill"));
      cardAi.style.setProperty("--tint", b ? b.color : "#0a84ff");
    }
    cardAi.classList.toggle("busy", busy);
    setText(aiName, cc ? `Claude Code · ${cc.project || ""}`.replace(/ · $/, "") : b ? `JARVIS · ${b.name}` : "JARVIS");
    setText(aiWord, cc ? (CLAUDE_WORD[cc.state] || "Hotovo") : (MOOD_WORD[mood] || "Připraven"));
    setText(aiSub, cc ? (cc.step || cc.prompt || "") : (moodDetail || "Napiš mi nebo řekni, co potřebuješ"));
    const nowS = Date.now() / 1000;
    const on = !!(focusState.active && focusState.until > nowS);
    const left = on ? Math.max(0, Math.round(focusState.until - nowS)) : 25 * 60;
    const total = on && focusState.started ? focusState.until - focusState.started : 0;
    const frac = on && total > 0 ? left / total : 1;
    ringArc.style.strokeDashoffset = `${(RING * (1 - frac)).toFixed(2)}`;
    cardFocus.classList.toggle("on", on);
    setText(fxTime, mmss(left));
    setText(fxLabel, on ? "zbývá · klik ukončí" : "Soustředění");
    const today = (focusState.today || 0) + (on && focusState.started ? Math.max(0, nowS - Math.max(focusState.started, focusState.at || focusState.started)) : 0);
    setText(fxToday, today >= 60 ? `Dnes ${dur(today)}` : "Dnes zatím nic");
    const fi = on ? "stop" : "play";
    if (fi !== fxIco) { fxIco = fi; fxBtnIco.replaceChildren(icon(fi, "ph-fill")); }
  }
  window.setInterval(renderHome, 1000);

  // 3.12 subtitles of what the PC plays, right in the notch (Ctrl+Alt+T)
  const subsTile = h("button", { class: "more-tile", type: "button", onclick: () => ctx.client.send("live_subs_set", {}) });
  const paintSubsTile = (on: boolean) => {
    subsTile.classList.toggle("on", on);
    subsTile.replaceChildren(h("span", { class: "mo-ico" }, icon("closed-captioning", "ph-fill")), h("i", { class: "ak-sw", "aria-hidden": "true" }),
      h("div", { class: "mo-text" }, h("strong", {}, "Titulky z videa"),
        h("span", {}, on ? "Běží v notchi – vypneš tady nebo Ctrl+Alt+T" : "Co se říká ve videu nebo hře, rovnou v notchi")));
  };
  subsTile.className = "more-tile mo-wide mo-subs";
  paintSubsTile(false);
  // Více (3.12 redesign): tiles of different sizes – Průběh tall with what is going on right now, subtitles wide with
  // a switch, the rest compact with the icon beside the text
  const tile = (sec: Section | null, ic: string, label: string, sub: string, cls = "", fn?: () => void) =>
    h("button", { class: `more-tile ${cls}`, type: "button", onclick: () => (fn ? fn() : sec && show(sec)) },
      h("span", { class: "mo-ico" }, icon(ic, "ph-fill")), h("div", { class: "mo-text" }, h("strong", {}, label), h("span", {}, sub)));
  const moLive = h("span", { class: "mo-live" });
  const moActivity = tile("activity", "pulse", "Průběh", "Co AI právě dělá a co přesně změnila", "mo-tall mo-activity");
  moActivity.append(moLive, h("span", { class: "mo-go" }, "Otevřít", icon("caret-right")));
  const moreView = h("div", { class: "p-sec more mo" },
    moActivity,
    subsTile,
    tile(null, "eye-slash", "Schovat notch", "Zpátky Ctrl+Alt+N", "mo-hide", () => { (window as any).pywebview?.api?.hide_notch?.(); }),
    tile("files", "folder-simple", "Soubory", "Police na soubory"),
    tile("workspaces", "browsers", "Plochy", "Rozložení oken"),
    tile("tools", "wrench", "Nástroje", "Co JARVIS umí"),
    tile("settings", "sliders-horizontal", "Nastavení", "Hlas, animace, vzhled", "mo-wide"),
    tile(null, "arrow-square-out", "Celé okno", "Všechny stránky a nastavení JARVISe", "mo-wide", () => ctx.openChat("general")));
  function paintMore() {
    const cc = sessions.find((x) => ["working", "thinking", "waiting"].includes(x.state));
    const busy = ["thinking", "working", "speaking", "listening"].includes(mood);
    const text = cc ? `Claude Code · ${cc.project || ""} ${cc.state === "waiting" ? "čeká na tebe" : "pracuje"}` : busy ? "JARVIS pracuje…" : "Teď se nic neděje";
    moActivity.classList.toggle("live", !!cc || busy);
    if (moLive.textContent !== text) moLive.textContent = text;
  }
  ctx.client.on("live_subs", (m) => paintSubsTile(!!m.on));
  // ---------- 3.12 Průběh: what Claude Code / JARVIS is doing and exactly what it changed (added / removed lines) ----------
  let jChanges: any[] = [];
  const openDiffs = new Set<string>(), closedDiffs = new Set<string>();
  const activityView = h("div", { class: "p-sec activity" });
  const ago = (t: number) => {
    const s = Math.max(0, Math.round(Date.now() / 1000 - t));
    return s < 60 ? `před ${s} s` : s < 3600 ? `před ${Math.floor(s / 60)} min` : new Date(t * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  };
  const KIND: Record<string, [string, string]> = { edit: ["pencil-simple", "Úprava"], write: ["file-arrow-up", "Přepsání"], new: ["file-plus", "Nový soubor"], cmd: ["terminal-window", "Příkaz"] };
  const changeEl = (c: any, i = 1) => {
    const key = `${c.t}:${c.path || c.diff?.[0]?.[1] || ""}`;
    const [ic, label] = KIND[c.kind] || ["file", "Změna"];
    const d = h("details", { class: `chg ${c.kind}` }) as HTMLDetailsElement;
    d.open = openDiffs.has(key) || (i === 0 && c.kind !== "cmd" && !closedDiffs.has(key));   // the newest edit opens by itself
    d.addEventListener("toggle", () => {
      if (d.open) { openDiffs.add(key); closedDiffs.delete(key); } else { openDiffs.delete(key); closedDiffs.add(key); }
    });
    d.append(
      h("summary", {}, icon(ic), h("strong", {}, c.kind === "cmd" ? (c.note || "Příkaz") : c.file || label),
        c.kind === "cmd" ? h("code", { class: "chg-cmd" }, c.diff?.[0]?.[1] || "") : "",
        c.kind !== "cmd" ? h("span", { class: "chg-n" }, h("b", { class: "add" }, `+${c.add}`), h("b", { class: "rem" }, `−${c.rem}`)) : "",
        h("span", { class: "chg-t" }, ago(c.t))),
      c.kind === "cmd" ? "" : h("div", { class: "diff" }, ...(c.diff || []).map(([k, text]: [string, string]) =>
        h("div", { class: `dl ${k === "+" ? "add" : k === "-" ? "rem" : k === "@" ? "hunk" : ""}` },
          h("i", {}, k === "@" ? "⋯" : k === " " ? "" : k), h("span", {}, k === "@" ? "" : text || " ")))));
    return d;
  };
  function renderActivity() {
    if (current !== "activity") return;
    const blocks: HTMLElement[] = [];
    for (const s of sessions.filter((x) => x.state !== "idle" || (x.changes || []).length)) {
      const live = ["working", "thinking", "waiting"].includes(s.state);
      const changes: any[] = [...(s.changes || [])].reverse();
      const add = changes.reduce((a, c) => a + (c.add || 0), 0), rem = changes.reduce((a, c) => a + (c.rem || 0), 0);
      blocks.push(h("section", { class: `act-block ${live ? "live" : ""}` },
        h("div", { class: "act-head" }, brandEl(BRANDS.claude), h("strong", {}, `Claude Code · ${s.project}`),
          h("span", { class: `act-state ${s.state}` }, CLAUDE_WORD[s.state] || s.state),
          changes.length ? h("span", { class: "chg-n" }, h("b", { class: "add" }, `+${add}`), h("b", { class: "rem" }, `−${rem}`)) : ""),
        s.prompt ? h("p", { class: "act-prompt" }, `„${s.prompt}“`) : "",
        live && s.step ? h("p", { class: "act-now" }, h("span", { class: "n-orb sm" }), s.step) : "",
        changes.length ? h("div", { class: "chg-list" }, ...changes.map((c, i) => changeEl(c, changes.findIndex((x) => x.kind !== "cmd") === i ? 0 : 1)))
          : h("p", { class: "muted" }, "Zatím nic nezměnil."),
        (s.steps || []).length ? h("details", { class: "act-steps" }, h("summary", {}, `Všechny kroky (${s.steps.length})`),
          h("ol", {}, ...[...s.steps].reverse().map((st: any) => h("li", {}, h("span", { class: "chg-t" }, ago(st.t)), st.text)))) : ""));
    }
    if (jChanges.length) {
      const changes = [...jChanges].reverse();
      blocks.push(h("section", { class: "act-block" },
        h("div", { class: "act-head" }, brain ? brandEl(brandOf(brain.provider, brain.model)) : icon("sparkle", "ph-fill"), h("strong", {}, "JARVIS"),
          h("span", { class: "act-state" }, "změny souborů")),
        h("div", { class: "chg-list" }, ...changes.map((c, i) => changeEl(c, i)))));
    }
    activityView.replaceChildren(...(blocks.length ? blocks : [h("div", { class: "act-empty" }, icon("pulse"),
      h("strong", {}, "Teď se nic nemění"), h("span", {}, "Až Claude Code nebo JARVIS začne upravovat soubory, uvidíš tu každou změnu – co přidal zeleně, co ubral červeně."))]));
  }
  const centre = h("section", { class: "p-centre" });
  // 3.12 the music screen (a click on the player): big art, a progress bar to drag, lyrics that follow the song
  const music = createMusicView({ quick, back: () => show("home"), lyricsOn: () => settings?.notch?.lyrics !== false });
  npCard.classList.add("opens");
  npCard.title = "Otevřít přehrávač s textem";
  npCard.addEventListener("click", (e) => { if (!(e.target as HTMLElement).closest("button")) show("music"); });
  const views: Record<Section, HTMLElement> = { home: homeView, music: music.el, chat: chat.el, quick: quickView, system: systemView, files: filesView, workspaces: wsView, tools: toolsView, settings: settingsView, more: moreView, activity: activityView };

  // the volume of the PC, right in the tab bar (follows changes made anywhere else)
  const volIcon = h("button", { class: "p-vol-ico", type: "button", "aria-label": "Ztlumit / zrušit ztlumení",
    onclick: () => quick("volume", { action: volume?.muted ? "unmute" : "mute" }) });
  const volRange = h("input", { type: "range", min: 0, max: 100, step: 2, class: "p-vol-range", "aria-label": "Hlasitost" }) as HTMLInputElement;
  volRange.onchange = () => quick("volume", { action: "set", level: Number(volRange.value) });
  const paintVol = () => {
    const lv = volume ? volume.level : 50;
    volIcon.replaceChildren(icon(volume?.muted || lv === 0 ? "speaker-slash" : lv < 34 ? "speaker-low" : "speaker-high", "ph-fill"));
    if (document.activeElement !== volRange) volRange.value = String(lv);
    volRange.style.setProperty("--v", `${volume?.muted ? 0 : lv}%`);
    const vi = volume?.muted || lv === 0 ? "speaker-slash" : lv < 34 ? "speaker-low" : "speaker-high";
    if (homeVolIcon.dataset.i !== vi) { homeVolIcon.dataset.i = vi; homeVolIcon.replaceChildren(icon(vi, "ph-fill")); }
    if (document.activeElement !== homeVol && performance.now() - volSentAt > 600) {   // not while the finger is on it
      homeVol.value = String(lv);
      homeVol.style.setProperty("--v", `${volume?.muted ? 0 : lv}%`);
      setText(homeVolNum, String(volume?.muted ? 0 : lv));
    }
  };
  paintVol();
  client.on("volume", () => { if (current === "quick") paintQuick(); });
  const navEl = h("nav", { class: "p-tabs", "aria-label": "Sekce" },
    ...NAV.map(([k, ic, label]) => h("button", { type: "button", "data-sec": k, title: label, class: EXTRA.includes(k) ? "nav-extra" : k === "more" ? "nav-more" : "",
      onclick: () => show(k) }, icon(ic), h("span", {}, label))),
    h("div", { class: "p-vol" }, volIcon, volRange));

  // 3.12 motion: a pill slides under the active tab, a section glides in from the side of its tab, and its cards
  // come in one after another (Web Animations: transform / opacity only, on the GPU)
  const ORDER: Section[] = ["home", "music", "chat", "quick", "system", "more", "activity", "files", "workspaces", "tools", "settings"];
  const tabInd = h("span", { class: "p-tab-ind", "aria-hidden": "true" });
  navEl.prepend(tabInd);
  const moveInd = (instant = false) => {
    const b = navEl.querySelector("button.active") as HTMLElement | null;
    if (!b || !b.offsetWidth) { tabInd.style.opacity = "0"; return; }
    if (instant) tabInd.style.transition = "none";
    tabInd.style.opacity = "1";
    tabInd.style.width = `${b.offsetWidth}px`;
    tabInd.style.transform = `translateX(${b.offsetLeft}px)`;
    if (instant) { void tabInd.offsetWidth; tabInd.style.transition = ""; }
  };
  const STAGGER = ".np, .tile, .dock, .qgroup, .qstop, .qrow, .stat, .weather, .update, .more-tile, .act-block, .tcat, .p-col, .ws-save, .shelf-empty, .p-card";
  const reduced = () => document.documentElement.dataset.motion === "reduced" || matchMedia("(prefers-reduced-motion: reduce)").matches;
  function intro(view: HTMLElement, dx = 0) {
    if (reduced()) return;
    view.animate([{ opacity: 0, transform: `translateX(${dx}px)` }, { opacity: 1, transform: "none" }], { duration: 340, easing: "cubic-bezier(.2,.9,.25,1)" });
    [...view.querySelectorAll(STAGGER)].slice(0, 14).forEach((c, i) =>
      (c as HTMLElement).animate([{ opacity: 0, transform: "translateY(10px) scale(.98)" }, { opacity: 1, transform: "none" }],
        { duration: 420, delay: 40 + i * 32, easing: "cubic-bezier(.2,.9,.25,1)", fill: "backwards" }));
  }
  /** The chat was filled while hidden (height 0), so it could not scroll: jump to the newest message when shown. */
  const toNewest = () => requestAnimationFrame(() => {
    const sc = chat.el.querySelector(".chat-scroll") as HTMLElement | null;
    if (sc) sc.scrollTop = sc.scrollHeight;
  });
  function show(s: Section) {
    const prev = current;
    current = s;
    music.show(s === "music");
    navEl.querySelectorAll("button").forEach((b) => b.classList.toggle("active", (b as HTMLElement).dataset.sec === s || ((b as HTMLElement).dataset.sec === "home" && s === "music") || ((b as HTMLElement).dataset.sec === "more" && EXTRA.includes(s))));
    requestAnimationFrame(() => moveInd());
    const changed = centre.firstChild !== views[s];
    centre.replaceChildren(views[s]);
    if (changed && prev !== s) intro(views[s], (ORDER.indexOf(s) - ORDER.indexOf(prev)) > 0 ? 18 : -18);
    if (s === "chat") toNewest();
    right.hidden = s !== "chat";
    el.classList.toggle("wide", s !== "chat");
    if (s === "system") { client.send("system_get"); client.send("weather_get"); }
    if (s === "workspaces") { client.send("workspaces_get"); wmap.refresh(); }
    if (s === "chat") client.send("notch_context_get");
    if (s === "tools") { client.send("tools_get"); client.send("skills_get"); client.send("mcp_get"); }
    if (s === "home") renderHome();
    if (s === "activity") renderActivity();
    if (s === "chat" && el.isConnected && el.closest(".notch")?.getAttribute("data-mode") === "panel") setTimeout(() => chat.focus(), 50);
  }

  const el = h("div", { class: "panel" }, centre, right, navEl);
  show("home");

  // ---------- events ----------
  client.on("welcome", (m) => {
    music.setMedia(m.media || {});
    if (m.lyrics) music.setLyrics(m.lyrics);
    focusState = { ...(m.focus || {}), at: Date.now() / 1000 };
    settings = m.settings;
    paintAiChips();
    shelf = m.shelf || [];
    media = m.media || {};
    update = m.update;
    const name = settings?.general?.user_name;
    chat.setGreeting(name ? `Ahoj, ${name}! Jak ti dnes můžu pomoct?` : "Ahoj! Jak ti dnes můžu pomoct?");
    pins = m.pins || [];
    sessions = m.claude_sessions || [];
    jChanges = m.jarvis_changes || [];
    if (m.volume) { volume = { level: Number(m.volume.level) || 0, muted: !!m.volume.muted }; paintVol(); }
    renderShelf(); renderMedia(); renderSettings(); renderUpdate(); syncAgent(); renderPins();
  });
  client.on("pins", (m) => { pins = m.items || []; renderPins(); });
  client.on("app_context", (m) => { ctxInfo = { app: m.app, actions: m.actions || [], suggestions: m.suggestions ?? ctxInfo.suggestions }; renderCtx(); });
  client.on("workspaces", (m) => renderWs(m.items || []));
  client.on("workspace_result", (m) => toast(m.message, m.ok ? "ok" : "error", 6000));
  client.on("settings_changed", (m) => { settings = m.settings; paintAiChips(); syncAgent(); if (current === "settings") renderSettings(); });
  client.on("shelf", (m) => { shelf = m.items || []; renderShelf(); });
  client.on("media", (m) => { media = m; renderMedia(); renderHome(); music.setMedia(m); });
  client.on("lyrics", (m) => music.setLyrics(m));
  client.on("timers", () => renderHome());
  client.on("focus", (m) => { if ("today" in m || !m.active) focusState = { ...focusState, ...m, at: Date.now() / 1000 }; else focusState = { ...focusState, ...m }; renderHome(); });
  client.on("claude_sessions", (m) => { sessions = m.items || []; renderHome(); renderActivity(); });
  client.on("jarvis_changes", (m) => { jChanges = m.items || []; renderActivity(); });
  client.on("brain", (m) => { brain = { provider: m.provider || "", model: m.model || "" }; renderHome(); });
  client.on("volume", (m) => { volume = { level: Number(m.level) || 0, muted: !!m.muted }; paintVol(); });
  client.on("update_status", (m) => { update = m; renderUpdate(); });
  client.on("system", (m) => {
    sysVals.cpu.textContent = `${Math.round(m.cpu_percent)} %`;
    sysVals.ram.textContent = `${Math.round(m.ram_percent)} %`;
    sysVals.disk.textContent = `${Math.round(m.disk_percent)} %`;
    sysVals.bat.textContent = m.battery_percent != null ? `${m.battery_percent} %` : "Kabel";
    sysVals.net.textContent = "Online";
    sysVals.net.title = m.ip || "";
    setGauge("cpu", m.cpu_percent); setGauge("ram", m.ram_percent); setGauge("disk", m.disk_percent);
    setGauge("bat", m.battery_percent != null ? m.battery_percent : 100);
    setGauge("net", 100);
  });
  client.on("mood", (m) => { mood = m.mood; moodDetail = m.detail || ""; renderHome(); if (sysVals.net) sysVals.net.textContent = m.mood === "offline" ? "offline" : sysVals.net.textContent; });
  client.on("weather", (m) => {
    clock.weather(m);
    if (m.error) { weatherBox.replaceChildren(h("span", { class: "muted" }, "Počasí nedostupné")); return; }
    const dn = ["Ne", "Po", "Út", "St", "Čt", "Pá", "So"];
    const wIcon = /bouř/i.test(m.desc || "") ? "cloud-lightning" : /sníh|sněž/i.test(m.desc || "") ? "snowflake" : /déšť|přeháň|mrhol/i.test(m.desc || "") ? "cloud-rain"
      : /mlh/i.test(m.desc || "") ? "cloud-fog" : /zataž|oblač/i.test(m.desc || "") ? "cloud" : "sun";
    weatherBox.replaceChildren(h("span", { class: "w-ico" }, icon(wIcon, "ph-fill")), h("div", { class: "w-now" }, h("b", {}, `${Math.round(m.temp)}°`), h("span", {}, `${m.city} · ${m.desc}`)),
      h("div", { class: "w-days" }, ...(m.days || []).slice(1, 4).map((d: any) => h("div", {}, h("span", {}, dn[new Date(d.date).getDay()]), h("b", {}, `${Math.round(d.max)}°`), h("span", { class: "muted" }, `${Math.round(d.min)}°`)))));
  });
  client.on("tools", (m) => {
    const cats = new Map<string, number>();
    for (const t of m.items) cats.set(t.category, (cats.get(t.category) || 0) + 1);
    toolsBox.replaceChildren(...[...cats].map(([c, n]) => h("div", { class: "tcat" }, h("b", {}, String(n)), h("span", {}, c))));
  });
  client.on("skills", (m) => skillsBox.replaceChildren(...(m.items.length ? m.items.map((s: any) => h("span", { class: "p-chip" }, icon("wrench"), s.name)) : [h("span", { class: "muted" }, "Zatím žádné. Řekni třeba: Nauč se převádět měny.")])));
  client.on("mcp", (m) => mcpBox.replaceChildren(...(m.items.length ? m.items.map((s: any) => h("span", { class: `p-chip ${s.ok ? "ok" : "bad"}` }, icon("plug"), `${s.name} · ${s.ok ? `${s.tools} nástrojů` : "nepřipojeno"}`)) : [h("span", { class: "muted" }, "Žádné. Přidáš je v celém nastavení → Integrace.")])));

  window.addEventListener("resize", () => moveInd(true));
  /** The panel opened: the indicator jumps to its tab and the cards of the open section come in. */
  const enter = () => { moveInd(true); requestAnimationFrame(() => moveInd(true)); intro(views[current]); if (current === "chat") toNewest(); };
  return { el, show, chat, clock, dateEl: homeDate, navEl, enter, get section() { return current; } };
}
