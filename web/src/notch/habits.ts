// 3.12 Návyky a zdraví in the open notch – the tracker in small: the day's ring on the left; on the right NÁVYKY with the
// mint date pill and a row per habit (its colour dot, its name in heavy capitals) with a circle for every day of this
// week – mint with a tick = done; tap today (or a past day) to tick it. One button opens the whole tracker.
import { h, icon } from "../shared/dom";
import { ring, safeColor, type HabitItem, type HabitSnap } from "../shared/habitsui";
import type { JarvisClient } from "../shared/ws";

const WD = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"];
const MON = ["led", "úno", "bře", "dub", "kvě", "čvn", "čvc", "srp", "zář", "říj", "lis", "pro"];

export function createHabitsView(client: JarvisClient, openFull: () => void) {
  let snap: HabitSnap | null = null;
  const left = h("div", { class: "nhb-left" });
  const right = h("div", { class: "nhb-right" });
  const el = h("div", { class: "nhb" }, left, right);

  const dayOf = (s: HabitSnap, j: number) => {                   // j = 0..6 (Monday..Sunday of this week)
    const d = new Date(`${s.date}T12:00:00`);
    d.setDate(d.getDate() - s.weekday + j);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  const row = (s: HabitSnap, it: HabitItem) => {
    const hist = it.hist || [];
    const cells = WD.map((_, j) => {
      if (j > s.weekday) return h("span", { class: "nhb-c future" });
      const v = hist[hist.length - 1 - (s.weekday - j)];
      const isToday = j === s.weekday;
      const cls = v === null || v === undefined ? "off" : v ? "done" : isToday ? "today" : "miss";
      if (cls === "off") return h("span", { class: "nhb-c off" });
      return h("button", { type: "button", class: `nhb-c ${cls}`, "aria-label": `${it.name}, ${WD[j]}: ${v ? "splněno" : "nesplněno"}`,
        onclick: () => client.send("habit_log", { id: it.id, day: dayOf(s, j), value: v ? 0 : it.kind === "amount" ? it.target : 1 }) },
        v ? icon("check", "ph-bold") : "");
    });
    const amt = it.kind === "amount" ? h("em", {}, `${Math.round((it.value || 0) * 10) / 10}/${it.target}${it.unit === "h" ? " h" : ""}`) : "";
    return h("div", { class: "nhb-row", style: { "--c": safeColor(it.color) } as any },
      h("span", { class: "nhb-name" }, h("i", {}), h("b", {}, it.name), amt), ...cells);
  };
  const paint = () => {
    if (!snap) { right.replaceChildren(h("p", { class: "hb-empty" }, "Načítám…")); return; }
    const s = snap, t = s.today;
    const [y, m, d] = s.date.split("-").map(Number);
    left.replaceChildren(
      ring(t.pct, 112, 10, "dnes", t.due ? `${t.done} z ${t.due}` : "volno"),
      h("div", { class: "nhb-mini" },
        h("div", {}, h("span", {}, "Týden"), h("strong", {}, s.week == null ? "–" : `${s.week}%`)),
        h("div", {}, h("span", {}, "Série"), h("strong", {}, icon("fire", "ph-fill"), String(s.streaks[0]?.streak || 0)))),
      h("button", { type: "button", class: "nhb-full", onclick: openFull }, icon("arrows-out-simple"), "Celý tracker"));
    right.replaceChildren(
      h("div", { class: "nhb-head" }, h("h2", {}, "Návyky"), h("span", { class: "nhb-pill" }, `${d}. ${MON[m - 1]} ${y}`),
        h("span", { class: "grow" }), h("em", {}, s.delta == null ? "" : `${s.delta >= 0 ? "▲" : "▼"} ${Math.abs(s.delta)} % proti min. týdnu`)),
      h("div", { class: "nhb-row nhb-top" }, h("span", { class: "nhb-name nhb-col" }, "Návyk"),
        ...WD.map((w, j) => h("span", { class: `nhb-wd${j === s.weekday ? " now" : ""}` }, w))),
      h("div", { class: "nhb-rows" }, ...s.items.map((it) => row(s, it)),
        s.items.length ? "" : h("p", { class: "hb-empty" }, "Žádné návyky – přidej je v celém trackeru.")));
  };
  client.on("habits", (m) => { snap = m as unknown as HabitSnap; paint(); });
  paint();
  return { el, refresh: () => client.send("habits_get") };
}
