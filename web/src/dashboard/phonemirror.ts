// 3.12 Telefon na monitoru PC: the phone's screen in a window here; the mouse and keyboard drive the phone.
// Click = tap, hold = long press, drag = swipe, wheel = scroll, right click = Zpět, typing goes into the phone's field.
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import "./phonemirror.css";

let open = false;

export function openPhoneMirror(client: JarvisClient, base = ""): void {
  if (open) return;
  open = true;
  let ts = 0, alive = true, control = false, started = false;
  const img = h("img", { class: "pm-screen", alt: "Obrazovka telefonu", draggable: "false" }) as HTMLImageElement;
  const wait = h("div", { class: "pm-wait" }, icon("device-mobile", "ph-fill"),
    h("strong", {}, "Čekám na telefon…"), h("span", {}, "V telefonu povol sdílení obrazovky (Android se zeptá). Kdyby se nic neukázalo, otevři v telefonu JARVIS → Více → Telefon na monitoru PC → Spustit."));
  const hint = h("p", { class: "pm-hint" });
  const send = (m: Record<string, unknown>) => client.send("mirror_input", m);
  const btn = (ic: string, label: string, kind: string) =>
    h("button", { class: "btn", type: "button", title: label, onclick: () => { send({ kind }); stage.focus(); } }, icon(ic), h("span", {}, label));
  const stage = h("div", { class: "pm-stage", tabindex: "0" }, wait, img);
  const close = (stop: boolean) => {
    alive = false;
    open = false;
    if (stop) client.send("mirror_stop", {});
    off();
    layer.remove();
  };
  const layer = h("div", { class: "pm-layer", role: "dialog", "aria-label": "Telefon na monitoru PC" },
    h("div", { class: "pm-win" },
      h("header", { class: "pm-head" }, icon("device-mobile-camera", "ph-fill"), h("strong", {}, "Telefon na monitoru"),
        h("span", { class: "pm-spacer" }),
        h("button", { class: "icon-btn", type: "button", "aria-label": "Zavřít (telefon dál sdílí)", title: "Skrýt okno", onclick: () => close(false) }, icon("minus")),
        h("button", { class: "btn danger sm", type: "button", onclick: () => close(true) }, icon("stop"), "Ukončit")),
      stage,
      h("div", { class: "pm-keys" }, btn("arrow-u-up-left", "Zpět", "back"), btn("circle", "Domů", "home"),
        btn("squares-four", "Aplikace", "recents"), btn("bell", "Oznámení", "notifications")),
      hint));
  document.body.append(layer);
  stage.focus();

  // ---------- pictures ----------
  const pull = async () => {
    while (alive) {
      try {
        const r = await fetch(`${base}/api/phone/mirror/latest?after=${ts}`, { cache: "no-store" });
        if (r.status === 200) {
          ts = Number(r.headers.get("X-Ts")) || ts;
          const url = URL.createObjectURL(await r.blob());
          const old = img.src;
          img.src = url;
          if (old.startsWith("blob:")) setTimeout(() => URL.revokeObjectURL(old), 1000);
          if (!started) { started = true; wait.remove(); }
        } else if (r.status !== 204) await new Promise((ok) => setTimeout(ok, 1000));
      } catch {
        await new Promise((ok) => setTimeout(ok, 1000));
      }
    }
  };
  pull();
  const off = client.on("phone_mirror", (m) => {
    control = !!m.control;
    hint.textContent = !m.active ? "" : control ? "Klik = ťuknutí · podržet = dlouhý stisk · táhnout = přejetí · kolečko = posun · pravé tlačítko = Zpět · piš rovnou na klávesnici"
      : "Jen sledování. Ovládání myší zapneš v telefonu: JARVIS → Více → Telefon na monitoru PC → Povolit ovládání.";
    if (m.asked === false) toast("Telefon teď není připojený – otevři v něm JARVIS", "info");
    if (started && !m.active) { toast("Telefon přestal sdílet obrazovku", "info"); close(false); }
  });
  client.send("mirror_request", {});

  // ---------- mouse → the phone's finger ----------
  const pos = (e: MouseEvent) => {
    const r = img.getBoundingClientRect();
    return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height, ok: e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom };
  };
  let down: { x: number; y: number; t: number } | null = null;
  img.addEventListener("mousedown", (e) => { if (e.button === 0) { const p = pos(e); down = { x: p.x, y: p.y, t: performance.now() }; } e.preventDefault(); });
  window.addEventListener("mouseup", (e) => {
    if (!down || e.button !== 0) return;
    const p = pos(e), d = down, ms = performance.now() - d.t;
    down = null;
    if (Math.hypot((p.x - d.x) * img.width, (p.y - d.y) * img.height) > 12) send({ kind: "swipe", x1: d.x, y1: d.y, x2: p.x, y2: p.y, ms: Math.round(Math.min(1500, Math.max(120, ms))) });
    else send({ kind: ms > 550 ? "long" : "tap", x: d.x, y: d.y });
  });
  img.addEventListener("contextmenu", (e) => { e.preventDefault(); send({ kind: "back" }); });
  let wheelAt = 0;
  img.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (performance.now() - wheelAt < 250) return;                  // one swipe per notch burst
    wheelAt = performance.now();
    const p = pos(e as MouseEvent), dy = e.deltaY > 0 ? -0.25 : 0.25;
    send({ kind: "swipe", x1: p.x, y1: 0.5, x2: p.x, y2: Math.max(0.05, Math.min(0.95, 0.5 + dy)), ms: 220 });
  }, { passive: false });

  // ---------- keyboard → the phone's text field ----------
  let buf = "", timer = 0;
  const flush = () => { if (buf) { send({ kind: "text", text: buf }); buf = ""; } };
  stage.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    if (e.key === "Escape") { close(false); return; }
    if (e.key.length === 1) { buf += e.key; clearTimeout(timer); timer = window.setTimeout(flush, 150); }
    else if (e.key === "Backspace") { flush(); send({ kind: "backspace" }); }
    else if (e.key === "Enter") { flush(); send({ kind: "enter" }); }
    else return;
    e.preventDefault();
  });
  stage.addEventListener("paste", (e) => {
    const t = (e as ClipboardEvent).clipboardData?.getData("text") || "";
    if (t) { flush(); send({ kind: "text", text: t.slice(0, 500) }); e.preventDefault(); }
  });
}
