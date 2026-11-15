// 3.12 Návyky a zdraví – the pieces both the notch tab and the full screen use: the day's ring, a habit tile you tick,
// the month grid, the 30-day trend, the leaderboard and streaks, the meal log and the editor.
import { h, icon } from "./dom";
import type { JarvisClient } from "./ws";
import "./habits.css";

export interface HabitItem {
  id: number; name: string; icon: string; color: string; area: string; kind: "check" | "amount"; target: number; unit: string;
  days: string; value: number; note: string; due: boolean; done: boolean; streak: number; best: number; last7: (boolean | null)[];
  rate30: number | null;
}
export interface HabitSnap {
  date: string; weekday: number; items: HabitItem[]; today: { done: number; due: number; pct: number | null };
  week: number | null; last_week: number | null; delta: number | null; consistency: number | null;
  trend: { day: string; pct: number | null }[];
  month: { id: string; days: number; first_weekday: number; grid: { id: number; cells: string[] }[] };
  leaders: { id: number; name: string; color: string; rate: number }[];
  streaks: { id: number; name: string; color: string; streak: number }[];
  meals: { slot: string; label: string; text: string }[];
  areas: Record<string, string>;
  remind?: string;
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
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5ef2c0"/><stop offset="1" stop-color="#1fb8a0"/></linearGradient></defs>
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

/** the month: every habit a row, every day a circle (filled = done) – click a past day to fix it */
export function monthGrid(client: JarvisClient, s: HabitSnap, onMonth: (id: string) => void): HTMLElement {
  const [y, m] = s.month.id.split("-").map(Number);
  const shift = (d: number) => { const dt = new Date(y, m - 1 + d, 1); onMonth(`${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`); };
  const head = h("div", { class: "hb-month-head" },
    h("button", { type: "button", class: "hb-nav", "aria-label": "Předchozí měsíc", onclick: () => shift(-1) }, icon("caret-left")),
    h("strong", {}, `${MONTHS[m - 1]} ${y}`),
    h("button", { type: "button", class: "hb-nav", "aria-label": "Další měsíc", onclick: () => shift(1), disabled: s.month.id >= s.date.slice(0, 7) }, icon("caret-right")));
  const days = Array.from({ length: s.month.days }, (_, i) => i + 1);
  const cols = `minmax(150px, 1.3fr) repeat(${s.month.days}, minmax(0, 1fr))`;
  const top = h("div", { class: "hb-grid-row hb-grid-top", style: { gridTemplateColumns: cols } }, h("span", {}, ""),
    ...days.map((d) => h("span", { class: (s.month.first_weekday + d - 1) % 7 >= 5 ? "we" : "" }, String(d))));
  const rows = s.month.grid.map((g) => {
    const it = s.items.find((x) => x.id === g.id);
    if (!it) return null;
    const color = safeColor(it.color);
    return h("div", { class: "hb-grid-row", style: { gridTemplateColumns: cols, "--c": color } as any },
      h("span", { class: "hb-grid-name" }, h("i", { class: "hb-pip" }), it.name),
      ...g.cells.map((c, i) => {
        const day = `${s.month.id}-${String(i + 1).padStart(2, "0")}`;
        const clickable = c === "done" || c === "miss" || c === "today";
        return h("button", { type: "button", class: `hb-cell ${c}`, disabled: !clickable, title: `${it.name} · ${i + 1}. ${m}.`,
          "aria-label": `${it.name}, ${i + 1}. ${m}.: ${c === "done" ? "splněno" : c === "off" ? "volno" : c === "future" ? "ještě nebylo" : "nesplněno"}`,
          onclick: () => client.send("habit_log", { id: it.id, day, value: c === "done" ? 0 : it.kind === "amount" ? it.target : 1 }) },
        c === "done" ? icon("check", "ph-bold") : "");
      }));
  });
  return h("div", { class: "hb-month" }, head, h("div", { class: "hb-grid" }, top, ...rows.filter(Boolean) as HTMLElement[]));
}

/** the last 30 days as a soft glowing area */
export function trendChart(trend: HabitSnap["trend"], w = 640, hgt = 170): HTMLElement {
  const pts = trend.map((t, i) => [i / Math.max(1, trend.length - 1) * w, t.pct == null ? null : hgt - 12 - (t.pct / 100) * (hgt - 28)] as [number, number | null]);
  const known = pts.filter((p) => p[1] != null) as [number, number][];
  const el = h("div", { class: "hb-trend" });
  if (known.length < 2) { el.append(h("p", { class: "hb-empty" }, "Graf se ukáže po pár dnech odškrtávání.")); return el; }
  let d = `M${known[0][0].toFixed(1)},${known[0][1].toFixed(1)}`;
  for (let i = 1; i < known.length; i++) {                         // a smooth curve through the days
    const [x0, y0] = known[i - 1], [x1, y1] = known[i], mx = (x0 + x1) / 2;
    d += ` C${mx.toFixed(1)},${y0.toFixed(1)} ${mx.toFixed(1)},${y1.toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
  }
  const area = `${d} L${known[known.length - 1][0].toFixed(1)},${hgt} L${known[0][0].toFixed(1)},${hgt} Z`;
  const labels = [0, 7, 14, 21, 29].filter((i) => trend[i]).map((i) => {
    const [, mm, dd] = trend[i].day.split("-");
    return `<text x="${(i / (trend.length - 1) * w).toFixed(0)}" y="${hgt + 16}" text-anchor="${i === 0 ? "start" : i === 29 ? "end" : "middle"}">${+dd}. ${+mm}.</text>`;
  }).join("");
  el.innerHTML = `<svg viewBox="0 -4 ${w} ${hgt + 24}" preserveAspectRatio="none" aria-label="Vývoj za 30 dní" role="img">
    <defs><linearGradient id="hbtr" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2ee6a6" stop-opacity=".42"/><stop offset="1" stop-color="#2ee6a6" stop-opacity="0"/></linearGradient></defs>
    <path d="${area}" fill="url(#hbtr)"/><path d="${d}" fill="none" stroke="#5ef2c0" stroke-width="2.5" stroke-linecap="round"/>${labels}</svg>`;
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
export function meals(client: JarvisClient, s: HabitSnap): HTMLElement {
  return h("div", { class: "hb-card hb-meals" }, h("h3", {}, icon("bowl-food", "ph-fill"), " Jídelníček · dnes"),
    ...s.meals.map((m) => {
      const inp = h("input", { class: "hb-meal-in", value: m.text, placeholder: "Co jsi jedl?", maxlength: "200", "aria-label": m.label }) as HTMLInputElement;
      inp.addEventListener("change", () => client.send("habit_meal", { slot: m.slot, text: inp.value }));
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") inp.blur(); });
      return h("label", { class: `hb-meal${m.text ? " has" : ""}` }, h("span", {}, m.label), inp);
    }));
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
  box.append(list, h("button", { type: "button", class: "btn primary hb-add", onclick: () => { box.querySelector(".hb-form")?.remove(); list.after(form()); } }, icon("plus"), "Přidat návyk"));
  return box;
}
