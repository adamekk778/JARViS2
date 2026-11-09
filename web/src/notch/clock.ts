/* 3.12 the clock on the notch's main screen. Six looks (digital, analog, flip cards, a ring of seconds, stacked,
   in words) and colours: a click on the clock changes the colour, the small button in its corner the look. Both are
   remembered on this PC. Painted once a second, only what changed. */
import { h, icon } from "../shared/dom";

export const CLOCK_STYLES = ["digital", "analog", "flip", "ring", "stack", "words"] as const;
export const CLOCK_COLORS = ["#ffffff", "#0a84ff", "#ff9f0a", "#ff375f", "#30d158", "#bf5af2", "#64d2ff", "#ffd60a", "grad"] as const;
export const STYLE_NAMES: Record<string, string> = { digital: "Digitální", analog: "Ručičky", flip: "Překlápěcí", ring: "Kruh", stack: "Pod sebou", words: "Slovy" };
const STYLE_NAME = STYLE_NAMES;

const ONES = ["nula", "jedna", "dva", "tři", "čtyři", "pět", "šest", "sedm", "osm", "devět", "deset", "jedenáct", "dvanáct", "třináct", "čtrnáct",
  "patnáct", "šestnáct", "sedmnáct", "osmnáct", "devatenáct"];
const TENS = ["", "", "dvacet", "třicet", "čtyřicet", "padesát"];
/** a number 0–59 in Czech words ("čtyřicet sedm") */
export function czWords(n: number): string {
  if (n < 20) return ONES[n];
  const t = TENS[Math.floor(n / 10)], o = n % 10;
  return o ? `${t} ${ONES[o]}` : t;
}

const load = (k: string, d: string) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
const save = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private */ } };
const pad = (n: number) => String(n).padStart(2, "0");

export function createClock() {
  let style = load("jarvis.clock.style", "digital");
  let color = load("jarvis.clock.color", "#ffffff");
  if (!(CLOCK_STYLES as readonly string[]).includes(style)) style = "digital";
  const face = h("div", { class: "ck-face" });
  const date = h("div", { class: "ck-date" });
  const extra = h("div", { class: "ck-extra" });          // weather under the date (when known)
  const styleBtn = h("button", { class: "ck-style", type: "button", title: "Změnit vzhled hodin", "aria-label": "Změnit vzhled hodin",
    onclick: (e: Event) => { e.stopPropagation(); next("style"); } }, icon("shapes", "ph-fill"));
  const label = h("span", { class: "ck-label" });
  const el = h("button", { class: "tile clock", type: "button", title: "Klikni pro jinou barvu", "aria-label": "Hodiny – klikni pro jinou barvu",
    onclick: () => next("color") }, styleBtn, face, date, extra, label);
  let last = "", minuteKey = "";

  function applyColor() {
    el.style.setProperty("--ck", color === "grad" ? "#ff9f0a" : color);
    el.classList.toggle("grad", color === "grad");
  }
  function next(what: "style" | "color") {
    if (what === "style") {
      style = CLOCK_STYLES[(CLOCK_STYLES.indexOf(style as any) + 1) % CLOCK_STYLES.length];
      save("jarvis.clock.style", style);
      build();
    } else {
      color = CLOCK_COLORS[(Math.max(-1, CLOCK_COLORS.indexOf(color as any)) + 1) % CLOCK_COLORS.length];
      save("jarvis.clock.color", color);
      applyColor();
    }
    label.textContent = what === "style" ? STYLE_NAME[style] : "Barva";
    label.classList.remove("show"); void label.offsetWidth; label.classList.add("show");
    el.animate([{ transform: "scale(.97)" }, { transform: "scale(1)" }], { duration: 300, easing: "cubic-bezier(.3,1.6,.5,1)" });
  }

  // pieces of each look, made in build()
  let big: HTMLElement, sec: HTMLElement, hh: HTMLElement, mm: HTMLElement, hourHand: SVGElement, minHand: SVGElement, secHand: SVGElement, arc: SVGCircleElement;
  const RING = 2 * Math.PI * 44;
  function svg(markup: string, box = "0 0 100 100") {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", box);
    s.innerHTML = markup;
    return s;
  }
  function build() {
    el.dataset.style = style;
    last = ""; minuteKey = "";
    if (style === "digital") {
      hh = h("span", {}); mm = h("span", { class: "ck-mm" });
      big = h("strong", { class: "ck-big" }, hh, h("i", { class: "ck-dots" }, ":"), mm); sec = h("span", { class: "ck-sec" });
      face.replaceChildren(h("div", { class: "ck-row" }, big, sec));
    } else if (style === "analog") {
      let ticks = "";
      for (let i = 0; i < 60; i++) {
        const major = i % 5 === 0;
        ticks += `<line x1="50" y1="${major ? 6 : 7}" x2="50" y2="${major ? 13 : 9.5}" transform="rotate(${i * 6} 50 50)" class="${major ? "tk maj" : "tk"}"/>`;
      }
      const s = svg(`<circle cx="50" cy="50" r="47" class="dial"/>${ticks}<line x1="50" y1="50" x2="50" y2="27" class="hh"/>`
        + `<line x1="50" y1="50" x2="50" y2="15" class="mh"/><line x1="50" y1="58" x2="50" y2="11" class="sh"/><circle cx="50" cy="50" r="3" class="pin"/>`);
      s.setAttribute("class", "ck-analog");
      hourHand = s.querySelector(".hh")!; minHand = s.querySelector(".mh")!; secHand = s.querySelector(".sh")!;
      const t = new Date();
      (secHand as unknown as HTMLElement).style.animationDelay = `-${t.getSeconds() + t.getMilliseconds() / 1000}s`;   // it sweeps, like a real watch
      face.replaceChildren(s);
    } else if (style === "flip") {
      hh = h("span", { class: "ck-card" }); mm = h("span", { class: "ck-card" });
      face.replaceChildren(h("div", { class: "ck-flip" }, hh, h("i", { class: "ck-colon" }), mm));
    } else if (style === "ring") {
      const s = svg(`<circle cx="50" cy="50" r="44" class="rg-bg"/><circle cx="50" cy="50" r="44" class="rg-arc" transform="rotate(-90 50 50)"/>`);
      s.setAttribute("class", "ck-ring");
      arc = s.querySelector(".rg-arc") as SVGCircleElement;
      arc.style.strokeDasharray = `${RING}`;
      big = h("strong", { class: "ck-ring-time" });
      face.replaceChildren(h("div", { class: "ck-ring-box" }, s, big));
    } else if (style === "stack") {
      hh = h("strong", { class: "ck-h" }); mm = h("strong", { class: "ck-m" });
      face.replaceChildren(h("div", { class: "ck-stack" }, hh, mm));
    } else {
      hh = h("strong", { class: "ck-w1" }); mm = h("span", { class: "ck-w2" });
      face.replaceChildren(h("div", { class: "ck-words" }, hh, mm));
    }
    paint(true);
  }
  /** the new number slides in from above (only when it changed) */
  function roll(el: HTMLElement, text: string) {
    if (el.textContent === text) return;
    const first = !el.textContent;
    el.textContent = text;
    if (!first) el.animate([{ transform: "translateY(-.35em)", opacity: 0, filter: "blur(3px)" }, { transform: "none", opacity: 1, filter: "blur(0)" }],
      { duration: 420, easing: "cubic-bezier(.2,.8,.2,1)" });
  }
  function flip(card: HTMLElement, text: string) {
    if (card.textContent === text) return;
    card.textContent = text;
    card.animate([{ transform: "rotateX(-90deg)", filter: "brightness(.6)" }, { transform: "rotateX(0)", filter: "none" }],
      { duration: 450, easing: "cubic-bezier(.3,1.3,.5,1)" });
  }
  function paint(force = false) {
    const now = new Date();
    const H = now.getHours(), M = now.getMinutes(), Sx = now.getSeconds();
    const key = `${style}${H}:${M}:${Sx}`;
    if (!force && key === last) return;
    last = key;
    const dkey = now.toDateString();
    if (force || date.dataset.k !== dkey) {
      date.dataset.k = dkey;
      const d = now.toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" });
      date.textContent = d.charAt(0).toUpperCase() + d.slice(1);          // "Pondělí 9. listopadu"
    }
    if (style === "digital") {
      roll(hh, String(H)); roll(mm, pad(M));
      sec.textContent = pad(Sx);
    } else if (style === "analog") {
      hourHand.setAttribute("transform", `rotate(${(H % 12) * 30 + M * 0.5} 50 50)`);
      minHand.setAttribute("transform", `rotate(${M * 6 + Sx * 0.1} 50 50)`);
    } else if (style === "flip") {
      flip(hh, pad(H)); flip(mm, pad(M));
    } else if (style === "ring") {
      big.textContent = `${H}:${pad(M)}`;
      arc.style.strokeDashoffset = `${RING * (1 - (Sx || 60) / 60)}`;
      arc.classList.toggle("reset", Sx === 0);
    } else if (style === "stack") {
      roll(hh, pad(H)); roll(mm, pad(M));
    } else if (`${H}:${M}` !== minuteKey) {
      minuteKey = `${H}:${M}`;
      hh.textContent = czWords(H);
      mm.textContent = M ? czWords(M) : "nula nula";
    }
  }
  /** the weather under the date: an icon and the temperature */
  function weather(m: any) {
    if (!m || m.error || typeof m.temp !== "number") { extra.replaceChildren(); return; }
    const d = String(m.desc || "");
    const ic = /bouř/i.test(d) ? "cloud-lightning" : /sníh|sněž/i.test(d) ? "snowflake" : /déšť|přeháň|mrhol/i.test(d) ? "cloud-rain"
      : /mlh/i.test(d) ? "cloud-fog" : /zataž|oblač/i.test(d) ? "cloud" : new Date().getHours() >= 19 || new Date().getHours() < 6 ? "moon" : "sun";
    extra.replaceChildren(icon(ic, "ph-fill"), h("b", {}, `${Math.round(m.temp)}°`), h("span", {}, m.city || ""));
  }
  applyColor();
  build();
  return {
    el, paint: () => paint(), weather,
    get style() { return style; },
    get color() { return color; },
    /** from the "Přizpůsobit" sheet: any colour (#rrggbb or "grad") and any of the looks */
    setColor(c: string) { color = c; save("jarvis.clock.color", c); applyColor(); },
    setStyle(st: string) { if ((CLOCK_STYLES as readonly string[]).includes(st)) { style = st; save("jarvis.clock.style", st); build(); } },
  };
}
