/* 3.12 "Průvodce" – the first run: your name, which free AI to use, the key pasted and tried right away ("Funguje ✓"),
   and three things worth knowing. Shown once in the window while no AI key is saved; any time later from
   Nastavení → AI mozek → Průvodce nastavením. */
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import "./onboarding.css";

type Brain = { id: "groq" | "gemini"; name: string; tag: string; lines: string[]; url: string; host: string; prefix: string; steps: string[]; base: string; model: string };
const BRAINS: Brain[] = [
  { id: "groq", name: "Groq", tag: "Doporučeno", lines: ["Zdarma, bez platební karty", "Nejrychlejší odpovědi", "Model GPT-OSS 120B"],
    url: "https://console.groq.com/keys", host: "console.groq.com/keys", prefix: "gsk_",
    steps: ["Přihlas se (stačí Google účet)", "Klikni na „Create API Key“, napiš libovolný název", "Zkopíruj klíč (začíná gsk_) – ukáže se jen jednou"],
    base: "https://api.groq.com/openai/v1", model: "openai/gpt-oss-120b" },
  { id: "gemini", name: "Google Gemini", tag: "Umí i obrázky", lines: ["Zdarma s Google účtem", "Rozumí fotkám a screenshotům", "Model Gemini 2.5 Flash"],
    url: "https://aistudio.google.com/apikey", host: "aistudio.google.com/apikey", prefix: "AIza",
    steps: ["Přihlas se Google účtem", "Klikni na „Create API key“", "Zkopíruj klíč (začíná AIza)"],
    base: "https://generativelanguage.googleapis.com/v1beta/openai", model: "gemini-2.5-flash" },
];

let settings: any = null;
let openNow: (() => void) | null = null;

/** listen for the welcome; returns `open()` for the button in Settings */
export function onboarding(client: JarvisClient) {
  client.on("welcome", (m) => { settings = m.settings; if (m.onboarding && !document.querySelector(".ob")) show(client, m.settings); });
  client.on("settings", (m) => { if (m.settings) settings = m.settings; });
  client.on("settings_changed", (m) => { if (m.settings) settings = m.settings; });
  openNow = () => { if (!document.querySelector(".ob")) show(client, settings); };
  return openNow;
}
export const openOnboarding = () => openNow?.();

function eyes() {
  return h("div", { class: "ob-eyes", "aria-hidden": "true" }, h("i", {}), h("i", {}));
}

function show(client: JarvisClient, s: any) {
  let step = 0, brain: Brain = BRAINS[0], working = false, off: (() => void) | null = null;
  const name = { value: String(s?.general?.user_name || "") };
  const dots = h("div", { class: "ob-dots" });
  const body = h("div", { class: "ob-body" });
  const back = h("button", { class: "btn ghost", type: "button", onclick: () => go(step - 1) }, icon("caret-left"), "Zpět");
  const next = h("button", { class: "btn primary", type: "button" });
  const skip = h("button", { class: "ob-skip", type: "button", onclick: () => finish() }, "Přeskočit průvodce");
  const card = h("div", { class: "ob-card", role: "dialog", "aria-modal": "true", "aria-label": "Průvodce nastavením" },
    h("div", { class: "ob-top" }, dots, skip), body, h("div", { class: "ob-foot" }, back, next));
  const root = h("div", { class: "ob" }, h("div", { class: "ob-glow", "aria-hidden": "true" }), card);
  document.body.append(root);
  const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") finish(); };
  window.addEventListener("keydown", onKey);

  function finish() {
    client.send("settings_set", { patch: { general: { onboarded: true, ...(name.value.trim() ? { user_name: name.value.trim() } : {}) } } });
    window.removeEventListener("keydown", onKey);
    off?.();
    root.classList.add("out");
    window.setTimeout(() => root.remove(), 260);
  }

  /** make sure the chosen AI is in the list and first in line, then save the key and try it */
  function useKey(raw: string, status: HTMLElement, paint: (st: "idle" | "busy" | "ok" | "fail", text: string) => void) {
    const key = raw.replace(/[\s"'“”„]/g, "");
    if (!key) return;
    const cur = settings?.brain || {};
    const provs: any[] = Array.isArray(cur.providers) ? cur.providers.map((p: any) => ({ ...p })) : [];
    let p = provs.find((x) => x.id === brain.id) || provs.find((x) => x.preset === brain.id);
    if (!p) { p = { id: brain.id, preset: brain.id, base_url: brain.base, model: brain.model, enabled: true }; provs.push(p); }
    p.enabled = true;
    if (!p.model) p.model = brain.model;
    const chain = [p.id, ...((cur.chain as string[]) || []).filter((c) => c !== p.id)];
    client.send("settings_set", { patch: { brain: { providers: provs, chain } } });
    client.send("secret_set", { name: p.id, value: key });
    const warn = !key.startsWith(brain.prefix) ? ` Pozor: klíč ${brain.name} obvykle začíná ${brain.prefix}.` : "";
    paint("busy", `Klíč uložen – zkouším, jestli ${brain.name} odpovídá…${warn}`);
    working = false;
    client.send("provider_test", { id: p.id });
    status.dataset.id = p.id;
  }

  function go(n: number) {
    step = Math.max(0, Math.min(3, n));
    dots.replaceChildren(...[0, 1, 2, 3].map((i) => h("i", { class: i === step ? "on" : i < step ? "done" : "" })));
    back.hidden = step === 0 || step === 3;
    skip.hidden = step === 3;
    next.disabled = false;
    let view: HTMLElement;
    if (step === 0) {
      const inp = h("input", { class: "input ob-name", placeholder: "Tvoje jméno", value: name.value, autocomplete: "off", "aria-label": "Jak ti mám říkat" }) as HTMLInputElement;
      inp.oninput = () => (name.value = inp.value);
      inp.onkeydown = (e) => { if (e.key === "Enter") go(1); };
      view = h("div", { class: "ob-hero" }, eyes(),
        h("h1", {}, "Ahoj, já jsem JARVIS"),
        h("p", { class: "ob-lead" }, "Za minutu mě nastavíme: vybereš si, která AI bude mým mozkem, a hned vyzkoušíme, že funguje. Všechno je zdarma."),
        h("label", { class: "ob-field" }, h("span", {}, "Jak ti mám říkat?"), inp));
      next.replaceChildren(h("span", {}, "Pojďme na to"), icon("arrow-right"));
      next.onclick = () => go(1);
      // only in a window that already has focus: a focus() from a background WebView2 asks Windows to activate it
      window.setTimeout(() => { if (document.hasFocus()) inp.focus({ preventScroll: true }); }, 60);
    } else if (step === 1) {
      const pick = (b: Brain) => h("button", { type: "button", class: `ob-brain ${brain.id === b.id ? "on" : ""}`, "data-id": b.id,
        onclick: () => { brain = b; go(1); } },
        h("div", { class: "ob-brain-head" }, h("span", { class: "ob-logo" }, icon(b.id === "groq" ? "lightning" : "sparkle", "ph-fill")),
          h("strong", {}, b.name), h("em", {}, b.tag)),
        h("ul", {}, ...b.lines.map((l) => h("li", {}, icon("check"), l))),
        h("span", { class: "ob-radio" }));
      view = h("div", {},
        h("h2", {}, "Vyber mi mozek"),
        h("p", { class: "ob-lead" }, "Obě možnosti jsou zdarma a běží, i když je počítač slabý. Později můžeš přidat další v Nastavení → AI mozek."),
        h("div", { class: "ob-brains" }, ...BRAINS.map(pick)),
        h("button", { type: "button", class: "ob-link", onclick: () => go(3) }, "Už mám AI nastavenou (OmniRoute, Ollama…) – přeskočit"));
      next.replaceChildren(h("span", {}, `Pokračovat s ${brain.name}`), icon("arrow-right"));
      next.onclick = () => go(2);
    } else if (step === 2) {
      const status = h("div", { class: "ob-status", role: "status", "aria-live": "polite" });
      const paint = (st: "idle" | "busy" | "ok" | "fail", text: string) => {
        status.className = `ob-status ${st}`;
        status.replaceChildren(icon(st === "ok" ? "check-circle" : st === "fail" ? "warning-circle" : st === "busy" ? "circle-notch" : "info", "ph-fill"), h("span", {}, text));
        working = st === "ok";
        next.replaceChildren(h("span", {}, working ? "Hotovo, dál" : "Pokračovat bez testu"), icon("arrow-right"));
        next.classList.toggle("primary", working || st === "idle");
      };
      const key = h("input", { class: "input ob-key", type: "password", placeholder: `Vlož klíč (${brain.prefix}…)`, autocomplete: "off", spellcheck: "false", "aria-label": `API klíč ${brain.name}` }) as HTMLInputElement;
      let last = "";
      const save = () => { const v = key.value.trim(); if (!v || v === last) return; last = v; useKey(v, status, paint); key.value = ""; key.placeholder = "Uloženo ✓ – nový klíč vložíš sem"; };
      key.onpaste = () => window.setTimeout(save, 30);
      key.onkeydown = (e) => { if (e.key === "Enter") save(); };
      key.onchange = save;
      const pasteBtn = h("button", { class: "btn", type: "button", onclick: async () => {
        try { const t = await navigator.clipboard.readText(); if (t) { key.value = t; save(); } else toast("Ve schránce nic není – zkopíruj klíč na stránce", "error"); }
        catch { key.focus(); toast("Vlož klíč zkratkou Ctrl+V", "info"); }
      } }, icon("clipboard-text"), "Vložit ze schránky");
      view = h("div", {},
        h("h2", {}, `Klíč pro ${brain.name}`),
        h("p", { class: "ob-lead" }, "Klíč je jako heslo, díky kterému mě AI pustí dovnitř. Uloží se bezpečně do Windows, nikam jinam."),
        h("ol", { class: "ob-steps" },
          h("li", {}, h("b", {}, "1"), h("div", {}, h("a", { class: "btn ob-open", href: brain.url, target: "_blank", rel: "noopener noreferrer" }, icon("arrow-square-out"), `Otevřít ${brain.host}`))),
          ...brain.steps.map((t, i) => h("li", {}, h("b", {}, String(i + 2)), h("div", {}, t))),
          h("li", {}, h("b", {}, String(brain.steps.length + 2)), h("div", { class: "ob-keyrow" }, key, pasteBtn))),
        status);
      paint("idle", "Až klíč vložíš, hned ho vyzkouším.");
      next.onclick = () => go(3);
      const onResult = (m: any) => {
        if (!root.isConnected || step !== 2 || m.id !== status.dataset.id) return;
        if (m.ok) {
          paint("ok", `Funguje ✓ ${brain.name} odpověděl za ${m.ms} ms${m.model ? ` (model ${m.model})` : ""}.`);
          card.animate([{ transform: "scale(1)" }, { transform: "scale(1.012)" }, { transform: "scale(1)" }], { duration: 420, easing: "cubic-bezier(.3,1.6,.5,1)" });
        } else {
          const msg = String(m.message || "Nepovedlo se.").replace(/^[\w-]+:\s*/, "");
          paint("fail", /zkopíruj|klíč/i.test(msg) ? msg : `${msg} Zkus klíč zkopírovat znovu a vložit.`);
        }
      };
      off?.();
      off = client.on("provider_test_result", onResult);
    } else {
      const who = name.value.trim();
      const tip = (ic: string, t: string, d: string) => h("div", { class: "ob-tip" }, h("span", {}, icon(ic, "ph-fill")), h("div", {}, h("strong", {}, t), h("p", {}, d)));
      view = h("div", { class: "ob-hero" }, eyes(),
        h("h1", {}, who ? `Jsme připraveni, ${who}` : "Jsme připraveni"),
        h("p", { class: "ob-lead" }, "Tři věci, které se hodí hned:"),
        h("div", { class: "ob-tips" },
          tip("chat-circle-dots", "Napiš nebo řekni, co chceš", "„Jaké bude zítra počasí?“, „Ukliď mi plochu“, „Pusť hudbu“."),
          tip("microphone", "Diktování kdekoli", "Drž pravý Ctrl, mluv a pusť – text se napíše tam, kde máš kurzor."),
          tip("cursor-click", "Notch nahoře", "Klikni na něj pro hodiny, hudbu a soustředění. Schováš ho Ctrl+Alt+N.")));
      next.replaceChildren(h("span", {}, "Začít"), icon("rocket-launch"));
      next.onclick = () => finish();
    }
    view.classList.add("ob-step");
    body.replaceChildren(view);
    view.animate([{ opacity: 0, transform: "translateX(14px)" }, { opacity: 1, transform: "none" }], { duration: 320, easing: "cubic-bezier(.2,.9,.25,1)" });
  }
  go(0);
}
