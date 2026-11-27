// 3.20 Vzhled+ in the notch (nápady 101–112, 115): the wheel changes the volume, only urgent things go red, a photo
// from this day years ago, a countdown ring before a meeting / a shutdown, zen (invisible until needed), the season's
// shades, your own theme, a tiny weather scene, the size by the monitor, a timeline of the day, a second clock, and
// Mochi stretching after a long stretch of work. On a PC with several notches only the one you work on shows notices.
import "./x320.css";
import { applyCustomTheme } from "../shared/theme320";
import { h } from "../shared/dom";

type Client = { on: (t: any, f: (m: any) => void) => void; send: (t: any, d?: any) => void };
type BlobLike = { play: (r: { name: string; id: number }) => void };

const pad = (n: number) => String(n).padStart(2, "0");

export function season(d = new Date()): string {
  const m = d.getMonth() + 1;
  return m === 12 || m <= 2 ? "winter" : m <= 5 ? "spring" : m <= 8 ? "summer" : "autumn";
}

export function notchScale(w: number, h: number): number {
  if (w / Math.max(1, h) >= 2.2) return 1.2;          // ultrawide
  if (w >= 3200) return 1.15;
  if (w <= 1400) return 0.9;
  return 1;
}

export function initX320(client: Client, shape: HTMLElement, blob: BlobLike): void {
  const myMonitor = Number(new URLSearchParams(location.search).get("monitor") || "0");
  let settings: any = {};
  // ---------- (101) volume with the wheel
  let lastWheel = 0;
  shape.addEventListener("wheel", (e) => {
    if (settings?.notch?.wheel_volume === false) return;
    const now = performance.now();
    if (now - lastWheel < 120) return;
    lastWheel = now;
    client.send("quick_action", { action: "volume", args: { action: (e as WheelEvent).deltaY < 0 ? "up" : "down" } });
  }, { passive: true });

  // ---------- (102) red only when urgent
  client.on("notify", (m) => {
    if (!m.urgent) return;
    shape.classList.add("urgent");
    window.setTimeout(() => shape.classList.remove("urgent"), 9000);
  });

  // ---------- (103) a photo from this day
  const photo = h("figure", { class: "x-photo", hidden: true }, h("img", { alt: "" }), h("figcaption", {}));
  shape.append(photo);
  client.on("photo_frame", (m) => {
    if (settings?.notch?.photo_frame === false || !String(m.img || "").startsWith("data:image/")) return;
    (photo.querySelector("img") as HTMLImageElement).src = m.img;
    (photo.querySelector("figcaption") as HTMLElement).textContent = String(m.caption || "");
    photo.hidden = false;
    photo.classList.add("in");
    window.setTimeout(() => { photo.classList.remove("in"); window.setTimeout(() => { photo.hidden = true; }, 600); }, 12000);
  });

  // ---------- (104, 91) countdown ring
  const ring = h("div", { class: "x-count", hidden: true, role: "timer" });
  ring.innerHTML = '<svg viewBox="0 0 36 36" aria-hidden="true"><circle class="bg" cx="18" cy="18" r="15"/><circle class="fg" cx="18" cy="18" r="15"/></svg><span></span>';
  shape.append(ring);
  let cd: { until: number; total: number; title: string } | null = null;
  let cdTimer = 0;
  const stopCount = () => { cd = null; if (!ring.hidden) ring.hidden = true; window.clearInterval(cdTimer); cdTimer = 0; };
  const paintCount = () => {
    if (!cd) { stopCount(); return; }
    const left = cd.until - Date.now() / 1000;
    if (left <= 0) { stopCount(); return; }
    ring.hidden = false;
    const frac = Math.max(0, Math.min(1, left / cd.total));
    (ring.querySelector(".fg") as SVGCircleElement).style.strokeDashoffset = String(94.25 * (1 - frac));
    const mm = Math.floor(left / 60), ss = Math.floor(left % 60);
    (ring.querySelector("span") as HTMLElement).textContent = mm >= 60 ? `${Math.floor(mm / 60)}:${pad(mm % 60)}` : `${mm}:${pad(ss)}`;
    ring.title = `${cd.title} – za ${mm} min`;
    ring.classList.toggle("soon", left < 120);
  };
  client.on("countdown", (m) => {
    const until = Number(m.until) || 0;
    cd = until > Date.now() / 1000 ? { until, total: Math.max(60, until - Date.now() / 1000), title: String(m.title || "") } : null;
    paintCount();
    if (cd && !cdTimer) cdTimer = window.setInterval(paintCount, 1000);   // ticks only while a countdown runs
  });

  // 3.20 Zdraví+ a Učení+ in the notch: (242) breathing, (258) the water glass, (374) speed reading, (245) quiet hints
  const panel = document.createElement("div");
  panel.className = "x-panel";
  panel.hidden = true;
  shape.append(panel);
  let panelTimer = 0;
  const hide = () => { panel.hidden = true; panel.replaceChildren(); window.clearTimeout(panelTimer); };
  const show = (ms: number) => { panel.hidden = false; window.clearTimeout(panelTimer); panelTimer = window.setTimeout(hide, ms); };
  client.on("breathe", (m) => {
    const steps = (Array.isArray(m.steps) ? m.steps : []) as { say: string; s: number }[];
    const rounds = Math.max(1, Number(m.rounds) || 1);
    if (!steps.length) return;
    const ring = document.createElement("div");
    ring.className = "x-breathe";
    const say = document.createElement("span");
    panel.replaceChildren(ring, say);
    let i = 0;
    const total = steps.reduce((a, b) => a + b.s, 0) * rounds * 1000;
    show(total + 1500);
    const next = () => {
      if (panel.hidden || i >= steps.length * rounds) { hide(); return; }
      const st = steps[i % steps.length];
      say.textContent = st.say;
      ring.style.transition = `transform ${st.s}s ease-in-out`;
      ring.style.transform = st.say.startsWith("nádech") ? "scale(1.6)" : st.say.startsWith("výdech") ? "scale(.6)" : ring.style.transform;
      i += 1;
      window.setTimeout(next, st.s * 1000);
    };
    next();
  });
  client.on("water_glass", (m) => {
    const goal = Math.max(1, Number(m.goal) || 8), n = Math.max(0, Number(m.n) || 0);
    const glass = document.createElement("div");
    glass.className = "x-glass";
    const fill = document.createElement("i");
    fill.style.height = `${Math.min(100, (n / goal) * 100)}%`;
    glass.append(fill);
    const txt = document.createElement("span");
    txt.textContent = `${n} / ${goal} sklenic`;
    panel.replaceChildren(glass, txt);
    show(5000);
  });
  client.on("rsvp", (m) => {
    const words = (Array.isArray(m.words) ? m.words : []).map(String);
    const ms = Math.max(60, Number(m.ms) || 200);
    if (!words.length) return;
    const w = document.createElement("b");
    w.className = "x-rsvp";
    panel.replaceChildren(w);
    show(words.length * ms + 1500);
    let i = 0;
    const tick = () => {
      if (panel.hidden || i >= words.length) { hide(); return; }
      w.textContent = words[i++];
      window.setTimeout(tick, ms * (/[.!?]$/.test(w.textContent || "") ? 2 : 1));
    };
    tick();
  });
  client.on("notice_hint", (m) => {
    const t = document.createElement("span");
    t.textContent = String(m.text || "").slice(0, 60);
    panel.replaceChildren(t);
    show(6000);
  });

  // 3.20 (207) a savings goal moved: a thin bar with its percentage for a few seconds
  const goal = document.createElement("div");
  goal.className = "x-goal";
  goal.hidden = true;
  shape.append(goal);
  let goalTimer = 0;
  client.on("savings_goal", (m) => {
    const pct = Math.max(0, Math.min(100, Number(m.pct) || 0));
    goal.replaceChildren(Object.assign(document.createElement("i"), { style: `width:${pct}%` }),
      Object.assign(document.createElement("span"), { textContent: `${String(m.name || "Cíl").slice(0, 24)} ${pct} %` }));
    goal.hidden = false;
    window.clearTimeout(goalTimer);
    goalTimer = window.setTimeout(() => { goal.hidden = true; }, 8000);
  });

  // (143) ♥ the heart rate from the watch while you play (gone 20 s after the last sample)
  const hr = document.createElement("div");
  hr.className = "x-hr";
  hr.hidden = true;
  shape.append(hr);
  let hrTimer = 0;
  client.on("hr_now", (m) => {
    const bpm = Number(m.bpm) || 0;
    if (!bpm) return;
    hr.textContent = `♥ ${bpm}`;
    hr.classList.toggle("high", bpm >= 140);
    hr.hidden = false;
    window.clearTimeout(hrTimer);
    hrTimer = window.setTimeout(() => { hr.hidden = true; }, 20_000);
  });

  // ---------- (108) weather scene, (111) the day's timeline, (115) a second clock
  // inside the shape's clipped layer: they follow the rounded outline instead of the box (the box is a few px taller
  // than the island and has square corners – a line there showed under the card)
  const scene = h("div", { class: "x-weather", "aria-hidden": "true" });
  const line = h("div", { class: "x-timeline", "aria-hidden": "true", hidden: true }, h("i", { class: "now" }));
  const edge = h("div", { class: "x-ring", "aria-hidden": "true" });   // (102) urgent red, (106) the season's tint
  const clock2 = h("div", { class: "x-clock2", hidden: true });
  const inner = shape.querySelector(".n-inner") || shape;
  inner.prepend(scene);
  inner.append(line, edge);
  shape.append(clock2);
  client.on("weather_now", (m) => {
    if (settings?.notch?.weather_scene === false) { delete shape.dataset.weather; return; }
    if (m.scene) shape.dataset.weather = String(m.scene); else delete shape.dataset.weather;
  });
  let tl: any = null;
  const paintLine = () => {
    if (!tl || settings?.notch?.timeline === false) { line.hidden = true; return; }
    line.hidden = false;
    const s = Number(tl.day_start), e = Number(tl.day_end), now = Date.now() / 1000;
    const pct = (t: number) => `${Math.max(0, Math.min(100, ((t - s) / (e - s)) * 100))}%`;
    (line.querySelector(".now") as HTMLElement).style.width = pct(now);
    line.querySelectorAll(".ev").forEach((x) => x.remove());
    for (const ev of tl.events || []) {
      const el = h("b", { class: "ev", title: String(ev.title || "") });
      el.style.left = pct(Number(ev.start));
      el.style.width = `calc(${pct(Number(ev.end))} - ${pct(Number(ev.start))})`;
      line.append(el);
    }
  };
  client.on("day_timeline", (m) => { tl = m; paintLine(); });
  window.setInterval(paintLine, 60000);
  let tz = "", tzLabel = "";
  const paintClock = () => {
    const want = tz || settings?.notch?.second_tz || "";
    if (!want) { clock2.hidden = true; return; }
    try {
      const t = new Intl.DateTimeFormat("cs-CZ", { hour: "2-digit", minute: "2-digit", timeZone: want }).format(new Date());
      clock2.textContent = `${tzLabel || want.split("/").pop()?.replace("_", " ")} ${t}`;
      clock2.hidden = false;
    } catch { clock2.hidden = true; }
  };
  client.on("second_clock", (m) => { tz = String(m.tz || ""); tzLabel = String(m.label || ""); paintClock(); });
  window.setInterval(paintClock, 30000);

  // ---------- (112) Mochi stretches
  client.on("mochi_action", (m) => { if (m.action) blob.play({ name: String(m.action), id: Date.now() }); });

  // ---------- (110) several notches: only the one you work on shows notices
  client.on("notch_active", (m) => { if (myMonitor) shape.classList.toggle("passive", Number(m.monitor) !== myMonitor); });

  // ---------- settings: zen (105), season (106), own theme (107), size by the monitor (109)
  const apply = (s: any) => {
    settings = s || settings;
    const n = settings?.notch || {}, a = settings?.appearance || {};
    shape.classList.toggle("zen", !!n.zen);
    document.documentElement.dataset.season = a.seasonal === false ? "" : season();
    applyCustomTheme(a);
    // (109) the closed island's size, not a CSS scale: the window region is cut from these numbers too, so a scaled
    // drawing would be clipped at the edges (the main script reads it when it sizes the closed / hover shape)
    shape.dataset.sizek = String(n.auto_size === false ? 1 : notchScale(window.screen.width, window.screen.height));
    paintLine();
    paintClock();
  };
  client.on("welcome", (m) => apply(m.settings));
  client.on("settings_changed", (m) => apply(m.settings));
}
