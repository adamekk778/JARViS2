// 3.12 Návyky a zdraví on the phone: the day's ring up top, every habit a big tile for the thumb, a calendar of the
// month (all habits as a heat map, or one habit day by day), insights, the meals and the editor. Works without the PC
// too: ticks are kept on the phone and sent the moment the PC is back. A buzz on every tick, a little party at 100 %.
import { h, icon, loading, toast } from "../shared/dom";
import { editor, goalsView, habitTile, insights, meals, monthGrid, ring, weekPlanner, type HabitItem, type HabitSnap } from "../shared/habitsui";
import type { JarvisClient } from "../shared/ws";
import { gymView, type GymSnap } from "../shared/gymui";
import { healthConnect, healthOff, healthState, healthSupported, healthSync } from "./health";
import { native } from "./native";
import "./habits.css";

type Tab = "today" | "habits" | "tasks" | "gym" | "goals" | "insights" | "edit";
const CACHE = "jarvis.habits.snap", QUEUE = "jarvis.habits.queue";
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
  let gym: GymSnap | null = null;
  c.on("gym", (m) => {
    gym = m as unknown as GymSnap;
    const a = document.activeElement as HTMLElement | null;
    if (tab === "gym" && !(a && a.tagName === "INPUT" && a.closest(".gy") && !a.classList.contains("gy-ex"))) paint();
  });
  let tab: Tab = "today";
  let month = "";
  let week = 0;
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
  const proxy = { send, on: c.on.bind(c) } as unknown as JarvisClient;      // on: the meal photo answer
  const ask = () => { if (c.status === "open") c.send("habits_get", { month: month || undefined, week }); };
  /** tasks and goals change on the PC only (no waiting queue for them): say so when it is away */
  const online = () => ({ send: (t: string, m: any) => { native.haptic(); if (c.status === "open") c.send(t as any, m); else toast("Úkoly a cíle jdou změnit, když je PC připojené.", "info"); } }) as unknown as JarvisClient;
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
    const TITLE: Record<Tab, string> = { today: "Dnes", habits: "Návyky", tasks: "Tracker", gym: "Gym", goals: "Cíle", insights: "Přehled", edit: "Upravit" };
    const head = h("div", { class: "mhb-date" },
      h("h1", { class: "mhb-title" }, TITLE[tab]),
      h("span", { class: "hb-date-pill" }, `${d.getDate()}. ${MONTHS_OF[d.getMonth()]} ${d.getFullYear()}`),
      queue.length ? h("span", { class: "mhb-off" }, icon("cloud-slash"), ` ${queue.length} čeká na PC`) : c.status !== "open" ? h("span", { class: "mhb-off" }, icon("cloud-slash"), " offline") : "");
    if (tab !== "today") { top.replaceChildren(head); return; }
    top.replaceChildren(head,
      h("div", { class: "mhb-hero" }, ring(t.pct, 150, 12, "dnes", t.due ? `${t.done} z ${t.due}` : "volno"),
        h("div", { class: "mhb-chips" },
          h("div", {}, h("span", {}, "Týden"), h("strong", {}, s.week == null ? "–" : `${s.week}%`),
            s.delta == null ? "" : h("em", { class: s.delta >= 0 ? "up" : "down" }, `${s.delta >= 0 ? "▲" : "▼"} ${Math.abs(s.delta)}`)),
          h("div", {}, h("span", {}, "30 dní"), h("strong", {}, s.consistency == null ? "–" : `${s.consistency}%`)),
          h("div", {}, h("span", {}, "Série"), h("strong", {}, icon("fire", "ph-fill"), ` ${best ? best.streak : 0}`)))),
      h("p", { class: "mhb-msg" }, msg));
  }

  function paint() {
    seg.replaceChildren(...([["today", "Dnes"], ["habits", "Návyky"], ["tasks", "Úkoly"], ["gym", "Gym"], ["goals", "Cíle"], ["insights", "Přehled"]] as [Tab, string][]).map(([k, l]) =>
      h("button", { type: "button", role: "tab", class: tab === k ? "on" : "", "aria-selected": tab === k ? "true" : "false",
        onclick: () => { tab = k; native.haptic(); paint(); } }, l)),
      h("button", { type: "button", class: `mhb-gear${tab === "edit" ? " on" : ""}`, "aria-label": "Upravit návyky",
        onclick: () => { tab = tab === "edit" ? "today" : "edit"; native.haptic(); paint(); } }, icon("gear-six")));
    if (!snap) { top.replaceChildren(); body.replaceChildren(h("p", { class: "hb-empty" }, c.status === "open" ? "Načítám…" : "Připoj telefon k PC – návyky se načtou.")); return; }
    const s = snap;
    paintTop();
    if (tab === "today") {
      const order = (a: HabitItem, b: HabitItem) => Number(b.due) - Number(a.due) || Number(a.done) - Number(b.done);
      const due = s.items.filter((i) => i.due).sort(order), rest = s.items.filter((i) => !i.due);
      body.replaceChildren(
        h("div", { class: "mhb-list" }, ...due.map((it) => habitTile(proxy, it, true))),
        rest.length ? h("p", { class: "hbp-sub" }, "Dnes volno") : "", rest.length ? h("div", { class: "mhb-list" }, ...rest.map((it) => habitTile(proxy, it, true))) : "",
        meals(proxy, s), healthCard());
    } else if (tab === "habits") {
      body.replaceChildren(h("div", { class: "hb-card mhb-grid" }, monthGrid(proxy, s, (id) => { month = id; ask(); }),
        h("p", { class: "hbp-hint" }, "Posuň do strany pro celý měsíc. Ťukni na kroužek a opravíš den.")));
      requestAnimationFrame(() => {                                 // show today, not the 1st
        const g = body.querySelector(".hb-grid") as HTMLElement | null, t = body.querySelector(".hb-cell.today, .hb-cell.done:last-of-type") as HTMLElement | null;
        if (g && t) g.scrollLeft = Math.max(0, t.offsetLeft - g.clientWidth * 0.6);
      });
    } else if (tab === "tasks") {
      body.replaceChildren(s.plan ? weekPlanner(online(), s, (w) => { week = w; ask(); }) : loading());
      requestAnimationFrame(() => (body.querySelector(".hb-day.today") as HTMLElement | null)?.scrollIntoView({ inline: "center", block: "nearest" }));
    } else if (tab === "gym") {
      body.replaceChildren(c.status === "open" ? gymView(online(), gym) : h("p", { class: "hb-empty" }, "Gym deník jde, když je PC připojené."));
    } else if (tab === "goals") {
      body.replaceChildren(goalsView(online(), s));
    } else if (tab === "insights") {
      body.replaceChildren(insights(s));
    } else {
      body.replaceChildren(c.status === "open" ? editor(c, s) : h("p", { class: "hb-empty" }, "Upravovat návyky jde, když je PC připojené."));
    }
  }

  c.on("habits", (m) => {
    const s = m as unknown as HabitSnap;
    if ((month && s.month.id !== month) || (s.plan && s.plan.week !== week)) { ask(); return; }
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
    const typing = document.activeElement && body.contains(document.activeElement) && document.activeElement.tagName === "INPUT";
    if (!el.hidden && !((tab === "edit" || tab === "goals") && (body.querySelector(".hb-form") || typing))) paint();
  });
  paint();
  c.onStatus((st) => {                                               // (registered last: it calls paint() at once)
    if (st !== "open") { paint(); return; }
    for (const q of queue.splice(0)) c.send(q.type, q.msg);       // the PC is back: hand over what waited
    save(QUEUE, queue);
    ask();
  });
  // 3.12 spánek a kroky z telefonu (Health Connect)
  function healthCard(): HTMLElement | string {
    if (!healthSupported()) return "";
    const st = healthState();
    const msg = h("p", { class: "mhb-health-msg" });
    const connect = async () => {
      msg.textContent = "Otevírám Health Connect…";
      const err = await healthConnect().catch((e: any) => e?.message || "Nepovedlo se.");
      if (err) { msg.textContent = err; return; }
      await healthSync(c, true);
      paint();
    };
    return h("div", { class: "hb-card mhb-health" },
      h("div", { class: "mhb-health-h" }, icon("heartbeat", "ph-fill"), h("strong", {}, "Spánek, kroky a tep z hodinek")),
      st.on
        ? h("p", {}, `Propojeno ✓${st.steps != null ? ` · dnes ${st.steps.toLocaleString("cs-CZ")} kroků` : ""}${st.sleep != null ? ` · spánek ${String(st.sleep).replace(".", ",")} h` : ""}${st.rest_hr != null ? ` · klidový tep ${Math.round(st.rest_hr)}` : ""}. Zapisuje se samo.`)
        : h("p", {}, "Telefon sám zapíše, kolik jsi spal a nachodil, a z hodinek (Wear OS, Samsung, Garmin, Fitbit – přes Health Connect) i tep. Data jdou jen do tvého PC."),
      st.on && snap?.body?.text ? h("p", { class: `mhb-body lvl-${snap.body.level}` }, snap.body.text) : "",
      h("div", { class: "mhb-health-b" },
        st.on ? h("button", { type: "button", class: "btn", onclick: async () => { await healthSync(c, true); paint(); } }, icon("arrows-clockwise"), "Načíst teď") : "",
        st.on ? h("button", { type: "button", class: "btn ghost", onclick: () => { healthOff(); paint(); } }, "Odpojit")
          : h("button", { type: "button", class: "btn primary", onclick: connect }, icon("link"), "Propojit")),
      msg);
  }
  window.setInterval(() => { healthSync(c).catch(() => {}); }, 30 * 60 * 1000);
  return { el, show: () => { ask(); paint(); healthSync(c).catch(() => {}); } };
}
