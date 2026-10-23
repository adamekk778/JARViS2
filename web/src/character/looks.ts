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

// Eye shape: half-width, half-height, top curvature, bottom curvature (negative = curves the other way).
export interface Eye { w: number; h: number; top: number; bottom: number; tilt: number }

export const EYES: Record<string, Eye> = {
  open: { w: 11, h: 15, top: 1.35, bottom: 1.35, tilt: 0 },
  wide: { w: 13, h: 18, top: 1.35, bottom: 1.35, tilt: 0 },
  happy: { w: 13, h: 11, top: 1.5, bottom: -0.55, tilt: 0 },     // ^ ^
  sleepy: { w: 13, h: 9, top: -0.45, bottom: 1.35, tilt: 0 },   // ‿ ‿ (lids down)
  closed: { w: 13, h: 3.5, top: 0.25, bottom: 0.25, tilt: 0 },    // — —
  sad: { w: 11, h: 12, top: 0.45, bottom: 1.35, tilt: -16 },
  focused: { w: 12, h: 10, top: 0.45, bottom: 1.2, tilt: 5 },
  up: { w: 11, h: 10, top: 1.3, bottom: 0.4, tilt: 0 },            // thinking: looking up
};

export type Accessory =
  | "waves" | "dots" | "voice" | "notes" | "laptop" | "progress" | "sparkles" | "alert" | "zzz" | "limit"
  | "wifi" | "download" | "bell" | "cursor" | "headphones" | "clock" | "hearts" | "ripple";

export interface Look {
  eyes: keyof typeof EYES;
  gaze: [number, number];   // -1..1
  bob: number;              // px amplitude
  bobSpeed: number;         // Hz
  squash: number;           // >1 wide & short, <1 tall
  tilt: number;             // deg
  glow: number;             // 0..1
  glowColor?: string;       // override (error/limit red)
  dim?: number;             // 0..1 grey out (offline)
  accessories: Accessory[];
  audio?: boolean;          // body pulses with level
  dance?: boolean;
  hop?: boolean;
  shake?: boolean;
  blink?: boolean;          // random blinking allowed
}

const base: Look = { eyes: "open", gaze: [0, 0], bob: 1.5, bobSpeed: 0.25, squash: 1, tilt: 0, glow: 0.45, accessories: [], blink: true };
const L = (o: Partial<Look>): Look => ({ ...base, ...o });

export const LOOKS: Record<Mood, Look> = {
  closed: L({ eyes: "closed", glow: 0.2, bob: 0.6, blink: false }),
  idle: L({}),
  hover: L({ eyes: "wide", squash: 0.96, glow: 0.65 }),
  opening: L({ eyes: "wide", squash: 0.92, glow: 0.7 }),
  expanded: L({ eyes: "open", glow: 0.6 }),
  closing: L({ eyes: "happy", squash: 1.04, glow: 0.4 }),
  listening: L({ eyes: "open", glow: 0.85, accessories: ["waves"], audio: true }),
  thinking: L({ eyes: "up", gaze: [-0.5, -0.8], accessories: ["dots"], bob: 2, bobSpeed: 0.6, glow: 0.6, blink: false }),
  speaking: L({ eyes: "happy", accessories: ["voice"], audio: true, glow: 0.8 }),
  dancing: L({ eyes: "happy", accessories: ["notes"], dance: true, glow: 0.75, blink: false }),
  working: L({ eyes: "focused", gaze: [0.35, 0.5], accessories: ["laptop", "progress"], tilt: -4, glow: 0.55 }),
  success: L({ eyes: "happy", accessories: ["sparkles"], hop: true, glow: 0.9, blink: false }),
  error: L({ eyes: "sad", accessories: ["alert"], shake: true, glow: 0.5, glowColor: "#ff4d57", squash: 1.04 }),
  sleeping: L({ eyes: "closed", accessories: ["zzz"], bob: 2.5, bobSpeed: 0.18, squash: 1.08, glow: 0.25, blink: false }),
  limit: L({ eyes: "happy", accessories: ["limit"], glow: 0.9, glowColor: "#ff3b3b", tilt: -3 }),
  offline: L({ eyes: "open", accessories: ["wifi"], dim: 0.35, glow: 0.2 }),
  updating: L({ eyes: "open", gaze: [0, 0.6], accessories: ["download", "progress"], glow: 0.6 }),
  notify: L({ eyes: "wide", accessories: ["bell"], glow: 0.7 }),
  dragged: L({ eyes: "wide", squash: 0.82, glow: 0.8, blink: false }),
  desktop_interact: L({ eyes: "open", gaze: [0.6, 0.2], accessories: ["cursor", "ripple"], glow: 0.7 }),
  focus: L({ eyes: "closed", accessories: ["headphones"], bob: 1, bobSpeed: 0.15, glow: 0.35, blink: false }),
  personalize: L({ eyes: "happy", glow: 0.8 }),
  waiting: L({ eyes: "open", accessories: ["clock"], bob: 2, bobSpeed: 0.35, tilt: 3 }),
  joy: L({ eyes: "happy", accessories: ["hearts"], hop: true, glow: 0.9, blink: false }),
};

export type CharacterColor = "black" | "midnight" | "violet" | "rose" | "white";

export const BODY_COLORS: Record<CharacterColor, { light: string; mid: string; dark: string; eye: string; rim: string }> = {
  black: { light: "#3a414c", mid: "#14181e", dark: "#030405", eye: "#f4f8ff", rim: "#7fb8ff" },
  midnight: { light: "#3a4f82", mid: "#141d3b", dark: "#04060f", eye: "#f4f8ff", rim: "#6aa8ff" },
  violet: { light: "#6a4aa6", mid: "#2a1648", dark: "#0b0414", eye: "#f8f4ff", rim: "#b48cff" },
  rose: { light: "#a5507a", mid: "#45162d", dark: "#12040b", eye: "#fff4f8", rim: "#ff8cc0" },
  white: { light: "#ffffff", mid: "#dfe5ee", dark: "#9aa6b6", eye: "#0b0e13", rim: "#ffffff" },
};
