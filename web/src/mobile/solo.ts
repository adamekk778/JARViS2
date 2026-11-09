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

type Pid = "groq" | "gemini";
const AI: Record<Pid, { name: string; base: string; model: string; url: string; prefix: string; hint: string }> = {
  groq: { name: "Groq", base: "https://api.groq.com/openai/v1", model: "openai/gpt-oss-120b", url: "https://console.groq.com/keys",
    prefix: "gsk_", hint: "Nejrychlejší. Klíč začíná gsk_." },
  gemini: { name: "Gemini", base: "https://generativelanguage.googleapis.com/v1beta/openai", model: "gemini-2.5-flash", url: "https://aistudio.google.com/apikey",
    prefix: "AIza", hint: "Od Googlu. Klíč začíná AIza." },
};
const CFG = "jarvis.solo", HIST = "jarvis.solo.history", MAX_HIST = 60;
type Msg = { role: "user" | "assistant"; text: string; at: number; queued?: boolean };

const memKeys: Partial<Record<Pid, string>> = {};      // a normal browser: only while the page is open
const load = <T>(k: string, d: T): T => { try { return JSON.parse(localStorage.getItem(k) || "") ?? d; } catch { return d; } };
const save = (k: string, v: unknown) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* full */ } };

export const soloProvider = (): Pid | null => load<{ provider?: Pid }>(CFG, {}).provider || null;

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

/** one answer from the AI (no streaming: the native request avoids the browser's CORS limits) */
async function ask(p: Pid, key: string, messages: { role: string; content: string }[]): Promise<string> {
  const a = AI[p];
  const url = `${a.base}/chat/completions`;
  const body = { model: a.model, messages, temperature: 0.6, max_tokens: 1200 };
  const headers = { Authorization: `Bearer ${key}`, "Content-Type": "application/json" };
  let status = 0, data: any = null;
  try {
    if (Capacitor.isNativePlatform()) {
      const r = await CapacitorHttp.request({ url, method: "POST", headers, data: body, connectTimeout: 15000, readTimeout: 60000 });
      status = r.status; data = typeof r.data === "string" ? JSON.parse(r.data || "{}") : r.data;
    } else {
      const r = await fetch(url, { method: "POST", headers, body: JSON.stringify(body) });
      status = r.status; data = await r.json().catch(() => ({}));
    }
  } catch {
    throw new Error("Nejde se spojit s internetem. Zkontroluj data nebo Wi-Fi.");
  }
  if (status === 401 || status === 403) throw new Error(`${a.name} klíč odmítl – zkopíruj ho znovu celý (začíná ${a.prefix}).`);
  if (status === 429) throw new Error(`${a.name}: vyčerpaný bezplatný limit – zkus to za chvíli.`);
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
export function soloScreen(app: HTMLElement, o: { retry: () => Promise<boolean>; pair: () => void; reason?: string }) {
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

  function paintPill() { pill.replaceChildren(icon(provider === "groq" ? "lightning" : "sparkle", "ph-fill"), h("span", {}, AI[provider].name), icon("caret-down")); }
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
      const answer = await ask(provider, key, [{ role: "system", content: system(name) }, ...ctx]);
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
      choose.replaceChildren(...(Object.keys(AI) as Pid[]).map((p) => h("button", { type: "button", class: `solo-opt ${pick === p ? "on" : ""}`,
        onclick: () => { pick = p; paintChoose(); } }, icon(p === "groq" ? "lightning" : "sparkle", "ph-fill"), h("strong", {}, AI[p].name), h("span", {}, AI[p].hint))));
      link.href = AI[pick].url;
      (link.lastChild as HTMLElement).textContent = `Získat klíč (${new URL(AI[pick].url).host})`;
      const has = !!(await getKey(pick));
      key.placeholder = has ? "Klíč je uložený ✓ – nový vložíš sem" : `Vlož klíč (${AI[pick].prefix}…)`;
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
      h("p", { class: "solo-p" }, "Když je PC vypnuté, odpovídá tahle AI. Je zdarma – stačí klíč. Uloží se jen v telefonu (v zabezpečeném úložišti Androidu)."),
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
