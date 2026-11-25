// 3.15 Živá tapeta (návrh 35): behind the desktop icons – the holographic reactor or the 3D globe turning slowly, with
// the time. It stops while anything runs full screen and on battery it stays still (the effects tier decides).
import "@fontsource-variable/orbitron";
import { applyAppearance } from "../shared/base";
import { h } from "../shared/dom";
import { at, onTier } from "../shared/motion";
import { JarvisClient, localEndpoint } from "../shared/ws";
import { mountGlobe, type Globe } from "../hud/globe3d";
import { mountReactor3d } from "../hud/reactor3d";
import "./style.css";

const client = new JarvisClient(localEndpoint(), "wallpaper", "PC");
const root = document.getElementById("wp")!;
const stage = h("div", { class: "wp-stage" });
const clock = h("div", { class: "wp-clock" });
const date = h("div", { class: "wp-date" });
const still = h("div", { class: "wp-still", "aria-hidden": "true" }, h("i", {}), h("i", {}), h("i", {}), h("b", {}));
root.append(still, stage, h("div", { class: "wp-time" }, clock, date));
const DAYS = ["neděle", "pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota"];
const tick = () => {
  const d = new Date();
  clock.textContent = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  date.textContent = `${DAYS[d.getDay()]} ${d.getDate()}. ${d.getMonth() + 1}.`.toUpperCase();
};
tick();
setInterval(tick, 15000);

let kind = new URLSearchParams(location.search).get("kind") || "reactor";
let off: (() => void) | null = null;
let globe: Globe | null = null;
let mood = "idle";
async function mount() {
  off?.(); off = null; globe?.dispose(); globe = null;
  stage.replaceChildren();
  root.dataset.kind = kind;
  if (!at("high")) { still.hidden = false; return; }           // on battery / a weak card: the still picture
  still.hidden = true;
  if (kind === "globe") {
    globe = await mountGlobe(stage);
    if (globe) { globe.update({ home: null, car: null, trips: [], planes: [] }); off = () => { globe?.dispose(); globe = null; }; }
  } else {
    off = await mountReactor3d(stage, () => ({ mood, level: 0 }));
  }
  if (!off) still.hidden = false;
}
onTier(() => { void mount(); });
client.on("welcome", (m) => {
  applyAppearance(m.settings);
  const k = m.settings?.appearance?.live_wallpaper;
  if (k && k !== "off" && k !== kind) { kind = k; void mount(); }
});
client.on("settings_changed", (m) => {
  applyAppearance(m.settings);
  const k = m.settings?.appearance?.live_wallpaper;
  if (k && k !== "off" && k !== kind) { kind = k; void mount(); }
});
client.on("mood", (m) => { mood = m.mood; });
// 3.20 (116) the day's three most important tasks on the wallpaper (your pinned tasks)
const tasksBox = document.createElement("ol");
tasksBox.className = "wp-tasks";
tasksBox.hidden = true;
root.append(tasksBox);
client.on("wallpaper_tasks" as any, (m: any) => {
  const items: string[] = Array.isArray(m.items) ? m.items.slice(0, 3).map((x: unknown) => String(x).slice(0, 80)) : [];
  tasksBox.replaceChildren(...items.map((t) => { const li = document.createElement("li"); li.textContent = t; return li; }));
  tasksBox.hidden = !items.length;
});
client.connect();
void mount();
