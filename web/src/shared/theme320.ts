// 3.20 (107) your own theme: colours, font, animation speed and roundness, saved in Nastavení → Vzhled → Moje témata.
// Only checked values are used (#rrggbb colours, a known font) – a theme cannot inject anything else.
const FONTS: Record<string, string> = {
  system: "system-ui, sans-serif", Inter: "Inter, system-ui, sans-serif", Rajdhani: "Rajdhani, system-ui, sans-serif",
  Orbitron: "Orbitron, system-ui, sans-serif", "JetBrains Mono": "'JetBrains Mono', ui-monospace, monospace", Georgia: "Georgia, serif",
};
const HEX = /^#[0-9a-fA-F]{6}$/;

export type CustomTheme = { name: string; accent?: string; bg?: string; text?: string; font?: string; speed?: number; radius?: number };

export function themeVars(t: CustomTheme | null | undefined): Record<string, string> {
  if (!t) return {};
  const v: Record<string, string> = {};
  if (t.accent && HEX.test(t.accent)) v["--accent"] = t.accent;
  if (t.bg && HEX.test(t.bg)) v["--x-theme-bg"] = t.bg;
  if (t.text && HEX.test(t.text)) v["--x-theme-text"] = t.text;
  if (t.font && FONTS[t.font]) v["--x-theme-font"] = FONTS[t.font];
  if (typeof t.speed === "number" && t.speed >= 0.25 && t.speed <= 2) v["--x-anim-speed"] = String(t.speed);
  if (typeof t.radius === "number" && t.radius >= 0 && t.radius <= 30) v["--x-radius"] = `${t.radius}px`;
  return v;
}

let applied: string[] = [];

export function applyCustomTheme(appearance: { custom_themes?: CustomTheme[]; active_theme?: string } | undefined): void {
  const root = document.documentElement;
  for (const k of applied) root.style.removeProperty(k);
  applied = [];
  const t = (appearance?.custom_themes || []).find((x) => x && x.name === appearance?.active_theme);
  const vars = themeVars(t);
  for (const [k, val] of Object.entries(vars)) { root.style.setProperty(k, val); applied.push(k); }
  root.classList.toggle("x-custom-theme", applied.length > 0);
}
