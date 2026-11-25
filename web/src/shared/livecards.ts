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
  | { kind: "body"; level: string; sleep: number | null; rest_hr: number | null }
  | { kind: "offers"; title: string; items: Offer[] };

/** 3.18 Cesty: one offer of a hotel or flight search (what the card shows side by side). */
export interface Offer {
  n: number; kind: "hotel" | "flight"; name: string; stars: number | null; rating: number | null; total: number | null;
  currency: string; per_night: number | null; nights: number; km: number | null; why: string; refundable: boolean;
  pay_at_property: boolean; breakfast: boolean; legs: { from: string; to: string; dep: string; stops: number }[];
}

const money = (v: number | null, cur: string) => (v == null ? "–" : `${Math.round(v).toLocaleString("cs-CZ")} ${cur}`);

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
    case "offers":
      return h("div", { class: "lc lc-offers" }, c.title ? h("span", { class: "lc-offers-title" }, c.title) : null,
        h("div", { class: "lc-offers-row" }, ...c.items.map((o, i) => h("div", { class: `lc-offer ${o.refundable ? "free" : ""}`, style: { "--i": String(i) } },
          h("b", { class: "lc-offer-n" }, String(o.n)),
          h("strong", {}, o.name || (o.kind === "flight" ? "Let" : "Hotel")),
          o.kind === "flight"
            ? h("span", {}, o.legs.map((l) => `${l.from}→${l.to} ${l.dep.slice(5, 16).replace("T", " ")}${l.stops ? ` · ${l.stops}× přestup` : " · přímý"}`).join("  ·  "))
            : h("span", {}, [o.stars ? "★".repeat(Math.round(o.stars)) : "", o.rating != null ? `${String(o.rating).replace(".", ",")}/10` : "",
              o.km != null ? `${String(o.km).replace(".", ",")} km` : ""].filter(Boolean).join(" · ")),
          h("div", { class: "lc-offer-price" }, h("strong", {}, money(o.total, o.currency)),
            o.kind === "hotel" && o.per_night != null ? h("span", {}, `${money(o.per_night, o.currency)} / noc`) : null),
          h("div", { class: "lc-offer-tags" },
            o.refundable ? h("i", { class: "ok" }, "zrušení zdarma") : h("i", { class: "warn" }, "nevratné"),
            o.pay_at_property ? h("i", {}, "platba na hotelu") : null, o.breakfast ? h("i", {}, "snídaně") : null),
          o.why ? h("span", { class: "lc-offer-why" }, o.why) : null))));
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
