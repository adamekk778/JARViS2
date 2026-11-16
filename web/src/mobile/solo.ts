/* 3.12 "Bez PC": when the PC is off or out of reach, the phone talks to a free AI (Groq or Gemini) directly.
   The key stays in Android's secure storage (Keystore) – in a normal browser only for this visit. Chats are kept on the
   phone; anything that needs the PC can be queued and goes to JARVIS on the PC once it answers again. Every 20 s the
   app checks whether the PC is back and switches over. */
import { Capacitor, CapacitorHttp } from "@capacitor/core";
import "../shared/chat.css";
import { h, icon, toast } from "../shared/dom";
import { renderMarkdown, wireCodeCopy } from "../shared/markdown";
import { native } from "./native";
import { queueForPc } from "./offline";
import "./solo.css";

type Pid = "groq" | "gemini" | "cerebras" | "openrouter" | "nvidia" | "mistral" | "github";
// 3.12 every free AI the phone can talk to by itself; with more keys saved, a used-up limit simply moves on to the next
const AI: Record<Pid, { name: string; base: string; model: string; url: string; prefix: string; hint: string; ico: string }> = {
  groq: { name: "Groq", base: "https://api.groq.com/openai/v1", model: "openai/gpt-oss-120b", url: "https://console.groq.com/keys",
    prefix: "gsk_", hint: "Velmi rychlá. Klíč gsk_…", ico: "lightning" },
  cerebras: { name: "Cerebras", base: "https://api.cerebras.ai/v1", model: "gpt-oss-120b", url: "https://cloud.cerebras.ai",
    prefix: "csk-", hint: "Nejrychlejší. Klíč csk-…", ico: "rocket-launch" },
  gemini: { name: "Gemini", base: "https://generativelanguage.googleapis.com/v1beta/openai", model: "gemini-flash-latest", url: "https://aistudio.google.com/apikey",
    prefix: "AIza", hint: "Od Googlu. Klíč AIza…", ico: "sparkle" },
  openrouter: { name: "OpenRouter", base: "https://openrouter.ai/api/v1", model: "openrouter/free", url: "https://openrouter.ai/keys",
    prefix: "sk-or-", hint: "Modely zdarma. Klíč sk-or-…", ico: "shuffle" },
  nvidia: { name: "NVIDIA", base: "https://integrate.api.nvidia.com/v1", model: "openai/gpt-oss-20b", url: "https://build.nvidia.com",
    prefix: "nvapi-", hint: "Velké modely. Klíč nvapi-…", ico: "cpu" },
  mistral: { name: "Mistral", base: "https://api.mistral.ai/v1", model: "mistral-medium-latest", url: "https://console.mistral.ai/api-keys",
    prefix: "", hint: "Hodně zdarma za měsíc.", ico: "wind" },
  github: { name: "GitHub", base: "https://models.github.ai/inference", model: "openai/gpt-4.1-mini", url: "https://github.com/settings/tokens",
    prefix: "github_pat_", hint: "S účtem GitHub. Klíč github_pat_…", ico: "github-logo" },
};
const ORDER: Pid[] = ["cerebras", "groq", "gemini", "openrouter", "nvidia", "mistral", "github"];
const CFG = "jarvis.solo", HIST = "jarvis.solo.history", MAX_HIST = 60;
type Msg = { role: "user" | "assistant"; text: string; at: number; queued?: boolean };

const memKeys: Partial<Record<Pid, string>> = {};      // a normal browser: only while the page is open
const load = <T>(k: string, d: T): T => { try { return JSON.parse(localStorage.getItem(k) || "") ?? d; } catch { return d; } };
const save = (k: string, v: unknown) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* full */ } };

export const soloProvider = (): Pid | null => {
  const p = load<{ provider?: Pid }>(CFG, {}).provider;
  return p && p in AI ? p : null;
};

async function getKey(p: Pid): Promise<string> {
  if (!native.isNative) return memKeys[p] || "";
  try {
    const { NativeBiometric } = await import("@capgo/capacitor-native-biometric");
    return (await NativeBiometric.getCredentials({ server: `jarvis.solo.${p}` })).password || "";
  } catch { return ""; }
}
async function setKey(p: Pid, key: string) {
  if (!native.isNative) { memKeys[p] = key; return; }
  const { NativeBiometric } = await import("@capgo/capacitor-native-biometric");
  if (key) await NativeBiometric.setCredentials({ server: `jarvis.solo.${p}`, username: p, password: key });
  else await NativeBiometric.deleteCredentials({ server: `jarvis.solo.${p}` }).catch(() => {});
}

/** a request to the AI service (the native one avoids the browser's CORS limits) */
async function call(url: string, method: "GET" | "POST", headers: Record<string, string>, body?: unknown): Promise<{ status: number; data: any }> {
  try {
    if (Capacitor.isNativePlatform()) {
      const r = await CapacitorHttp.request({ url, method, headers, data: body, connectTimeout: 15000, readTimeout: 60000 });
      let data: any = r.data;
      if (typeof data === "string") { try { data = JSON.parse(data || "{}"); } catch { data = {}; } }
      return { status: r.status, data };
    }
    const r = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, data: await r.json().catch(() => ({})) };
  } catch {
    throw Object.assign(new Error("Nejde se spojit s internetem. Zkontroluj data nebo Wi-Fi."), { net: true });
  }
}

// 3.12 services switch models off (NVIDIA's Llama, OpenRouter's free Llama in 2026): when the model is gone, the phone
// asks the service which ones it has, takes the best and remembers it
const MODELS = "jarvis.solo.models";
const NOT_CHAT = /whisper|tts|guard|embed|safety|moderation|retriev|clip|detector|calibration|translate|starcoder|code/i;
const modelOf = (p: Pid) => load<Record<string, string>>(MODELS, {})[p] || AI[p].model;
function pickModel(ids: string[], free: boolean): string {
  const chat = ids.filter((m) => !NOT_CHAT.test(m));
  if (free) {
    if (ids.includes("openrouter/free")) return "openrouter/free";
    const f = chat.find((m) => m.endsWith(":free"));
    if (f) return f;
  }
  for (const want of ["openai/gpt-oss-120b", "gpt-oss-120b", "gemini-flash-latest", "openai/gpt-oss-20b", "gpt-oss-20b"]) if (ids.includes(want)) return want;
  return chat.find((m) => /gemini.*flash|mistral-(medium|large)|llama|qwen|deepseek|nemotron|gemma/i.test(m)) || chat[0] || "";
}
const goneModel = (status: number, data: any) => [400, 404, 410, 422].includes(status)
  && /model/i.test(JSON.stringify(data || {})) && /not found|unknown|does not exist|no longer|end of life|retired|deprecated|decommission|invalid|gone|not available/i.test(JSON.stringify(data || {}));

/** one answer from the AI (no streaming) */
async function ask(p: Pid, key: string, messages: { role: string; content: string }[]): Promise<string> {
  const a = AI[p];
  const headers = { Authorization: `Bearer ${key}`, "Content-Type": "application/json" };
  let model = modelOf(p);
  let { status, data } = await call(`${a.base}/chat/completions`, "POST", headers, { model, messages, temperature: 0.6, max_tokens: 1200 });
  if (goneModel(status, data)) {
    const list = await call(`${a.base}/models`, "GET", headers).catch(() => ({ status: 0, data: null }));
    const ids: string[] = (Array.isArray(list.data?.data) ? list.data.data : Array.isArray(list.data) ? list.data : [])
      .map((m: any) => String(m?.id || "").replace(/^models\//, "")).filter(Boolean);
    const next = pickModel(ids, model.endsWith(":free") || model === "openrouter/free");
    if (next && next !== model) {
      model = next;
      save(MODELS, { ...load<Record<string, string>>(MODELS, {}), [p]: next });
      ({ status, data } = await call(`${a.base}/chat/completions`, "POST", headers, { model, messages, temperature: 0.6, max_tokens: 1200 }));
    }
  }
  if (status === 401 || status === 403) throw new Error(`${a.name} klíč odmítl – zkopíruj ho znovu celý${a.prefix ? ` (začíná ${a.prefix})` : ""}.`);
  if (status === 429) throw Object.assign(new Error(`${a.name}: vyčerpaný bezplatný limit – zkus to za chvíli.`), { limit: true });
  if (status === 503 || status === 529) throw Object.assign(new Error(`${a.name} je teď přetížený – zkus to za chvíli.`), { limit: true });   // "high demand": the next AI answers
  if (status >= 400) throw new Error(`${a.name} odpověděl chybou ${status}${data?.error?.message ? `: ${String(data.error.message).slice(0, 140)}` : ""}`);
  const text = data?.choices?.[0]?.message?.content;
  if (typeof text !== "string" || !text.trim()) throw new Error(`${a.name} poslal prázdnou odpověď – zkus to znovu.`);
  return text.trim();
}

function system(name: string) {
  const now = new Date().toLocaleString("cs-CZ", { weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
  return `Jsi JARVIS, osobní asistent${name ? ` uživatele ${name}` : ""}. Odpovídej česky, stručně, přátelsky a věcně; formátuj Markdownem.
Teď běžíš jen v telefonu, protože počítač je vypnutý nebo mimo dosah. Nemůžeš ovládat počítač, číst jeho soubory, posílat e-maily ani SMS.
Když o něco takového uživatel požádá, řekni, že to udělá JARVIS na PC, a ať klepne na „Poslat PC“ pod zprávou – úkol počká a PC ho udělá, až se zapne.
Teď je ${now}.`;
}

/** the screen; `retry` looks for the PC (true = found, the app switches back) */
export function soloScreen(app: HTMLElement, o: { retry: () => Promise<boolean>; pair: () => void; reason?: string; wake?: () => void }) {
  let hist = load<Msg[]>(HIST, []);
  let provider: Pid = soloProvider() || "groq";
  let busy = false, timer = 0;
  const list = h("div", { class: "chat-list solo-list" });
  const scroll = h("div", { class: "chat-scroll" }, list);
  wireCodeCopy(list);
  const input = h("textarea", { class: "chat-input", rows: 1, placeholder: "Zeptej se na cokoli…", "aria-label": "Zpráva" }) as HTMLTextAreaElement;
  const send = h("button", { class: "send-btn", type: "button", "aria-label": "Odeslat", onclick: () => submit() }, icon("arrow-up", "ph-bold"));
  input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${Math.min(160, input.scrollHeight)}px`; });
  const pill = h("button", { class: "solo-pill", type: "button", onclick: () => setup() });
  const banner = h("div", { class: "solo-banner" },
    h("span", { class: "solo-dot" }), h("div", {}, h("strong", {}, "PC je vypnuté"), h("span", {}, o.reason || "Odpovídám přímo z telefonu. Až se PC zapne, přepnu se sám.")),
    o.wake ? h("button", { class: "btn sm primary", type: "button", onclick: () => o.wake?.() }, icon("power"), "Zapnout PC") : null,
    h("button", { class: "btn sm", type: "button", onclick: () => lookForPc(true) }, icon("arrows-clockwise"), "Zkusit PC"));
  const body = h("div", { class: "solo-body" }, scroll,
    h("div", { class: "composer" }, h("div", { class: "composer-row" }, input, send)));
  const head = h("header", { class: "m-head solo-head" },
    h("div", { class: "m-title" }, h("div", { class: "solo-eyes", "aria-hidden": "true" }, h("i"), h("i")),
      h("div", {}, h("strong", {}, "JARVIS"), h("span", { class: "m-status" }, "bez PC"))),
    pill,
    h("button", { class: "icon-btn", type: "button", "aria-label": "Smazat konverzaci", title: "Nová konverzace",
      onclick: () => { if (!hist.length || confirm("Smazat konverzaci v telefonu?")) { hist = []; save(HIST, hist); paint(); } } }, icon("note-pencil")));
  const shell = h("div", { class: "solo" }, head, banner, body);
  app.replaceChildren(shell);

  function paintPill() { pill.replaceChildren(icon(AI[provider]?.ico || "sparkle", "ph-fill"), h("span", {}, AI[provider]?.name || "AI"), icon("caret-down")); }
  function msgEl(m: Msg, i: number) {
    if (m.role === "user") return h("div", { class: "msg user" }, h("div", { class: "bubble" }, h("div", { class: "user-text" }, m.text)),
      m.queued ? h("div", { class: "meta solo-queued" }, icon("clock"), " Čeká na PC") : null);
    const md = h("div", { class: "md", html: renderMarkdown(m.text) });
    const prev = hist[i - 1];
    return h("div", { class: "msg assistant" }, h("div", { class: "solo-mini", "aria-hidden": "true" }, h("i"), h("i")),
      h("div", { class: "a-main" }, md,
        prev?.role === "user" && !prev.queued ? h("div", { class: "solo-acts" },
          h("button", { class: "chip", type: "button", onclick: () => { queueForPc(prev.text); prev.queued = true; save(HIST, hist); paint(); toast("Uloženo – PC to udělá, až se zapne", "ok"); } },
            icon("desktop-tower"), "Poslat PC")) : null));
  }
  function paint(thinking = false) {
    if (!hist.length && !thinking) {
      const tip = (t: string) => h("button", { class: "suggest", type: "button", onclick: () => { input.value = t; submit(); } }, h("span", {}, t), icon("arrow-up-right", "suggest-go"));
      list.replaceChildren(h("div", { class: "chat-empty solo-empty" },
        h("div", { class: "solo-eyes big", "aria-hidden": "true" }, h("i"), h("i")),
        h("h2", {}, "Jsem tu i bez PC"), h("p", { class: "chat-sub" }, `Odpovídá ${AI[provider].name} zdarma přímo z telefonu.`),
        h("div", { class: "chat-suggest" }, tip("Vymysli mi rychlou večeři"), tip("Vysvětli mi jednoduše, jak funguje AI"), tip("Napiš omluvnou SMS, že přijdu pozdě"))));
    } else list.replaceChildren(...hist.map(msgEl), ...(thinking ? [h("div", { class: "msg assistant live" }, h("div", { class: "solo-mini", "aria-hidden": "true" }, h("i"), h("i")),
      h("div", { class: "a-main" }, h("div", { class: "md" }, h("span", { class: "think" }, "Přemýšlím…"))))] : []));
    scroll.scrollTop = scroll.scrollHeight;
  }
  async function submit() {
    const text = input.value.trim();
    if (!text || busy) return;
    const key = await getKey(provider);
    if (!key) { setup(); return; }
    busy = true; send.disabled = true;
    input.value = ""; input.style.height = "";
    hist.push({ role: "user", text, at: Date.now() / 1000 });
    save(HIST, hist.slice(-MAX_HIST));
    paint(true);
    native.haptic();
    try {
      const name = load<{ name?: string }>(CFG, {}).name || "";
      const ctx = hist.slice(-16).map((m) => ({ role: m.role, content: m.text }));
      const msgs = [{ role: "system", content: system(name) }, ...ctx];
      let answer = "";
      try {
        answer = await ask(provider, key, msgs);
      } catch (e: any) {
        if (!e?.limit && e?.net) throw e;                 // no internet at all: another AI will not help
        // this AI's limit is used up (or it failed): the next one with a saved key answers instead
        let done = false;
        for (const p of ORDER.filter((x) => x !== provider)) {
          const k2 = await getKey(p);
          if (!k2) continue;
          try { answer = await ask(p, k2, msgs); toast(`${AI[provider].name} nejde – odpověděl ${AI[p].name}`, "info", 3000); done = true; break; }
          catch { /* the next one */ }
        }
        if (!done) throw e;
      }
      hist.push({ role: "assistant", text: answer, at: Date.now() / 1000 });
      hist = hist.slice(-MAX_HIST);
      save(HIST, hist);
    } catch (e: any) {
      toast(e.message || "Nepovedlo se", "error", 6000);
      hist.pop(); save(HIST, hist);
      input.value = text;
    } finally {
      busy = false; send.disabled = false;
      paint();
    }
  }

  // ---- choosing the AI and its key ----
  function setup() {
    const sheet = h("div", { class: "solo-sheet", role: "dialog", "aria-label": "Nastavit AI bez PC" });
    const close = () => { sheet.remove(); };
    let pick: Pid = provider;
    const status = h("div", { class: "solo-status" });
    const key = h("input", { class: "input", type: "password", autocomplete: "off", spellcheck: "false", "aria-label": "API klíč" }) as HTMLInputElement;
    const choose = h("div", { class: "solo-choose" });
    const link = h("a", { class: "btn", target: "_blank", rel: "noopener noreferrer" }, icon("arrow-square-out"), h("span"));
    const paintChoose = async () => {
      const saved = await Promise.all(ORDER.map(async (p) => !!(await getKey(p))));
      choose.replaceChildren(...ORDER.map((p, i) => h("button", { type: "button", class: `solo-opt ${pick === p ? "on" : ""}`,
        onclick: () => { pick = p; paintChoose(); } }, icon(AI[p].ico, "ph-fill"), h("strong", {}, AI[p].name, saved[i] ? " ✓" : ""), h("span", {}, AI[p].hint))));
      link.href = AI[pick].url;
      (link.lastChild as HTMLElement).textContent = `Získat klíč (${new URL(AI[pick].url).host})`;
      const has = !!(await getKey(pick));
      key.placeholder = has ? "Klíč je uložený ✓ – nový vložíš sem" : AI[pick].prefix ? `Vlož klíč (${AI[pick].prefix}…)` : "Vlož klíč";
    };
    const go = async () => {
      const raw = key.value.replace(/[\s"'“”„]/g, "");
      const k = raw || (await getKey(pick));
      if (!k) { status.className = "solo-status fail"; status.textContent = "Nejdřív vlož klíč."; return; }
      status.className = "solo-status busy"; status.textContent = `Zkouším ${AI[pick].name}…`;
      try {
        await ask(pick, k, [{ role: "user", content: "Odpověz jen slovem: funguju" }]);
        if (raw) await setKey(pick, raw);
        provider = pick;
        save(CFG, { ...load(CFG, {}), provider });
        paintPill(); paint();
        toast(`${AI[pick].name} funguje ✓`, "ok");
        close();
      } catch (e: any) { status.className = "solo-status fail"; status.textContent = e.message; }
    };
    sheet.append(h("div", { class: "solo-card" },
      h("div", { class: "row" }, h("strong", { class: "solo-h" }, "AI v telefonu"), h("button", { class: "icon-btn", type: "button", "aria-label": "Zavřít", onclick: close }, icon("x"))),
      h("p", { class: "solo-p" }, "Když je PC vypnuté, odpovídá tahle AI. Je zdarma – stačí klíč. Ulož klidně víc klíčů: když jedné AI dojde limit, odpoví další. Klíče zůstanou jen v telefonu (v zabezpečeném úložišti Androidu)."),
      choose, link, key,
      h("button", { class: "btn primary", type: "button", onclick: go }, icon("check"), "Uložit a vyzkoušet"), status,
      h("button", { class: "btn ghost", type: "button", onclick: () => { close(); o.pair(); } }, icon("qr-code"), "Spárovat s PC znovu")));
    shell.append(sheet);
    paintChoose();
  }

  async function lookForPc(manual = false) {
    if (manual) toast("Hledám PC…", "info", 1500);
    if (await o.retry()) { window.clearInterval(timer); return; }
    if (manual) toast("PC zatím neodpovídá", "error");
  }
  timer = window.setInterval(() => { if (!shell.isConnected) { window.clearInterval(timer); return; } if (!busy) lookForPc(); }, 20000);
  paintPill();
  paint();
  getKey(provider).then((k) => { if (!k) setup(); });
}
