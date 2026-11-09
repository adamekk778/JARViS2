/* 3.12 "Týden soustředění": a sheet over the notch panel – minutes per day as bars, the total, the streak of days in a
   row, the longest session and what pulled you away most often (only service names, e.g. YouTube). */
import { h, icon } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import "./focusstats.css";

const dur = (sec: number) => { const m = Math.round(sec / 60); return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60 ? `${m % 60} min` : ""}`.trim() : `${m} min`; };
const days = (n: number) => (n === 1 ? "den" : n >= 2 && n <= 4 ? "dny" : "dní");

export function createFocusStats(host: HTMLElement, client: JarvisClient) {
  const body = h("div", { class: "fs-body" }, h("p", { class: "fs-muted" }, "Načítám…"));
  const sheet = h("div", { class: "lk-sheet fs-sheet", role: "dialog", "aria-label": "Týden soustředění", hidden: true },
    h("div", { class: "lk-head" }, h("strong", {}, "Týden soustředění"),
      h("button", { type: "button", class: "lk-x", "aria-label": "Zavřít", onclick: () => open(false) }, icon("x"))), body);
  host.append(sheet);
  client.on("focus_stats", (m) => paint(m));

  function paint(m: any) {
    const ds: { label: string; seconds: number; day: string }[] = m?.days || [];
    if (!ds.length) { body.replaceChildren(h("p", { class: "fs-muted" }, "Statistiky teď nejsou k dispozici.")); return; }
    const max = Math.max(25 * 60, ...ds.map((d) => d.seconds));
    const bars = h("div", { class: "fs-bars" }, ...ds.map((d, i) => {
      const today = i === ds.length - 1;
      const bar = h("i", { style: { height: "0%" } });
      requestAnimationFrame(() => requestAnimationFrame(() => (bar.style.height = `${Math.max(d.seconds ? 4 : 0, (d.seconds / max) * 100)}%`)));
      return h("div", { class: `fs-col ${today ? "today" : ""}`, title: `${d.label}: ${dur(d.seconds)}` },
        h("span", { class: "fs-v" }, d.seconds >= 60 ? dur(d.seconds).replace(" min", "m").replace(" h ", "h ") : ""),
        h("div", { class: "fs-track" }, bar), h("span", { class: "fs-l" }, today ? "Dnes" : d.label));
    }));
    const stat = (ic: string, big: string, small: string) => h("div", { class: "fs-stat" }, icon(ic, "ph-fill"), h("strong", {}, big), h("span", {}, small));
    const top: { app: string; count: number }[] = m.distractions || [];
    body.replaceChildren(
      h("section", { class: "fs-chart" }, bars),
      h("section", { class: "fs-side" },
        h("div", { class: "fs-stats" },
          stat("timer", dur(m.total || 0), "za 7 dní"),
          stat("flame", `${m.streak || 0} ${days(m.streak || 0)}`, "v řadě"),
          stat("trophy", m.longest ? dur(m.longest) : "–", "nejdelší blok")),
        h("h4", {}, "Co tě nejvíc rušilo"),
        top.length ? h("div", { class: "fs-dist" }, ...top.map((t) => h("div", {}, h("span", {}, t.app), h("b", {}, `${t.count}×`))))
          : h("p", { class: "fs-muted" }, m.total ? "Nic – skvělé soustředění! 🎯" : "Spusť soustředění na 25 minut – tady uvidíš, jak ti to jde.")));
  }
  function open(on: boolean) {
    sheet.hidden = !on;
    if (on) {
      client.send("focus_stats_get");
      sheet.animate([{ opacity: 0, transform: "translateY(10px) scale(.98)" }, { opacity: 1, transform: "none" }], { duration: 280, easing: "cubic-bezier(.2,.9,.25,1)" });
    }
  }
  return { open: () => open(true), close: () => open(false) };
}
