// 3.12 Návyky a zdraví in the open notch: the day's ring, this week, and every habit as a tile you tick right here.
// One button opens the same thing over the whole screen (the main window, page Návyky).
import { h, icon } from "../shared/dom";
import { habitTile, ring, type HabitSnap } from "../shared/habitsui";
import type { JarvisClient } from "../shared/ws";

export function createHabitsView(client: JarvisClient, openFull: () => void) {
  let snap: HabitSnap | null = null;
  const left = h("div", { class: "nhb-left" });
  const tiles = h("div", { class: "nhb-tiles" });
  const el = h("div", { class: "nhb" }, left, tiles);
  const paint = () => {
    if (!snap) { tiles.replaceChildren(h("p", { class: "hb-empty" }, "Načítám…")); return; }
    const s = snap;
    const t = s.today;
    const delta = s.delta == null ? "" : `${s.delta >= 0 ? "+" : ""}${s.delta} % proti minulému týdnu`;
    left.replaceChildren(
      ring(t.pct, 118, 10, "dnes", t.due ? `${t.done} z ${t.due}` : "volno"),
      h("div", { class: "nhb-mini" },
        h("div", {}, h("span", {}, "Týden"), h("strong", {}, s.week == null ? "–" : `${s.week} %`)),
        h("div", {}, h("span", {}, "30 dní"), h("strong", {}, s.consistency == null ? "–" : `${s.consistency} %`))),
      delta ? h("em", { class: `nhb-delta ${s.delta! >= 0 ? "up" : "down"}` }, icon(s.delta! >= 0 ? "trend-up" : "trend-down"), ` ${delta}`) : "",
      h("button", { type: "button", class: "nhb-full", onclick: openFull }, icon("arrows-out-simple"), "Celá obrazovka"));
    const due = s.items.filter((i) => i.due), rest = s.items.filter((i) => !i.due);
    tiles.replaceChildren(...[...due, ...rest].map((it) => habitTile(client, it)),
      s.items.length ? "" : h("p", { class: "hb-empty" }, "Žádné návyky – přidej je na celé obrazovce."));
  };
  client.on("habits", (m) => { snap = m as unknown as HabitSnap; paint(); });
  paint();
  return { el, refresh: () => client.send("habits_get") };
}
