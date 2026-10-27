import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "@phosphor-icons/web/regular";
import "@phosphor-icons/web/bold";
import "@phosphor-icons/web/fill";
import "highlight.js/styles/github-dark.css";
import "./theme.css";

export function applyAppearance(s: any) {
  const a = s?.appearance;
  if (!a) return;
  const root = document.documentElement;
  // the notch is a black hardware-like cut-out: it keeps the dark tokens in the light theme too
  root.dataset.theme = a.theme === "light" && !root.classList.contains("notch-doc") ? "light" : "dark";
  if (a.accent) {
    root.style.setProperty("--accent", a.accent);
    root.style.setProperty("--accent-ink", inkFor(a.accent));
  }
  root.dataset.motion = a.animations === "reduced" ? "reduced" : "full";
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
