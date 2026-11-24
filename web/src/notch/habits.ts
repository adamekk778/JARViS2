// 3.12 Návyky a zdraví in the open notch – today at a glance and one tap away: the day's ring on the left with what is
// left; on the right DNES with the date and the week's bars, then a card per habit in its own colour – its icon, how
// far it is today (a tap ticks it, − / + for sleep and water), its streak and this week as dots. One button opens the
// whole tracker.
import { h, icon, loading } from "../shared/dom";
import { ring, safeColor, type HabitItem, type HabitSnap } from "../shared/habitsui";
import type { JarvisClient } from "../shared/ws";

const WD = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"];
const WDL = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"];
const MON = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září", "října", "listopadu", "prosince"];
const num = (v: number) => String(Math.round(v * 10) / 10).replace(".", ",");

export function createHabitsView(client: JarvisClient, openFull: () => void) {
  let snap: HabitSnap | null = null;
  const left = h("div", { class: "nhb-left" });
  const right = h("div", { class: "nhb-right" });
  const el = h("div", { class: "nhb" }, left, right);

  const recount = (s: HabitSnap) => {
    const due = s.items.filter((x) => x.due), done = due.filter((x) => x.done).length;
    s.today = { done, due: due.length, pct: due.length ? Math.round((100 * done) / due.length) : null };
  };
  // the tap shows at once; the PC's answer (a new snapshot) follows a moment later
  const log = (it: HabitItem, value: number) => {
    client.send("habit_log", { id: it.id, value });
    if (!snap) return;
    it.value = value;
    it.done = it.kind === "amount" ? value >= it.target : value >= 1;
    if (it.hist && it.hist.length) it.hist[it.hist.length - 1] = it.due ? it.done : null;
    recount(snap);
    paint();
  };

  const weekDots = (s: HabitSnap, it: HabitItem) => {
    const hist = it.hist || [];
    return h("div", { class: "nhb-wk", "aria-hidden": "true" }, ...WD.map((w, j) => {
      const v = j > s.weekday ? undefined : hist[hist.length - 1 - (s.weekday - j)];
      const cls = j > s.weekday ? "future" : v === null || v === undefined ? "off" : v ? "on" : j === s.weekday ? "now" : "miss";
      return h("i", { class: cls, title: w });
    }));
  };

  const card = (s: HabitSnap, it: HabitItem) => {
    const amount = it.kind === "amount";
    const step = it.target >= 100 ? Math.round(it.target / 10) : it.unit === "h" ? 0.5 : 1;
    const p = amount ? Math.min(100, (100 * (it.value || 0)) / (it.target || 1)) : it.done ? 100 : 0;
    const sub = !it.due ? "dnes volno" : amount ? `${num(it.value || 0)} / ${num(it.target)} ${it.unit}`.trim() : it.done ? "splněno" : "ťukni, až to dáš";
    const streak = it.streak >= 2 ? h("span", { class: "nhb-fire" }, icon("fire", "ph-fill"), String(it.streak)) : "";
    let ctl: HTMLElement;
    if (amount) {
      const bar = h("span", { class: "nhb-bar" }, h("i", { style: { width: `${p}%` } }));
      ctl = h("div", { class: "nhb-amt" },
        h("button", { type: "button", class: "nhb-step", "aria-label": `Ubrat: ${it.name}`, onclick: (e: Event) => { e.stopPropagation(); log(it, Math.max(0, (it.value || 0) - step)); } }, icon("minus", "ph-bold")),
        bar,
        h("button", { type: "button", class: "nhb-step", "aria-label": `Přidat: ${it.name}`, onclick: (e: Event) => { e.stopPropagation(); log(it, (it.value || 0) + step); } }, icon("plus", "ph-bold")));
    } else {
      ctl = h("span", { class: "nhb-tick", "aria-hidden": "true" }, icon(it.done ? "check" : "plus", "ph-bold"));
    }
    const c = h("div", { class: `nhb-card${it.done ? " done" : ""}${it.due ? "" : " rest"}${amount ? " amount" : ""}`, style: { "--c": safeColor(it.color) },
      role: amount ? "group" : "button", tabindex: amount ? undefined : "0", "aria-pressed": amount ? undefined : String(!!it.done),
      "aria-label": `${it.name}: ${sub}` },
      h("div", { class: "nhb-top" },
        h("span", { class: "nhb-ic" }, icon(it.icon || "check-circle", "ph-fill")),
        h("div", { class: "nhb-tt" }, h("b", {}, it.name), h("span", {}, sub, streak)),
        amount ? "" : ctl),
      amount ? ctl : "",
      weekDots(s, it));
    if (!amount) {
      const toggle = () => { log(it, it.done ? 0 : 1); };
      c.addEventListener("click", toggle);
      c.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
    }
    return c;
  };

  const weekBars = (s: HabitSnap) => {
    const days = s.plan?.days;
    if (!days || days.length !== 7) return "";
    return h("div", { class: "nhb-days", "aria-label": "Tento týden" }, ...days.map((d, j) => {
      const v = d.habit_pct;
      return h("div", { class: `nhb-day${d.today ? " today" : ""}${d.future ? " future" : ""}`, title: `${WD[j]}: ${v == null ? "–" : `${v} %`}` },
        h("span", { class: "nhb-day-bar" }, h("i", { style: { height: `${d.future || v == null ? 0 : Math.max(6, v)}%` } })),
        h("em", {}, WD[j]));
    }));
  };

  function paint() {
    if (!snap) { right.replaceChildren(loading()); return; }
    const s = snap, t = s.today;
    const [, m, d] = s.date.split("-").map(Number);
    const left_ = t.due - t.done;
    const msg = !t.due ? "Dnes máš volno." : left_ === 0 ? "Všechno splněno 🔥" : t.done === 0 ? "Začni prvním návykem." : `Ještě ${left_} a máš hotovo.`;
    left.replaceChildren(
      h("div", { class: `nhb-ring${t.due && left_ === 0 ? " full" : ""}` }, ring(t.pct, 116, 11, "dnes", t.due ? `${t.done} z ${t.due}` : "volno")),
      h("p", { class: "nhb-msg" }, msg),
      h("div", { class: "nhb-mini" },
        h("div", {}, h("span", {}, "Týden"), h("strong", {}, s.week == null ? "–" : `${s.week} %`)),
        h("div", {}, h("span", {}, "Série"), h("strong", {}, icon("fire", "ph-fill"), String(s.streaks[0]?.streak || 0)))),
      h("button", { type: "button", class: "nhb-full", onclick: openFull }, icon("arrows-out-simple", "ph-bold"), "Celý tracker"));
    const order = (a: HabitItem, b: HabitItem) => Number(b.due) - Number(a.due);
    right.replaceChildren(
      h("div", { class: "nhb-head" },
        h("div", { class: "nhb-hl" }, h("h2", {}, "Dnes"), h("span", { class: "nhb-pill" }, `${WDL[s.weekday]} ${d}. ${MON[m - 1]}`)),
        weekBars(s)),
      s.items.length
        ? h("div", { class: "nhb-cards" }, ...[...s.items].sort(order).map((it) => card(s, it)))
        : h("p", { class: "hb-empty" }, "Žádné návyky – přidej si je v celém trackeru."));
  }
  client.on("habits", (m) => { snap = m as unknown as HabitSnap; paint(); });
  paint();
  return { el, refresh: () => client.send("habits_get") };
}
