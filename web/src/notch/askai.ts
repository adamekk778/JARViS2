/* 3.12 "Zeptej se …": the logos of your AIs (Claude, ChatGPT, Gemini, Groq…) on the JARVIS card; a click opens a small
   box for that one AI – write, add a photo with the clip, Enter sends. The answer comes in Chat, from that AI only. */
import { brandEl, brandOf } from "../shared/brands";
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import "./askai.css";

type Prov = { id: string; preset?: string; model?: string; enabled?: boolean };

/** the AIs you can ask: enabled providers, one chip per brand (the first in your chain wins) */
export function askTargets(settings: any): { p: Prov; brand: ReturnType<typeof brandOf> }[] {
  const provs: Prov[] = settings?.brain?.providers || [];
  const chain: string[] = settings?.brain?.chain || [];
  const ordered = [...chain.map((id) => provs.find((p) => p.id === id)).filter(Boolean) as Prov[], ...provs.filter((p) => !chain.includes(p.id))];
  const out: { p: Prov; brand: ReturnType<typeof brandOf> }[] = [];
  for (const p of ordered) {
    if (p.enabled === false) continue;
    // the service you picked (Groq, Ollama…) shows its own logo, not the maker of the model it runs (GPT-OSS → OpenAI)
    const own = brandOf(p.preset || p.id, "");
    const brand = !["router", "openrouter"].includes(own.id) ? own : brandOf(p.preset || p.id, p.model || "");   // gateways: the model decides
    if (brand.id === "router" && (p.model || "auto").startsWith("auto")) continue;   // a gateway choosing for you is not one AI
    out.push({ p, brand });
  }
  // the well-known ones first (as on an island bar: Claude, ChatGPT, Gemini), then the rest in your order
  const rank = (id: string) => { const i = ["claude", "chatgpt", "gemini", "groq"].indexOf(id); return i < 0 ? 9 : i; };
  return out.map((t, i) => ({ t, i })).sort((a, b) => rank(a.t.brand.id) - rank(b.t.brand.id) || a.i - b.i).map((x) => x.t)
    .filter((t, i, all) => all.findIndex((o) => o.brand.id === t.brand.id) === i).slice(0, 3);   // one per logo, three fit the bar
}

/** where the AI runs, when that is not obvious from its logo ("Groq" for GPT-OSS, "Ollama" for Llama) */
const host = (t: { p: Prov; brand: { name: string } }) => {
  const pr = (t.p.preset || t.p.id).toLowerCase();
  const names: Record<string, string> = { openai: "OpenAI", anthropic: "Anthropic", gemini: "Google", groq: "Groq", openrouter: "OpenRouter",
    ollama: "Ollama (v PC)", lmstudio: "LM Studio (v PC)", omniroute: "OmniRoute", custom: "vlastní" };
  return names[pr] || t.p.id;
};
const label = (t: { p: Prov; brand: { name: string } }) => {
  const hn = host(t);
  return hn.toLowerCase().startsWith(t.brand.name.toLowerCase().slice(0, 4)) || ["OpenAI", "Anthropic", "Google"].includes(hn) ? t.brand.name : `${t.brand.name} · ${hn}`;
};

export function createAskAi(getHost: () => HTMLElement, client: JarvisClient, toChat: () => void) {
  let target: { p: Prov; brand: ReturnType<typeof brandOf> } | null = null;
  let atts: { id: string; url: string }[] = [];
  let busy = false;
  const logo = h("span", { class: "aa-logo" }), title = h("strong", {}), model = h("span", { class: "aa-model" });
  // 3.14 the AI that answers now: its model switches right here (Ollama: the models on this PC; Claude: Opus, Sonnet…)
  const modelSel = h("select", { class: "aa-model-sel", "aria-label": "Model", hidden: true }) as HTMLSelectElement;
  let activeId = "";
  modelSel.onchange = () => {
    if (!target || !modelSel.value) return;
    client.send("brain_use", { key: target.p.id, model: modelSel.value });
    model.textContent = `${host(target)} · ${modelSel.value}`;
    toast(`Model: ${modelSel.value}`, "ok", 1600);
  };
  client.on("brain_models", (m: any) => {
    if (!target || (m.key !== target.p.id && m.id !== target.p.id)) return;
    const list: { id: string; label: string; note: string }[] = Array.isArray(m.models) ? m.models : [];
    if (list.length < 2) { modelSel.hidden = true; model.hidden = false; return; }
    const now = target.p.model || String(m.current || "");
    modelSel.replaceChildren(...list.map((x) => h("option", { value: x.id, selected: x.id === now }, x.note ? `${x.label} – ${x.note}` : x.label)));
    modelSel.hidden = false;
    model.hidden = true;
  });
  const input = h("textarea", { class: "aa-input", rows: 3, placeholder: "Na co se chceš zeptat?", "aria-label": "Dotaz" }) as HTMLTextAreaElement;
  const thumbs = h("div", { class: "aa-thumbs" });
  const file = h("input", { type: "file", accept: "image/*", multiple: true, hidden: true }) as HTMLInputElement;
  const send = h("button", { class: "aa-send", type: "button", "aria-label": "Odeslat", onclick: () => submit() }, icon("arrow-up", "ph-bold"));
  const clip = h("button", { class: "aa-clip", type: "button", title: "Přidat fotku", "aria-label": "Přidat fotku", onclick: () => file.click() }, icon("paperclip"));
  const sheet = h("div", { class: "lk-sheet aa-sheet", role: "dialog", "aria-label": "Zeptat se AI", hidden: true },
    h("div", { class: "aa-head" },
      h("button", { class: "aa-back", type: "button", "aria-label": "Zpět", onclick: () => open(null) }, icon("caret-left")),
      logo, h("div", { class: "aa-titles" }, title, model, modelSel)),
    h("div", { class: "aa-box" }, input, thumbs, h("div", { class: "aa-tools" }, clip, send)),
    h("p", { class: "aa-hint" }, "Enter odešle · Shift+Enter nový řádek · sponka: přidat fotku"), file);

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
    if (e.key === "Escape") open(null);
  });
  input.addEventListener("paste", (e) => { const fs = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/")); if (fs.length) { e.preventDefault(); fs.forEach(add); } });
  file.onchange = () => { [...(file.files || [])].forEach(add); file.value = ""; };

  async function add(f: File) {
    const url = URL.createObjectURL(f);
    const th = h("div", { class: "aa-thumb up" }, h("img", { src: url, alt: "" }));
    thumbs.append(th);
    try {
      const a = await client.upload(f, f.name || "fotka.png");
      atts.push({ id: a.id, url });
      th.classList.remove("up");
      th.append(h("button", { type: "button", class: "aa-x", "aria-label": "Odebrat fotku", onclick: () => { atts = atts.filter((x) => x.id !== a.id); th.remove(); } }, icon("x")));
    } catch (e: any) { th.remove(); toast(e?.message || "Fotku se nepodařilo nahrát", "error"); }
  }
  function submit() {
    const text = input.value.trim();
    if (!target || busy || (!text && !atts.length)) return;
    if (thumbs.querySelector(".up")) { toast("Chvilku – fotka se ještě nahrává", "info", 1800); return; }
    busy = true;
    client.send("user_text", { text, attachments: atts.map((a) => a.id), ai: target.p.id });
    input.value = ""; atts = []; thumbs.replaceChildren();
    busy = false;
    open(null);
    toChat();
  }
  function open(t: { p: Prov; brand: ReturnType<typeof brandOf> } | null) {
    target = t;
    if (t && !sheet.isConnected) getHost().append(sheet);    // made here: the panel is in the page by now
    sheet.hidden = !t;
    if (!t) return;
    logo.replaceChildren(brandEl(t.brand));
    logo.dataset.brand = t.brand.id;
    sheet.style.setProperty("--tint", t.brand.color);
    title.textContent = `Zeptej se ${t.brand.name}`;
    model.textContent = `${host(t)} · ${t.p.model || "výchozí model"}`;
    model.hidden = false;
    modelSel.hidden = true;
    if (t.p.id === activeId) client.send("brain_models_get", { key: t.p.id });   // only the one answering now switches here
    sheet.animate([{ opacity: 0, transform: "translateY(10px) scale(.98)" }, { opacity: 1, transform: "none" }], { duration: 260, easing: "cubic-bezier(.2,.9,.25,1)" });
    window.setTimeout(() => input.focus(), 30);
  }

  /** the row of logos for the JARVIS card */
  const chips = h("div", { class: "aa-chips", role: "group", "aria-label": "Zeptat se konkrétní AI" });
  function paintChips(settings: any) {
    const ts = askTargets(settings);
    const chain: string[] = settings?.brain?.chain || [];
    const provs: Prov[] = settings?.brain?.providers || [];
    const active = chain.find((id) => provs.some((p) => p.id === id && p.enabled !== false)) || "";
    activeId = active;
    chips.hidden = !ts.length;
    chips.replaceChildren(...ts.map((t) => {
      const on = t.p.id === active;
      // 3.13 a click: from now on this AI answers (the others stay as backup); right-click: ask it just once (with a photo)
      const b = h("button", { type: "button", class: `aa-chip ${on ? "on" : ""}`, "aria-pressed": on ? "true" : "false",
        title: on ? `Teď odpovídá ${label(t)} · klikni: přepnout model` : `Odpovídat bude ${label(t)} · pravým: zeptat se jednou`,
        "aria-label": `Odpovídat bude ${label(t)}`,
        onclick: (e: Event) => { e.stopPropagation(); if (!on) { client.send("brain_pick", { id: t.p.id }); toast(`Teď odpovídá ${label(t)} · klikni znovu a vybereš model`, "ok", 2400); } else open(t); },
        oncontextmenu: (e: Event) => { e.preventDefault(); e.stopPropagation(); open(t); } }, brandEl(t.brand));
      b.style.setProperty("--c", t.brand.color);
      b.dataset.brand = t.brand.id;                   // app-icon colours per brand (askai.css)       // custom properties do not go through h()'s style object
      return b;
    }));
  }
  return { chips, paintChips, close: () => open(null) };
}
