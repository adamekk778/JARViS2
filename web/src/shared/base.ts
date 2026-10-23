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
  root.dataset.theme = a.theme === "light" ? "light" : "dark";
  if (a.accent) root.style.setProperty("--accent", a.accent);
  root.dataset.motion = a.animations === "reduced" ? "reduced" : "full";
}
