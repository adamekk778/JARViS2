// What every mood looks like (spec §3). Numbers are targets the Blob animates toward.

export const MOODS = [
  "closed", "idle", "hover", "opening", "expanded", "closing",
  "listening", "thinking", "speaking", "dancing", "working", "success", "error", "sleeping",
  "limit", "offline", "updating", "notify", "dragged", "desktop_interact", "focus", "personalize", "waiting", "joy",
] as const;
export type Mood = (typeof MOODS)[number];

export const MOOD_LABEL: Record<Mood, string> = {
  closed: "Zavřený", idle: "Idle", hover: "Hover", opening: "Otevírání", expanded: "Rozbalený", closing: "Zasouvání",
  listening: "Poslouchá", thinking: "Přemýšlí", speaking: "Mluví", dancing: "Tančí", working: "Pracuje",
  success: "Úspěch", error: "Chyba", sleeping: "Spí", limit: "Limit", offline: "Bez internetu",
  updating: "Aktualizace", notify: "Upozornění", dragged: "Přetažení", desktop_interact: "Interakce",
  focus: "Režim fokus", personalize: "Personalizace", waiting: "Čeká", joy: "Radost",
};

// Eye shape: half-width, half-height, top curvature, bottom curvature (negative = curves the other way),
// tilt (deg, mirrored for the right eye) and cut (0..1: bite taken from the inner side → crescent "( )").
export interface Eye { w: number; h: number; top: number; bottom: number; tilt: number; cut: number }

const E = (w: number, h: number, top: number, bottom: number, tilt = 0, cut = 0): Eye => ({ w, h, top, bottom, tilt, cut });
export const EYES: Record<string, Eye> = {
  open: E(14.5, 18, 1.3, 1.3),
  wide: E(15.5, 20, 1.3, 1.3),
  small: E(8, 10, 1.3, 1.3),                 // peeking from the closed notch
  crescent: E(12.5, 19, 1.3, 1.3, 0, 1),       // ( ) offline
  happy: E(14, 13, 1.55, -0.6),              // ◠ ◠
  lidded: E(14, 14, 0.05, 1.3),              // half-closed, flat lid
  pensive: E(14, 14, 0.05, 1.3, 7),          // thinking: lids slightly slanted
  sleepy: E(14.5, 17, -0.15, 1.15),           // ‿ ‿
  closed: E(13, 3.5, 0.25, 0.25),            // — —
  sad: E(13.5, 16, 0.05, 1.3, -20),          // droopy lids, outer corners down
};

export type Accessory =
  | "waves" | "dots" | "voice" | "notes" | "laptop" | "check" | "warn" | "zzz" | "limit" | "cloud"
  | "spinner" | "bell" | "cursor" | "dragbox" | "minus" | "stars" | "wait" | "heart";

export interface Look {
  eyes: keyof typeof EYES;
  gaze: [number, number];   // -1..1
  bob: number;              // px amplitude
  bobSpeed: number;         // Hz
  squash: number;           // >1 wide & short, <1 tall
  tilt: number;             // deg
  glow: number;             // 0..1
  glowColor?: string;       // override
  dim?: number;             // 0..1 grey out
  noEyes?: boolean;         // eyes hidden (updating shows a ring instead)
  accessories: Accessory[];
  audio?: boolean;          // body pulses with level
  dance?: boolean;
  hop?: boolean;
  shake?: boolean;
  blink?: boolean;          // random blinking allowed
}

const base: Look = { eyes: "open", gaze: [0, 0], bob: 1.5, bobSpeed: 0.25, squash: 1, tilt: 0, glow: 0.45, accessories: [], blink: true };
const L = (o: Partial<Look>): Look => ({ ...base, ...o });

// One entry per tile of docs/superpowers/specs/assets/jarvis-character-reference-v2.png
export const LOOKS: Record<Mood, Look> = {
  closed: L({ eyes: "small", glow: 0.25, bob: 0.6 }),
  idle: L({}),
  hover: L({ eyes: "happy", glow: 0.6 }),
  opening: L({ eyes: "open", squash: 0.95, glow: 0.65 }),
  expanded: L({ eyes: "open", glow: 0.6 }),
  closing: L({ eyes: "happy", squash: 1.04, glow: 0.4 }),
  listening: L({ eyes: "open", glow: 0.8, accessories: ["waves"], audio: true }),
  thinking: L({ eyes: "pensive", accessories: ["dots"], bob: 1.5, bobSpeed: 0.5, glow: 0.55, blink: false }),
  speaking: L({ eyes: "open", accessories: ["voice"], audio: true, glow: 0.75 }),
  dancing: L({ eyes: "happy", accessories: ["notes"], dance: true, glow: 0.7, blink: false }),
  working: L({ eyes: "open", gaze: [0.6, 0.15], accessories: ["laptop"], glow: 0.55 }),
  success: L({ eyes: "happy", accessories: ["check"], hop: true, glow: 0.8, blink: false }),
  error: L({ eyes: "sad", accessories: ["warn"], shake: true, glow: 0.45, squash: 1.04, blink: false }),
  sleeping: L({ eyes: "sleepy", accessories: ["zzz"], bob: 1.5, bobSpeed: 0.18, squash: 1.22, glow: 0.3, blink: false }),
  limit: L({ eyes: "lidded", accessories: ["limit"], glow: 0.45, squash: 1.06, blink: false }),
  offline: L({ eyes: "crescent", accessories: ["cloud"], dim: 0.12, glow: 0.3 }),
  updating: L({ eyes: "open", noEyes: true, accessories: ["spinner"], glow: 0.6, blink: false }),
  notify: L({ eyes: "open", accessories: ["bell"], glow: 0.65 }),
  dragged: L({ eyes: "open", accessories: ["dragbox"], squash: 0.94, glow: 0.7 }),
  desktop_interact: L({ eyes: "open", gaze: [0.6, 0.35], accessories: ["cursor"], glow: 0.6 }),
  focus: L({ eyes: "lidded", accessories: ["minus"], bob: 1, bobSpeed: 0.15, glow: 0.35, blink: false }),
  personalize: L({ eyes: "open", accessories: ["stars"], glow: 0.75 }),
  waiting: L({ eyes: "open", accessories: ["wait"], bob: 1.5, bobSpeed: 0.3 }),
  joy: L({ eyes: "happy", accessories: ["heart"], hop: true, glow: 0.8, blink: false }),
};

export type CharacterColor = "black" | "midnight" | "violet" | "rose" | "white" | "blue" | "orange" | "green" | "amber" | "cyan";

export const BODY_COLORS: Record<CharacterColor, { light: string; mid: string; dark: string; eye: string; rim: string }> = {
  black: { light: "#2c323d", mid: "#0e1116", dark: "#030405", eye: "#f6f9ff", rim: "#a9c8ff" },
  midnight: { light: "#3a4f82", mid: "#141d3b", dark: "#04060f", eye: "#f4f8ff", rim: "#6aa8ff" },
  violet: { light: "#6a4aa6", mid: "#2a1648", dark: "#0b0414", eye: "#f8f4ff", rim: "#b48cff" },
  rose: { light: "#a5507a", mid: "#45162d", dark: "#12040b", eye: "#fff4f8", rim: "#ff8cc0" },
  white: { light: "#ffffff", mid: "#dfe5ee", dark: "#9aa6b6", eye: "#0b0e13", rim: "#ffffff" },
  // bright bodies with dark eyes (page bands, wardrobe)
  blue: { light: "#a9c8ff", mid: "#4f8dff", dark: "#1d4fc4", eye: "#06101f", rim: "#cfe0ff" },
  orange: { light: "#ffc89a", mid: "#fb923c", dark: "#b8520f", eye: "#1a0c03", rim: "#ffe0c4" },
  green: { light: "#9df0c9", mid: "#34d399", dark: "#0f8a5c", eye: "#03140d", rim: "#cffae6" },
  amber: { light: "#ffe08a", mid: "#f7b32b", dark: "#b07408", eye: "#1a1203", rim: "#fff0c2" },
  cyan: { light: "#a5f3fc", mid: "#22d3ee", dark: "#0e7f92", eye: "#03161a", rim: "#d5fbff" },
};
