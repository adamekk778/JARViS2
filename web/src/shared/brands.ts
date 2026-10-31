// Which AI is answering right now: its logo (Simple Icons, CC0) and colour, from the provider and the model name.
// Used by the notch while JARVIS works and by the home cards. A logo only names the service in use.
import {
  siClaude, siDeepseek, siGooglegemini, siKimi, siLmstudio, siMeta, siMistralai, siNvidia, siOllama, siOpenrouter,
  siPerplexity, siQwen, siX,
} from "simple-icons";

export interface Brand { id: string; name: string; color: string; svg: string }

const path = (d: string) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="${d}"/></svg>`;
const si = (id: string, name: string, icon: { path: string; hex: string }, color?: string): Brand =>
  ({ id, name, color: color || `#${icon.hex}`, svg: path(icon.path) });

// marks without a Simple Icons glyph, drawn here
const PETALS = Array.from({ length: 6 }, (_, i) =>
  `<rect x="9.2" y="2.2" width="5.6" height="11" rx="2.8" transform="rotate(${i * 60} 12 12)"/>`).join("");
const CHATGPT = `<svg viewBox="0 0 24 24" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.6">${PETALS}</g></svg>`;
const GROQ = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor"/>`
  + `<text x="12" y="16.4" text-anchor="middle" font-family="system-ui,Segoe UI,sans-serif" font-weight="800" font-size="13" fill="#000">g</text></svg>`;
const ROUTER = `<svg viewBox="0 0 24 24" aria-hidden="true"><g fill="currentColor"><circle cx="5" cy="12" r="2.6"/><circle cx="19" cy="5" r="2.6"/>`
  + `<circle cx="19" cy="19" r="2.6"/></g><path d="M7.4 11 16.8 6M7.4 13l9.4 5" stroke="currentColor" stroke-width="1.8" fill="none"/></svg>`;

export const BRANDS: Record<string, Brand> = {
  claude: si("claude", "Claude", siClaude),
  chatgpt: { id: "chatgpt", name: "ChatGPT", color: "#f2f5f8", svg: CHATGPT },
  gemini: si("gemini", "Gemini", siGooglegemini, "#8ab4ff"),
  llama: si("llama", "Llama", siMeta, "#4a9bff"),
  mistral: si("mistral", "Mistral", siMistralai),
  deepseek: si("deepseek", "DeepSeek", siDeepseek),
  qwen: si("qwen", "Qwen", siQwen, "#8f7bff"),
  grok: si("grok", "Grok", siX, "#f2f5f8"),
  kimi: si("kimi", "Kimi", siKimi, "#f2f5f8"),
  perplexity: si("perplexity", "Perplexity", siPerplexity),
  nvidia: si("nvidia", "Nemotron", siNvidia),
  ollama: si("ollama", "Ollama", siOllama, "#f2f5f8"),
  lmstudio: si("lmstudio", "LM Studio", siLmstudio, "#a99bff"),
  openrouter: si("openrouter", "OpenRouter", siOpenrouter, "#c7d2e0"),
  groq: { id: "groq", name: "Groq", color: "#f55036", svg: GROQ },
  router: { id: "router", name: "OmniRoute", color: "#4fd1ff", svg: ROUTER },
};

const BY_MODEL: [RegExp, string][] = [
  [/claude|anthropic|sonnet|opus|haiku|fable/, "claude"],
  [/gpt|chatgpt|openai|\bo[134](-|$)|davinci/, "chatgpt"],
  [/gemini|gemma|bard/, "gemini"],
  [/llama|meta-/, "llama"],
  [/mistral|mixtral|codestral|magistral|ministral|devstral/, "mistral"],
  [/deepseek/, "deepseek"],
  [/qwen|qwq/, "qwen"],
  [/grok|xai/, "grok"],
  [/kimi|moonshot/, "kimi"],
  [/sonar|perplexity/, "perplexity"],
  [/nemotron|nvidia/, "nvidia"],
];
const BY_PROVIDER: [RegExp, string][] = [
  [/anthropic|claude/, "claude"], [/openai/, "chatgpt"], [/gemini|google/, "gemini"], [/ollama/, "ollama"],
  [/lmstudio|lm-studio/, "lmstudio"], [/openrouter/, "openrouter"], [/groq/, "groq"], [/mistral/, "mistral"],
  [/deepseek/, "deepseek"], [/perplexity/, "perplexity"],
];

/** The model name decides first (OmniRoute or OpenRouter can serve Claude, Gemini, …); then the provider. */
export function brandOf(provider = "", model = ""): Brand {
  const m = model.toLowerCase(), p = provider.toLowerCase();
  for (const [re, id] of BY_MODEL) if (re.test(m)) return BRANDS[id];
  for (const [re, id] of BY_PROVIDER) if (re.test(p)) return BRANDS[id];
  return { ...BRANDS.router, name: provider ? provider.charAt(0).toUpperCase() + provider.slice(1) : "AI" };
}

/** The logo as an element (sized by CSS font-size, coloured with the brand colour). */
export function brandEl(b: Brand, cls = "brand-logo"): HTMLElement {
  const el = document.createElement("span");
  el.className = cls;
  el.style.color = b.color;
  el.title = b.name;
  el.innerHTML = b.svg;
  return el;
}
