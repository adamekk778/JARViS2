// 3.12 The header on top of each page of the JARVIS window – calm and clean: the page's icon in its colour, the title,
// one line under it and the page's buttons. (The old band with drifting particles and walking characters was busy and
// kept the processor working; the characters live in the notch.)
import { h, icon } from "./dom";
import type { CharacterColor } from "../character/blob";

export interface CastMember { color: CharacterColor; size: number; start: number; glow?: string; sleeps?: boolean }
export interface HeroSpec { color: string; cast: CastMember[] }

/** kept for the pages that call it after showing a band – nothing animates any more */
export function wakeBands() { /* nothing to wake */ }

const ICONS: Record<string, string> = {
  learn: "graduation-cap", knowledge: "brain", files: "folders", rescue: "first-aid-kit", security: "shield-check", home: "house-line",
  auto: "flow-arrow", comms: "envelope-simple", stark: "circle-notch", claude: "terminal-window", dictate: "microphone", stats: "chart-bar",
  notetaker: "record", dictation: "sliders", dictionary: "book-open", chat: "chat-circle-dots", tasks: "list-checks", diagnostics: "pulse",
  general: "user-circle", brain: "brain", voice: "waveform", notch: "rectangle", appearance: "palette", hotkeys: "keyboard",
  permissions: "shield-check", tools: "toolbox", integrations: "plugs-connected", phone: "device-mobile", memory: "database",
  jobs: "calendar-check", backup: "floppy-disk",
};

export function hero(spec: HeroSpec, title: string, subtitle: string | null, actions: HTMLElement[] = [], compact = false): HTMLElement {
  const key = Object.keys(HEROES).find((k) => HEROES[k] === spec) || "";
  const root = h("div", { class: `phead ${compact ? "compact" : ""}` },
    h("span", { class: "phead-ico", "aria-hidden": "true" }, icon(ICONS[key] || "sparkle", "ph-fill")),
    h("div", { class: "phead-copy" }, h("h1", {}, title), subtitle ? h("p", {}, subtitle) : null),
    actions.length ? h("div", { class: "phead-actions" }, ...actions) : null);
  root.style.setProperty("--hero-color", spec.color);
  return root;
}

/** Every page's colour and cast (the JARVIS window's palette). */
export const HEROES: Record<string, HeroSpec> = {
  learn: { color: "#34d399", cast: [{ color: "green", size: 56, start: 0.2 }, { color: "white", size: 46, start: 0.6 }, { color: "cyan", size: 40, start: 0.95 }] },
  knowledge: { color: "#c084fc", cast: [{ color: "violet", size: 56, start: 0.2 }, { color: "white", size: 46, start: 0.6 }, { color: "rose", size: 40, start: 0.95 }] },
  files: { color: "#fbbf24", cast: [{ color: "amber", size: 56, start: 0.2 }, { color: "white", size: 46, start: 0.6 }, { color: "cyan", size: 40, start: 0.95 }] },
  rescue: { color: "#f87171", cast: [{ color: "rose", size: 56, start: 0.2 }, { color: "white", size: 46, start: 0.6 }, { color: "amber", size: 40, start: 0.95 }] },
  security: { color: "#60a5fa", cast: [{ color: "blue", size: 56, start: 0.2 }, { color: "white", size: 46, start: 0.6 }, { color: "midnight", size: 42, start: 0.95 }] },
  home: { color: "#34d399", cast: [{ color: "green", size: 56, start: 0.2 }, { color: "amber", size: 46, start: 0.6 }, { color: "white", size: 40, start: 0.95 }] },
  auto: { color: "#a78bfa", cast: [{ color: "violet", size: 56, start: 0.2 }, { color: "white", size: 46, start: 0.6 }, { color: "cyan", size: 40, start: 0.95 }] },
  comms: { color: "#f59e0b", cast: [{ color: "amber", size: 56, start: 0.2 }, { color: "white", size: 46, start: 0.65 }, { color: "orange", size: 40, start: 1 }] },
  stark: { color: "#5fd4ff", cast: [{ color: "cyan", size: 58, start: 0.2 }, { color: "black", size: 50, start: 0.6 }, { color: "blue", size: 42, start: 0.95 }] },
  claude: { color: "#e07950", cast: [{ color: "orange", size: 58, start: 0.3 }, { color: "white", size: 48, start: 0.85 }] },
  dictate: { color: "#fb923c", cast: [{ color: "white", size: 62, start: 0.2 }, { color: "orange", size: 50, start: 0.65 }, { color: "rose", size: 42, start: 0.95 }] },
  stats: { color: "#34d399", cast: [{ color: "amber", size: 60, start: 0.3 }, { color: "green", size: 48, start: 0.75 }, { color: "white", size: 40, start: 1 }] },
  notetaker: { color: "#3b9eff", cast: [{ color: "blue", size: 58, start: 0.1 }, { color: "green", size: 48, start: 0.5 }, { color: "violet", size: 44, start: 0.9 }] },
  dictation: { color: "#8e939c", cast: [{ color: "white", size: 56, start: 0.3 }, { color: "black", size: 46, start: 0.95, sleeps: true }] },
  dictionary: { color: "#a78bfa", cast: [{ color: "violet", size: 58, start: 0.2 }, { color: "white", size: 46, start: 0.8 }] },
  chat: { color: "#4f8dff", cast: [{ color: "black", size: 58, start: 0.2 }, { color: "blue", size: 44, start: 0.7 }] },
  tasks: { color: "#34d399", cast: [{ color: "green", size: 52, start: 0.15 }, { color: "black", size: 60, start: 0.55 }, { color: "white", size: 40, start: 0.95 }] },
  "voice-mode": { color: "#f97316", cast: [{ color: "orange", size: 56, start: 0.3 }, { color: "black", size: 46, start: 0.85 }] },
  diagnostics: { color: "#22d3ee", cast: [{ color: "cyan", size: 50, start: 0.2 }, { color: "black", size: 58, start: 0.7 }] },
  general: { color: "#8e939c", cast: [{ color: "white", size: 58, start: 0.35 }, { color: "black", size: 46, start: 0.85 }] },
  brain: { color: "#a78bfa", cast: [{ color: "violet", size: 60, start: 0.2 }, { color: "white", size: 46, start: 0.6 }, { color: "cyan", size: 40, start: 1 }] },
  voice: { color: "#f97316", cast: [{ color: "orange", size: 58, start: 0.3 }, { color: "white", size: 46, start: 0.85 }] },
  notch: { color: "#4f8dff", cast: [{ color: "black", size: 56, start: 0.25 }, { color: "blue", size: 44, start: 0.8 }] },
  appearance: { color: "#f472b6", cast: [{ color: "rose", size: 58, start: 0.2 }, { color: "white", size: 46, start: 0.6 }, { color: "cyan", size: 40, start: 1 }] },
  hotkeys: { color: "#6366f1", cast: [{ color: "midnight", size: 56, start: 0.2 }, { color: "white", size: 44, start: 0.8 }] },
  permissions: { color: "#f7b32b", cast: [{ color: "amber", size: 56, start: 0.25 }, { color: "black", size: 48, start: 0.8 }] },
  tools: { color: "#fb923c", cast: [{ color: "orange", size: 54, start: 0.15 }, { color: "amber", size: 46, start: 0.6 }, { color: "white", size: 40, start: 0.95 }] },
  integrations: { color: "#7c5cff", cast: [{ color: "violet", size: 54, start: 0.15 }, { color: "cyan", size: 46, start: 0.55 }, { color: "amber", size: 42, start: 0.95 }] },
  phone: { color: "#3ddc84", cast: [{ color: "green", size: 56, start: 0.25 }, { color: "white", size: 46, start: 0.8 }] },
  memory: { color: "#3b9eff", cast: [{ color: "blue", size: 58, start: 0.1 }, { color: "green", size: 48, start: 0.5 }, { color: "violet", size: 44, start: 0.9 }] },
  jobs: { color: "#f7b32b", cast: [{ color: "amber", size: 56, start: 0.2 }, { color: "orange", size: 46, start: 0.6 }, { color: "white", size: 40, start: 0.95 }] },
  backup: { color: "#8e939c", cast: [{ color: "white", size: 56, start: 0.3 }, { color: "black", size: 46, start: 0.95, sleeps: true }] },
};
