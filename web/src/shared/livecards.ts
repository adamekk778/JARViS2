// 3.15 Mega animace (návrh 25): a small live picture under some tool results in the chat – rain or snow falling on
// the weather, a plane flying its route, parcels on their way, a song's wave, the body's state. CSS only; with the
// effects off they stand still.
import { h, icon } from "./dom";
import "./livecards.css";

export type LiveCard =
  | { kind: "weather"; sky: string; temp: number | null; city: string; desc: string; days: { max: number | null; min: number | null; rain: number }[] }
  | { kind: "flight" | "train"; number: string; from: string; to: string; flying: boolean }
  | { kind: "parcel"; items: { name: string; state: string }[] }
  | { kind: "music"; title: string; artist: string }
  | { kind: "body"; level: string; sleep: number | null; rest_hr: number | null };

const n = (v: number | null | undefined, unit = "") => (v == null ? "–" : `${Math.round(v)}${unit}`);

export function liveCard(c: LiveCard | null | undefined): HTMLElement | null {
  if (!c || typeof c !== "object") return null;
  switch (c.kind) {
    case "weather": {
      const fx = h("div", { class: `lc-sky ${c.sky}`, "aria-hidden": "true" });
      const drops = c.sky === "rain" || c.sky === "storm" ? 24 : c.sky === "snow" ? 18 : 0;
      for (let i = 0; i < drops; i++) fx.append(h("i", { style: { "--x": `${(i * 37) % 100}%`, "--d": `${(i % 7) * 0.17}s`, "--s": `${0.6 + (i % 5) * 0.12}s` } }));
      if (c.sky === "clear") fx.append(h("b", { class: "lc-sun" }));
      if (c.sky === "cloud" || c.sky === "storm" || c.sky === "rain") fx.append(h("u", { class: "lc-cloud" }), h("u", { class: "lc-cloud c2" }));
      const max = Math.max(1, ...c.days.map((d) => d.max ?? 0));
      return h("div", { class: "lc lc-weather" }, fx,
        h("div", { class: "lc-main" }, h("strong", {}, n(c.temp, "°")), h("span", {}, `${c.city} · ${c.desc}`)),
        h("div", { class: "lc-days" }, ...c.days.map((d, i) => h("i", { style: { "--h": `${Math.max(8, ((d.max ?? 0) / max) * 100)}%`, "--i": String(i) },
          title: `${n(d.max, "°")} / ${n(d.min, "°")} · déšť ${d.rain} %`, class: d.rain >= 50 ? "wet" : "" }))));
    }
    case "flight":
    case "train":
      return h("div", { class: `lc lc-route ${c.kind} ${c.flying ? "flying" : ""}` },
        h("span", { class: "lc-end" }, c.from || "odjezd"),
        h("div", { class: "lc-track", "aria-hidden": "true" }, h("i", { class: "lc-vehicle" }, icon(c.kind === "flight" ? "airplane-tilt" : "train", "ph-fill"))),
        h("span", { class: "lc-end" }, c.to || "cíl"),
        h("b", { class: "lc-no" }, c.number));
    case "parcel":
      return h("div", { class: "lc lc-parcels" }, ...c.items.map((p) => h("div", { class: `lc-parcel ${p.state}` },
        h("span", {}, p.name), h("div", { class: "lc-path", "aria-hidden": "true" }, h("i", {}, icon(p.state === "done" ? "check-circle" : p.state === "ready" ? "package" : "truck", "ph-fill"))))));
    case "music":
      return h("div", { class: "lc lc-music" }, h("div", { class: "lc-eq", "aria-hidden": "true" }, ...Array.from({ length: 14 }, (_, i) => h("i", { style: { "--i": String(i) } }))),
        h("div", {}, h("strong", {}, c.title), h("span", {}, c.artist)));
    case "body":
      return h("div", { class: `lc lc-body ${c.level}` }, ecg(),
        h("div", {}, h("strong", {}, { full: "Plná síla", normal: "Běžný den", easy: "Lehčí den" }[c.level] || c.level),
          h("span", {}, `spánek ${c.sleep == null ? "–" : String(c.sleep).replace(".", ",")} h · klidový tep ${n(c.rest_hr)}`)));
  }
  return null;
}

/** The heartbeat line (an SVG made element by element). */
function ecg(): SVGSVGElement {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "lc-ecg");
  svg.setAttribute("viewBox", "0 0 120 30");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(NS, "path");
  path.setAttribute("pathLength", "1");
  path.setAttribute("d", "M0 15 H34 L39 6 L45 26 L50 2 L55 22 L59 15 H120");
  svg.append(path);
  return svg;
}
