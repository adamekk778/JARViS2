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
