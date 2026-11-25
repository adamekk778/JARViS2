// The wardrobe (3.0): outfits drawn in the character's own SVG (viewBox 0..200, the dome's crown at y≈45,
// the eyes at y≈133), so they move, squash and tilt with him. "auto" dresses him for the season.
export const OUTFITS = ["auto", "none", "beanie", "crown", "party", "santa", "witch", "sunglasses", "bow", "cap",
  "headphones", "graduate", "flower", "halo"] as const;
/** 3.14 návrh 78: outfits Mochi unlocks as you spend time together (the level comes from the core: mochi_level). */
export const UNLOCK_LEVEL: Partial<Record<Outfit, number>> = { headphones: 2, graduate: 4, flower: 6, halo: 9 };
export type Outfit = (typeof OUTFITS)[number];

export const OUTFIT_LABEL: Record<Outfit, string> = {
  auto: "Podle sezóny", none: "Nic", beanie: "Kulich", crown: "Koruna", party: "Párty čepička", santa: "Santa",
  witch: "Čarodějnický klobouk", sunglasses: "Sluneční brýle", bow: "Mašle", cap: "Kšiltovka",
  headphones: "Sluchátka", graduate: "Čepice absolventa", flower: "Kytička", halo: "Svatozář",
};

/** "auto" → what to wear today (Christmas, Halloween, New Year, summer). */
export function resolveOutfit(o: string | undefined, today = new Date()): Exclude<Outfit, "auto"> {
  if (o && o !== "auto" && (OUTFITS as readonly string[]).includes(o)) return o as Exclude<Outfit, "auto">;
  const m = today.getMonth() + 1, d = today.getDate();
  if (m === 12 && d <= 26) return "santa";
  if ((m === 12 && d === 31) || (m === 1 && d === 1)) return "party";
  if ((m === 10 && d >= 24) || (m === 11 && d === 1)) return "witch";
  if (m === 7 || m === 8) return "sunglasses";
  return "none";
}

export const OUTFIT_SVG: Record<Exclude<Outfit, "auto" | "none">, string> = {
  beanie: `<path d="M38 74 C40 18 160 18 162 74 Z" fill="#e5484d"/><path d="M54 40 C70 30 130 30 146 40" stroke="#ff8a8f" stroke-width="3" fill="none" opacity=".5"/>
    <rect x="32" y="64" width="136" height="18" rx="9" fill="#b8323a"/><g stroke="#e5484d" stroke-width="2" opacity=".6"><path d="M48 66v14M62 66v14M76 66v14M90 66v14M104 66v14M118 66v14M132 66v14M146 66v14"/></g>
    <circle cx="100" cy="22" r="11" fill="#fff"/>`,
  crown: `<path d="M68 54 L68 24 L83 40 L100 16 L117 40 L132 24 L132 54 Z" fill="#f7c948" stroke="#c9961a" stroke-width="2" stroke-linejoin="round"/>
    <rect x="66" y="50" width="68" height="9" rx="3" fill="#e5ad2b"/><circle cx="100" cy="36" r="4" fill="#e5484d"/><circle cx="82" cy="46" r="2.6" fill="#3b9eff"/><circle cx="118" cy="46" r="2.6" fill="#34d399"/>`,
  party: `<g transform="rotate(14 112 46)"><path d="M88 52 L112 -4 L136 52 Z" fill="#a78bfa"/>
    <path d="M97 31 L127 31 M93 41 L131 41 M102 20 L122 20" stroke="#fde68a" stroke-width="5" stroke-linecap="round"/>
    <circle cx="112" cy="-6" r="7" fill="#f472b6"/></g>`,
  santa: `<path d="M44 70 C52 22 112 8 150 40 C162 50 170 62 172 78 L164 80 C160 62 150 54 140 52 C120 50 80 56 56 74 Z" fill="#dc2626"/>
    <path d="M40 66 C70 52 130 52 162 66 L160 82 C130 70 70 70 42 82 Z" fill="#fff"/><circle cx="170" cy="84" r="10" fill="#fff"/>`,
  witch: `<ellipse cx="100" cy="56" rx="78" ry="11" fill="#2a1648"/><path d="M68 54 C76 30 92 8 128 -14 C116 10 120 30 134 54 Z" fill="#3b1d6e"/>
    <path d="M70 48 C90 42 112 42 132 48 L133 55 C112 50 90 50 69 55 Z" fill="#f97316"/><rect x="94" y="43" width="12" height="10" rx="2" fill="#fde68a"/>`,
  sunglasses: `<g fill="#0b0b10" stroke="#2a2d36" stroke-width="2"><rect x="43" y="117" width="46" height="30" rx="11"/><rect x="111" y="117" width="46" height="30" rx="11"/></g>
    <path d="M89 126 C96 121 104 121 111 126" stroke="#2a2d36" stroke-width="4" fill="none"/>
    <path d="M50 124 L62 124" stroke="#fff" stroke-width="3" stroke-linecap="round" opacity=".5"/><path d="M118 124 L130 124" stroke="#fff" stroke-width="3" stroke-linecap="round" opacity=".5"/>`,
  bow: `<g transform="translate(138 50) rotate(18)"><path d="M0 0 L-24 -14 L-24 14 Z" fill="#f472b6"/><path d="M0 0 L24 -14 L24 14 Z" fill="#f472b6"/>
    <circle r="7" fill="#db2777"/></g>`,
  headphones: `<path d="M34 112 C30 40 170 40 166 112" stroke="#2a2d36" stroke-width="10" fill="none" stroke-linecap="round"/>
    <rect x="22" y="100" width="24" height="40" rx="10" fill="#3b82f6"/><rect x="154" y="100" width="24" height="40" rx="10" fill="#3b82f6"/>
    <rect x="27" y="106" width="8" height="28" rx="4" fill="#93c5fd" opacity=".6"/><rect x="165" y="106" width="8" height="28" rx="4" fill="#93c5fd" opacity=".6"/>`,
  graduate: `<path d="M100 18 L178 40 L100 62 L22 40 Z" fill="#111318" stroke="#2a2d36" stroke-width="2" stroke-linejoin="round"/>
    <path d="M60 50 L60 70 C80 80 120 80 140 70 L140 50 L100 62 Z" fill="#1c1f26"/>
    <path d="M150 44 L156 82" stroke="#f7c948" stroke-width="3"/><circle cx="156" cy="86" r="5" fill="#f7c948"/>`,
  flower: `<g transform="translate(140 46)"><g fill="#f9a8d4">${[0, 72, 144, 216, 288].map((a) => `<ellipse cx="0" cy="-11" rx="7" ry="11" transform="rotate(${a})"/>`).join("")}</g>
    <circle r="6" fill="#fde047"/></g><path d="M140 58 C138 66 136 70 132 74" stroke="#22c55e" stroke-width="3" fill="none"/>`,
  halo: `<ellipse cx="100" cy="20" rx="44" ry="10" fill="none" stroke="#fde68a" stroke-width="6" opacity=".95"/>
    <ellipse cx="100" cy="20" rx="44" ry="10" fill="none" stroke="#fff7d6" stroke-width="2" opacity=".8"/>`,
  cap: `<path d="M40 76 C42 22 158 22 160 76 Z" fill="#3b82f6"/><path d="M150 74 C170 70 190 74 196 82 C180 86 160 84 146 82 Z" fill="#1d4ed8"/>
    <circle cx="100" cy="27" r="5" fill="#1d4ed8"/><path d="M100 28 L100 74" stroke="#1d4ed8" stroke-width="2" opacity=".5"/>`,
};
