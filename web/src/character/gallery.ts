// Dev gallery: every mood side by side (used for screenshots / comparing with the reference picture).
import { applyAppearance } from "../shared/base";
import { Blob, MOOD_LABEL, MOODS, type CharacterColor } from "./blob";

applyAppearance({ appearance: { theme: "stark", accent: "#4f8dff" } });
const style = document.createElement("style");
style.textContent = `
body { background: radial-gradient(120% 80% at 50% 0%, #2b3a52 0%, #111821 45%, #07090c 100%); min-height: 100vh; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; padding: 24px; }
.card { position: relative; min-height: 230px; border-radius: 16px; background: linear-gradient(180deg, rgb(255 255 255 / .04), rgb(0 0 0 / .25)); border: 1px solid rgb(255 255 255 / .07); display: grid; justify-items: center; align-content: end; padding: 12px; overflow: hidden; }
.card .stage { flex: 1; display: grid; place-items: center; min-height: 150px; }
.card h3 { margin: 6px 0 0; font: 600 14px var(--font); letter-spacing: .04em; text-transform: uppercase; color: #e8edf3; }
.colors { display: flex; gap: 18px; justify-content: center; padding: 0 24px 24px; }
`;
document.head.append(style);
const grid = document.createElement("div");
grid.className = "grid";
const params = new URLSearchParams(location.search);
const only = params.get("mood");
MOODS.filter((m) => !only || m === only).forEach((m, i) => {
  const card = document.createElement("div");
  card.className = "card";
  const stage = document.createElement("div");
  stage.className = "stage";
  const b = new Blob({ size: Number(params.get("size")) || 110, trackCursor: false });
  ((window as any).__blobs ??= []).push(b);
  b.setMood(m, { badge: m === "notify" ? 3 : 0, progress: m === "working" ? 0.6 : null });
  if (m === "listening" || m === "speaking") setInterval(() => b.setLevel(0.08 + Math.random() * 0.12), 90);
  stage.append(b.el);
  const h = document.createElement("h3");
  h.textContent = `${i + 1}. ${MOOD_LABEL[m]}`;
  card.append(stage, h);
  grid.append(card);
});
const colors = document.createElement("div");
colors.className = "colors";
(["black", "midnight", "violet", "rose", "white", "blue", "orange", "green", "amber", "cyan"] as CharacterColor[]).forEach((c) => {
  const b = new Blob({ size: 80, color: c, trackCursor: false });
  b.setMood("personalize");
  colors.append(b.el);
});
document.getElementById("app")!.append(grid, colors);
