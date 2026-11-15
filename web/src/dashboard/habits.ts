// 3.12 Návyky a zdraví over the whole screen, laid out like the habit trackers people love: Dnes (tick everything,
// the meals), Návyky (the month grid with its trend line), Úkoly (the week planner), Cíle (goals) and Přehled
// (consistency, this week, the leaderboard, streaks); the gear opens Upravit (your own habits, the reminder).
import { hero, HEROES } from "../shared/hero";
import { h, icon } from "../shared/dom";
import { editor, goalsView, habitTile, insights, meals, monthGrid, ring, statCard, weekPlanner, type HabitSnap } from "../shared/habitsui";
import type { JarvisClient } from "../shared/ws";

type Tab = "today" | "habits" | "tasks" | "goals" | "insights" | "edit";
const TABS: [Tab, string, string][] = [["today", "house-simple", "Dnes"], ["habits", "grid-four", "Návyky"], ["tasks", "check-square", "Úkoly"],
  ["goals", "target", "Cíle"], ["insights", "chart-line-up", "Přehled"]];

export function buildHabits(client: JarvisClient) {
  let snap: HabitSnap | null = null;
  let tab: Tab = "today";
  let month = "";
  let week = 0;
  const body = h("div", { class: "hbp-body" });
  const tabs = h("div", { class: "hbp-tabs", role: "tablist" });
  const gear = h("button", { type: "button", class: "hbp-gear", title: "Upravit návyky", "aria-label": "Upravit návyky", onclick: () => go(tab === "edit" ? "today" : "edit") }, icon("gear-six"));
  const go = (t: Tab) => { tab = t; paintTabs(); paint(); };
  const paintTabs = () => {
    tabs.replaceChildren(...TABS.map(([k, ic, label]) => h("button", { type: "button", role: "tab", class: tab === k ? "on" : "",
      "aria-selected": tab === k ? "true" : "false", onclick: () => go(k) }, icon(ic), label)));
    gear.classList.toggle("on", tab === "edit");
  };
  const head = hero(HEROES.habits, "Návyky a zdraví", "Gym, jídlo, spánek, voda… – odškrtni, co jsi dnes udělal, a JARVIS spočítá, jak na tom jsi.");
  const el = h("section", { class: "page hbp", hidden: true }, head, h("div", { class: "hbp-tools" }, tabs, gear), body);
  const ask = () => client.send("habits_get", { month: month || undefined, week });

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
    } else if (tab === "habits") {
      body.replaceChildren(h("div", { class: "hb-card" }, monthGrid(client, s, (id) => { month = id; ask(); }),
        h("p", { class: "hbp-hint" }, "Klikni na kroužek a opravíš den zpětně. Tečka = ten den návyk neplánuješ.")));
    } else if (tab === "tasks") {
      body.replaceChildren(s.plan ? weekPlanner(client, s, (w) => { week = w; ask(); }) : h("p", { class: "hb-empty" }, "Načítám…"));
    } else if (tab === "goals") {
      body.replaceChildren(goalsView(client, s));
    } else if (tab === "insights") {
      body.replaceChildren(insights(s));
    } else {
      body.replaceChildren(editor(client, s));
    }
  }
  client.on("habits", (m) => {
    const s = m as unknown as HabitSnap;
    // a tick sent the default view (this month, this week): ask again for the one shown here
    if ((month && s.month.id !== month) || (s.plan && s.plan.week !== week)) { ask(); return; }
    snap = s;
    if (el.hidden) return;
    const typing = body.querySelector(".hb-form") || (document.activeElement && body.contains(document.activeElement) && document.activeElement.tagName === "INPUT");
    if (typing && (tab === "edit" || tab === "goals")) return;      // do not throw away a half-filled form
    if (typing && tab === "tasks") {                                // keep the field you type in focused
      const id = (document.activeElement as HTMLElement).getAttribute("aria-label");
      paint();
      if (id) (body.querySelector(`input[aria-label="${CSS.escape(id)}"]`) as HTMLInputElement | null)?.focus();
      return;
    }
    paint();
  });
  paintTabs();
  paint();
  return { el, show: () => { ask(); paint(); } };
}
