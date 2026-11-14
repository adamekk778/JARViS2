// 3.12 Návyky a zdraví over the whole screen: Dnes (tick everything, the meals), Měsíc (the grid of circles),
// Přehled (consistency, the trend, this week, the leaderboard, streaks) and Upravit (your own habits).
import { hero, HEROES } from "../shared/hero";
import { h, icon } from "../shared/dom";
import { editor, habitTile, leaders, meals, monthGrid, ring, statCard, streaks, trendChart, type HabitSnap } from "../shared/habitsui";
import type { JarvisClient } from "../shared/ws";

type Tab = "today" | "month" | "insights" | "edit";
const TABS: [Tab, string, string][] = [["today", "sun-horizon", "Dnes"], ["month", "calendar-dots", "Měsíc"], ["insights", "chart-line-up", "Přehled"], ["edit", "sliders-horizontal", "Upravit"]];

export function buildHabits(client: JarvisClient) {
  let snap: HabitSnap | null = null;
  let tab: Tab = "today";
  let month = "";
  const body = h("div", { class: "hbp-body" });
  const tabs = h("div", { class: "hbp-tabs", role: "tablist" });
  const paintTabs = () => tabs.replaceChildren(...TABS.map(([k, ic, label]) => h("button", { type: "button", role: "tab", class: tab === k ? "on" : "",
    "aria-selected": tab === k ? "true" : "false", onclick: () => { tab = k; paintTabs(); paint(); } }, icon(ic), label)));
  const head = hero(HEROES.habits, "Návyky a zdraví", "Gym, jídlo, spánek, voda… – odškrtni, co jsi dnes udělal, a JARVIS spočítá, jak na tom jsi.");
  const el = h("section", { class: "page hbp", hidden: true }, head, tabs, body);

  function paint() {
    if (!snap) { body.replaceChildren(h("p", { class: "hb-empty" }, "Načítám…")); return; }
    const s = snap;
    if (tab === "today") {
      const t = s.today;
      const due = s.items.filter((i) => i.due), rest = s.items.filter((i) => !i.due);
      body.replaceChildren(h("div", { class: "hbp-today" },
        h("div", { class: "hb-card hbp-summary" },
          ring(t.pct, 168, 13, "dnes splněno", t.due ? `${t.done} z ${t.due}` : "dnes volno"),
          h("div", { class: "hbp-sum-stats" },
            statCard("Tento týden", s.week == null ? "–" : `${s.week} %`),
            statCard("Proti minulému", s.delta == null ? "–" : `${s.delta >= 0 ? "+" : ""}${s.delta} %`, undefined, s.delta == null ? "" : s.delta >= 0 ? "up" : "down"),
            statCard("30 dní", s.consistency == null ? "–" : `${s.consistency} %`))),
        h("div", { class: "hbp-list" }, ...due.map((it) => habitTile(client, it, true)),
          rest.length ? h("p", { class: "hbp-sub" }, "Dnes volno") : "", ...rest.map((it) => habitTile(client, it, true))),
        meals(client, s)));
    } else if (tab === "month") {
      body.replaceChildren(h("div", { class: "hb-card" }, monthGrid(client, s, (id) => { month = id; client.send("habits_get", { month }); }),
        h("p", { class: "hbp-hint" }, "Klikni na kroužek a opravíš den zpětně. Tečka = ten den návyk neplánuješ.")));
    } else if (tab === "insights") {
      body.replaceChildren(h("div", { class: "hbp-insights" },
        h("div", { class: "hb-card hbp-trend" },
          h("div", { class: "hbp-trend-head" }, h("div", {}, h("h3", {}, "Celková vytrvalost · 30 dní"), h("strong", { class: "hbp-big" }, s.consistency == null ? "–" : `${s.consistency} %`))),
          trendChart(s.trend)),
        h("div", { class: "hbp-cards" },
          statCard("Tento týden", s.week == null ? "–" : `${s.week} %`),
          statCard("Proti minulému týdnu", s.delta == null ? "–" : `${s.delta >= 0 ? "+" : ""}${s.delta} %`, undefined, s.delta == null ? "" : s.delta >= 0 ? "up" : "down"),
          statCard("Nejlepší série", s.streaks[0] ? `${s.streaks[0].streak}` : "0", s.streaks[0] ? h("em", {}, s.streaks[0].name) : "")),
        h("div", { class: "hbp-two" }, leaders(s), streaks(s))));
    } else {
      body.replaceChildren(editor(client, s));
    }
  }
  client.on("habits", (m) => {
    const s = m as unknown as HabitSnap;
    if (month && s.month.id !== month) {                             // a tick sent today's month: ask for the one shown
      client.send("habits_get", { month });
      return;
    }
    snap = s;
    if (!el.hidden) {
      if (tab === "edit" && body.querySelector(".hb-form")) {        // do not throw away a half-filled form
        const list = body.querySelector(".hb-edit-list");
        const fresh = editor(client, s).querySelector(".hb-edit-list");
        if (list && fresh) list.replaceWith(fresh);
        return;
      }
      paint();
    }
  });
  paintTabs();
  paint();
  return {
    el,
    show: () => { client.send("habits_get", month ? { month } : {}); paint(); },
  };
}
