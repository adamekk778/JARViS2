/* 3.12 "Poslat na PC": pick files (or share them into JARVIS from the gallery) and they wait as cards. Swipe a card
   to the right and it flies to the PC – the PC on the right edge catches it, a ring shows the upload, a tick when it
   landed; the PC's notch shows it arriving. A short swipe springs back; "Poslat vše" works without swiping too. */
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import { native } from "./native";
import "./fling.css";

type Item = { blob: Blob; name: string; url: string; image: boolean };
const KB = (n: number) => (n >= 1 << 20 ? `${(n / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} kB`);
const FILE_ICON = (name: string, type: string) => (/^video\//.test(type) ? "film-strip" : /^audio\//.test(type) ? "music-notes" : /pdf$/i.test(name) ? "file-pdf"
  : /\.(docx?|odt|rtf)$/i.test(name) ? "file-doc" : /\.(xlsx?|csv|ods)$/i.test(name) ? "file-xls" : /\.(zip|rar|7z)$/i.test(name) ? "file-zip" : "file");

export function flingPad(c: JarvisClient) {
  let items: Item[] = [], busy = false, lastBump = 0, motionOn = false;
  const file = h("input", { type: "file", multiple: true, hidden: true }) as HTMLInputElement;
  const stack = h("div", { class: "fl-stack" });
  const ring = h("span", { class: "fl-ring" });
  const pc = h("span", { class: "fl-pc" }, icon("desktop", "ph-fill"));
  const target = h("div", { class: "fl-target", "aria-hidden": "true" }, ring, pc, h("b", {}, "PC"),
    h("span", { class: "fl-arrows" }, icon("caret-right", "ph-bold"), icon("caret-right", "ph-bold"), icon("caret-right", "ph-bold")));
  const hint = h("p", { class: "fl-hint" });
  // "přilož k monitoru": a little picture of the phone tapping the screen
  const guide = h("div", { class: "fl-guide", "aria-hidden": "true" }, h("span", { class: "fl-g-mon" }, icon("monitor", "ph-fill")), h("span", { class: "fl-g-ph" }, icon("device-mobile", "ph-fill")));
  const sendAll = h("button", { type: "button", class: "btn fl-all", onclick: () => sendNext(true) }, icon("paper-plane-tilt", "ph-fill"), "Poslat vše");
  const sheet = h("div", { class: "fl", role: "dialog", "aria-label": "Poslat na PC", hidden: true },
    h("div", { class: "fl-head" }, h("strong", {}, "Poslat na PC"),
      h("button", { type: "button", class: "icon-btn", "aria-label": "Zavřít", onclick: () => close() }, icon("x"))),
    guide, h("div", { class: "fl-stage" }, stack, target), hint,
    h("div", { class: "fl-actions" }, h("button", { type: "button", class: "btn", onclick: () => file.click() }, icon("plus"), "Přidat soubor"), sendAll), file);
  file.onchange = () => { add([...(file.files || [])].map((f) => ({ blob: f, name: f.name }))); file.value = ""; };

  function add(files: { blob: Blob; name: string }[]) {
    for (const f of files) items.push({ ...f, url: URL.createObjectURL(f.blob), image: /^image\//.test(f.blob.type) });
    open();
    paint();
  }
  function open() {
    if (!sheet.isConnected) document.body.append(sheet);
    sheet.hidden = false;
    if (!motionOn) { motionOn = true; window.addEventListener("devicemotion", onMotion); }
    paint();
  }
  function close() {
    if (busy) return;
    sheet.hidden = true;
    items.forEach((i) => URL.revokeObjectURL(i.url));
    items = [];
    if (motionOn) { motionOn = false; window.removeEventListener("devicemotion", onMotion); }
    ready();
  }
  /** the PC's notch waits ("Přilož telefon k monitoru") while files are ready here */
  let readySent = -1;
  function ready() {
    const n = sheet.hidden || document.hidden ? 0 : items.length;
    if (n === readySent) return;
    readySent = n;
    c.send("share_ready", { on: n > 0, count: n });
  }
  document.addEventListener("visibilitychange", ready);
  /** a tap of the phone against the monitor: a short, sharp jolt (the phone stops dead) → the top file goes */
  function onMotion(e: DeviceMotionEvent) {
    if (busy || sheet.hidden || !items.length || Date.now() - lastBump < 1500) return;
    const a = e.acceleration, g = e.accelerationIncludingGravity;
    const v = a && a.x != null ? Math.hypot(a.x || 0, a.y || 0, a.z || 0) : g && g.x != null ? Math.abs(Math.hypot(g.x || 0, g.y || 0, g.z || 0) - 9.81) : 0;
    if (v < 17) return;
    lastBump = Date.now();
    const top = stack.querySelector(".fl-card.top") as HTMLElement | null;
    if (top) fling(top, "tap");
  }
  function paint() {
    hint.replaceChildren(...(items.length
      ? [h("strong", {}, "Přilož telefon k monitoru"), h("span", {}, items.length > 1 ? `nebo švihni kartou doprava · zbývá ${items.length}` : "nebo švihni kartou doprava →")]
      : [h("span", {}, "Přidej soubor – fotku, video, dokument…")]));
    guide.hidden = !items.length;
    ready();
    sendAll.hidden = items.length < 2;
    stack.replaceChildren(...items.slice(0, 3).map((it, i) => {
      const card = h("div", { class: `fl-card ${i === 0 ? "top" : ""}` },
        it.image ? h("img", { src: it.url, alt: "" }) : h("div", { class: "fl-file" }, icon(FILE_ICON(it.name, it.blob.type), "ph-fill")),
        h("div", { class: "fl-meta" }, h("strong", {}, it.name), h("span", {}, KB(it.blob.size))));
      card.style.setProperty("--i", String(i));
      if (i === 0) drag(card);
      return card;
    }).reverse());
    if (!items.length) stack.append(h("button", { type: "button", class: "fl-empty", onclick: () => file.click() }, icon("upload-simple"), h("span", {}, "Vybrat soubor")));
  }

  /** the top card follows your finger; far enough (or fast enough) to the right = it flies to the PC */
  function drag(card: HTMLElement) {
    let x0 = 0, y0 = 0, t0 = 0, dx = 0, dy = 0, on = false, ticked = false;
    const w = () => stack.clientWidth || 300;
    card.addEventListener("pointerdown", (e) => {
      if (busy) return;
      on = true; ticked = false; x0 = e.clientX; y0 = e.clientY; t0 = performance.now(); dx = dy = 0;
      card.setPointerCapture(e.pointerId);
      card.style.transition = "none";
    });
    card.addEventListener("pointermove", (e) => {
      if (!on) return;
      dx = e.clientX - x0; dy = (e.clientY - y0) * 0.35;
      const p = Math.max(0, Math.min(1, dx / (w() * 0.42)));
      card.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx / 22}deg) scale(${1 - p * 0.06})`;
      target.style.setProperty("--p", p.toFixed(3));
      target.classList.toggle("ready", p >= 1);
      if (p >= 1 && !ticked) { ticked = true; native.haptic(); }
      if (p < 1) ticked = false;
    });
    const end = () => {
      if (!on) return;
      on = false;
      const vx = dx / Math.max(1, performance.now() - t0);
      target.classList.remove("ready");
      if (dx > w() * 0.42 || (dx > 40 && vx > 0.6)) fling(card);
      else {
        card.style.transition = "transform .45s cubic-bezier(.3, 1.5, .5, 1)";
        card.style.transform = "";
        target.style.setProperty("--p", "0");
      }
    };
    card.addEventListener("pointerup", end);
    card.addEventListener("pointercancel", end);
  }

  async function fling(card: HTMLElement, how: "swipe" | "tap" = "swipe") {
    const it = items[0];
    if (!it || busy) return;
    busy = true;
    native.haptic();
    const tr = target.getBoundingClientRect(), cr = card.getBoundingClientRect();
    const tx = tr.left + tr.width / 2 - (cr.left + cr.width / 2), ty = tr.top + tr.height / 2 - (cr.top + cr.height / 2);
    if (how === "tap") {                         // into the monitor: a flash, then the card sinks away from you
      sheet.classList.remove("flash"); void sheet.offsetWidth; sheet.classList.add("flash");
      card.style.transition = "transform .55s cubic-bezier(.4, 0, .2, 1), opacity .55s ease-in, filter .55s";
      card.style.transform = "perspective(700px) translateZ(-900px) rotateX(18deg)";
    } else {
      card.style.transition = "transform .42s cubic-bezier(.5, 0, .75, 0), opacity .42s ease-in, filter .42s";
      card.style.transform = `translate(${tx}px, ${ty}px) rotate(24deg) scale(.12)`;
    }
    card.style.opacity = "0";
    card.style.filter = "blur(2px)";
    window.setTimeout(() => target.classList.add("catch"), 360);
    target.classList.add("sending");
    target.style.setProperty("--p", "0");
    ring.style.setProperty("--up", "0");
    try {
      const att = await c.upload(it.blob, it.name, (p) => ring.style.setProperty("--up", String(Math.round(p * 100) / 100)));
      c.send("share", { kind: "file", attachment_id: att.id });
      ring.style.setProperty("--up", "1");
      target.classList.add("done");
      pc.replaceChildren(icon("check", "ph-bold"));
      native.haptic();
      URL.revokeObjectURL(it.url);
      items.shift();
      await new Promise((r) => window.setTimeout(r, 750));
    } catch (e: any) {
      toast(c.status === "open" ? `${it.name}: ${e?.message || "nepodařilo se"}` : "PC teď není připojené – zkus to za chvíli", "error", 4000);
      card.style.transition = "transform .5s cubic-bezier(.3, 1.5, .5, 1), opacity .3s";
      card.style.transform = ""; card.style.opacity = ""; card.style.filter = "";
    } finally {
      target.classList.remove("sending", "catch", "done");
      pc.replaceChildren(icon("desktop", "ph-fill"));
      busy = false;
      paint();
      if (!items.length) { toast("Hotovo – je to na PC", "ok", 1800); window.setTimeout(() => { if (!items.length) close(); }, 500); }
    }
  }
  async function sendNext(all = false) {
    const top = stack.querySelector(".fl-card.top") as HTMLElement | null;
    if (!top || busy) return;
    await fling(top);
    if (all && items.length) window.setTimeout(() => sendNext(true), 120);
  }
  return { open, add, pick: () => { open(); file.click(); } };
}
