// 3.15 Mega animace v telefonu (návrhy 32, 33): the app opens with the reactor powering up, the main buttons answer
// with a light tap of the vibration motor, and an SOS shows full screen – red rings, the countdown until your
// contacts get a message, and a big "Jsem v pořádku".
import { h, icon } from "../shared/dom";
import { at } from "../shared/motion";
import type { JarvisClient } from "../shared/ws";
import { native } from "./native";
import "./cinema.css";

/** The opening: once per app start, about a second, never in the way (a tap skips it). */
export function splash(): void {
  try { if (sessionStorage.getItem("jarvis.splash")) return; sessionStorage.setItem("jarvis.splash", "1"); } catch { /* fine */ }
  if (!at("eco")) return;
  const el = h("div", { class: "m-splash", "aria-hidden": "true" },
    h("div", { class: "ms-core" }, h("i", {}), h("i", {}), h("i", {}), h("b", {})), h("strong", {}, "J.A.R.V.I.S."));
  document.body.append(el);
  const done = () => { el.classList.add("out"); setTimeout(() => el.remove(), 500); };
  el.addEventListener("pointerdown", done);
  setTimeout(done, 1300);
}

/** A light tap under the finger on the buttons that matter (not on every scroll or text field). */
export function hapticTouch(): void {
  let last = 0;
  document.addEventListener("pointerdown", (e) => {
    const t = (e.target as HTMLElement)?.closest?.(".btn.primary, .btn.danger, .m-nav button, .m-tabs button, .ed-shutter, .send, .m-talk, [data-haptic]");
    if (!t || Date.now() - last < 90) return;
    last = Date.now();
    native.haptic();
  }, { passive: true });
}

/** The SOS countdown over everything, while the emergency protocol waits for "Jsem v pořádku". */
export function sosScreen(c: JarvisClient): void {
  let el: HTMLElement | null = null, timer = 0;
  const close = () => { window.clearInterval(timer); el?.classList.add("out"); const old = el; el = null; setTimeout(() => old?.remove(), 450); };
  c.on("emergency_state" as any, (m: any) => {
    if (!m.active) {
      if (el && m.alerted) {
        const sent = (m.sent || []).join(", ");
        el.querySelector(".sos-count")!.textContent = "✓";
        el.querySelector(".sos-text")!.textContent = sent ? `Napsal jsem: ${sent}.` : "Nemám komu napsat – nastav nouzové kontakty.";
        setTimeout(close, 6000);
      } else close();
      return;
    }
    if (el) return;
    const count = h("b", { class: "sos-count" }, "");
    const text = h("p", { class: "sos-text" }, `JARVIS: ${m.reason || "nouzový protokol"}. Když neodpovíš, napíšu tvým nouzovým kontaktům i s polohou.`);
    el = h("div", { class: "sos-screen", role: "alertdialog", "aria-label": "Nouzový protokol" },
      h("div", { class: "sos-rings", "aria-hidden": "true" }, h("i", {}), h("i", {}), h("i", {}), count),
      h("strong", {}, "JSI V POŘÁDKU?"), text,
      h("button", { class: "btn sos-ok", type: "button", onclick: () => { c.send("emergency_cancel" as any, {}); native.haptic(); close(); } },
        icon("check-circle", "ph-fill"), "Jsem v pořádku"),
      h("a", { class: "btn danger sos-112", href: "tel:112" }, icon("phone-call", "ph-fill"), "Volat 112"));
    document.body.append(el);
    native.haptic();
    const tick = () => {
      const left = Math.max(0, Math.round(Number(m.until || 0) - Date.now() / 1000));
      count.textContent = String(left);
      if (left <= 10 && left > 0) native.haptic();
    };
    tick();
    timer = window.setInterval(tick, 1000);
  });
}
