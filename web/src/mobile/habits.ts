// 3.12 Návyky a zdraví on the phone: the day's ring up top, every habit a big tile for the thumb, a calendar of the
// month (all habits as a heat map, or one habit day by day), insights, the meals and the editor. Works without the PC
// too: ticks are kept on the phone and sent the moment the PC is back. A buzz on every tick, a little party at 100 %.
import { h, icon, toast } from "../shared/dom";
import { editor, habitTile, leaders, meals, ring, safeColor, statCard, streaks, trendChart, type HabitItem, type HabitSnap } from "../shared/habitsui";
import type { JarvisClient } from "../shared/ws";
import { native } from "./native";
import "./habits.css";

type Tab = "today" | "month" | "insights" | "edit";
const CACHE = "jarvis.habits.snap", QUEUE = "jarvis.habits.queue";
const DAYS = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"];
const MONTHS = ["leden", "únor", "březen", "duben", "květen", "červen", "červenec", "srpen", "září", "říjen", "listopad", "prosinec"];
const WEEKDAY = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"];
const MONTHS_OF = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září", "října", "listopadu", "prosince"];

const load = <T,>(k: string, d: T): T => { try { return JSON.parse(localStorage.getItem(k) || "") ?? d; } catch { return d; } };
const save = (k: string, v: unknown) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* full or blocked */ } };

/** what the phone shows on its Domov tab: today's ring and how many are left – a tap opens the tab */
export function habitsGlance(c: JarvisClient, open: () => void): HTMLElement {
  const el = h("button", { type: "button", class: "mhb-glance", onclick: open, hidden: true });
  const paint = (s: HabitSnap | null) => {
    if (!s || !s.items.length) { el.hidden = true; return; }
    el.hidden = false;
    const t = s.today, left = s.items.filter((i) => i.due && !i.done);
    el.replaceChildren(ring(t.pct, 64, 7), h("div", {}, h("strong", {}, "Návyky dnes"),
      h("span", {}, left.length ? `Zbývá: ${left.slice(0, 3).map((i) => i.name).join(", ")}${left.length > 3 ? "…" : ""}` : t.due ? "Všechno splněno 🔥" : "Dnes volno")),
      icon("caret-right"));
  };
  paint(load<HabitSnap | null>(CACHE, null));
  c.on("habits", (m) => paint(m as unknown as HabitSnap));
  return el;
}

export function habitsView(c: JarvisClient): { el: HTMLElement; show: () => void } {
  let snap: HabitSnap | null = load<HabitSnap | null>(CACHE, null);
  let tab: Tab = "today";
  let month = "";
  let focus: number | "all" = "all";
  let celebrated = localStorage.getItem("jarvis.habits.party") || "";
  const queue: any[] = load<any[]>(QUEUE, []);

  // ticks go to the PC – or wait on the phone while it is away (and the screen already shows them)
  const send = (type: string, msg: any = {}) => {
    native.haptic();
    if (type === "habit_log" && snap) optimistic(msg);
    if (c.status === "open") { c.send(type as any, msg); return; }
    if (type === "habit_log" || type === "habit_meal") {
      queue.push({ type, msg: { ...msg, day: msg.day || snap?.date } });
      save(QUEUE, queue);
      paint();
    } else toast("Tohle jde změnit, jen když je PC připojené.", "info");
  };
  const proxy = { send } as unknown as JarvisClient;
  const optimistic = (m: any) => {
    const s = snap!;
    if (m.day && m.day !== s.date) return;
    const it = s.items.find((x) => x.id === m.id);
    if (!it || m.value == null) return;
    it.value = +m.value;
    it.done = it.kind === "amount" ? it.value >= it.target : it.value >= 1;
    it.last7[it.last7.length - 1] = it.due ? it.done : null;
    const due = s.items.filter((x) => x.due);
    s.today = { done: due.filter((x) => x.done).length, due: due.length, pct: due.length ? Math.round((100 * due.filter((x) => x.done).length) / due.length) : null };
    save(CACHE, s);
    paint();
  };

  const top = h("div", { class: "mhb-top" });
  const seg = h("div", { class: "mhb-seg", role: "tablist" });
  const body = h("div", { class: "mhb-body" });
  const el = h("section", { class: "m-view mhb", hidden: true }, top, seg, body);

  const party = () => {
    native.haptic();
    const burst = h("div", { class: "mhb-party", "aria-hidden": "true" },
      ...Array.from({ length: 26 }, (_, i) => h("i", { style: { "--a": `${(i / 26) * 360}deg`, "--d": `${70 + (i % 5) * 18}px`, "--h": `${(i * 47) % 360}` } as any })));
    top.append(burst);
    window.setTimeout(() => burst.remove(), 1400);
    toast("Den splněn na 100 % 🔥", "ok", 3500);
  };

  function paintTop() {
    const s = snap!;
    const d = new Date(`${s.date}T12:00:00`);
    const t = s.today;
    const best = s.streaks[0];
    const msg = t.due === 0 ? "Dnes nic naplánovaného – užij si volno." : t.done === t.due ? "Všechno splněno. Paráda!" :
      t.done === 0 ? "Začni prvním návykem – stačí ťuknout." : `Ještě ${t.due - t.done} a máš hotovo.`;
    top.replaceChildren(
      h("div", { class: "mhb-date" }, h("strong", {}, `${WEEKDAY[s.weekday]} ${d.getDate()}. ${MONTHS_OF[d.getMonth()]}`),
        queue.length ? h("span", { class: "mhb-off" }, icon("cloud-slash"), ` ${queue.length} čeká na PC`) : c.status !== "open" ? h("span", { class: "mhb-off" }, icon("cloud-slash"), " offline") : ""),
      h("div", { class: "mhb-hero" }, ring(t.pct, 150, 12, "dnes", t.due ? `${t.done} z ${t.due}` : "volno"),
        h("div", { class: "mhb-chips" },
          h("div", {}, h("span", {}, "Týden"), h("strong", {}, s.week == null ? "–" : `${s.week}%`),
            s.delta == null ? "" : h("em", { class: s.delta >= 0 ? "up" : "down" }, `${s.delta >= 0 ? "▲" : "▼"} ${Math.abs(s.delta)}`)),
          h("div", {}, h("span", {}, "30 dní"), h("strong", {}, s.consistency == null ? "–" : `${s.consistency}%`)),
          h("div", {}, h("span", {}, "Série"), h("strong", {}, icon("fire", "ph-fill"), ` ${best ? best.streak : 0}`)))),
      h("p", { class: "mhb-msg" }, msg));
  }

  /** the month as a calendar: all habits = how much of the day was done (a heat map), one habit = done / not */
  function calendar(s: HabitSnap): HTMLElement {
    const [y, m] = s.month.id.split("-").map(Number);
    const shift = (dlt: number) => { const dt = new Date(y, m - 1 + dlt, 1); month = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`; c.send("habits_get", { month }); };
    const chips = h("div", { class: "mhb-focus" },
      h("button", { type: "button", class: focus === "all" ? "on" : "", onclick: () => { focus = "all"; paint(); } }, "Vše"),
      ...s.items.map((it) => h("button", { type: "button", class: focus === it.id ? "on" : "", style: { "--c": safeColor(it.color) } as any,
        onclick: () => { focus = it.id; paint(); } }, icon(it.icon, "ph-fill"), it.name)));
    const cells: HTMLElement[] = [];
    for (let i = 0; i < s.month.first_weekday; i++) cells.push(h("span", { class: "mhb-cal-pad" }));
    for (let d = 0; d < s.month.days; d++) {
      const day = `${s.month.id}-${String(d + 1).padStart(2, "0")}`;
      if (focus === "all") {
        const states = s.month.grid.map((g) => g.cells[d]);
        const due = states.filter((x) => x === "done" || x === "miss" || x === "today").length;
        const done = states.filter((x) => x === "done").length;
        const future = states.every((x) => x === "future" || x === "off") && day > s.date;
        const p = due ? done / due : 0;
        const cell = h("span", { class: `mhb-cal-day${future ? " future" : ""}${day === s.date ? " today" : ""}`, title: due ? `${Math.round(p * 100)} %` : "" },
          h("b", {}, String(d + 1)));
        if (!future && due) cell.style.setProperty("--p", String(p));
        cells.push(cell);
      } else {
        const it = s.items.find((x) => x.id === focus)!;
        const g = s.month.grid.find((x) => x.id === focus);
        const st = g?.cells[d] || "future";
        const clickable = st === "done" || st === "miss" || st === "today";
        cells.push(h("button", { type: "button", class: `mhb-cal-day one ${st}`, disabled: !clickable, style: { "--c": safeColor(it.color) } as any,
          "aria-label": `${d + 1}. ${m}.: ${st === "done" ? "splněno" : st === "off" ? "volno" : "nesplněno"}`,
          onclick: () => send("habit_log", { id: it.id, day, value: st === "done" ? 0 : it.kind === "amount" ? it.target : 1 }) },
          h("b", {}, String(d + 1)), st === "done" ? icon("check", "ph-bold") : ""));
      }
    }
    return h("div", { class: "hb-card mhb-cal" },
      h("div", { class: "hb-month-head" },
        h("button", { type: "button", class: "hb-nav", "aria-label": "Předchozí měsíc", onclick: () => shift(-1) }, icon("caret-left")),
        h("strong", {}, `${MONTHS[m - 1]} ${y}`),
        h("button", { type: "button", class: "hb-nav", "aria-label": "Další měsíc", disabled: s.month.id >= s.date.slice(0, 7), onclick: () => shift(1) }, icon("caret-right"))),
      chips,
      h("div", { class: "mhb-cal-grid" }, ...DAYS.map((x) => h("span", { class: "mhb-cal-wd" }, x)), ...cells),
      h("p", { class: "hbp-hint" }, focus === "all" ? "Čím zelenější den, tím víc návyků jsi splnil. Vyber návyk nahoře a ťuknutím opravíš den zpětně." : "Ťukni na den a opravíš ho."));
  }

  function paint() {
    seg.replaceChildren(...([["today", "Dnes"], ["month", "Měsíc"], ["insights", "Přehled"], ["edit", "Upravit"]] as [Tab, string][]).map(([k, l]) =>
      h("button", { type: "button", role: "tab", class: tab === k ? "on" : "", "aria-selected": tab === k ? "true" : "false",
        onclick: () => { tab = k; native.haptic(); paint(); } }, l)));
    if (!snap) { top.replaceChildren(); body.replaceChildren(h("p", { class: "hb-empty" }, c.status === "open" ? "Načítám…" : "Připoj telefon k PC – návyky se načtou.")); return; }
    const s = snap;
    paintTop();
    if (tab === "today") {
      const order = (a: HabitItem, b: HabitItem) => Number(b.due) - Number(a.due) || Number(a.done) - Number(b.done);
      const due = s.items.filter((i) => i.due).sort(order), rest = s.items.filter((i) => !i.due);
      body.replaceChildren(
        h("div", { class: "mhb-list" }, ...due.map((it) => habitTile(proxy, it, true))),
        rest.length ? h("p", { class: "hbp-sub" }, "Dnes volno") : "", rest.length ? h("div", { class: "mhb-list" }, ...rest.map((it) => habitTile(proxy, it, true))) : "",
        meals(proxy, s));
    } else if (tab === "month") {
      body.replaceChildren(calendar(s));
    } else if (tab === "insights") {
      body.replaceChildren(
        h("div", { class: "hb-card hbp-trend" }, h("h3", {}, "Vytrvalost · 30 dní"), h("strong", { class: "hbp-big" }, s.consistency == null ? "–" : `${s.consistency} %`), trendChart(s.trend, 360, 140)),
        h("div", { class: "mhb-cards" },
          statCard("Tento týden", s.week == null ? "–" : `${s.week} %`),
          statCard("Proti minulému", s.delta == null ? "–" : `${s.delta >= 0 ? "+" : ""}${s.delta} %`, undefined, s.delta == null ? "" : s.delta >= 0 ? "up" : "down")),
        leaders(s), streaks(s));
    } else {
      body.replaceChildren(c.status === "open" ? editor(c, s) : h("p", { class: "hb-empty" }, "Upravovat návyky jde, když je PC připojené."));
    }
  }

  c.on("habits", (m) => {
    const s = m as unknown as HabitSnap;
    if (month && s.month.id !== month) { c.send("habits_get", { month }); return; }
    const before = snap?.today.pct;
    snap = s;
    save(CACHE, s);
    if (s.today.pct === 100 && before !== 100 && celebrated !== s.date && !el.hidden) {
      celebrated = s.date;
      localStorage.setItem("jarvis.habits.party", s.date);
      paint();
      party();
      return;
    }
    if (!el.hidden && !(tab === "edit" && body.querySelector(".hb-form"))) paint();
  });
  paint();
  c.onStatus((st) => {                                               // (registered last: it calls paint() at once)
    if (st !== "open") { paint(); return; }
    for (const q of queue.splice(0)) c.send(q.type, q.msg);       // the PC is back: hand over what waited
    save(QUEUE, queue);
    c.send("habits_get", month ? { month } : {});
  });
  return { el, show: () => { if (c.status === "open") c.send("habits_get", month ? { month } : {}); paint(); } };
}
