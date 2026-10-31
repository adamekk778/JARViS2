// The big notch panel (spec §5): content, right column (chat), tab bar at the bottom. "Domů" = three live cards.
import { Blob, type CharacterColor } from "../character/blob";
import { ChatView } from "../shared/chat";
import { fmtSize, h, icon, KIND_ICON, toast } from "../shared/dom";
import type { Attachment } from "../shared/protocol";
import type { JarvisClient } from "../shared/ws";
import { TaskCard } from "../shared/taskcard";
import { missingModelCard } from "../shared/localmissing";
import { windowMap } from "../shared/viz";
import { brandEl, brandOf, BRANDS } from "../shared/brands";

export type Section = "home" | "chat" | "quick" | "system" | "files" | "workspaces" | "tools" | "settings";

const NAV: [Section, string, string][] = [
  ["home", "house", "Domů"],
  ["chat", "chat-circle-dots", "Chat"],
  ["quick", "squares-four", "Rychlé akce"],
  ["system", "gear-six", "Systém"],
  ["files", "folder-simple", "Soubory"],
  ["workspaces", "browsers", "Plochy"],
  ["tools", "wrench", "Nástroje"],
  ["settings", "sliders-horizontal", "Nastavení"],
];

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
  let timers: any[] = [];
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
    h("div", { class: "p-card" },
      h("div", { class: "p-card-head" }, h("span", {}, "Rychlé akce"), h("button", { class: "p-icon sm", type: "button", "aria-label": "Všechny akce", onclick: () => show("quick") }, icon("squares-four"))),
      h("div", { class: "qgrid" },
        card("squares-four", "Otevřít aplikaci", "Spustit program", () => { show("chat"); chat.prefill("Otevři "); }),
        card("magnifying-glass", "Hledat soubory", "Najít na počítači", () => { show("chat"); chat.prefill("Najdi soubor "); }),
        card("article", "Shrnout text", "Získat přehled", () => { show("chat"); client.send("user_text", { text: "Shrň mi text, který mám ve schránce.", attachments: [] }); }),
        card("image", "Analyzovat obrázek", "Popsat a vysvětlit", () => { show("chat"); chat.prefill("Co je na tomhle obrázku? ", true); }))));

  // ---------- other sections ----------
  const big = (ic: string, label: string, fn: () => void, cls = "") =>
    h("button", { class: `qbtn ${cls}`, type: "button", onclick: fn }, icon(ic), h("span", {}, label));

  const quickView = h("div", { class: "p-sec p-quick" },
    h("div", { class: "qbig" },
      big("play-pause", "Play / pauza", () => quick("media_control", { action: "play_pause" })),
      big("skip-forward", "Další", () => quick("media_control", { action: "next" })),
      big("speaker-low", "Tišeji", () => quick("volume", { action: "down", level: 10 })),
      big("speaker-high", "Hlasitěji", () => quick("volume", { action: "up", level: 10 })),
      big("speaker-slash", "Ztlumit", () => quick("volume", { action: "mute" })),
      big("camera", "Screenshot", () => client.send("user_text", { text: "Udělej screenshot", attachments: [] })),
      big("lock", "Zamknout", () => quick("system_power", { action: "lock" })),
      big("moon", "Tmavý režim", () => quick("set_dark_mode", { dark: true })),
      big("headphones", "Fokus zap/vyp", () => client.send("mood_set", { mood: mood === "focus" ? null : "focus" }), "accent"),
      big("moon-stars", "Uspat JARVISe", () => client.send("mood_set", { mood: "sleeping" })),
      big("bell-slash", "Přečteno", () => client.send("mood_set", { clear: "notify" })),
      (agentBtn = big("robot", "Režim Agent", () => client.send("settings_set", { patch: { agent: { mode: !settings?.agent?.mode } } }))),
      big("microphone-stage", "Hlasový režim", () => ctx.openChat("voice-mode")),
      big("hand-palm", "STOP", () => client.send("stop_all"), "danger")),
    h("div", { class: "timers-row clip-row" }, h("span", {}, icon("clipboard-text"), " Schránka"),
      ...([["Shrň", "Shrň stručně text, který mám ve schránce."], ["Přelož", "Přelož text ze schránky (česky ↔ anglicky)."],
        ["Vysvětli", "Vysvětli mi jednoduše text, který mám ve schránce."]] as const).map(([label, text]) =>
        h("button", { class: "p-pill", type: "button", onclick: () => { show("chat"); client.send("user_text", { text, attachments: [] }); } }, label))),
    h("div", { class: "timers-row" }, h("span", {}, icon("timer"), " Minutka"),
      ...[1, 5, 10, 25].map((m) => h("button", { class: "p-pill", type: "button", onclick: () => quick("set_timer", { seconds: m * 60, label: `${m} min` }) }, `+${m} min`))));

  const syncAgent = () => agentBtn?.classList.toggle("accent", !!settings?.agent?.mode);
  const sysVals: Record<string, HTMLElement> = {};
  const stat = (k: string, ic: string, label: string) => h("div", { class: "stat" }, icon(ic), h("span", {}, label), (sysVals[k] = h("b", {}, "–")));
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
  const systemView = h("div", { class: "p-sec p-system" },
    h("div", { class: "stats" }, stat("cpu", "cpu", "CPU"), stat("ram", "memory", "RAM"), stat("disk", "hard-drives", "Disk"),
      stat("bat", "battery-high", "Baterie"), stat("net", "wifi-high", "Síť")),
    weatherBox, updateBox);

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

  // ---------- home: date and time, then three big live cards (JARVIS / Claude Code, music, focus timer) ----------
  const MOOD_WORD: Record<string, string> = { idle: "Připraven", listening: "Poslouchám", thinking: "Přemýšlím", working: "Pracuji",
    speaking: "Mluvím", waiting: "Čekám na tebe", success: "Hotovo", error: "Chyba", offline: "Offline", sleeping: "Odpočívám", notify: "Novinka" };
  const CLAUDE_WORD: Record<string, string> = { working: "Pracuje", thinking: "Přemýšlí", waiting: "Čeká na tebe", done: "Hotovo", idle: "Hotovo" };
  const homeDate = h("div", { class: "home-date" });          // shown in the panel head (island look)
  const cardAi = h("button", { class: "hcard ai", type: "button", onclick: () => show("chat") });
  const cardMusic = h("div", { class: "hcard music", role: "group" });
  const cardFocus = h("div", { class: "hcard focus", role: "group" });
  const homeView = h("div", { class: "home" }, h("div", { class: "home-cards" }, cardAi, cardMusic, cardFocus));
  const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.max(0, s) % 60).padStart(2, "0")}`;
  function renderHome() {
    const now = new Date();
    homeDate.replaceChildren(h("i", { class: "home-eyes", "aria-hidden": "true" }, h("b"), h("b")),
      now.toLocaleDateString("cs-CZ", { weekday: "short", day: "numeric", month: "numeric", year: "numeric" }), " ",
      h("strong", {}, now.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })));
    if (current !== "home") return;
    const cc = sessions.find((s) => ["working", "thinking", "waiting"].includes(s.state)) || sessions[0];
    const b = cc ? BRANDS.claude : brain ? brandOf(brain.provider, brain.model) : null;
    cardAi.style.setProperty("--tint", b ? b.color : "#2563eb");
    const word = cc ? (CLAUDE_WORD[cc.state] || "Hotovo") : (MOOD_WORD[mood] || "Připraven");
    const sub = cc ? (cc.step || cc.prompt || cc.project || "") : (moodDetail || "Klikni a napiš mi, co potřebuješ");
    cardAi.replaceChildren(h("span", { class: "h-label" }, cc ? "Claude Code" : b ? `JARVIS · ${b.name}` : "JARVIS"),
      h("span", { class: "h-btn brand" }, b ? brandEl(b) : icon("chat-circle-dots", "ph-bold")),
      h("strong", { class: "h-big" }, word), h("span", { class: "h-sub" }, sub));
    const playing = !!media?.playing;
    cardMusic.replaceChildren(h("span", { class: "h-label" }, "Hudba"),
      media?.thumb ? h("img", { class: "h-art", src: media.thumb, alt: "" }) : h("span", { class: "h-art none" }, icon("music-notes", "ph-fill")),
      h("strong", { class: "h-big sm" }, media?.title || "Nic nehraje"),
      h("span", { class: "h-sub" }, media?.title ? (playing ? (media.artist || "hraje") : "pozastaveno") : "Pusť si něco a uvidíš to tady"),
      h("button", { class: "h-play", type: "button", "aria-label": playing ? "Pauza" : "Přehrát",
        onclick: () => quick("media_control", { action: "play_pause" }) }, icon(playing ? "pause" : "play", "ph-fill")));
    const t = timers[0];
    const left = t ? Math.max(0, Math.round(t.ends_at - Date.now() / 1000)) : 0;
    cardFocus.replaceChildren(h("span", { class: "h-label" }, t ? (t.label || "Časovač") : "Soustředění"),
      h("button", { class: "h-btn", type: "button", "aria-label": t ? "Zastavit" : "Spustit 25 minut",
        onclick: () => t ? quick("cancel_timer", { id_or_label: t.id }) : quick("set_timer", { seconds: 25 * 60, label: "Soustředění" }) },
        icon(t ? "stop" : "play", "ph-fill")),
      h("strong", { class: "h-big" }, t ? mmss(left) : "25:00"),
      h("span", { class: "h-sub" }, t ? `zbývá ${Math.ceil(left / 60)} min` : "Klikni a začni soustředění"));
  }
  window.setInterval(renderHome, 1000);

  const centre = h("section", { class: "p-centre" });
  const views: Record<Section, HTMLElement> = { home: homeView, chat: chat.el, quick: quickView, system: systemView, files: filesView, workspaces: wsView, tools: toolsView, settings: settingsView };

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
  };
  paintVol();
  const navEl = h("nav", { class: "p-tabs", "aria-label": "Sekce" },
    ...NAV.map(([k, ic, label]) => h("button", { type: "button", "data-sec": k, title: label, onclick: () => show(k) }, icon(ic), h("span", {}, label))),
    h("div", { class: "p-vol" }, volIcon, volRange));

  function show(s: Section) {
    current = s;
    navEl.querySelectorAll("button").forEach((b) => b.classList.toggle("active", (b as HTMLElement).dataset.sec === s));
    centre.replaceChildren(views[s]);
    right.hidden = s !== "chat";
    el.classList.toggle("wide", s !== "chat");
    if (s === "system") { client.send("system_get"); client.send("weather_get"); }
    if (s === "workspaces") { client.send("workspaces_get"); wmap.refresh(); }
    if (s === "chat") client.send("notch_context_get");
    if (s === "tools") { client.send("tools_get"); client.send("skills_get"); client.send("mcp_get"); }
    if (s === "home") renderHome();
    if (s === "chat" && el.isConnected && el.closest(".notch")?.getAttribute("data-mode") === "panel") setTimeout(() => chat.focus(), 50);
  }

  const el = h("div", { class: "panel" }, centre, right, navEl);
  show("home");

  // ---------- events ----------
  client.on("welcome", (m) => {
    settings = m.settings;
    shelf = m.shelf || [];
    media = m.media || {};
    update = m.update;
    const name = settings?.general?.user_name;
    chat.setGreeting(name ? `Ahoj, ${name}! Jak ti dnes můžu pomoct?` : "Ahoj! Jak ti dnes můžu pomoct?");
    pins = m.pins || [];
    timers = m.timers || [];
    sessions = m.claude_sessions || [];
    if (m.volume) { volume = { level: Number(m.volume.level) || 0, muted: !!m.volume.muted }; paintVol(); }
    renderShelf(); renderMedia(); renderSettings(); renderUpdate(); syncAgent(); renderPins();
  });
  client.on("pins", (m) => { pins = m.items || []; renderPins(); });
  client.on("app_context", (m) => { ctxInfo = { app: m.app, actions: m.actions || [], suggestions: m.suggestions ?? ctxInfo.suggestions }; renderCtx(); });
  client.on("workspaces", (m) => renderWs(m.items || []));
  client.on("workspace_result", (m) => toast(m.message, m.ok ? "ok" : "error", 6000));
  client.on("settings_changed", (m) => { settings = m.settings; syncAgent(); if (current === "settings") renderSettings(); });
  client.on("shelf", (m) => { shelf = m.items || []; renderShelf(); });
  client.on("media", (m) => { media = m; renderMedia(); renderHome(); });
  client.on("timers", (m) => { timers = m.items || []; renderHome(); });
  client.on("claude_sessions", (m) => { sessions = m.items || []; renderHome(); });
  client.on("brain", (m) => { brain = { provider: m.provider || "", model: m.model || "" }; renderHome(); });
  client.on("volume", (m) => { volume = { level: Number(m.level) || 0, muted: !!m.muted }; paintVol(); });
  client.on("update_status", (m) => { update = m; renderUpdate(); });
  client.on("system", (m) => {
    sysVals.cpu.textContent = `${Math.round(m.cpu_percent)} %`;
    sysVals.ram.textContent = `${Math.round(m.ram_percent)} %`;
    sysVals.disk.textContent = `${Math.round(m.disk_percent)} %`;
    sysVals.bat.textContent = m.battery_percent != null ? `${m.battery_percent} %` : "síť";
    sysVals.net.textContent = m.ip || "online";
  });
  client.on("mood", (m) => { mood = m.mood; moodDetail = m.detail || ""; renderHome(); if (sysVals.net) sysVals.net.textContent = m.mood === "offline" ? "offline" : sysVals.net.textContent; });
  client.on("weather", (m) => {
    if (m.error) { weatherBox.replaceChildren(h("span", { class: "muted" }, "Počasí nedostupné")); return; }
    const dn = ["Ne", "Po", "Út", "St", "Čt", "Pá", "So"];
    weatherBox.replaceChildren(h("div", { class: "w-now" }, h("b", {}, `${Math.round(m.temp)}°`), h("span", {}, `${m.city}, ${m.desc}`)),
      h("div", { class: "w-days" }, ...(m.days || []).slice(1, 4).map((d: any) => h("div", {}, h("span", {}, dn[new Date(d.date).getDay()]), h("b", {}, `${Math.round(d.max)}°`), h("span", { class: "muted" }, `${Math.round(d.min)}°`)))));
  });
  client.on("tools", (m) => {
    const cats = new Map<string, number>();
    for (const t of m.items) cats.set(t.category, (cats.get(t.category) || 0) + 1);
    toolsBox.replaceChildren(...[...cats].map(([c, n]) => h("div", { class: "tcat" }, h("b", {}, String(n)), h("span", {}, c))));
  });
  client.on("skills", (m) => skillsBox.replaceChildren(...(m.items.length ? m.items.map((s: any) => h("span", { class: "p-chip" }, icon("wrench"), s.name)) : [h("span", { class: "muted" }, "Zatím žádné. Řekni třeba: Nauč se převádět měny.")])));
  client.on("mcp", (m) => mcpBox.replaceChildren(...(m.items.length ? m.items.map((s: any) => h("span", { class: `p-chip ${s.ok ? "ok" : "bad"}` }, icon("plug"), `${s.name} · ${s.ok ? `${s.tools} nástrojů` : "nepřipojeno"}`)) : [h("span", { class: "muted" }, "Žádné. Přidáš je v celém nastavení → Integrace.")])));

  return { el, show, chat, dateEl: homeDate, get section() { return current; } };
}
