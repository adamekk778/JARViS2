// Which AI is answering right now: its logo (Simple Icons, CC0) and colour, from the provider and the model name.
// Used by the notch while JARVIS works and by the home cards. A logo only names the service in use.
import {
  siApplemusic, siCrunchyroll, siDeezer, siHbomax, siKick, siNetflix, siPlex, siSoundcloud, siSpotify, siSteam, siTidal, siTwitch,
  siVimeo, siVlcmediaplayer, siYoutube, siYoutubemusic,
  siClaude, siDeepseek, siGooglegemini, siKimi, siLmstudio, siMeta, siMistralai, siNvidia, siOllama, siOpenrouter,
  siPerplexity, siQwen, siX,
} from "simple-icons";

export interface Brand { id: string; name: string; color: string; svg: string }

const path = (d: string) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="${d}"/></svg>`;
const si = (id: string, name: string, icon: { path: string; hex: string }, color?: string): Brand =>
  ({ id, name, color: color || `#${icon.hex}`, svg: path(icon.path) });

// marks without a Simple Icons glyph, drawn here
// the OpenAI mark (from Simple Icons 10.4, CC0 – later versions dropped it); it names the service, nothing more
const CHATGPT = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z"/></svg>`;
// Gemini as it really looks: its spark in the blue → violet → rose gradient
const gemini = (d: string) => `<svg viewBox="0 0 24 24" aria-hidden="true"><defs><linearGradient id="jv-gem" x1="0" y1="1" x2="1" y2="0">`
  + `<stop offset="0" stop-color="#1c7dff"/><stop offset=".52" stop-color="#9177c7"/><stop offset="1" stop-color="#e86b7c"/></linearGradient></defs>`
  + `<path fill="url(#jv-gem)" d="${d}"/></svg>`;
const GROQ = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor"/>`
  + `<text x="12" y="16.4" text-anchor="middle" font-family="system-ui,Segoe UI,sans-serif" font-weight="800" font-size="13" fill="#000">g</text></svg>`;
const ROUTER = `<svg viewBox="0 0 24 24" aria-hidden="true"><g fill="currentColor"><circle cx="5" cy="12" r="2.6"/><circle cx="19" cy="5" r="2.6"/>`
  + `<circle cx="19" cy="19" r="2.6"/></g><path d="M7.4 11 16.8 6M7.4 13l9.4 5" stroke="currentColor" stroke-width="1.8" fill="none"/></svg>`;

export const BRANDS: Record<string, Brand> = {
  claude: si("claude", "Claude", siClaude),
  chatgpt: { id: "chatgpt", name: "ChatGPT", color: "#f2f5f8", svg: CHATGPT },
  gemini: { id: "gemini", name: "Gemini", color: "#8ab4ff", svg: gemini(siGooglegemini.path) },
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

// 3.12: what is playing / being watched – the service's logo at the left of the notch (subtitles, lyrics)
const GLYPH = (ph: string) => `<i class="ph-fill ph-${ph}" aria-hidden="true"></i>`;
export const MEDIA: Record<string, Brand> = {
  youtube: si("youtube", "YouTube", siYoutube),
  youtubemusic: si("youtubemusic", "YouTube Music", siYoutubemusic),
  spotify: si("spotify", "Spotify", siSpotify),
  netflix: si("netflix", "Netflix", siNetflix),
  twitch: si("twitch", "Twitch", siTwitch, "#a970ff"),
  applemusic: si("applemusic", "Apple Music", siApplemusic),
  deezer: si("deezer", "Deezer", siDeezer),
  tidal: si("tidal", "TIDAL", siTidal, "#ffffff"),
  soundcloud: si("soundcloud", "SoundCloud", siSoundcloud),
  vlc: si("vlc", "VLC", siVlcmediaplayer),
  hbomax: si("hbomax", "Max", siHbomax, "#ffffff"),
  crunchyroll: si("crunchyroll", "Crunchyroll", siCrunchyroll),
  vimeo: si("vimeo", "Vimeo", siVimeo),
  kick: si("kick", "Kick", siKick),
  plex: si("plex", "Plex", siPlex),
  steam: si("steam", "Steam", siSteam, "#c7d5e0"),
  browser: { id: "browser", name: "Prohlížeč", color: "#c7cad0", svg: GLYPH("globe") },
  game: { id: "game", name: "Hra", color: "#c7cad0", svg: GLYPH("game-controller") },
};
export const mediaBrand = (src = ""): Brand | null => MEDIA[src] || null;
