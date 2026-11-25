// 3.12 Návyky a zdraví – the pieces both the notch tab and the full screen use: the day's ring, a habit tile you tick,
// the month grid, the 30-day trend, the leaderboard and streaks, the meal log and the editor.
import { h, icon } from "./dom";
import type { JarvisClient } from "./ws";
import "./habits.css";

export interface HabitItem {
  id: number; name: string; icon: string; color: string; area: string; kind: "check" | "amount"; target: number; unit: string;
  days: string; value: number; note: string; due: boolean; done: boolean; streak: number; best: number; last7: (boolean | null)[];
  rate30: number | null; rate7?: number | null; rate90?: number | null; hist?: (boolean | null)[];
}
export interface PlanDay { day: string; weekday: number; tasks: { id: number; text: string; done: boolean }[]; mindset: string; future: boolean; today: boolean;
  task_pct: number | null; habit_pct: number | null; pct: number | null; energy?: number | null; focus?: number | null; motivation?: number | null }
export interface Goal { id: number; name: string; target: number; current: number; unit: string; deadline: string; color: string; pct: number; days_left: number | null }
export interface HabitSnap {
  date: string; weekday: number; items: HabitItem[]; today: { done: number; due: number; pct: number | null };
  week: number | null; last_week: number | null; delta: number | null; consistency: number | null;
  trend: { day: string; pct: number | null }[];
  month: { id: string; days: number; first_weekday: number; grid: { id: number; cells: string[] }[] };
  leaders: { id: number; name: string; color: string; rate: number }[];
  streaks: { id: number; name: string; color: string; streak: number }[];
  meals: { slot: string; label: string; text: string; kcal?: number | null; protein?: number | null }[];
  nutrition?: { kcal: number; protein: number; known: boolean };
  areas: Record<string, string>;
  remind?: string;
  wake?: string; bedtime?: string;
  plan?: { week: number; start: string; end: string; days: PlanDay[]; done: number; total: number; pct: number | null };
  goals?: Goal[];
  body?: BodyStatus | null;
}

/** 3.14 the watch's numbers and the morning verdict ("Stav systémů") */
export interface BodyStatus {
  day: string; level: "full" | "normal" | "easy" | "unknown"; text: string; reasons: string[];
  now: Partial<Record<"steps" | "sleep_h" | "rest_hr" | "hrv" | "hr" | "spo2", number | null>>;
  base: Partial<Record<"steps" | "sleep_h" | "rest_hr" | "hrv", number | null>>;
  yesterday: Partial<Record<"steps" | "sleep_h", number | null>>;
}

const LEVEL: Record<string, [string, string]> = { full: ["Plná síla", "battery-full"], normal: ["Běžný den", "battery-medium"],
  easy: ["Lehčí den", "battery-low"], unknown: ["Bez dat", "battery-empty"] };

/** 3.14 the "Stav systémů" card: last night, the heart against your normal, what it means for today */
export function bodyCard(b: BodyStatus | null | undefined): HTMLElement | string {
  if (!b || b.level === "unknown") return "";
  const [label, ic] = LEVEL[b.level] || LEVEL.unknown;
  const stat = (name: string, v: number | null | undefined, unit: string, base?: number | null) =>
    v == null ? "" : h("div", { class: "hb-body-stat" }, h("span", {}, name), h("strong", {}, `${num(v)}${unit}`),
      base ? h("small", {}, `obvykle ${num(base)}${unit}`) : "");
  return h("div", { class: `hb-card hb-body lvl-${b.level}`, role: "group", "aria-label": "Stav systémů" },
    h("div", { class: "hb-body-head" }, icon(ic, "ph-fill"), h("strong", {}, "Stav systémů"), h("span", { class: "hb-body-lvl" }, label)),
    h("div", { class: "hb-body-stats" },
      stat("Spánek", b.now.sleep_h, " h", b.base.sleep_h), stat("Klidový tep", b.now.rest_hr, "", b.base.rest_hr),
      stat("Variabilita", b.now.hrv, " ms", b.base.hrv), stat("Kyslík", b.now.spo2, " %")),
    h("p", { class: "hb-body-text" }, b.text.replace(/^Stav systémů:[^.]*\.\s*/, "")));
}

const DAY = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"];
const MONTHS = ["leden", "únor", "březen", "duben", "květen", "červen", "červenec", "srpen", "září", "říjen", "listopad", "prosinec"];
export const safeColor = (c: string) => (/^#[0-9a-f]{3,8}$/i.test(c || "") ? c : "#3ddc97");
const num = (v: number) => (Math.round(v * 10) / 10).toString().replace(".", ",");

/** the day's (or any) percentage as a glowing ring */
export function ring(pct: number | null, size = 120, stroke = 10, label = "", sub = ""): HTMLElement {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, p = Math.max(0, Math.min(100, pct ?? 0));
  const id = `hbg${Math.random().toString(36).slice(2, 8)}`;
  const el = h("div", { class: "hb-ring", style: { width: `${size}px`, height: `${size}px` } });
  el.innerHTML = `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" aria-hidden="true">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#a1a1aa"/></linearGradient></defs>
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="${stroke}"/>
    <circle class="hb-ring-arc" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="url(#${id})" stroke-width="${stroke}"
      stroke-linecap="round" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${(c * (1 - p / 100)).toFixed(1)}"
      transform="rotate(-90 ${size / 2} ${size / 2})"/></svg>`;
  el.append(h("div", { class: "hb-ring-in" }, h("strong", {}, pct == null ? "–" : `${pct}%`), label ? h("span", {}, label) : "", sub ? h("em", {}, sub) : ""));
  return el;
}

function dots(last7: (boolean | null)[]): HTMLElement {
  return h("span", { class: "hb-dots", "aria-hidden": "true" }, ...last7.map((d, i) =>
    h("i", { class: d === null ? "off" : d ? "on" : i === last7.length - 1 ? "now" : "miss" })));
}

/** one habit: tick it (or add to it), see the last week and the streak */
export function habitTile(client: JarvisClient, it: HabitItem, big = false): HTMLElement {
  const color = safeColor(it.color);
  const send = (value: number) => client.send("habit_log", { id: it.id, value });
  const amount = it.kind === "amount";
  const sub = !it.due ? "dnes volno" : amount ? `${num(it.value || 0)} / ${num(it.target)} ${it.unit}`.trim() : it.done ? "splněno" : "čeká";
  const streak = it.streak >= 2 ? h("span", { class: "hb-streak", title: `${it.streak} dní v řadě (rekord ${it.best})` }, icon("fire", "ph-fill"), String(it.streak)) : "";
  let action: HTMLElement;
  if (amount) {
    const step = it.target >= 100 ? Math.round(it.target / 10) : it.unit === "h" ? 0.5 : 1;
    const bar = h("span", { class: "hb-amt-bar" });
    bar.style.setProperty("--p", `${Math.min(100, (100 * (it.value || 0)) / (it.target || 1))}%`);
    action = h("div", { class: "hb-amt" },
      h("button", { type: "button", class: "hb-step", "aria-label": `Ubrat: ${it.name}`, onclick: (e: Event) => { e.stopPropagation(); send(Math.max(0, (it.value || 0) - step)); } }, icon("minus")),
      bar,
      h("button", { type: "button", class: "hb-step", "aria-label": `Přidat: ${it.name}`, onclick: (e: Event) => { e.stopPropagation(); send((it.value || 0) + step); } }, icon("plus")));
  } else {
    action = h("button", { type: "button", class: "hb-check", "aria-pressed": it.done ? "true" : "false", "aria-label": `${it.done ? "Zrušit" : "Splněno"}: ${it.name}`,
      onclick: (e: Event) => { e.stopPropagation(); send(it.done ? 0 : 1); } }, icon(it.done ? "check-circle" : "circle", it.done ? "ph-fill" : ""));
  }
  const tile = h("div", { class: `hb-tile${it.done ? " done" : ""}${it.due ? "" : " rest"}${big ? " big" : ""}`, style: { "--c": color } as any },
    h("span", { class: "hb-ico" }, icon(it.icon || "check-circle", "ph-fill")),
    h("div", { class: "hb-txt" }, h("strong", {}, it.name), h("span", {}, sub, streak)),
    dots(it.last7), action);
  if (!amount) tile.addEventListener("click", () => send(it.done ? 0 : 1));
  if (big && (it.area === "gym" || it.area === "jidlo" || it.note)) {      // what you trained / ate – not on every habit
    const note = h("input", { class: "hb-note", placeholder: it.area === "gym" ? "Co jsi cvičil? (nepovinné)" : "Poznámka (nepovinné)", value: it.note || "", maxlength: "300",
      "aria-label": `Poznámka: ${it.name}` }) as HTMLInputElement;
    note.addEventListener("click", (e) => e.stopPropagation());
    note.addEventListener("change", () => client.send("habit_log", { id: it.id, value: it.value || 0, note: note.value }));
    tile.append(note);
  }
  return tile;
}

let gridMode: "day" | "week" = "day";

/** the month (like the tracker): NÁVYKY, the month, the big mint DENNĚ / TÝDNĚ pill, a TREND line over the days,
 *  then a row per habit (its colour dot, its name in heavy capitals) and a circle per day – mint with a tick = done */
export function monthGrid(client: JarvisClient, s: HabitSnap, onMonth: (id: string) => void): HTMLElement {
  const [y, m] = s.month.id.split("-").map(Number);
  const root = h("div", { class: "hb-month" });
  const shift = (d: number) => { const dt = new Date(y, m - 1 + d, 1); onMonth(`${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`); };
  const paint = () => {
    const head = h("div", { class: "hb-month-head" },
      h("div", { class: "hb-month-title" }, h("h2", {}, "Návyky"), h("span", {}, `${MONTHS[m - 1]} ${y}`), h("em", {}, "Měsíční souhrn")),
      h("span", { class: "grow" }),
      h("button", { type: "button", class: "hb-nav", "aria-label": "Předchozí měsíc", onclick: () => shift(-1) }, icon("caret-left")),
      h("button", { type: "button", class: "hb-nav", "aria-label": "Další měsíc", onclick: () => shift(1), disabled: s.month.id >= s.date.slice(0, 7) }, icon("caret-right")));
    const pill = h("div", { class: "hb-mode" },
      h("button", { type: "button", class: gridMode === "day" ? "on" : "", onclick: () => { gridMode = "day"; paint(); } }, "Denně"),
      h("button", { type: "button", class: gridMode === "week" ? "on" : "", onclick: () => { gridMode = "week"; paint(); } }, "Týdně"));
    root.replaceChildren(head, pill, gridMode === "day" ? dayGrid() : weekGrid());
  };
  const days = Array.from({ length: s.month.days }, (_, i) => i + 1);
  const name = (it: HabitItem) => h("span", { class: "hb-grid-name" }, h("i", { class: "hb-pip" }), h("b", {}, it.name));
  function dayGrid(): HTMLElement {
    const cols = `minmax(170px, 1.4fr) repeat(${s.month.days}, minmax(0, 1fr))`;
    const top = h("div", { class: "hb-grid-row hb-grid-top", style: { gridTemplateColumns: cols } }, h("span", { class: "hb-col-head" }, "Návyk"),
      ...days.map((d) => h("span", { class: (s.month.first_weekday + d - 1) % 7 >= 5 ? "we" : "" }, String(d))));
    const pcts = days.map((_, i) => {
      const st = s.month.grid.map((g) => g.cells[i]);
      const due = st.filter((x) => x === "done" || x === "miss").length;
      return due ? st.filter((x) => x === "done").length / due : null;
    });
    const pts = pcts.map((p, i) => (p == null ? null : [i + 0.5, 34 - p * 30] as [number, number])).filter(Boolean) as [number, number][];
    const trendRow = h("div", { class: "hb-grid-row hb-grid-trend", style: { gridTemplateColumns: cols } },
      h("span", { class: "hb-grid-name trend" }, h("i", { class: "hb-pip", style: { "--c": "#f2f2f2" } as any }), "Trend"));
    const box = h("div", { class: "hb-trend-line" });
    box.innerHTML = `<svg viewBox="0 0 ${s.month.days} 38" preserveAspectRatio="none" aria-hidden="true">${pts.length > 1
      ? `<polyline points="${pts.map(([x, yy]) => `${x.toFixed(2)},${yy.toFixed(1)}`).join(" ")}" fill="none" stroke="#ffffff" stroke-width="1.8" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>` : ""}</svg>`;
    pts.forEach(([x, yy]) => box.append(h("i", { class: "hb-tdot", style: { left: `${(x / s.month.days) * 100}%`, top: `${(yy / 38) * 100}%` } })));
    trendRow.append(box);
    const rows = s.month.grid.map((g) => {
      const it = s.items.find((x) => x.id === g.id);
      if (!it) return null;
      return h("div", { class: "hb-grid-row", style: { gridTemplateColumns: cols, "--c": safeColor(it.color) } as any }, name(it),
        ...g.cells.map((c, i) => {
          const day = `${s.month.id}-${String(i + 1).padStart(2, "0")}`;
          const clickable = c === "done" || c === "miss" || c === "today";
          return h("button", { type: "button", class: `hb-cell ${c}`, disabled: !clickable, title: `${it.name} · ${i + 1}. ${m}.`,
            "aria-label": `${it.name}, ${i + 1}. ${m}.: ${c === "done" ? "splněno" : c === "off" ? "volno" : c === "future" ? "ještě nebylo" : "nesplněno"}`,
            onclick: () => client.send("habit_log", { id: it.id, day, value: c === "done" ? 0 : it.kind === "amount" ? it.target : 1 }) },
          c === "done" ? icon("check", "ph-bold") : "");
        }));
    });
    return h("div", { class: "hb-grid" }, trendRow, top, ...rows.filter(Boolean) as HTMLElement[]);
  }
  function weekGrid(): HTMLElement {
    // the month's weeks: how much of each week a habit held (a ring fills up)
    const weeks: number[][] = [];
    days.forEach((d) => {
      const w = Math.floor((s.month.first_weekday + d - 1) / 7);
      (weeks[w] ||= []).push(d - 1);
    });
    const cols = `minmax(170px, 1.4fr) repeat(${weeks.length}, minmax(0, 1fr))`;
    const top = h("div", { class: "hb-grid-row hb-grid-top", style: { gridTemplateColumns: cols } }, h("span", { class: "hb-col-head" }, "Návyk"),
      ...weeks.map((w) => h("span", {}, `${w[0] + 1}.–${w[w.length - 1] + 1}.`)));
    const rows = s.month.grid.map((g) => {
      const it = s.items.find((x) => x.id === g.id);
      if (!it) return null;
      return h("div", { class: "hb-grid-row", style: { gridTemplateColumns: cols, "--c": safeColor(it.color) } as any }, name(it),
        ...weeks.map((w) => {
          const st = w.map((i) => g.cells[i]);
          const due = st.filter((x) => x === "done" || x === "miss" || x === "today").length;
          const done = st.filter((x) => x === "done").length;
          const el = h("span", { class: `hb-wcell${due ? "" : " off"}` }, due ? `${done}/${due}` : "–");
          el.style.setProperty("--p", String(due ? done / due : 0));
          return el;
        }));
    });
    return h("div", { class: "hb-grid weeks" }, top, ...rows.filter(Boolean) as HTMLElement[]);
  }
  paint();
  return root;
}

/** a soft, smooth glowing area (a rolling average, so it reads as a trend and not as noise) */
export function trendChart(trend: HabitSnap["trend"], w = 640, hgt = 170, smooth = 5): HTMLElement {
  const vals = trend.map((_, i) => {
    const win = trend.slice(Math.max(0, i - smooth + 1), i + 1).filter((x) => x.pct != null);
    return win.length ? win.reduce((a, x) => a + (x.pct || 0), 0) / win.length : null;
  });
  const pts = vals.map((v, i) => [i / Math.max(1, trend.length - 1) * w, v == null ? null : hgt - 12 - (v / 100) * (hgt - 28)] as [number, number | null]);
  const known = pts.filter((p) => p[1] != null) as [number, number][];
  const el = h("div", { class: "hb-trend" });
  if (known.length < 2) { el.append(h("p", { class: "hb-empty" }, "Graf se ukáže po pár dnech odškrtávání.")); return el; }
  let d = `M${known[0][0].toFixed(1)},${known[0][1].toFixed(1)}`;
  for (let i = 1; i < known.length; i++) {                         // Catmull-Rom through the points → soft curves
    const p0 = known[i - 2] || known[i - 1], p1 = known[i - 1], p2 = known[i], p3 = known[i + 1] || p2;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  const area = `${d} L${known[known.length - 1][0].toFixed(1)},${hgt} L${known[0][0].toFixed(1)},${hgt} Z`;
  const step = Math.max(1, Math.round((trend.length - 1) / 5));
  const idx = Array.from(new Set([0, ...Array.from({ length: 5 }, (_, k) => k * step), trend.length - 1])).filter((i) => i < trend.length);
  const labels = idx.map((i) => {
    const [, mm, dd] = trend[i].day.split("-");
    return `<text x="${(i / (trend.length - 1) * w).toFixed(0)}" y="${hgt + 16}" text-anchor="${i === 0 ? "start" : i === trend.length - 1 ? "end" : "middle"}">${+dd}. ${+mm}.</text>`;
  }).join("");
  el.innerHTML = `<svg viewBox="0 -4 ${w} ${hgt + 24}" preserveAspectRatio="none" aria-label="Vývoj" role="img">
    <defs><linearGradient id="hbtr" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f2f2f2" stop-opacity=".55"/><stop offset="1" stop-color="#f2f2f2" stop-opacity="0"/></linearGradient></defs>
    <path d="${area}" fill="url(#hbtr)"/><path d="${d}" fill="none" stroke="#7af5cc" stroke-width="2.6" stroke-linecap="round"/>${labels}</svg>`;
  return el;
}

export function statCard(label: string, value: string, extra?: HTMLElement | string, cls = ""): HTMLElement {
  return h("div", { class: `hb-stat ${cls}` }, h("span", {}, label), h("strong", {}, value), extra || "");
}

export function leaders(s: HabitSnap): HTMLElement {
  return h("div", { class: "hb-card hb-leaders" }, h("h3", {}, "Žebříček návyků · 30 dní"),
    ...(s.leaders.length ? s.leaders.map((l, i) => {
      const row = h("div", { class: "hb-lead", style: { "--c": safeColor(l.color) } as any },
        h("span", { class: "hb-medal" }, ["🥇", "🥈", "🥉"][i] || String(i + 1)), h("span", { class: "hb-lead-name" }, l.name),
        h("span", { class: "hb-lead-bar" }, h("i", { style: { width: `${l.rate}%` } })), h("em", {}, `${l.rate}%`));
      return row;
    }) : [h("p", { class: "hb-empty" }, "Zatím málo dat.")]));
}

export function streaks(s: HabitSnap): HTMLElement {
  return h("div", { class: "hb-card hb-streaks" }, h("h3", {}, "Nejdelší série"),
    ...(s.streaks.length ? s.streaks.map((x) => h("div", { class: "hb-srow", style: { "--c": safeColor(x.color) } as any },
      h("span", {}, x.name), h("strong", {}, icon("fire", "ph-fill"), ` ${x.streak} ${x.streak === 1 ? "den" : x.streak < 5 ? "dny" : "dní"}`)))
      : [h("p", { class: "hb-empty" }, "Odškrtni návyk dva dny po sobě a začne série.")]));
}

/** today's meals – typed in, saved when you leave the field */
/** a photo shrunk to at most 1024 px (JPEG) – enough for the AI, small enough to send from the phone */
function shrink(file: File): Promise<string> {
  return new Promise((ok, bad) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, 1024 / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      ok(c.toDataURL("image/jpeg", 0.82));
    };
    img.onerror = () => { URL.revokeObjectURL(url); bad(new Error("Tohle není obrázek.")); };
    img.src = url;
  });
}

let mealStatus = "";
export function meals(client: JarvisClient, s: HabitSnap): HTMLElement {
  const status = h("p", { class: "hb-meal-status" }, mealStatus);
  const file = h("input", { type: "file", accept: "image/*", capture: "environment", hidden: true }) as HTMLInputElement;
  file.addEventListener("change", async () => {
    const f = file.files?.[0];
    if (!f) return;
    mealStatus = "Prohlížím fotku…";
    status.textContent = mealStatus;
    try {
      client.send("habit_meal_photo", { image: await shrink(f) });
    } catch (e: any) { mealStatus = e.message; status.textContent = mealStatus; }
    file.value = "";
  });
  const off = client.on("habit_meal_result", (m: any) => {
    mealStatus = m.ok ? `${m.label}: ${m.food}${m.kcal ? ` · ~${m.kcal} kcal` : ""}${m.protein ? ` · ${m.protein} g bílkovin` : ""}` : m.message || "Nepovedlo se.";
    if (status.isConnected) status.textContent = mealStatus; else off?.();
  });
  const n = s.nutrition;
  return h("div", { class: "hb-card hb-meals" },
    h("div", { class: "hb-meals-h" }, h("h3", {}, icon("bowl-food", "ph-fill"), " Jídelníček · dnes"),
      h("button", { type: "button", class: "hb-photo", onclick: () => file.click(), title: "Vyfoť jídlo – AI odhadne kalorie a bílkoviny" },
        icon("camera", "ph-fill"), "Z fotky"), file),
    ...s.meals.map((m) => {
      const inp = h("input", { class: "hb-meal-in", value: m.text, placeholder: "Co jsi jedl?", maxlength: "200", "aria-label": m.label }) as HTMLInputElement;
      inp.addEventListener("change", () => client.send("habit_meal", { slot: m.slot, text: inp.value }));
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") inp.blur(); });
      return h("label", { class: `hb-meal${m.text ? " has" : ""}` }, h("span", {}, m.label), inp,
        m.kcal ? h("em", { class: "hb-kcal" }, `~${m.kcal} kcal`) : "");
    }),
    n?.known ? h("div", { class: "hb-nutri" }, h("span", {}, "Dnes celkem"), h("strong", {}, `~${n.kcal} kcal`), h("strong", {}, `${n.protein} g bílkovin`)) : "",
    status);
}

const ICONS = ["barbell", "person-simple-run", "moon-stars", "drop", "bowl-food", "cookie", "flower-lotus", "book-open", "heartbeat",
  "pill", "sun-horizon", "brain", "bicycle", "swimming-pool", "coffee", "prohibit", "tooth", "pencil-simple-line", "phone-slash", "check-circle"];
const COLORS = ["#3ddc97", "#4cc9f0", "#8b9cff", "#c77dff", "#ff6b6b", "#ffb84d", "#f472b6", "#a3e635"];

/** add / change / remove habits */
export function editor(client: JarvisClient, s: HabitSnap): HTMLElement {
  const box = h("div", { class: "hb-edit" });
  const form = (it?: HabitItem) => {
    const st = { name: it?.name || "", icon: it?.icon || "check-circle", color: safeColor(it?.color || COLORS[0]), kind: it?.kind || "check",
      target: it?.target || 1, unit: it?.unit || "", days: it?.days || "0123456", area: it?.area || "jine" };
    const f = h("div", { class: "hb-form hb-card" });
    const paint = () => {
      const name = h("input", { class: "input", value: st.name, placeholder: "Název (třeba Čtení 10 stran)", maxlength: "40", "aria-label": "Název návyku" }) as HTMLInputElement;
      name.oninput = () => (st.name = name.value);
      const kinds = h("div", { class: "hb-seg" }, ...([["check", "Splněno / ne"], ["amount", "Množství"]] as const).map(([k, l]) =>
        h("button", { type: "button", class: st.kind === k ? "on" : "", onclick: () => { st.kind = k; paint(); } }, l)));
      const target = h("input", { class: "input hb-num", type: "number", min: "0.5", step: "0.5", value: String(st.target), "aria-label": "Cíl" }) as HTMLInputElement;
      target.oninput = () => (st.target = parseFloat(target.value) || 1);
      const unit = h("input", { class: "input hb-unit", value: st.unit, placeholder: "jednotka (h, sklenic, kroků)", maxlength: "16", "aria-label": "Jednotka" }) as HTMLInputElement;
      unit.oninput = () => (st.unit = unit.value);
      const days = h("div", { class: "hb-days" }, ...DAY.map((d, i) => h("button", { type: "button", class: st.days.includes(String(i)) ? "on" : "",
        "aria-pressed": st.days.includes(String(i)) ? "true" : "false",
        onclick: () => { st.days = st.days.includes(String(i)) ? st.days.replace(String(i), "") : st.days + i; if (!st.days) st.days = String(i); paint(); } }, d)));
      const areas = h("select", { class: "input", "aria-label": "Oblast" }, ...Object.entries(s.areas).map(([k, l]) => h("option", { value: k, selected: k === st.area }, l))) as HTMLSelectElement;
      areas.onchange = () => (st.area = areas.value);
      const icons = h("div", { class: "hb-icons" }, ...ICONS.map((ic) => h("button", { type: "button", class: st.icon === ic ? "on" : "", "aria-label": ic,
        onclick: () => { st.icon = ic; paint(); } }, icon(ic, "ph-fill"))));
      const colors = h("div", { class: "hb-colors" }, ...COLORS.map((c) => h("button", { type: "button", class: st.color === c ? "on" : "", style: { background: c }, "aria-label": `Barva ${c}`,
        onclick: () => { st.color = c; paint(); } })));
      f.replaceChildren(
        h("h3", {}, it ? `Upravit: ${it.name}` : "Nový návyk"), name, kinds,
        st.kind === "amount" ? h("div", { class: "hb-row" }, h("span", {}, "Cíl za den"), target, unit) : "",
        h("div", { class: "hb-row" }, h("span", {}, "Které dny"), days),
        h("div", { class: "hb-row" }, h("span", {}, "Oblast"), areas),
        icons, colors,
        h("div", { class: "hb-row end" },
          it ? h("button", { type: "button", class: "btn danger", onclick: () => { if (confirm(`Přestat sledovat „${it.name}“? Historie zůstane.`)) { client.send("habit_delete", { id: it.id }); f.remove(); } } }, icon("trash"), "Odebrat") : "",
          h("span", { class: "grow" }),
          h("button", { type: "button", class: "btn", onclick: () => f.remove() }, "Zrušit"),
          h("button", { type: "button", class: "btn primary", onclick: () => {
            if (!st.name.trim()) { name.focus(); return; }
            client.send("habit_save", { habit: { ...st, id: it?.id } });
            f.remove();
          } }, icon("check"), "Uložit")));
      name.focus();
    };
    paint();
    return f;
  };
  const list = h("div", { class: "hb-edit-list" }, ...s.items.map((it) => h("button", { type: "button", class: "hb-edit-item", style: { "--c": safeColor(it.color) } as any,
    onclick: () => { box.querySelector(".hb-form")?.remove(); list.after(form(it)); } },
    h("span", { class: "hb-ico" }, icon(it.icon, "ph-fill")), h("strong", {}, it.name),
    h("span", {}, it.kind === "amount" ? `cíl ${num(it.target)} ${it.unit}` : "splněno / ne", " · ", it.days.length === 7 ? "každý den" : it.days.split("").map((d) => DAY[+d]).join(" ")),
    icon("pencil-simple"))));
  // the evening reminder ("what is still left today") – on the PC and on the phone
  const on = !!s.remind;
  const time = h("input", { class: "input hb-time", type: "time", value: s.remind || "20:30", disabled: !on, "aria-label": "Čas připomínky" }) as HTMLInputElement;
  time.onchange = () => client.send("habit_remind_set", { time: time.value });
  const sw = h("button", { type: "button", class: `hb-switch${on ? " on" : ""}`, role: "switch", "aria-checked": on ? "true" : "false", "aria-label": "Večerní připomínka",
    onclick: () => client.send("habit_remind_set", { time: on ? "" : time.value || "20:30" }) }, h("i"));
  box.append(h("div", { class: "hb-card hb-remind" }, icon("bell-ringing", "ph-fill"),
    h("div", {}, h("strong", {}, "Večerní připomínka"), h("span", {}, on ? `V ${s.remind} ti připomenu, co ještě zbývá (PC i telefon).` : "Vypnutá.")), time, sw));
  // 3.12 bedtime: from when you get up and your sleep goal, a nudge 30 minutes before
  const wakeOn = !!s.wake;
  const wake = h("input", { class: "input hb-time", type: "time", value: s.wake || "07:00", disabled: !wakeOn, "aria-label": "Kdy vstávám" }) as HTMLInputElement;
  wake.onchange = () => client.send("habit_remind_set", { wake: wake.value });
  const wsw = h("button", { type: "button", class: `hb-switch${wakeOn ? " on" : ""}`, role: "switch", "aria-checked": wakeOn ? "true" : "false", "aria-label": "Připomínka spánku",
    onclick: () => client.send("habit_remind_set", { wake: wakeOn ? "" : wake.value || "07:00" }) }, h("i"));
  box.append(h("div", { class: "hb-card hb-remind" }, icon("moon-stars", "ph-fill"),
    h("div", {}, h("strong", {}, "Připomínka spánku"), h("span", {}, wakeOn
      ? (s.bedtime ? `Vstáváš v ${s.wake} → do postele v ${s.bedtime}. Půl hodiny předtím ti dám vědět.` : "Přidej si návyk Spánek s počtem hodin.")
      : "Vypnutá.")), wake, wsw));
  box.append(list, h("button", { type: "button", class: "btn primary hb-add", onclick: () => { box.querySelector(".hb-form")?.remove(); list.after(form()); } }, icon("plus"), "Přidat návyk"));
  return box;
}


const WD = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"];
const WD3 = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"];

const MOOD: [keyof PlanDay & ("energy" | "focus" | "motivation"), string, string][] = [["energy", "Energie", "#ffb84d"], ["focus", "Soustředění", "#4cc9f0"], ["motivation", "Motivace", "#f472b6"]];

/** Úkoly (the tracker's week): CELKOVÝ POKROK – a bar per day, the week's ring "x / y splněno" and the MINDSET TRACKER
 *  (energy, focus, motivation as lines) – then a card per day: its date, its ring, its tasks and its mindset */
export function weekPlanner(client: JarvisClient, s: HabitSnap, onWeek: (w: number) => void): HTMLElement {
  const p = s.plan!;
  const dmy = (d: string) => { const [yy, mm, dd] = d.split("-"); return `${dd}/${mm}/${yy}`; };
  const bars = h("div", { class: "hb-bars-row" }, ...p.days.map((d) => {
    const v = d.pct ?? 0;
    return h("div", { class: `hb-bar${d.today ? " today" : ""}${d.future ? " future" : ""}` },
      h("em", {}, d.pct == null ? "" : `${d.pct}%`), h("i", { style: { height: `${Math.max(6, v)}%` } }), h("span", {}, WD3[d.weekday]));
  }));
  // the mindset tracker: three soft lines over the week
  const mt = h("div", { class: "hb-mt" });
  const W = 300, H = 110;
  const lines = MOOD.map(([k, , c]) => {
    const pts = p.days.map((d, i) => (d[k] ? [i / 6 * W, H - 8 - ((d[k] as number) - 1) / 4 * (H - 16)] : null)).filter(Boolean) as number[][];
    if (!pts.length) return "";
    const path = pts.map((q, i) => `${i ? "L" : "M"}${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" ");
    return `<path d="${path}" fill="none" stroke="${c}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>` +
      pts.map((q) => `<circle cx="${q[0].toFixed(1)}" cy="${q[1].toFixed(1)}" r="3.2" fill="${c}"/>`).join("");
  }).join("");
  mt.innerHTML = `<svg viewBox="-6 -6 ${W + 12} ${H + 12}" aria-label="Mindset tracker" role="img">
    ${[0, 1, 2, 3].map((i) => `<line x1="0" x2="${W}" y1="${8 + i * (H - 16) / 3}" y2="${8 + i * (H - 16) / 3}" stroke="rgba(255,255,255,.06)"/>`).join("")}${lines ||
    `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" fill="rgba(255,255,255,.4)" font-size="12">Ohodnoť den v kartě dne níž</text>`}</svg>`;
  const overall = h("div", { class: "hb-card hb-overall" },
    h("div", { class: "hb-ov-bars" },
      h("div", { class: "hb-bars-head" }, h("h3", {}, "Celkový pokrok"), h("span", { class: "grow" }),
        h("button", { type: "button", class: "hb-nav", "aria-label": "Předchozí týden", onclick: () => onWeek(p.week - 1) }, icon("caret-left")),
        h("span", { class: "hb-week-label" }, p.week === 0 ? "Tento týden" : p.week === -1 ? "Minulý týden" : p.week === 1 ? "Příští týden" : `${dmy(p.start).slice(0, 5)} – ${dmy(p.end).slice(0, 5)}`),
        h("button", { type: "button", class: "hb-nav", "aria-label": "Další týden", onclick: () => onWeek(p.week + 1) }, icon("caret-right"))),
      bars),
    h("div", { class: "hb-ov-ring" }, ring(p.pct, 128, 11), h("span", {}, `${p.done} / ${p.total} splněno`)),
    h("div", { class: "hb-ov-mind" }, h("h3", {}, "Mindset tracker"),
      h("div", { class: "hb-legend" }, ...MOOD.map(([, label, c]) => h("span", {}, h("i", { style: { background: c } }), label))), mt));
  const cards = h("div", { class: "hb-days" }, ...p.days.map((d) => {
    const add = h("input", { class: "hb-task-add", placeholder: "+ Přidat úkol", maxlength: "160", "aria-label": `Nový úkol na ${WD[d.weekday]}` }) as HTMLInputElement;
    add.addEventListener("keydown", (e) => { if (e.key === "Enter" && add.value.trim()) { client.send("habit_task", { action: "add", day: d.day, text: add.value }); add.value = ""; } });
    const mind = h("input", { class: "hb-mind", placeholder: "Myšlenka dne…", value: d.mindset, maxlength: "200", "aria-label": `Mindset ${WD[d.weekday]}` }) as HTMLInputElement;
    mind.addEventListener("change", () => client.send("habit_mindset", { day: d.day, text: mind.value }));
    const rates = h("div", { class: "hb-rates" }, ...MOOD.map(([k, label, c]) => h("div", { class: "hb-rate", style: { "--c": c } as any },
      h("span", {}, label),
      h("div", {}, ...[1, 2, 3, 4, 5].map((v) => h("button", { type: "button", class: (d[k] || 0) >= v ? "on" : "", disabled: d.future,
        "aria-label": `${label} ${v} z 5`, onclick: () => client.send("habit_mindset", { day: d.day, [k]: d[k] === v ? 0 : v }) }))))));
    const done = d.tasks.filter((t) => t.done).length;
    return h("div", { class: `hb-day${d.today ? " today" : ""}` },
      h("div", { class: "hb-day-head" }, h("strong", {}, WD[d.weekday]), h("span", {}, dmy(d.day))),
      ring(d.pct, 96, 8),
      h("h4", {}, "Úkoly"),
      h("div", { class: "hb-tasks" }, ...d.tasks.map((t) => h("div", { class: `hb-task${t.done ? " done" : ""}` },
        h("button", { type: "button", class: "hb-box", "aria-pressed": t.done ? "true" : "false", "aria-label": `${t.done ? "Zrušit" : "Hotovo"}: ${t.text}`,
          onclick: () => client.send("habit_task", { id: t.id, done: !t.done }) }, t.done ? icon("check", "ph-bold") : ""),
        h("span", {}, t.text),
        h("button", { type: "button", class: "hb-x", "aria-label": `Smazat: ${t.text}`, onclick: () => client.send("habit_task", { action: "delete", id: t.id }) }, icon("x")))),
        add),
      h("h4", {}, "Mindset"), rates, mind,
      h("p", { class: "hb-day-foot" }, d.tasks.length ? `${done} hotovo · ${d.tasks.length - done} zbývá` : "Žádné úkoly"));
  }));
  return h("div", { class: "hb-plan" }, overall, cards);
}

/** Cíle: something bigger (50 km this month, −5 kg, 12 books) with a glowing bar */
export function goalsView(client: JarvisClient, s: HabitSnap): HTMLElement {
  const list = s.goals || [];
  const form = (g?: Goal) => {
    const st = { name: g?.name || "", target: g?.target || 10, current: g?.current || 0, unit: g?.unit || "", deadline: g?.deadline || "", color: safeColor(g?.color || COLORS[0]) };
    const name = h("input", { class: "input", value: st.name, placeholder: "Cíl (třeba Uběhnout 50 km)", maxlength: "60", "aria-label": "Název cíle" }) as HTMLInputElement;
    const target = h("input", { class: "input hb-num", type: "number", min: "0.1", step: "any", value: String(st.target), "aria-label": "Cílová hodnota" }) as HTMLInputElement;
    const cur = h("input", { class: "input hb-num", type: "number", min: "0", step: "any", value: String(st.current), "aria-label": "Teď mám" }) as HTMLInputElement;
    const unit = h("input", { class: "input hb-unit", value: st.unit, placeholder: "jednotka (km, kg, knih)", maxlength: "16", "aria-label": "Jednotka" }) as HTMLInputElement;
    const dl = h("input", { class: "input", type: "date", value: st.deadline, "aria-label": "Do kdy" }) as HTMLInputElement;
    const f = h("div", { class: "hb-card hb-form" }, h("h3", {}, g ? "Upravit cíl" : "Nový cíl"), name,
      h("div", { class: "hb-row" }, h("span", {}, "Cíl"), target, unit), h("div", { class: "hb-row" }, h("span", {}, "Teď mám"), cur),
      h("div", { class: "hb-row" }, h("span", {}, "Do kdy"), dl),
      h("div", { class: "hb-row end" },
        g ? h("button", { type: "button", class: "btn danger", onclick: () => { if (confirm(`Smazat cíl „${g.name}“?`)) client.send("habit_goal", { action: "delete", id: g.id }); } }, icon("trash"), "Smazat") : "",
        h("span", { class: "grow" }), h("button", { type: "button", class: "btn", onclick: () => f.remove() }, "Zrušit"),
        h("button", { type: "button", class: "btn primary", onclick: () => {
          if (!name.value.trim()) { name.focus(); return; }
          client.send("habit_goal", { goal: { id: g?.id, name: name.value, target: parseFloat(target.value) || 1, current: parseFloat(cur.value) || 0, unit: unit.value, deadline: dl.value, color: st.color } });
          f.remove();
        } }, icon("check"), "Uložit")));
    return f;
  };
  const box = h("div", { class: "hb-goals" });
  const grid = h("div", { class: "hb-goal-grid" }, ...list.map((g) => {
    const step = g.target >= 100 ? Math.round(g.target / 20) : g.target >= 10 ? 1 : 0.5;
    const set = (v: number) => client.send("habit_goal", { goal: { ...g, current: Math.max(0, Math.round(v * 100) / 100) } });
    return h("div", { class: `hb-card hb-goal${g.pct >= 100 ? " won" : ""}`, style: { "--c": safeColor(g.color) } as any },
      h("div", { class: "hb-goal-top" }, h("strong", {}, g.name),
        h("button", { type: "button", class: "hb-x", "aria-label": `Upravit: ${g.name}`, onclick: () => { box.querySelector(".hb-form")?.remove(); grid.after(form(g)); } }, icon("pencil-simple"))),
      h("div", { class: "hb-goal-pct" }, `${g.pct}%`),
      h("div", { class: "hb-goal-bar" }, h("i", { style: { width: `${g.pct}%` } })),
      h("div", { class: "hb-goal-meta" }, h("span", {}, `${num(g.current)} / ${num(g.target)} ${g.unit}`.trim()),
        g.days_left == null ? "" : h("span", {}, g.days_left < 0 ? "po termínu" : g.days_left === 0 ? "dnes je termín" : `zbývá ${g.days_left} ${g.days_left === 1 ? "den" : g.days_left < 5 ? "dny" : "dní"}`)),
      h("div", { class: "hb-goal-btns" },
        h("button", { type: "button", class: "hb-step", "aria-label": "Ubrat", onclick: () => set(g.current - step) }, icon("minus")),
        h("button", { type: "button", class: "hb-step", "aria-label": "Přidat", onclick: () => set(g.current + step) }, icon("plus"))));
  }), h("button", { type: "button", class: "hb-card hb-goal-new", onclick: () => { box.querySelector(".hb-form")?.remove(); grid.after(form()); } }, icon("plus-circle"), "Nový cíl"));
  box.append(grid);
  return box;
}

/** Přehled: the consistency (all habits or one), this week, the leaderboard for a day / week / month, the streaks */
let pick: number | "all" = "all";                 // kept while the snapshot refreshes (every tick)
let period: "7" | "30" | "90" = "30";
/** 3.12 the week as a picture (1080×1350, black and white) – saved or shared from the phone */
export async function weekCard(s: HabitSnap): Promise<void> {
  const W = 1080, H = 1350, c = document.createElement("canvas");
  c.width = W; c.height = H;
  const g = c.getContext("2d")!;
  const font = (w: number, px: number) => `${w} ${px}px "Geist Variable", system-ui, sans-serif`;
  g.fillStyle = "#0a0a0b"; g.fillRect(0, 0, W, H);
  g.fillStyle = "#fff"; g.font = font(900, 96); g.fillText("TÝDEN", 80, 190);
  const [y, m, d] = s.date.split("-").map(Number);
  g.font = font(700, 34); g.fillStyle = "rgba(255,255,255,.55)"; g.fillText(`${d}. ${MONTHS[m - 1]} ${y} · JARVIS`, 84, 245);
  g.fillStyle = "#fff"; g.font = font(900, 240); g.fillText(`${s.week ?? 0}%`, 70, 520);
  g.font = font(700, 40); g.fillStyle = "rgba(255,255,255,.7)";
  g.fillText(s.delta == null ? "splněných návyků" : `${s.delta >= 0 ? "▲ +" : "▼ "}${s.delta} % proti minulému týdnu`, 84, 590);
  const best = [...s.items].sort((a, b) => b.streak - a.streak)[0];
  if (best && best.streak >= 2) { g.fillStyle = "#fff"; g.font = font(800, 44); g.fillText(`🔥 ${best.name} – ${best.streak} dní v řadě`, 84, 680); }
  let yy = 780;
  for (const it of s.items.slice(0, 7)) {
    const r = Math.max(0, Math.min(100, it.rate7 ?? 0));
    g.fillStyle = "#fff"; g.font = font(800, 36); g.fillText(it.name.toUpperCase(), 84, yy);
    g.textAlign = "right"; g.fillText(`${Math.round(r)} %`, W - 84, yy); g.textAlign = "left";
    g.fillStyle = "rgba(255,255,255,.1)"; g.beginPath(); g.roundRect(84, yy + 18, W - 168, 16, 8); g.fill();
    g.fillStyle = "#fff"; g.beginPath(); g.roundRect(84, yy + 18, Math.max(16, (W - 168) * r / 100), 16, 8); g.fill();
    yy += 78;
  }
  const blob: Blob = await new Promise((ok) => c.toBlob((b) => ok(b!), "image/png"));
  const file = new File([blob], `jarvis-tyden-${s.date}.png`, { type: "image/png" });
  const nav = navigator as any;
  if (nav.canShare?.({ files: [file] })) { try { await nav.share({ files: [file], title: "Můj týden" }); return; } catch { /* cancelled: save instead */ } }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = file.name;
  document.body.append(a); a.click(); a.remove();
  window.setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

export function insights(s: HabitSnap): HTMLElement {
  if (pick !== "all" && !s.items.some((x) => x.id === pick)) pick = "all";
  const root = h("div", { class: "hbp-insights" });
  const paint = () => {
    const it = pick === "all" ? null : s.items.find((x) => x.id === pick) || null;
    const trend = it ? (it.hist || []).map((v, i) => ({ day: s.trend[i]?.day || "", pct: v == null ? null : v ? 100 : 0 })) : s.trend;
    const roll = it ? trend.map((t, i) => {                       // one habit: a 7-day rolling share, so the line means something
      const w = trend.slice(Math.max(0, i - 6), i + 1).filter((x) => x.pct != null);
      return { day: t.day, pct: w.length ? Math.round(w.reduce((a, x) => a + (x.pct || 0), 0) / w.length) : null };
    }) : trend;
    const big = it ? it.rate30 : s.consistency;
    const filter = h("div", { class: "hb-filter" },
      h("div", { class: "hb-pick" }, it ? it.name : "Celkově", icon("caret-down")),
      h("button", { type: "button", class: pick === "all" ? "on" : "", onclick: () => { pick = "all"; paint(); } }, "Celkově"),
      ...s.items.map((x) => h("button", { type: "button", class: pick === x.id ? "on" : "", style: { "--c": safeColor(x.color) } as any,
        onclick: () => { pick = x.id; paint(); } }, h("i", { class: "hb-pip" }), x.name)));
    const rate = (x: HabitItem) => (period === "7" ? x.rate7 : period === "90" ? x.rate90 : x.rate30) ?? null;
    const board = s.items.filter((x) => rate(x) != null).sort((a, b) => (rate(b)! - rate(a)!)).slice(0, 5);
    const bestStreak = s.items.reduce((a, x) => (x.streak > a.streak ? x : a), s.items[0] || { streak: 0, name: "" } as any);
    const maxStreak = Math.max(1, ...s.items.map((x) => x.streak));
    root.replaceChildren(
      h("div", { class: "hb-card hbp-trend" },
        h("div", { class: "hbp-trend-grid" },
          h("div", {}, h("h3", {}, it ? `${it.name} · vytrvalost` : "Celková vytrvalost"), h("strong", { class: "hbp-big" }, big == null ? "–" : `${big}%`), trendChart(roll)),
          filter)),
      h("div", { class: "hbp-cards" },
        statCard("Tento týden", s.week == null ? "–" : `${s.week}%`),
        statCard("Proti minulému týdnu", s.delta == null ? "–" : `${s.delta >= 0 ? "+" : ""}${s.delta}%`, undefined, s.delta == null ? "" : s.delta >= 0 ? "up" : "down"),
        statCard("Nejlepší série", bestStreak?.streak ? `${bestStreak.streak}` : "0", h("em", {}, icon("fire", "ph-fill"), ` ${bestStreak?.name || ""}`), "fire")),
      h("div", { class: "hbp-two" },
        h("div", { class: "hb-card hb-leaders" },
          h("div", { class: "hb-lead-head" }, h("h3", {}, "Žebříček návyků"),
            h("div", { class: "hb-seg sm" }, ...([["7", "T"], ["30", "M"], ["90", "3M"]] as const).map(([k, l]) =>
              h("button", { type: "button", class: period === k ? "on" : "", title: k === "7" ? "Týden" : k === "30" ? "Měsíc" : "3 měsíce", onclick: () => { period = k; paint(); } }, l)))),
          ...(board.length ? board.map((x, i) => h("div", { class: "hb-lead", style: { "--c": safeColor(x.color) } as any },
            h("span", { class: "hb-medal" }, ["🥇", "🥈", "🥉"][i] || String(i + 1)), h("span", { class: "hb-lead-name" }, x.name),
            h("span", { class: "hb-lead-bar" }, h("i", { style: { width: `${rate(x)}%` } })), h("em", {}, `${rate(x)}%`))) : [h("p", { class: "hb-empty" }, "Zatím málo dat.")])),
        h("div", { class: "hb-card hb-streaks" }, h("h3", {}, "Nejdelší série"),
          ...(s.streaks.length ? s.streaks.map((x) => h("div", { class: "hb-srow", style: { "--c": safeColor(x.color) } as any },
            h("span", {}, x.name), h("span", { class: "hb-sbar" }, h("i", { style: { width: `${(100 * x.streak) / maxStreak}%` } })),
            h("strong", {}, icon("fire", "ph-fill"), ` ${x.streak}`))) : [h("p", { class: "hb-empty" }, "Odškrtni návyk dva dny po sobě a začne série.")]))),
      h("button", { type: "button", class: "hb-photo hb-weekcard", onclick: () => { weekCard(s).catch(() => {}); } },
        icon("image", "ph-fill"), "Uložit kartu týdne"));
  };
  paint();
  return root;
}


const MON_SHORT = ["led", "úno", "bře", "dub", "kvě", "čvn", "čvc", "srp", "zář", "říj", "lis", "pro"];
/** the tracker's head: a huge title, the mint date pill and the tabs (with icons) */
export function trackerHead(title: string, date: string, tabs: HTMLElement, extra?: HTMLElement): HTMLElement {
  const [y, m, d] = date.split("-").map(Number);
  return h("div", { class: "hb-head" },
    h("div", { class: "hb-head-l" }, h("h1", {}, title), h("span", { class: "hb-date-pill" }, `${d}. ${MON_SHORT[m - 1]} ${y}`)),
    h("div", { class: "hb-head-r" }, tabs, extra || ""));
}
