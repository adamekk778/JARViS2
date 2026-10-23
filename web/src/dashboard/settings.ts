import { h, icon, toast, TOOL_ICON } from "../shared/dom";
import { Blob as Character, DEFAULT_GLOW } from "../character/blob";
import type { JarvisClient } from "../shared/ws";

export type Section =
  | "general" | "brain" | "voice" | "notch" | "appearance" | "hotkeys" | "permissions" | "tools" | "integrations"
  | "phone" | "memory" | "jobs" | "backup";

const TITLES: Record<Section, [string, string, string]> = {
  general: ["user-circle", "Obecné", "Kdo jsi a jak se k tobě JARVIS chová."],
  brain: ["brain", "Mozek (AI)", "Odkud JARVIS bere inteligenci. Zkouší poskytovatele odshora dolů, dokud jeden neodpoví."],
  voice: ["waveform", "Hlas", "Probouzení, rozpoznávání řeči a hlas JARVISe."],
  notch: ["rectangle", "Notch", "Výřez nahoře na obrazovce, který se po najetí myší rozevře."],
  appearance: ["palette", "Vzhled", "Barvy a animace."],
  hotkeys: ["keyboard", "Zkratky", "Globální klávesové zkratky (fungují v jakékoli aplikaci)."],
  permissions: ["shield-check", "Oprávnění", "Co JARVIS smí dělat. Vypnutá oblast okamžitě zmizí – JARVIS ji nepoužije, dokud ji znovu nezapneš."],
  tools: ["toolbox", "Nástroje a skilly", "Jednotlivé nástroje, co musíš potvrdit, povolené složky a naučené dovednosti."],
  integrations: ["plugs-connected", "Integrace", "MCP servery (Gmail, kalendář, Spotify, chytrá domácnost…) a generování obrázků."],
  phone: ["device-mobile", "Telefon", "Spáruj Android aplikaci naskenováním QR kódu."],
  memory: ["database", "Paměť", "Co si o tobě JARVIS pamatuje."],
  jobs: ["calendar-check", "Rutiny a připomínky", "Naplánované úlohy. Vytváříš je hlasem nebo v chatu („každý den v 7:00 mi řekni počasí“)."],
  backup: ["floppy-disk", "Záloha", "Export a import nastavení a paměti."],
};

const TILE_NAMES: Record<string, string> = {
  ask: "Zeptej se", media: "Právě hraje", shelf: "Police", quick: "Rychlé akce", timers: "Časovače",
  system: "Systém", weather: "Počasí", phone: "Telefon",
};

const VOICES = [
  ["cs-CZ-AntoninNeural", "Antonín (čeština, muž)"], ["cs-CZ-VlastaNeural", "Vlasta (čeština, žena)"],
  ["sk-SK-LukasNeural", "Lukáš (slovenština)"], ["en-GB-RyanNeural", "Ryan (britská angličtina, JARVIS)"],
  ["en-GB-ThomasNeural", "Thomas (britská angličtina)"], ["en-US-GuyNeural", "Guy (americká angličtina)"],
  ["de-DE-ConradNeural", "Conrad (němčina)"],
];

const PERM_HELP: Record<string, string> = {
  apps: "Spouštět a zavírat aplikace, okna, média, časovače, schránka.",
  input: "Myš, klávesnice a klikání v aplikacích (UI Automation, ovládání počítače).",
  screen: "Snímky obrazovky a čtení textu z oken.",
  files_read: "Hledat a číst soubory, git stav a rozdíly.",
  files_write: "Vytvářet, přesouvat a mazat soubory (mazání vždy s potvrzením).",
  shell: "PowerShell, Python, testy, Claude Code a skilly (vždy s potvrzením).",
  network: "Web, prohlížeč, stahování, MCP servery.",
  system: "Napájení, tmavý režim, stav a výkon PC.",
};
const MODES: [string, string][] = [["eco", "Úsporný – malý kontext, málo vláken, rychle uvolní paměť"], ["balanced", "Vyvážený (doporučeno)"], ["performance", "Výkon – velký kontext, všechna jádra"]];
const norm = (s: string) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

const getPath = (o: any, path: string) => path.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
function patchOf(path: string, value: unknown) {
  const out: any = {};
  let cur = out;
  const parts = path.split(".");
  parts.slice(0, -1).forEach((p) => (cur = cur[p] = {}));
  cur[parts[parts.length - 1]] = value;
  return out;
}

export function buildSettings(client: JarvisClient, host: HTMLElement) {
  let S: any = null;
  let secretsFlags: Record<string, boolean> = {};
  let presets: Record<string, any> = {};
  let voiceStatus: any = {};
  let current: Section = "general";
  let local = true;
  let permLabels: Record<string, string> = {};
  let query = "";
  const extra: Record<string, any> = {};

  const set = (path: string, value: unknown) => {
    if (!local) return toast("Nastavení jde měnit jen přímo na PC.", "error");
    client.send("settings_set", { patch: patchOf(path, value) });
  };

  // ----- field helpers -----
  const sw = (path: string, title: string, desc = "") => {
    const inp = h("input", { type: "checkbox", role: "switch", "aria-label": title }) as HTMLInputElement;
    inp.checked = !!getPath(S, path);
    inp.onchange = () => set(path, inp.checked);
    return h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, title), desc ? h("span", {}, desc) : null),
      h("label", { class: "switch" }, inp, h("span")));
  };
  const text = (path: string, label: string, help = "", type = "text") => {
    const inp = h("input", { class: "input", type, value: getPath(S, path) ?? "" }) as HTMLInputElement;
    inp.onchange = () => set(path, type === "number" ? Number(inp.value) : inp.value);
    return h("label", { class: "field" }, label, inp, help ? h("span", { class: "help" }, help) : null);
  };
  const select = (path: string, label: string, options: [string, string][], help = "", onChange?: (v: string) => void) => {
    const sel = h("select", { class: "input" }, ...options.map(([v, l]) => h("option", { value: v }, l))) as HTMLSelectElement;
    const cur = String(getPath(S, path) ?? "");
    if (!options.some(([v]) => v === cur)) sel.append(h("option", { value: cur }, cur));
    sel.value = cur;
    sel.onchange = () => { set(path, sel.value); onChange?.(sel.value); };
    return h("label", { class: "field" }, label, sel, help ? h("span", { class: "help" }, help) : null);
  };
  const range = (path: string, label: string, min: number, max: number, step: number, fmt: (v: number) => string, parse?: (s: any) => number, out?: (v: number) => unknown) => {
    const raw = getPath(S, path);
    const val = parse ? parse(raw) : Number(raw);
    const inp = h("input", { type: "range", min, max, step, value: val }) as HTMLInputElement;
    const o = h("output", {}, fmt(val));
    inp.oninput = () => (o.textContent = fmt(Number(inp.value)));
    inp.onchange = () => set(path, out ? out(Number(inp.value)) : Number(inp.value));
    return h("label", { class: "field" }, label, h("div", { class: "range" }, inp, o));
  };
  const card = (title: string, help: string | null, ...kids: (Node | null)[]) =>
    h("div", { class: "card" }, h("h2", {}, title), help ? h("p", { class: "help" }, help) : null, ...kids);
  const pct = (s: string) => parseInt(String(s || "0").replace("%", ""), 10) || 0;
  const signed = (v: number, unit: string) => `${v >= 0 ? "+" : ""}${v}${unit}`;

  // ----- sections -----
  const sections: Record<Section, () => Node[]> = {
    general: () => [
      card("O tobě", null,
        h("div", { class: "grid2" }, text("general.user_name", "Tvoje jméno"), text("general.address_as", "Jak tě má oslovovat", "Např. pane, šéfe, Adame")),
        h("div", { class: "grid2" }, text("general.city", "Domovské město", "Pro počasí"),
          select("general.language", "Jazyk", [["cs", "Čeština"], ["sk", "Slovenčina"], ["en", "English"], ["de", "Deutsch"]]))),
      card("Osobnost", null,
        select("general.personality", "Styl", [["jarvis", "J.A.R.V.I.S. (zdvořilý, suchý humor)"], ["friend", "Kamarád (tyká, uvolněný)"], ["brief", "Stručný (jen fakta)"], ["custom", "Vlastní prompt"]], "", () => setTimeout(render, 150)),
        S.general.personality === "custom" ? (() => {
          const ta = h("textarea", { class: "input", rows: 6 }, S.general.custom_prompt) as HTMLTextAreaElement;
          ta.onchange = () => set("general.custom_prompt", ta.value);
          return h("label", { class: "field" }, "Vlastní systémový prompt", ta);
        })() : null),
      card("Systém", null, sw("general.autostart", "Spouštět po startu Windows", "JARVIS poběží na pozadí v trayi")),
    ],

    brain: () => {
      const providers: any[] = S.brain.providers;
      const chain: string[] = S.brain.chain;
      const ordered = [...chain.map((id) => providers.find((p) => p.id === id)).filter(Boolean), ...providers.filter((p) => !chain.includes(p.id))];
      const saveProviders = (list: any[], newChain?: string[]) => {
        client.send("settings_set", { patch: { brain: { providers: list, chain: newChain ?? list.map((p) => p.id) } } });
      };
      const list = h("div", { style: { display: "grid", gap: "12px" } });
      ordered.forEach((p, i) => {
        const upd = (k: string, v: unknown) => saveProviders(ordered.map((x) => (x.id === p.id ? { ...x, [k]: v } : x)));
        const inp = (k: string, label: string, ph = "") => {
          const el = h("input", { class: "input", value: p[k] ?? "", placeholder: ph }) as HTMLInputElement;
          el.onchange = () => upd(k, el.value.trim());
          return h("label", { class: "field" }, label, el);
        };
        const key = h("input", { class: "input", type: "password", placeholder: secretsFlags[p.id] ? "•••••• (uloženo)" : (presets[p.preset]?.needs_key ? "vlož API klíč" : "není potřeba"), autocomplete: "off" }) as HTMLInputElement;
        key.onchange = () => { client.send("secret_set", { name: p.id, value: key.value.trim() }); key.value = ""; toast("Klíč uložen do Správce pověření Windows", "ok"); };
        const out = h("span", { class: "test-out" });
        const en = h("input", { type: "checkbox", "aria-label": "Zapnuto" }) as HTMLInputElement;
        en.checked = p.enabled;
        en.onchange = () => upd("enabled", en.checked);
        const move = (d: number) => {
          const arr = [...ordered];
          const j = i + d;
          if (j < 0 || j >= arr.length) return;
          [arr[i], arr[j]] = [arr[j], arr[i]];
          saveProviders(arr);
        };
        extra[`test_${p.id}`] = out;
        list.append(h("div", { class: `provider ${p.enabled ? "" : "off"}` },
          h("div", { class: "provider-head" }, h("span", { class: "order" }, String(i + 1)),
            h("strong", {}, `${p.id}`), h("span", { class: "help" }, presets[p.preset]?.label || p.preset),
            h("span", { class: `chip ${presets[p.preset]?.local ? "local" : "cloud"}` }, icon(presets[p.preset]?.local ? "cpu" : "cloud"), presets[p.preset]?.local ? " Lokální" : " Cloud"),
            h("button", { class: "icon-btn sm", type: "button", title: "Výš", "aria-label": "Posunout výš", onclick: () => move(-1) }, icon("arrow-up")),
            h("button", { class: "icon-btn sm", type: "button", title: "Níž", "aria-label": "Posunout níž", onclick: () => move(1) }, icon("arrow-down")),
            h("label", { class: "switch" }, en, h("span")),
            h("button", { class: "icon-btn sm", type: "button", title: "Odebrat", "aria-label": "Odebrat poskytovatele", onclick: () => { if (confirm(`Odebrat ${p.id}?`)) saveProviders(ordered.filter((x) => x.id !== p.id)); } }, icon("trash"))),
          h("div", { class: "grid2" }, inp("base_url", "Adresa (base URL)", presets[p.preset]?.base_url), inp("model", "Model", presets[p.preset]?.model)),
          h("div", { class: "grid2" }, inp("vision_model", "Model pro obrázky (volitelné)"), inp("fast_model", "Rychlý model (volitelné)")),
          h("label", { class: "field" }, "API klíč", key),
          h("div", { class: "row" }, out, h("button", { class: "btn", type: "button", onclick: () => { out.className = "test-out"; out.textContent = "testuji…"; client.send("provider_test", { id: p.id }); } }, icon("plugs"), "Otestovat"))));
      });
      const presetSel = h("select", { class: "input" }, ...Object.entries(presets).map(([k, v]: any) => h("option", { value: k }, v.label))) as HTMLSelectElement;
      const add = () => {
        const pr = presetSel.value;
        let id = pr;
        let n = 2;
        while (providers.some((p) => p.id === id)) id = `${pr}${n++}`;
        saveProviders([...ordered, { id, preset: pr, base_url: presets[pr]?.base_url || "", model: presets[pr]?.model || "", vision_model: "", fast_model: "", enabled: true }]);
      };
      return [
        card("Poskytovatelé (záložní řetěz)", "Výchozí: OmniRoute (zdarma, běží na tvém PC na portu 20128) a pak Ollama (offline). Když jeden selže nebo dojde limit, JARVIS automaticky zkusí další.",
          list, h("div", { class: "row" }, h("div", { style: { flex: "1" } }, presetSel), h("button", { class: "btn primary", type: "button", onclick: add }, icon("plus"), "Přidat poskytovatele"))),
        localCard(),
        card("Chování", null,
          range("brain.temperature", "Kreativita (temperature)", 0, 1.5, 0.1, (v) => v.toFixed(1)),
          h("div", { class: "grid2" }, text("brain.max_tokens", "Max délka odpovědi (tokeny)", "", "number"), text("brain.first_token_timeout", "Čekat na první odpověď (s)", "Pak zkusí dalšího poskytovatele", "number")),
          sw("brain.offline_only", "Jen offline režim", "Používat jen lokální modely (Ollama, LM Studio). Nic neodchází na internet."),
          h("p", { class: "help" }, "Pozor: předplatné Claude Code nedává API klíč. Claude jako mozek potřebuje vlastní klíč z console.anthropic.com (placený).")),
      ];
    },

    voice: () => [
      card("Poslech", null,
        voiceStatus.available ? null : h("div", { class: "readonly-note" }, icon("warning"), " Hlasový modul teď neběží: ", voiceStatus.error || "chybí mikrofon nebo hlasové modely."),
        sw("voice.enabled", "Hlasové ovládání", "Mikrofon, rozpoznávání řeči a hlas"),
        sw("voice.wake_word", "Probouzení slovem „Hey Jarvis“", "Bez toho funguje zkratka (výchozí Ctrl+Alt+Mezerník)"),
        range("voice.wake_threshold", "Citlivost probouzení", 0.2, 0.9, 0.05, (v) => (v < 0.4 ? "vysoká" : v > 0.65 ? "nízká" : "střední") + ` (${v.toFixed(2)})`),
        voiceStatus.devices?.length
          ? select("voice.input_device", "Mikrofon", [["", "Výchozí systémový"], ...voiceStatus.devices.map((d: string) => [d, d] as [string, string])])
          : text("voice.input_device", "Mikrofon (název zařízení)", "Prázdné = výchozí"),
        range("voice.silence_seconds", "Konec věty po tichu", 0.4, 2, 0.1, (v) => `${v.toFixed(1)} s`),
        sw("voice.followup", "Navazovat v rozhovoru", "Po odpovědi JARVIS ještě 6 s poslouchá bez „Hey Jarvis“ (je to vidět). Ukončíš „díky, to je vše“.")),
      card("Rozpoznávání řeči", null,
        h("div", { class: "grid2" },
          select("voice.stt_provider", "Kde rozpoznávat", [["local", "Lokálně (offline, faster-whisper)"], ["groq", "Groq API (rychlé, zdarma, potřebuje klíč u poskytovatele groq)"]]),
          select("voice.stt_model", "Model", [["tiny", "tiny (nejrychlejší)"], ["base", "base (slabé PC)"], ["small", "small (doporučeno)"], ["medium", "medium (přesnější)"], ["large-v3-turbo", "large-v3-turbo (GPU)"]])),
        select("voice.stt_language", "Jazyk řeči", [["cs", "Čeština"], ["sk", "Slovenčina"], ["en", "Angličtina"], ["auto", "Automaticky"]])),
      card("Hlas JARVISe", null,
        select("voice.tts_voice", "Hlas", VOICES as [string, string][], "Microsoft Edge neurální hlasy, zdarma. Offline záloha: Piper."),
        select("voice.tts_voice_en", "Hlas pro angličtinu", VOICES.filter(([v]) => v.startsWith("en-")) as [string, string][], "Když na JARVISe promluvíš nebo napíšeš anglicky, odpoví anglicky tímhle hlasem."),
        (() => {
          const outs: string[] | undefined = extra.audio?.outputs;
          if (!extra.audioAsked) { extra.audioAsked = true; client.send("audio_devices_get"); }
          return outs?.length
            ? select("voice.output_device", "Reproduktor", [["", "Výchozí systémový"], ...outs.map((d) => [d, d] as [string, string])])
            : text("voice.output_device", "Reproduktor (název zařízení)", "Prázdné = výchozí");
        })(),
        h("div", { class: "grid2" },
          range("voice.tts_rate", "Rychlost", -50, 50, 5, (v) => signed(v, " %"), pct, (v) => signed(v, "%")),
          range("voice.tts_pitch", "Výška", -30, 30, 2, (v) => signed(v, " Hz"), (s) => parseInt(String(s).replace("Hz", ""), 10) || 0, (v) => signed(v, "Hz"))),
        range("voice.tts_volume", "Hlasitost hlasu", -50, 50, 5, (v) => signed(v, " %"), pct, (v) => signed(v, "%")),
        select("voice.speak_mode", "Kdy mluvit nahlas", [["voice", "Jen když na něj mluvím"], ["always", "Vždy (i odpovědi v chatu)"], ["never", "Nikdy (jen text)"]]),
        h("div", { class: "btn-row" }, h("button", { class: "btn", type: "button", onclick: () => client.send("speak", { text: "Dobrý den, pane. Všechny systémy jsou připraveny." }) }, icon("speaker-high"), "Přehrát ukázku"))),
    ],

    notch: () => {
      const tiles: string[] = S.notch.tiles;
      const tileBox = h("div", { class: "tiles" }, ...Object.entries(TILE_NAMES).map(([k, label]) => {
        const c = h("input", { type: "checkbox" }) as HTMLInputElement;
        c.checked = tiles.includes(k);
        c.onchange = () => set("notch.tiles", c.checked ? [...tiles, k] : tiles.filter((t) => t !== k));
        return h("label", {}, c, label);
      }));
      return [
        card("Notch", null, sw("notch.enabled", "Zobrazovat notch"), sw("notch.hide_in_fullscreen", "Schovat při hře nebo videu přes celou obrazovku"),
          sw("notch.pinned", "Připnutý panel", "Velký panel zůstane otevřený i po odjetí myší a po restartu")),
        card("Dlaždice v rozevřeném notchi", "Pořadí odpovídá pořadí zaškrtnutí.", tileBox),
        card("Rozměry a chování", null,
          h("div", { class: "grid2" }, text("notch.monitor", "Monitor (0 = hlavní)", "", "number"), text("notch.offset_x", "Posun vodorovně (px)", "", "number")),
          h("div", { class: "grid2" }, text("notch.width", "Šířka v klidu", "", "number"), text("notch.height", "Výška v klidu", "", "number")),
          h("div", { class: "grid2" }, text("notch.expanded_width", "Šířka rozevřeného", "", "number"), text("notch.expanded_height", "Výška rozevřeného", "", "number")),
          h("div", { class: "grid2" }, text("notch.open_delay_ms", "Zpoždění otevření (ms)", "", "number"), text("notch.close_delay_ms", "Zpoždění zavření (ms)", "", "number")),
          text("notch.linger_s", "Jak dlouho ukázat odpověď (s)", "", "number")),
      ];
    },

    appearance: () => {
      const colors = ["#2ee6ff", "#3ddc97", "#ffb547", "#ff5d63", "#7c9bff", "#f472b6", "#e9eef3"];
      const picker = h("input", { type: "color", value: S.appearance.accent, "aria-label": "Vlastní barva" }) as HTMLInputElement;
      picker.onchange = () => set("appearance.accent", picker.value);
      return [card("Barvy", null,
        select("appearance.theme", "Motiv", [["stark", "Stark (tmavý)"], ["light", "Světlý"]]),
        h("div", { class: "field" }, "Akcent", h("div", { class: "swatches" },
          ...colors.map((c) => h("button", { class: `swatch ${S.appearance.accent === c ? "on" : ""}`, type: "button", style: { background: c }, "aria-label": c, onclick: () => set("appearance.accent", c) })), picker)),
        select("appearance.animations", "Animace", [["full", "Plné"], ["reduced", "Omezené"]])),
        card("Zvuky", null, sw("appearance.sounds", "Jemné zvuky rozhraní", "Probuzení, poslech, hotovo, chyba, upozornění"),
          range("appearance.sound_volume", "Hlasitost zvuků", 0, 100, 5, (v) => `${v} %`)),
        characterCard()];
    },

    hotkeys: () => [card("Klávesové zkratky", "Formát: ctrl+alt+space, ctrl+alt+j, f9… (Esc zastaví JARVISe jen když mluví nebo pracuje)",
      text("hotkeys.talk", "Mluvit / psát JARVISovi"), text("hotkeys.chat", "Otevřít okno chatu"), text("hotkeys.stop", "Zastavit JARVISe (řeč i akci)"),
      text("hotkeys.stop_all", "STOP – nouzově zastavit úplně vše", "Zruší úkol, potvrzení, řeč i nahrávání a pustí myš a klávesnici."))],

    permissions: () => [
      card("Oblasti oprávnění", "Platí okamžitě. Nebezpečné akce (mazání, odesílání, instalace, PowerShell…) JARVIS vždy nejdřív potvrdí s tebou.",
        ...Object.keys(PERM_HELP).map((k) => sw(`permissions.${k}`, permLabels[k] || k, PERM_HELP[k]))),
      card("Soukromí", null,
        h("p", { class: "help" }, "Mikrofon se zapíná jen slovem „Hey Jarvis“, zkratkou nebo tlačítkem. Když JARVIS kouká na obrazovku, notch ukáže červenou tečku. Hesla a obsah obrazovky si nepamatuje."),
        h("div", { class: "btn-row" }, h("button", { class: "btn danger", type: "button", onclick: () => client.send("stop_all") }, icon("hand-palm"), "STOP – okamžitě zastavit vše"))),
    ],

    tools: () => {
      const items: any[] = extra.tools || [];
      if (!items.length) client.send("tools_get");
      const disabled: string[] = S.tools.disabled, always: string[] = S.tools.always_confirm, trusted: string[] = S.tools.trusted;
      const cats = new Map<string, any[]>();
      items.forEach((t) => (cats.get(t.category) ?? cats.set(t.category, []).get(t.category)!).push(t));
      const box = h("div", {});
      for (const [cat, list] of cats) {
        box.append(h("p", { class: "tool-cat" }, cat));
        for (const t of list) {
          const sel = h("select", { class: "input", "aria-label": `Oprávnění pro ${t.name}` },
            h("option", { value: "default" }, t.danger ? "Potvrzovat (výchozí)" : "Povoleno"),
            h("option", { value: "always" }, "Vždy potvrdit"),
            h("option", { value: "trusted" }, "Důvěřovat (bez potvrzení)"),
            h("option", { value: "off" }, "Vypnuto")) as HTMLSelectElement;
          sel.value = disabled.includes(t.name) ? "off" : always.includes(t.name) ? "always" : trusted.includes(t.name) ? "trusted" : "default";
          sel.onchange = () => {
            const without = (a: string[]) => a.filter((x) => x !== t.name);
            client.send("settings_set", { patch: { tools: {
              disabled: sel.value === "off" ? [...without(disabled), t.name] : without(disabled),
              always_confirm: sel.value === "always" ? [...without(always), t.name] : without(always),
              trusted: sel.value === "trusted" ? [...without(trusted), t.name] : without(trusted),
            } } });
          };
          box.append(h("div", { class: "tool-row" }, icon(TOOL_ICON[t.name] || "gear-six"),
            h("div", {}, h("div", { class: "t-name" }, t.name), h("div", { class: "t-desc" }, t.description)),
            t.danger ? h("span", { class: "chip", title: "Nebezpečná akce" }, icon("shield-warning")) : h("span"), sel));
        }
      }
      const folders = h("textarea", { class: "input", rows: 3, placeholder: "D:\\Projekty" }, (S.tools.allowed_folders || []).join("\n")) as HTMLTextAreaElement;
      folders.onchange = () => set("tools.allowed_folders", folders.value.split("\n").map((s) => s.trim()).filter(Boolean));
      return [
        card("Povolené složky", "Další složky, kde smí hledat soubory, a projekty pro programování (git, záchytné body, testy). Jedna na řádek. Hlavní oprávnění najdeš v sekci Oprávnění.",
          h("label", { class: "field" }, "Složky", folders)),
        skillsCard(),
        card(`Všechny nástroje (${items.length})`, "Nebezpečné akce JARVIS vždy nejdřív potvrdí s tebou, pokud jim nedáš důvěru.", box),
      ];
    },

    integrations: () => {
      const servers: any[] = S.integrations.mcp || [];
      const status: any[] = extra.mcp || [];
      if (!extra.mcpAsked) { extra.mcpAsked = true; client.send("mcp_get"); }
      const save = (list: any[]) => client.send("settings_set", { patch: { integrations: { mcp: list } } });
      const rows = servers.map((s, i) => {
        const st = status.find((x) => x.name === s.name);
        const f = (k: string, label: string, ph = "") => {
          const v = k === "args" ? (s.args || []).join(" ") : k === "env" ? JSON.stringify(s.env || {}) : s[k] ?? "";
          const el = h("input", { class: "input", value: v, placeholder: ph }) as HTMLInputElement;
          el.onchange = () => {
            let val: any = el.value;
            if (k === "args") val = el.value.split(" ").filter(Boolean);
            if (k === "env") { try { val = JSON.parse(el.value || "{}"); } catch { return toast("Env musí být JSON", "error"); } }
            save(servers.map((x, j) => (j === i ? { ...x, [k]: val } : x)));
          };
          return h("label", { class: "field" }, label, el);
        };
        return h("div", { class: "provider" },
          h("div", { class: "provider-head" }, icon("plug"), h("strong", {}, s.name),
            h("span", { class: `test-out ${st?.ok ? "ok" : st ? "fail" : ""}` }, st ? (st.ok ? `${st.tools} nástrojů` : st.error || "chyba") : ""),
            h("button", { class: "icon-btn sm", type: "button", "aria-label": "Odebrat", onclick: () => save(servers.filter((_, j) => j !== i)) }, icon("trash"))),
          h("div", { class: "grid2" }, f("command", "Příkaz (stdio)", "npx"), f("args", "Argumenty", "-y @modelcontextprotocol/server-filesystem C:\\Users")),
          h("div", { class: "grid2" }, f("url", "nebo URL (HTTP/SSE)", "http://localhost:3000/mcp"), f("env", "Proměnné prostředí (JSON)", '{"API_KEY":"..."}')));
      });
      const name = h("input", { class: "input", placeholder: "např. filesystem" }) as HTMLInputElement;
      return [
        card("MCP servery", "Každý MCP server přidá JARVISovi nové nástroje. Seznam serverů: github.com/modelcontextprotocol/servers.",
          ...rows,
          h("div", { class: "row" }, h("div", { style: { flex: "1" } }, name),
            h("button", { class: "btn primary", type: "button", onclick: () => { if (name.value.trim()) save([...servers, { name: name.value.trim(), command: "", args: [], url: "", env: {}, enabled: true }]); } }, icon("plus"), "Přidat server"))),
        card("Obrázky", null, select("integrations.image_provider", "Generování obrázků", [["pollinations", "Pollinations.ai (zdarma, bez klíče)"]])),
      ];
    },

    phone: () => {
      const p = extra.pairing;
      if (!p) client.send("pairing_get");
      return [
        card("Spárovat telefon", "1) Nainstaluj JARVIS.apk do telefonu. 2) V aplikaci klepni na Naskenovat QR. 3) Hotovo.",
          p ? h("div", { class: "qr" }, h("div", { class: "qr-img", html: p.qr_svg }),
            h("div", { style: { display: "grid", gap: "10px" } },
              h("div", {}, h("strong", {}, "Adresy PC"), h("div", { class: "mono" }, (p.hosts || []).join(", ") || "žádná síť")),
              h("div", {}, h("strong", {}, "Tailscale (odkudkoli)"), h("div", { class: "help" }, p.tailscale?.length ? `Aktivní: ${p.tailscale.join(", ")}` : "Nenalezen. Nainstaluj Tailscale (zdarma) na PC i telefon a přihlas se stejným účtem, pak se k JARVISovi připojíš i z mobilních dat.")),
              h("div", { class: "btn-row" },
                h("button", { class: "btn", type: "button", onclick: () => { navigator.clipboard?.writeText(p.url); toast("Odkaz zkopírován", "ok"); } }, icon("link"), "Kopírovat odkaz"),
                h("button", { class: "btn danger", type: "button", onclick: () => { if (confirm("Vygenerovat nový token? Všechny telefony se budou muset spárovat znovu.")) { extra.pairing = null; client.send("pairing_get", { regenerate: true }); } } }, icon("arrows-clockwise"), "Nový token"))))
            : h("p", { class: "help" }, "Načítám…")),
        card("Připojená zařízení", null, ...(p?.devices?.length ? p.devices.map((d: any) => h("div", { class: "row" }, h("span", {}, icon("device-mobile"), " ", d.name || "Telefon"), h("span", { class: "chip" }, "online"))) : [h("p", { class: "help" }, "Teď není připojený žádný telefon.")])),
      ];
    },

    memory: () => {
      const facts: any[] | undefined = extra.facts;
      if (!facts) client.send("memory_get");
      const add = h("input", { class: "input", placeholder: "Např. Mám rád rock a hraju na kytaru" }) as HTMLInputElement;
      return [
        card("Co si o tobě pamatuje", "JARVIS si fakta ukládá sám, když mu řekneš „zapamatuj si…“. Tady je můžeš upravit.",
          ...(facts || []).map((f) => {
            const inp = h("input", { class: "input", value: f.text }) as HTMLInputElement;
            inp.onchange = () => client.send("fact_update", { id: f.id, text: inp.value });
            return h("div", { class: "fact" }, inp, h("button", { class: "icon-btn", type: "button", "aria-label": "Smazat", onclick: () => client.send("fact_delete", { id: f.id }) }, icon("trash")));
          }),
          facts && !facts.length ? h("p", { class: "help" }, "Zatím si nic nepamatuje.") : null,
          h("div", { class: "fact" }, add, h("button", { class: "btn primary", type: "button", onclick: () => { if (add.value.trim()) client.send("fact_update", { text: add.value.trim() }); } }, icon("plus"), "Přidat"))),
        card("Export a import paměti", "Fakta (a volitelně konverzace) jako soubor JSON. Přílohy se neexportují.",
          (() => {
            const withConv = h("input", { type: "checkbox", "aria-label": "I konverzace" }) as HTMLInputElement;
            const file = h("input", { type: "file", accept: "application/json", hidden: true }) as HTMLInputElement;
            file.onchange = async () => {
              const f = file.files?.[0];
              if (!f) return;
              try { client.send("memory_import", { data: JSON.parse(await f.text()), merge: true }); }
              catch { toast("Soubor není platný JSON", "error"); }
              file.value = "";
            };
            return h("div", { class: "btn-row" },
              h("label", { class: "check" }, withConv, " i konverzace"),
              h("button", { class: "btn primary", type: "button", onclick: () => client.send("memory_export", { conversations: withConv.checked }) }, icon("download-simple"), "Exportovat"),
              h("button", { class: "btn", type: "button", onclick: () => file.click() }, icon("upload-simple"), "Importovat"), file);
          })()),
        card("Historie úkolů", "Úkoly a provedené akce se ukládají zvlášť od paměti.",
          h("div", { class: "btn-row" }, h("a", { class: "btn", href: "#tasks" }, icon("list-checks"), "Otevřít Úkoly"))),
        card("Smazat vše", "Smaže celou historii konverzací i paměť. Nejde vrátit.",
          h("div", {}, h("button", { class: "btn danger", type: "button", onclick: () => { if (confirm("Opravdu smazat celou paměť a historii?")) client.send("memory_wipe"); } }, icon("trash"), "Smazat paměť a historii"))),
      ];
    },

    jobs: () => {
      const jobs: any[] | undefined = extra.jobs;
      if (!jobs) client.send("jobs_get");
      return [card("Naplánované", null,
        ...(jobs || []).map((j) => h("div", { class: "row" },
          h("div", { class: "row-text" }, h("strong", {}, j.title || j.kind), h("span", {}, `${j.spec_text || ""} · další: ${j.next_run ? new Date(j.next_run * 1000).toLocaleString("cs-CZ") : "-"}`)),
          h("button", { class: "icon-btn", type: "button", "aria-label": "Smazat", onclick: () => client.send("job_delete", { id: j.id }) }, icon("trash")))),
        jobs && !jobs.length ? h("p", { class: "help" }, "Nic naplánováno. Zkus v chatu: „Každý všední den v 7:00 mi řekni počasí a co je nového.“") : null)];
    },

    backup: () => {
      const file = h("input", { type: "file", accept: "application/json", hidden: true }) as HTMLInputElement;
      file.onchange = async () => {
        const f = file.files?.[0];
        if (!f) return;
        try {
          const data = JSON.parse(await f.text());
          if (data.settings) {
            delete data.settings.phone;
            client.send("settings_set", { patch: data.settings });
          }
          for (const fact of data.facts || []) client.send("fact_update", { text: fact.text || fact });
          toast("Záloha obnovena", "ok");
        } catch {
          toast("Neplatný soubor zálohy", "error");
        }
      };
      const exportIt = () => {
        const blob = new Blob([JSON.stringify({ app: "JARVIS", version: 2, settings: S, facts: extra.facts || [] }, null, 2)], { type: "application/json" });
        const a = h("a", { href: URL.createObjectURL(blob), download: `jarvis-zaloha-${new Date().toISOString().slice(0, 10)}.json` });
        a.click();
      };
      if (!extra.facts) client.send("memory_get");
      return [card("Záloha", "API klíče se do zálohy neukládají.",
        h("div", { class: "btn-row" }, h("button", { class: "btn primary", type: "button", onclick: exportIt }, icon("download-simple"), "Exportovat"),
          h("button", { class: "btn", type: "button", onclick: () => file.click() }, icon("upload-simple"), "Importovat"), file))];
    },
  };

  function localCard() {
    const st = extra.local;
    if (!extra.localAsked) { extra.localAsked = true; client.send("local_status"); }
    if (!st) return card("Lokální AI (offline)", null, h("p", { class: "help" }, "Zjišťuji stav Ollamy a hardware…"));
    const hw = st.hardware || {};
    const gpu = (hw.gpus || []).map((g: any) => `${g.name}${g.vram_gb ? ` (${g.vram_gb} GB)` : ""}`).join(", ") || "nezjištěno";
    const installed = new Map<string, number>((st.installed || []).map((m: any) => [m.name, m.size_gb]));
    const loaded = new Set((st.loaded || []).map((m: any) => m.name));
    const prog = extra.pull || {};
    const rows = (st.catalog || []).map((m: any) => {
      const inst = installed.has(m.name);
      const p = prog[m.name];
      const action = p && !p.done && !p.error && !p.cancelled
        ? h("div", { class: "pull" }, h("span", { class: "p-progress" }, h("b", { style: { width: `${p.total ? Math.round((p.completed || 0) / p.total * 100) : 5}%` } })),
            h("button", { class: "btn ghost sm", type: "button", onclick: () => client.send("local_pull_cancel") }, "Zrušit"))
        : inst
          ? h("button", { class: "btn ghost sm", type: "button", onclick: () => { if (confirm(`Smazat ${m.name} (${installed.get(m.name)} GB)?`)) client.send("local_delete", { name: m.name }); } }, icon("trash"), "Smazat")
          : h("button", { class: "btn sm", type: "button", disabled: !st.running, onclick: () => {
              if (confirm(`Stáhnout ${m.name} (${m.size_gb} GB)? Volné místo: ${hw.disk_free_gb ?? "?"} GB.`)) { extra.pull = { ...prog, [m.name]: { completed: 0 } }; client.send("local_pull", { name: m.name }); render(); }
            } }, icon("download-simple"), `Stáhnout (${m.size_gb} GB)`);
      return h("div", { class: "model-row" },
        h("div", { class: "row-text" }, h("strong", {}, m.label, (st.recommended || []).includes(m.name) ? h("span", { class: "chip ok" }, "doporučeno") : null),
          h("span", {}, `${m.name} · ${m.size_gb} GB${m.vision ? " · vidí obrázky" : ""}${m.note ? ` · ${m.note}` : ""}`)),
        inst ? h("span", { class: "chip" }, loaded.has(m.name) ? "v paměti" : "staženo") : null,
        p?.error ? h("span", { class: "test-out fail" }, p.error) : null,
        action);
    });
    return card("Lokální AI (offline)", "Modely běží přímo v tvém PC přes Ollamu. Nic se nestáhne bez tvého kliknutí.",
      h("div", { class: "grid2" },
        h("div", { class: "row-text" }, h("strong", {}, "Tvůj počítač"), h("span", {}, `RAM ${hw.ram_gb ?? "?"} GB · procesor ${hw.cores ?? "?"}× · GPU: ${gpu} · volno na disku ${hw.disk_free_gb ?? "?"} GB`)),
        h("div", { class: "row-text" }, h("strong", {}, "Ollama"), st.running
          ? h("span", {}, `běží (verze ${st.version})`)
          : h("span", {}, "neběží – ", h("a", { href: "https://ollama.com/download", target: "_blank", rel: "noopener" }, "stáhnout Ollamu"), " a spustit"))),
      sw("brain.local_enabled", "Lokální AI zapnutá", "Vypnuto: JARVIS lokální modely nepoužívá a uvolní je z paměti. Notch a vše ostatní běží dál."),
      select("brain.local_mode", "Výkonový režim", MODES),
      h("div", { class: "models" }, ...rows),
      h("div", { class: "btn-row" },
        h("button", { class: "btn", type: "button", disabled: !st.running, onclick: () => { extra.gpuMsg = "Testuji… (první spuštění modelu může chvíli trvat)"; client.send("local_gpu_test"); render(); } }, icon("graphics-card"), "Otestovat GPU"),
        h("button", { class: "btn ghost", type: "button", disabled: !st.running, onclick: () => client.send("local_unload") }, icon("eject"), "Uvolnit z paměti"),
        h("button", { class: "btn ghost", type: "button", onclick: () => { extra.localAsked = false; render(); } }, icon("arrows-clockwise"), "Obnovit")),
      extra.gpuMsg || st.gpu ? h("p", { class: "help" }, extra.gpuMsg || (st.gpu === "gpu" ? "Poslední test: model běží na GPU." : "Poslední test: model běží jen na procesoru.")) : null);
  }

  function skillsCard() {
    const items: any[] | undefined = extra.skills;
    if (!extra.skillsAsked) { extra.skillsAsked = true; client.send("skills_get"); }
    return card("Naučené dovednosti (skilly)", "Izolace chrání před pádem a zaseknutím, není to bezpečnostní sandbox – povoluj jen kód, kterému rozumíš.",
      ...(items || []).map((s) => {
        const on = h("input", { type: "checkbox", role: "switch", "aria-label": `Povolit ${s.name}` }) as HTMLInputElement;
        on.checked = !!s.approved;
        on.onchange = () => client.send("skill_approve", { name: s.name, approved: on.checked });
        return h("details", { class: "skill" },
          h("summary", {}, h("strong", {}, s.name), h("span", { class: "help" }, s.manifest?.description || ""),
            ...(s.manifest?.permissions || []).map((p: string) => h("span", { class: "chip" }, permLabels[p] || p)),
            h("span", { class: "chip" }, `${s.manifest?.timeout ?? 30} s`),
            h("label", { class: "switch" }, on, h("span"))),
          h("pre", { class: "skill-code" }, s.code || ""));
      }),
      items && !items.length ? h("p", { class: "help" }, "Zatím žádné. Řekni třeba: „Nauč se převádět měny.“") : null);
  }

  function characterCard() {
    const ch = S.character || {};
    const preview = new Character({ size: 110 });
    preview.setMood("personalize");
    preview.setColor(ch.color || "black", ch.glow || undefined);
    const colors: [string, string][] = [["black", "Černá"], ["midnight", "Půlnoční"], ["violet", "Fialová"], ["rose", "Růžová"], ["white", "Bílá"]];
    const glow = h("input", { type: "color", value: ch.glow || DEFAULT_GLOW, "aria-label": "Barva záře" }) as HTMLInputElement;
    glow.onchange = () => set("character.glow", glow.value);
    return card("Postavička JARVIS", "Vzhled JARVISe v notchi, na ploše i v telefonu. Hlasem: „buď fialový“.",
      h("div", { class: "char-row" }, preview.el,
        h("div", { style: { display: "grid", gap: "12px" } },
          h("div", { class: "field" }, "Barva těla", h("div", { class: "swatches" }, ...colors.map(([c, label]) =>
            h("button", { class: `swatch char-${c} ${ch.color === c ? "on" : ""}`, type: "button", title: label, "aria-label": label, onclick: () => set("character.color", c) })))),
          h("div", { class: "field" }, "Záře", h("div", { class: "swatches" }, glow,
            h("button", { class: "btn ghost", type: "button", onclick: () => set("character.glow", "") }, "Výchozí modrá"))),
          select("character.size", "Velikost na ploše", [["S", "Malá"], ["M", "Střední"], ["L", "Velká"]]),
          sw("character.pet_mode", "Mazlíček na ploše", "JARVIS chodí po hlavním panelu a oknech. Dvojklik ho vrátí do notche."))));
  }

  const searchInput = h("input", { class: "input", type: "search", placeholder: "Hledat v nastavení…", "aria-label": "Hledat v nastavení" }) as HTMLInputElement;
  const searchBox = h("div", { class: "set-search" }, icon("magnifying-glass"), searchInput);
  let searchTimer = 0;
  searchInput.oninput = () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(() => { query = searchInput.value; render(); searchInput.focus(); }, 200); };

  function render() {
    if (!S) {
      host.replaceChildren(h("div", { class: "set-page" }, h("p", { class: "help" }, "Načítám nastavení…")));
      return;
    }
    const [ic, title, lead] = TITLES[current];
    const scroll = host.scrollTop;
    const q = norm(query.trim());
    let body: Node[];
    if (q) {
      // search across every section: keep only cards (and their rows) that match
      body = [];
      for (const sec of Object.keys(sections) as Section[]) {
        const cards = (sections[sec]() as HTMLElement[]).filter((c) => c instanceof HTMLElement && norm(c.textContent || "").includes(q));
        for (const c of cards) {
          c.querySelectorAll(".row, .field, .tool-row").forEach((r) => { if (!norm(r.textContent || "").includes(q) && !norm(c.querySelector("h2")?.textContent || "").includes(q)) (r as HTMLElement).hidden = true; });
          body.push(h("p", { class: "search-sec" }, icon(TITLES[sec][0]), " ", TITLES[sec][1]), c);
        }
      }
      if (!body.length) body = [h("p", { class: "help" }, "Nic nenalezeno.")];
    } else body = sections[current]();
    host.replaceChildren(searchBox, h("div", { class: "set-page" },
      q ? h("h1", {}, icon("magnifying-glass"), `Hledání „${query.trim()}“`) : h("h1", {}, icon(ic), title),
      q ? null : h("p", { class: "lead" }, lead),
      local ? null : h("div", { class: "readonly-note" }, "Nastavení jde měnit jen přímo na počítači."),
      ...body));
    host.scrollTop = scroll;
  }

  client.on("welcome", (m) => { S = m.settings; local = !!m.local; voiceStatus = m.voice || {}; client.send("settings_get"); render(); });
  client.on("settings", (m) => { S = m.settings; if (m.secrets) secretsFlags = m.secrets; if (m.presets) presets = m.presets; if (m.perm_labels) permLabels = m.perm_labels; if (m.voice) voiceStatus = m.voice; render(); });
  client.on("local_info", (m) => { extra.local = m; if (m.gpu_message) extra.gpuMsg = m.gpu_message; if (current === "brain") render(); });
  client.on("local_pull_progress", (m) => {
    extra.pull = { ...(extra.pull || {}), [m.name]: m };
    if (m.done || m.cancelled || m.error) { extra.localAsked = false; if (m.done) toast(`${m.name} staženo`, "ok"); }
    if (current === "brain") render();
  });
  client.on("local_model_missing", (m) => toast(`Pro offline režim stáhni ${m.name} (${m.size_gb} GB) v Nastavení → Mozek → Lokální AI.`, "info", 9000));
  client.on("audio_devices", (m) => { extra.audio = m; if (current === "voice") render(); });
  client.on("skills", (m) => { extra.skills = m.items; if (current === "tools") render(); });
  client.on("memory_export_data", (m) => {
    const blob = new Blob([JSON.stringify(m.data, null, 2)], { type: "application/json" });
    h("a", { href: URL.createObjectURL(blob), download: `jarvis-pamet-${new Date().toISOString().slice(0, 10)}.json` }).click();
  });
  client.on("memory_import_result", (m) => toast(`Importováno: ${m.facts_added} faktů, ${m.conversations_added} konverzací (přeskočeno ${m.facts_skipped})`, "ok"));
  client.on("settings_changed", (m) => { S = m.settings; render(); });
  client.on("voice_status", (m) => { voiceStatus = m; if (current === "voice") render(); });
  client.on("provider_test_result", (m) => {
    const out = extra[`test_${m.id}`] as HTMLElement | undefined;
    if (out) { out.className = `test-out ${m.ok ? "ok" : "fail"}`; out.textContent = m.ok ? `OK (${m.ms} ms): ${m.message}` : m.message; }
  });
  client.on("tools", (m) => { extra.tools = m.items; if (current === "tools") render(); });
  client.on("mcp", (m) => { extra.mcp = m.items; if (current === "integrations") render(); });
  client.on("pairing", (m) => { extra.pairing = m; if (current === "phone") render(); });
  client.on("memory", (m) => { extra.facts = m.facts; if (current === "memory" || current === "backup") render(); });
  client.on("jobs", (m) => { extra.jobs = m.items; if (current === "jobs") render(); });

  return {
    show(s: Section) {
      current = s;
      if (s === "phone") extra.pairing = null;
      if (s === "jobs") extra.jobs = undefined;
      if (s === "integrations") extra.mcpAsked = false;
      if (s === "brain") extra.localAsked = false;
      if (s === "tools") extra.skillsAsked = false;
      if (s === "voice") extra.audioAsked = false;
      query = "";
      searchInput.value = "";
      render();
    },
  };
}
