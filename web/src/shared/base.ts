import { setAutoDark, setKeyboardOnly, setSwitchScan } from "./access";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "@phosphor-icons/web/regular";
import "@phosphor-icons/web/bold";
import "@phosphor-icons/web/fill";
import "highlight.js/styles/github-dark.css";
import "./theme.css";
import "./glass.css";
import { configureMotion, initMotion } from "./motion";
import { applyCustomTheme } from "./theme320";

// OMEGA 240 / 255 / 764: "auto" = full animations on the charger, reduced on battery (and the phone's low-power mode)
let motionPref = "full";
let onBattery = false;
let heavyLoad = false;               // 3.14 návrh 79: the processor is busy → fewer effects (with "auto")
function applyMotion() {
  document.documentElement.dataset.motion = motionPref === "reduced" || (motionPref === "auto" && (onBattery || heavyLoad)) ? "reduced" : "full";
}
export function applyLoad(heavy: boolean) {
  heavyLoad = !!heavy;
  applyMotion();
  configureMotion({ heavy: heavyLoad });
}
export function applyPower(battery: boolean) {
  onBattery = !!battery;
  applyMotion();
  configureMotion({ battery: onBattery });
}
initMotion();                         // 3.15 the effects tier + one animation clock for the page

export const MOTIFS: Record<string, { accent: string; label: string }> = {
  stark: { accent: "#4fc3ff", label: "Stark – modrá" }, mark: { accent: "#ff4d3d", label: "Mark – červená a zlatá" },
  friday: { accent: "#b48cff", label: "FRIDAY – fialová" }, stealth: { accent: "#9aa4b2", label: "Stealth – grafit" },
};

export function applyAppearance(s: any) {
  const a = s?.appearance;
  if (!a) return;
  applyCustomTheme(a);                                             // 3.20 (107) your own theme on every page
  const root = document.documentElement;
  // the notch is a black hardware-like cut-out: it keeps the dark tokens in the light theme too
  root.dataset.theme = a.theme === "light" && !root.classList.contains("notch-doc") ? "light" : "dark";
  root.dataset.glass = a.theme === "glass" ? "1" : "0";            // 3.12 liquid glass (frosted panels over an aurora)
  // 3.15 motifs: Stark (blue), Mark (red and gold), FRIDAY (violet), Stealth (graphite) – or your own accent colour
  const motif = MOTIFS[a.motif as string];
  root.dataset.motif = motif ? String(a.motif) : "vlastni";
  const accent = motif?.accent || a.accent;
  if (accent) {
    root.style.setProperty("--accent", accent);
    root.style.setProperty("--accent-ink", inkFor(accent));
  }
  motionPref = a.animations || "full";
  applyMotion();
  configureMotion({ quality: a.fx_quality || "auto", animations: a.animations });
  root.dataset.contrast = a.high_contrast ? "high" : "normal";                  // 3.14 návrh 68
  root.dataset.dyslexia = a.dyslexia ? "1" : "0";                               // 3.20 (468)
  root.dataset.cb = a.colorblind || "";                                         // 3.20 (469)
  root.dataset.simple = a.simple ? "1" : "0";                                   // 3.20 (472)
  root.dataset.kb = a.keyboard_only ? "1" : "0";                                // 3.20 (464)
  setKeyboardOnly(!!a.keyboard_only);
  setSwitchScan(Number(a.switch_scan) || 0);                                    // 3.20 (474)
  if (!root.classList.contains("notch-doc")) setAutoDark(!!a.auto_dark, (t) => { root.dataset.theme = t; });   // 3.20 (479)
  const scale = Math.max(1, Math.min(1.6, Number(a.font_scale) || 1));
  if (!root.classList.contains("notch-doc")) (root.style as any).zoom = scale === 1 ? "" : String(scale);
  densityPref = a.density || "auto";
  applyDensity();
  inputPref = a.input_mode || "auto";
  applyInput();
}

// OMEGA 522: mouse, touch or voice – chosen, or from the device and the last real input. Touch gets bigger targets,
// voice a bigger microphone button (it never starts listening by itself).
let inputPref = "auto";
let lastInput = "";
let inputBound = false;
export function inputModeFor(pref: string, sig: { coarse: boolean; hover: boolean; last: string }): "mouse" | "touch" | "voice" {
  if (pref === "mouse" || pref === "touch" || pref === "voice") return pref;
  if (sig.last === "touch" || sig.last === "pen") return "touch";
  if (sig.last === "mouse") return "mouse";
  return sig.coarse && !sig.hover ? "touch" : "mouse";
}
function applyInput() {
  const mq = (q: string) => typeof window.matchMedia === "function" && window.matchMedia(q).matches;
  document.documentElement.dataset.input = inputModeFor(inputPref, { coarse: mq("(pointer: coarse)"), hover: mq("(hover: hover)"), last: lastInput });
  if (!inputBound) {
    inputBound = true;
    window.addEventListener("pointerdown", (e) => {
      const kind = e.pointerType || "mouse";
      if (kind !== lastInput) { lastInput = kind; applyInput(); }
    }, { passive: true, capture: true });
  }
}

// OMEGA 758: how dense the UI is – chosen, or by the window size ("auto"); the pages that use it scale with it
let densityPref = "auto";
let densityBound = false;
export function densityFor(pref: string, width: number): "compact" | "comfortable" | "large" {
  if (pref === "compact" || pref === "comfortable" || pref === "large") return pref;
  return width < 1100 ? "compact" : width >= 2200 ? "large" : "comfortable";
}
function applyDensity() {
  document.documentElement.dataset.density = densityFor(densityPref, window.innerWidth);
  if (!densityBound) {
    densityBound = true;
    let t = 0;
    window.addEventListener("resize", () => { window.clearTimeout(t); t = window.setTimeout(applyDensity, 150); });
  }
}

/** Text colour that stays readable on the accent (white on blue, near-black on yellow or white accents). */
export function inkFor(hex: string): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return "#fff";
  const n = parseInt(m[1], 16);
  const lin = (c: number) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  const L = 0.2126 * lin(n >> 16) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  return L > 0.36 ? "#06080c" : "#fff";
}
