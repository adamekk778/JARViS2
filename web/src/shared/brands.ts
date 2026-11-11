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
// the Groq mark (from @lobehub/icons-static-svg, MIT)
const GROQ = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd" d="M12.036 2c-3.853-.035-7 3-7.036 6.781-.035 3.782 3.055 6.872 6.908 6.907h2.42v-2.566h-2.292c-2.407.028-4.38-1.866-4.408-4.23-.029-2.362 1.901-4.298 4.308-4.326h.1c2.407 0 4.358 1.915 4.365 4.278v6.305c0 2.342-1.944 4.25-4.323 4.279a4.375 4.375 0 01-3.033-1.252l-1.851 1.818A7 7 0 0012.029 22h.092c3.803-.056 6.858-3.083 6.879-6.816v-6.5C18.907 4.963 15.817 2 12.036 2z"/></svg>`;
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
// Amazon Music (Simple Icons 10.4, CC0 – later versions dropped it)
const AMAZONMUSIC = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M14.8454 9.4083c-1.3907 1.0194-3.405 1.563-5.1424 1.563a9.333 9.333 0 0 1-6.2768-2.3835c-.1313-.117-.0143-.277.1415-.1846a12.693 12.693 0 0 0 6.285 1.6574c1.5384 0 3.2348-.318 4.7917-.9764.2359-.0985.4328.1538.203.324h-.002zm.5784-.6564c-.1784-.2257-1.1753-.1087-1.6225-.0554-.1374.0164-.158-.1026-.0349-.1867.796-.5558 2.0984-.3958 2.2502-.2092.1539.1867-.041 1.4872-.7856 2.1087-.1149.0964-.2236.0451-.1723-.082.1682-.4165.5436-1.3498.3651-1.5754zm-1.5917-4.1702v-.5394c0-.082.0615-.1375.1374-.1375h2.4348c.078 0 .1395.0554.1395.1354v.4636c0 .078-.0656.1805-.1846.3405L15.0997 6.635c.4677-.0102.9641.0595 1.3887.2974.0964.0534.123.1334.1292.2113v.5744c0 .082-.0882.1723-.1784.123a2.8163 2.8163 0 0 0-2.5723.0062c-.0861.0451-.1743-.0451-.1743-.1251v-.5477c0-.0882.002-.238.0902-.3713l1.4626-2.0881h-1.2718c-.078 0-.1415-.0534-.1436-.1354l.002.002zm4.808-.7466c1.0995 0 1.6944.9395 1.6944 2.1333 0 1.1528-.6564 2.0676-1.6943 2.0676-1.079 0-1.6656-.9395-1.6656-2.1087 0-1.1774.5948-2.0922 1.6656-2.0922zm.0062.7713c-.5456 0-.5805.7384-.5805 1.202 0 .4615-.0061 1.4481.5744 1.4481.5743 0 .601-.7958.601-1.282 0-.318-.0144-.6994-.1108-1.001-.082-.2625-.2482-.3671-.4841-.3671zm-6.008 3.3414c-.0493.041-.1395.0451-.1744.0164-.2543-.1949-.4246-.4923-.4246-.4923-.4061.4123-.6954.5374-1.2225.5374-.6215 0-1.1077-.3835-1.1077-1.1486a1.2512 1.2512 0 0 1 .7897-1.2041c.402-.1764.9641-.2072 1.3928-.2564 0 0 .0349-.4615-.0902-.6297a.521.521 0 0 0-.4164-.1908c-.2728 0-.5395.1477-.5928.4328-.0144.082-.0739.1518-.1395.1436L9.945 5.08a.1292.1292 0 0 1-.1108-.1537c.1641-.8657.9498-1.1282 1.6554-1.1282.361 0 .8307.0964 1.1158.3671.359.3344.3262.7795.3262 1.2677v1.1487c0 .3446.1436.4964.279.681.0471.0677.0574.1477-.002.197-.1519.125-.5703.4881-.5703.4881zm-.7467-1.7969v-.16c-.5353 0-1.1015.115-1.1015.7426 0 .318.1662.5333.4513.5333.2051 0 .3938-.1272.5128-.3344.1436-.2564.1374-.4943.1374-.7815zM2.9278 7.948c-.0472.041-.1375.045-.1723.0163-.2544-.1949-.4246-.4923-.4246-.4923-.4082.4123-.6954.5374-1.2226.5374-.6235 0-1.1076-.3835-1.1076-1.1486a1.2512 1.2512 0 0 1 .7897-1.2041c.402-.1764.964-.2072 1.3928-.2564 0 0 .0348-.4615-.0903-.6297a.521.521 0 0 0-.4164-.1908c-.2748 0-.5395.1477-.5928.4328-.0143.082-.0759.1518-.1395.1436L.2345 5.08a.1292.1292 0 0 1-.1087-.1537c.162-.8657.9497-1.1282 1.6553-1.1282.361 0 .8308.0964 1.1159.3671.359.3344.324.7795.324 1.2677v1.1487c0 .3446.1437.4964.279.681.0472.0677.0575.1477-.002.197-.1518.125-.5702.4881-.5702.4881zm-.7446-1.797v-.16c-.5354 0-1.1015.115-1.1015.7426 0 .318.164.5333.4512.5333.2052 0 .3939-.1272.5128-.3344.1436-.2564.1375-.4943.1375-.7815zm2.9127-.3343v2.002a.1379.1379 0 0 1-.1395.1374H4.218a.1374.1374 0 0 1-.1395-.1374v-3.766a.1379.1379 0 0 1 .1395-.1375h.6913a.1374.1374 0 0 1 .1374.1374v.482h.0143c.1805-.4758.519-.6994.9744-.6994.4636 0 .7528.2236.962.6995a1.0523 1.0523 0 0 1 1.0215-.6995c.3118 0 .6502.1272.8574.4143.236.318.1867.7795.1867 1.1857v2.3855c0 .076-.0636.1354-.1436.1354H8.181a.1374.1374 0 0 1-.1334-.1354v-2.004c0-.16.0144-.558-.0205-.7077-.0554-.2564-.2215-.3282-.4369-.3282a.4923.4923 0 0 0-.441.3118c-.076.1908-.0698.5087-.0698.724v2.0041c0 .076-.0635.1354-.1435.1354h-.7385a.1374.1374 0 0 1-.1333-.1354v-2.004c0-.4226.0677-1.042-.4574-1.042-.5334 0-.5128.603-.5128 1.042h.002zm16.8077 2.002a.1374.1374 0 0 1-.1374.1374h-.7405a.1374.1374 0 0 1-.1374-.1374v-3.766a.1374.1374 0 0 1 .1374-.1375h.683c.0821 0 .1396.0636.1396.1067v.5764h.0143c.2051-.517.4964-.7631 1.0092-.7631.3323 0 .6564.119.8636.4451.1928.3036.1928.8123.1928 1.1774V7.837a.1395.1395 0 0 1-.1415.119h-.7426a.1395.1395 0 0 1-.1313-.119V5.552c0-.763-.2933-.7856-.4635-.7856-.197 0-.357.1538-.4246.2953a1.7025 1.7025 0 0 0-.1231.722l.002 2.0349zM.1914 20.0582c-.1271 0-.1907-.0615-.1907-.1907v-4.4491c0-.1272.0636-.1908.1907-.1908H.616c.0616 0 .1129.0144.1477.039.0349.0246.0595.0738.0718.1436l.0575.3035c.6133-.4184 1.2102-.6276 1.7907-.6276.5948 0 .9969.2256 1.2081.6769.6318-.4513 1.2636-.677 1.8954-.677.441 0 .7794.1231 1.0153.3693.236.2502.3549.603.3549 1.0584v3.3538c0 .1271-.0656.1907-.1928.1907h-.5641c-.1272 0-.1928-.0615-.1928-.1907v-3.085c0-.318-.0616-.5539-.1805-.7057-.1231-.1538-.3139-.2297-.5744-.2297-.4677 0-.9353.1436-1.4092.4307a.997.997 0 0 1 .0103.1416v3.448c0 .1272-.0636.1908-.1908.1908H3.297c-.1272 0-.1908-.0615-.1908-.1907v-3.085c0-.318-.0615-.5539-.1825-.7057-.1231-.1538-.3139-.2297-.5744-.2297-.4861 0-.9517.1395-1.399.4205v3.5999c0 .1271-.0615.1907-.1907.1907H.1914zm9.731.1436c-.4533 0-.8-.1272-1.044-.3815-.242-.2544-.3631-.6133-.3631-1.0769v-3.321c0-.1292.0615-.1927.1908-.1927h.564c.1293 0 .1929.0635.1929.1907v3.0215c0 .3425.0656.5948.201.7569.1333.162.3487.242.642.242.4595 0 .923-.1518 1.3887-.4574v-3.565c0-.1272.0615-.1908.1908-.1908h.564c.1293 0 .1929.0636.1929.1908v4.4511c0 .1252-.0636.1887-.1928.1887h-.4103c-.0636 0-.1149-.0123-.1497-.0369-.0349-.0266-.0575-.0738-.0718-.1436l-.0657-.3323c-.5948.437-1.204.6564-1.8297.6564zm5.4399 0c-.5374 0-1.0195-.0882-1.4461-.2666a.3754.3754 0 0 1-.158-.1047c-.0287-.039-.043-.0984-.043-.1805v-.2687c0-.1148.0369-.1723.1148-.1723.0452 0 .1231.0205.238.0575.4225.1333.8615.199 1.3128.199.3138 0 .5517-.0616.7138-.1806.164-.121.244-.2954.244-.523a.4923.4923 0 0 0-.1476-.3734 1.606 1.606 0 0 0-.5415-.285l-.8144-.3037c-.7097-.2605-1.0625-.7056-1.0625-1.3333 0-.4143.16-.7487.484-1.001.3221-.2543.7447-.3815 1.2677-.3815a3.487 3.487 0 0 1 1.2164.2195c.076.0246.1313.0574.1641.0985.0308.041.0472.1025.0472.1846v.2584c0 .1149-.041.1723-.123.1723a.8615.8615 0 0 1-.2216-.0472 3.5495 3.5495 0 0 0-1.0359-.1538c-.6112 0-.919.2072-.919.6195 0 .164.0514.2953.154.3897.1025.0964.3035.201.603.3159l.7466.2872c.3774.1436.6482.318.8144.519.1661.1989.2482.4574.2482.7753 0 .4513-.1682.8102-.5067 1.0769-.3385.2666-.7877.4-1.3497.4v.002zm3.0645-.1436c-.1272 0-.1928-.0615-.1928-.1907v-4.4491c0-.1272.0656-.1908.1928-.1908h.5641c.1272 0 .1928.0636.1928.1908v4.4511c0 .1251-.0656.1887-.1928.1887h-.564zm.2872-5.688c-.1846 0-.3303-.0513-.437-.1559a.558.558 0 0 1-.1579-.4143c0-.1724.0534-.3098.158-.4144a.5907.5907 0 0 1 .4369-.158c.1846 0 .3282.0534.4349.158.1066.1026.1579.242.1579.4144 0 .1702-.0513.3076-.158.4143-.1046.1026-.2502.1559-.4348.1559zm4.002 5.7926c-.7529 0-1.3293-.2133-1.7272-.642-.4-.4307-.599-1.0502-.599-1.8625 0-.8061.2052-1.4318.6175-1.8728.4102-.441.9948-.6625 1.7476-.6625.3446 0 .683.0615 1.0154.1825.0697.0247.119.0554.1477.0944s.043.1026.043.1908v.2564c0 .1271-.041.1907-.123.1907-.0329 0-.082-.0082-.1539-.0287a2.8307 2.8307 0 0 0-.7959-.1128c-.5353 0-.923.1333-1.1589.404s-.3528.6996-.3528 1.2924v.123c0 .5764.119 1.001.359 1.2718.24.2687.6174.404 1.1343.404.2666 0 .5538-.043.8615-.1332.0718-.0206.119-.0288.1436-.0288.082 0 .1251.0636.1251.1908v.2585c0 .082-.0123.1435-.039.1805-.0246.0369-.0759.0718-.1518.1025-.3138.1354-.6769.201-1.0933.201z"/></svg>`;
export const MEDIA: Record<string, Brand> = {
  amazonmusic: { id: "amazonmusic", name: "Amazon Music", color: "#25d1da", svg: AMAZONMUSIC },
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
