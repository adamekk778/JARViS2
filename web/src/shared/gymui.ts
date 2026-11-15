// 3.12 Gym deník in the tracker (PC and phone): add a set (exercise, kg, reps, how many sets), today's sets, and a card
// per exercise – the best set, the estimated one-rep max as a line over the weeks, the gain and a record badge.
import "./gym.css";
import { h, icon } from "./dom";
import type { JarvisClient } from "./ws";

export interface GymSnap {
  date: string;
  today: { id: number; exercise: string; weight: number; reps: number }[];
  exercises: { name: string; best: { weight: number; reps: number; day: string } | null; sets: number; last: string;
    points: { day: string; rm: number }[]; rm: number; gain: number | null; pr_today: boolean }[];
  names: string[];
  week: { sets: number; volume: number; days: number; prev_volume: number };
}

const kg = (v: number) => `${String(Math.round(v * 10) / 10).replace(".", ",")} kg`;
const wt = (v: number) => (v > 0 ? String(v).replace(".", ",") : "vl. váha");        // 0 kg = own body weight (pull-ups)
const dm = (d: string) => { const [, m, dd] = d.split("-").map(Number); return `${dd}. ${m}.`; };

function line(pts: { day: string; rm: number }[]): HTMLElement {
  const box = h("div", { class: "gy-line" });
  if (pts.length < 2) { box.append(h("span", { class: "gy-line-empty" }, "Graf se ukáže od druhého tréninku")); return box; }
  const W = 220, H = 56, vals = pts.map((p) => p.rm), lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const xy = pts.map((p, i) => [(i / (pts.length - 1)) * W, H - 6 - ((p.rm - lo) / span) * (H - 14)] as const);
  const d = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <path d="${d} L${W},${H} L0,${H} Z" fill="rgba(255,255,255,.08)"/><path d="${d}" fill="none" stroke="#fff" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
    <circle cx="${xy[xy.length - 1][0]}" cy="${xy[xy.length - 1][1]}" r="3.5" fill="#fff"/></svg>`;
  return box;
}

export function gymView(client: JarvisClient, s: GymSnap | null): HTMLElement {
  if (!s) { client.send("gym_get"); return h("p", { class: "hb-empty" }, "Načítám…"); }
  const ex = h("input", { class: "gy-in gy-ex", placeholder: "Cvik (např. Bench press)", list: "gy-names", maxlength: "60", "aria-label": "Cvik" }) as HTMLInputElement;
  const w = h("input", { class: "gy-in", type: "number", inputmode: "decimal", min: "0", step: "0.5", placeholder: "kg", "aria-label": "Váha v kg" }) as HTMLInputElement;
  const r = h("input", { class: "gy-in", type: "number", inputmode: "numeric", min: "1", step: "1", placeholder: "opak.", "aria-label": "Opakování" }) as HTMLInputElement;
  const n = h("input", { class: "gy-in", type: "number", inputmode: "numeric", min: "1", max: "20", step: "1", value: "1", "aria-label": "Počet sérií" }) as HTMLInputElement;
  const last = s.today[s.today.length - 1];
  if (last) { ex.value = last.exercise; w.value = String(last.weight); r.value = String(last.reps); }
  const add = () => {
    if (!ex.value.trim() || !(Number(r.value) > 0)) { ex.focus(); return; }
    client.send("gym_set", { exercise: ex.value.trim(), weight: Number(w.value) || 0, reps: Math.round(Number(r.value)), sets: Math.max(1, Math.round(Number(n.value) || 1)) });
  };
  [ex, w, r, n].forEach((i) => i.addEventListener("keydown", (e) => { if ((e as KeyboardEvent).key === "Enter") { e.preventDefault(); add(); } }));
  const form = h("div", { class: "hb-card gy-form" },
    h("div", { class: "gy-form-h" }, h("strong", {}, "Zapsat sérii"), h("span", {}, "nebo řekni: „bench 60 kilo 8 opakování“")),
    h("div", { class: "gy-row" }, ex, w, r, h("span", { class: "gy-x" }, "×"), n,
      h("button", { type: "button", class: "gy-add", onclick: add }, icon("plus", "ph-bold"), "Přidat")),
    h("datalist", { id: "gy-names" }, ...s.names.map((x) => h("option", { value: x }))));

  const groups = new Map<string, typeof s.today>();
  for (const t of s.today) groups.set(t.exercise, [...(groups.get(t.exercise) || []), t]);
  const today = h("div", { class: "hb-card gy-today" },
    h("div", { class: "gy-form-h" }, h("strong", {}, "Dnešní trénink"),
      h("span", {}, s.today.length ? `${s.today.length} sérií · ${kg(s.today.reduce((a, t) => a + t.weight * t.reps, 0))} celkem` : "Zatím nic")),
    ...[...groups.entries()].map(([name, sets]) => h("div", { class: "gy-grp" }, h("b", {}, name),
      h("div", { class: "gy-sets" }, ...sets.map((t) => h("span", { class: "gy-set" }, `${wt(t.weight)} × ${t.reps}`,
        h("button", { type: "button", "aria-label": "Smazat sérii", onclick: () => client.send("gym_delete", { id: t.id }) }, icon("x")))))))) ;

  const wk = s.week;
  const delta = wk.prev_volume ? Math.round(((wk.volume - wk.prev_volume) / wk.prev_volume) * 100) : null;
  const stats = h("div", { class: "gy-stats" },
    h("div", { class: "hb-card" }, h("span", {}, "Tento týden"), h("strong", {}, `${wk.days}×`), h("em", {}, `${wk.sets} sérií`)),
    h("div", { class: "hb-card" }, h("span", {}, "Objem"), h("strong", {}, `${Math.round(wk.volume / 100) / 10} t`),
      h("em", {}, delta == null ? "zvednuto celkem" : `${delta >= 0 ? "+" : ""}${delta} % proti min. týdnu`)),
    h("div", { class: "hb-card" }, h("span", {}, "Cviků"), h("strong", {}, String(s.exercises.length)), h("em", {}, "za 4 měsíce")));

  const cards = h("div", { class: "gy-cards" }, ...s.exercises.map((e) => h("div", { class: "hb-card gy-card" },
    h("div", { class: "gy-card-h" }, h("strong", {}, e.name), e.pr_today && e.gain ? h("span", { class: "gy-pr" }, icon("trophy", "ph-fill"), "Rekord") : ""),
    h("div", { class: "gy-big" }, h("strong", {}, e.best ? (e.best.weight > 0 ? `${wt(e.best.weight)} kg × ${e.best.reps}` : `${e.best.reps} opakování`) : "–"),
      h("span", {}, e.best ? `nejlepší série · ${dm(e.best.day)}` : "")),
    line(e.points),
    h("div", { class: "gy-foot" }, h("span", {}, e.rm > 0 ? `1RM odhad ${kg(e.rm)}` : `${e.sets} sérií`),
      e.gain != null ? h("em", { class: e.gain >= 0 ? "up" : "down" }, `${e.gain >= 0 ? "▲" : "▼"} ${kg(Math.abs(e.gain))}`) : ""))));
  return h("div", { class: "gy" }, h("div", { class: "gy-top" }, form, today), stats,
    s.exercises.length ? cards : h("p", { class: "hb-empty" }, "Zapiš první sérii a tady uvidíš, jak sílíš."));
}
