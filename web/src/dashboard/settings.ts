import { h, icon, toast, TOOL_ICON } from "../shared/dom";
import { Blob as Character } from "../character/blob";
import type { JarvisClient } from "../shared/ws";

export type Section =
  | "general" | "brain" | "voice" | "notch" | "appearance" | "hotkeys" | "tools" | "integrations"
  | "phone" | "memory" | "jobs" | "backup";

const TITLES: Record<Section, [string, string, string]> = {
  general: ["user-circle", "Obecné", "Kdo jsi a jak se k tobě JARVIS chová."],
  brain: ["brain", "Mozek (AI)", "Odkud JARVIS bere inteligenci. Zkouší poskytovatele odshora dolů, dokud jeden neodpoví."],
  voice: ["waveform", "Hlas", "Probouzení, rozpoznávání řeči a hlas JARVISe."],
  notch: ["rectangle", "Notch", "Výřez nahoře na obrazovce, který se po najetí myší rozevře."],
  appearance: ["palette", "Vzhled", "Barvy a animace."],
  hotkeys: ["keyboard", "Zkratky", "Globální klávesové zkratky (fungují v jakékoli aplikaci)."],
  tools: ["toolbox", "Nástroje a oprávnění", "Co JARVIS smí dělat a co musíš potvrdit."],
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
        card("Chování", null,
          range("brain.temperature", "Kreativita (temperature)", 0, 1.5, 0.1, (v) => v.toFixed(1)),
          h("div", { class: "grid2" }, text("brain.max_tokens", "Max délka odpovědi (tokeny)", "", "number"), text("brain.first_token_timeout", "Čekat na první odpověď (s)", "Pak zkusí dalšího poskytovatele", "number")),
          sw("brain.offline_only", "Jen offline režim", "Používat jen lokální modely (Ollama, LM Studio). Nic neodchází na internet.")),
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
        range("voice.silence_seconds", "Konec věty po tichu", 0.4, 2, 0.1, (v) => `${v.toFixed(1)} s`)),
      card("Rozpoznávání řeči", null,
        h("div", { class: "grid2" },
          select("voice.stt_provider", "Kde rozpoznávat", [["local", "Lokálně (offline, faster-whisper)"], ["groq", "Groq API (rychlé, zdarma, potřebuje klíč u poskytovatele groq)"]]),
          select("voice.stt_model", "Model", [["tiny", "tiny (nejrychlejší)"], ["base", "base (slabé PC)"], ["small", "small (doporučeno)"], ["medium", "medium (přesnější)"], ["large-v3-turbo", "large-v3-turbo (GPU)"]])),
        select("voice.stt_language", "Jazyk řeči", [["cs", "Čeština"], ["sk", "Slovenčina"], ["en", "Angličtina"], ["auto", "Automaticky"]])),
      card("Hlas JARVISe", null,
        select("voice.tts_voice", "Hlas", VOICES as [string, string][], "Microsoft Edge neurální hlasy, zdarma. Offline záloha: Piper."),
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
        card("Notch", null, sw("notch.enabled", "Zobrazovat notch"), sw("notch.hide_in_fullscreen", "Schovat při hře nebo videu přes celou obrazovku")),
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
        characterCard()];
    },

    hotkeys: () => [card("Klávesové zkratky", "Formát: ctrl+alt+space, ctrl+alt+j, f9… (Esc zastaví JARVISe jen když mluví nebo pracuje)",
      text("hotkeys.talk", "Mluvit / psát JARVISovi"), text("hotkeys.chat", "Otevřít okno chatu"), text("hotkeys.stop", "Zastavit JARVISe (řeč i akci)"))],

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
        card("Hlavní oprávnění", null,
          sw("tools.computer_use", "Ovládání počítače (myš a klávesnice)", "JARVIS vidí obrazovku a kliká jako člověk. Na začátku úkolu se vždy zeptá."),
          h("label", { class: "field" }, "Další složky, kde smí hledat soubory (jedna na řádek)", folders)),
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

  function characterCard() {
    const ch = S.character || {};
    const preview = new Character({ size: 110 });
    preview.setMood("personalize");
    preview.setColor(ch.color || "black", ch.glow || undefined);
    const colors: [string, string][] = [["black", "Černá"], ["midnight", "Půlnoční"], ["violet", "Fialová"], ["rose", "Růžová"], ["white", "Bílá"]];
    const glow = h("input", { type: "color", value: ch.glow || S.appearance.accent, "aria-label": "Barva záře" }) as HTMLInputElement;
    glow.onchange = () => set("character.glow", glow.value);
    return card("Postavička JARVIS", "Vzhled JARVISe v notchi, na ploše i v telefonu. Hlasem: „buď fialový“.",
      h("div", { class: "char-row" }, preview.el,
        h("div", { style: { display: "grid", gap: "12px" } },
          h("div", { class: "field" }, "Barva těla", h("div", { class: "swatches" }, ...colors.map(([c, label]) =>
            h("button", { class: `swatch char-${c} ${ch.color === c ? "on" : ""}`, type: "button", title: label, "aria-label": label, onclick: () => set("character.color", c) })))),
          h("div", { class: "field" }, "Záře", h("div", { class: "swatches" }, glow,
            h("button", { class: "btn ghost", type: "button", onclick: () => set("character.glow", "") }, "Podle akcentu"))),
          select("character.size", "Velikost na ploše", [["S", "Malá"], ["M", "Střední"], ["L", "Velká"]]),
          sw("character.pet_mode", "Mazlíček na ploše", "JARVIS chodí po hlavním panelu a oknech. Dvojklik ho vrátí do notche."))));
  }

  function render() {
    if (!S) {
      host.replaceChildren(h("div", { class: "set-page" }, h("p", { class: "help" }, "Načítám nastavení…")));
      return;
    }
    const [ic, title, lead] = TITLES[current];
    const scroll = host.scrollTop;
    host.replaceChildren(h("div", { class: "set-page" },
      h("h1", {}, icon(ic), title), h("p", { class: "lead" }, lead),
      local ? null : h("div", { class: "readonly-note" }, "Nastavení jde měnit jen přímo na počítači."),
      ...sections[current]()));
    host.scrollTop = scroll;
  }

  client.on("welcome", (m) => { S = m.settings; local = !!m.local; voiceStatus = m.voice || {}; client.send("settings_get"); render(); });
  client.on("settings", (m) => { S = m.settings; if (m.secrets) secretsFlags = m.secrets; if (m.presets) presets = m.presets; if (m.voice) voiceStatus = m.voice; render(); });
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
      render();
    },
  };
}
