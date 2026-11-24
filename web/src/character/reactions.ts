// One-off reactions played over the mood (OMEGA 72 / 73 / 74 / 81 / 738 / 746 / 747 / 749 / 750), the props he wears
// by weather and time of day (739 / 740 / 741) and how lively each personality is (242).
import { EYES, type Look } from "./looks";

export interface Reaction { name: string; id: number; detail?: Record<string, any> }
export interface Ambient { part?: "night" | "morning" | "day" | "evening"; weather?: string | null; temp?: number | null }

export interface Phase {
  until: number;                         // seconds since the reaction started
  look: Partial<Look> & { spin?: boolean; wink?: boolean };
  extra?: string;                        // HTML for the reaction's own prop
}

const icon = (name: string, weight = "fill") => `<i class="ph${weight === "fill" ? "-fill" : weight === "bold" ? "-bold" : ""} ph-${name}"></i>`;
const safeIcon = (s: unknown) => String(s || "star").toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 40) || "star";
const safeColor = (s: unknown) => (/^#[0-9a-f]{3,8}$/i.test(String(s || "")) ? String(s) : undefined);
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
const TOY_ICON: Record<string, string> = { ball: "soccer-ball", yoyo: "disc", plane: "paper-plane-tilt", bubble: "drop" };

export const PERSONALITY_ENERGY: Record<string, number> = { "vyvážený": 1, "hravý": 1.35, "klidný": 0.6, "profesionální": 0.45 };

/** The phases of a reaction: what his face and body do and which prop shows, in order. */
export function reactionPhases(r: Reaction): Phase[] {
  const d = r.detail || {};
  switch (r.name) {
    case "stretch":   // the PC woke up: a long stretch, a yawn, then a happy hop
      return [{ until: 0.7, look: { eyes: "closed", squash: 0.74, glow: 0.3, blink: false } },
        { until: 1.7, look: { eyes: "happy", squash: 1.2, tilt: -4, blink: false }, extra: `<span class="acc-yawn">${icon("sun-horizon")}</span>` },
        { until: 3, look: { eyes: "open", hop: true } }];
    case "volume":
      return [{ until: 1.6, look: { eyes: d.up ? "wide" : "lidded", gaze: [0, -0.3] },
        extra: `${icon(d.level >= 66 ? "speaker-high" : d.level > 0 ? "speaker-low" : "speaker-none")}<b style="--lv:${Math.max(0, Math.min(100, Number(d.level) || 0))}%"></b>` }];
    case "mute":
      return [{ until: 2.4, look: { eyes: "lidded", squash: 1.06 }, extra: icon("speaker-slash") }];
    case "unmute":
      return [{ until: 1.6, look: { eyes: "wide", hop: true }, extra: icon("speaker-high") }];
    case "plug":
      return [{ until: 2.6, look: { eyes: "wide", hop: true, glow: 0.8 }, extra: icon("plugs-connected") }];
    case "unplug":
      return [{ until: 2.2, look: { eyes: "sad", shake: true }, extra: icon("plugs") }];
    case "switch":   // another AI took over: a little dizzy turn and the new name
      return [{ until: 2.2, look: { eyes: "pensive", wobble: true }, extra: `${icon("arrows-clockwise", "bold")}<em>${esc(d.to)}</em>` }];
    case "copy":
      return [{ until: 2.5, look: { eyes: "open", gaze: [0.7, 0.1] }, extra: `<span>${icon("file")}</span><span>${icon("file")}</span><span>${icon("file")}</span>` }];
    case "toy":
      return [{ until: 6, look: { eyes: "happy", gaze: [0.5, -0.2], blink: false }, extra: icon(TOY_ICON[d.toy] || "soccer-ball") }];
    case "easter":
      if (d.kind === "spin") return [{ until: 1.2, look: { eyes: "happy", spin: true } }, { until: 2.4, look: { eyes: "happy", accessories: ["stars"] } }];
      if (d.kind === "42") return [{ until: 3, look: { eyes: "pensive" }, extra: "<em>42</em>" }];
      if (d.kind === "juggle") return [{ until: 3, look: { eyes: "happy", hop: true, accessories: ["stars"] } }];
      return [{ until: 0.35, look: { eyes: "closed" } }, { until: 2, look: { eyes: "happy", accessories: ["heart"] } }];
    // 3.15 new feelings (návrh 19): surprised by a sudden notice, proud after a long job, a yawn at night, a wink
    case "surprised":
      return [{ until: 0.22, look: { eyes: "wide", squash: 0.84, glow: 0.85, blink: false } },
        { until: 1.2, look: { eyes: "wide", gaze: [0, -0.25], blink: false }, extra: "<em class=\"acc-bang\">!</em>" }];
    case "proud":
      return [{ until: 0.35, look: { eyes: "happy", squash: 0.8 } },
        { until: 2.4, look: { eyes: "happy", hop: true, glow: 0.95, accessories: ["stars"] } }];
    case "yawn":
      return [{ until: 0.5, look: { eyes: "sleepy", blink: false } },
        { until: 1.9, look: { eyes: "closed", squash: 1.16, tilt: -3, blink: false }, extra: `<span class="acc-yawn">${icon("moon")}</span>` },
        { until: 2.4, look: { eyes: "lidded" } }];
    case "wink":
      return [{ until: 0.45, look: { eyes: "happy", wink: true, blink: false } }, { until: 0.8, look: { eyes: "open" } }];
    case "custom": {
      const eyes = (d.eyes in EYES ? d.eyes : "wide") as keyof typeof EYES;
      const m = String(d.motion || "hop");
      const look: Phase["look"] = { eyes, glowColor: safeColor(d.color), hop: m === "hop", shake: m === "shake", dance: m === "dance", wobble: m === "wobble", spin: m === "spin" };
      return [{ until: Math.max(0.5, Math.min(15, Number(d.seconds) || 3)), look, extra: icon(safeIcon(d.icon)) }];
    }
  }
  return [];
}

/** What he wears for the weather and the time of day (only while calm, so it never hides a state). */
export function ambientExtra(a: Ambient | undefined): string {
  if (!a) return "";
  const out: string[] = [];
  if (a.weather === "rain" || a.weather === "storm") out.push(`<span class="amb-umbrella">${icon("umbrella")}</span>`);
  else if (a.weather === "snow" || (a.temp != null && a.temp < 2)) out.push(`<span class="amb-snow">${icon("snowflake")}</span>`);
  else if (a.weather === "sun" && a.temp != null && a.temp >= 24) out.push(`<span class="amb-sun">${icon("sun")}</span>`);
  if (a.part === "night") out.push(`<span class="amb-moon">${icon("moon-stars")}</span>`);
  else if (a.part === "morning") out.push(`<span class="amb-coffee">${icon("coffee")}</span>`);
  return out.join("");
}
