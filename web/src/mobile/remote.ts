// 3.12 Vzdálená plocha v telefonu: the PC screen full-screen on the phone, driven with a finger.
// Tap = click, two quick taps = double-click, hold = right click, drag = drag, two fingers up/down = scroll,
// the keyboard button types on the PC. The PC shows a frame and "Telefon ovládá PC" the whole time.
import "./remote.css";
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import { native } from "./native";

const KEYS: [string, string][] = [["esc", "Esc"], ["tab", "Tab"], ["enter", "Enter"], ["win", "Start"], ["alttab", "Alt+Tab"],
  ["copy", "Kopírovat"], ["paste", "Vložit"], ["undo", "Zpět"], ["desktop", "Plocha"], ["close", "Zavřít okno"],
  ["voldown", "Tišeji"], ["volup", "Hlasitěji"]];

export function openRemote(c: JarvisClient, ep: { base: string; token: string }): () => void {
  const img = h("img", { class: "rd-img", alt: "Obrazovka PC", draggable: "false" }) as HTMLImageElement;
  img.src = `${ep.base}/api/screen/stream?token=${encodeURIComponent(ep.token)}&t=${Date.now()}`;
  const typer = h("input", { class: "rd-typer", type: "text", autocomplete: "off", autocapitalize: "off", "aria-label": "Psát na PC" }) as HTMLInputElement;
  const keys = h("div", { class: "rd-keys", hidden: true },
    ...KEYS.map(([k, label]) => h("button", { type: "button", onclick: () => { send({ kind: "key", key: k }); native.haptic(); } }, label)));
  const dot = h("span", { class: "rd-dot" });
  const close = () => { c.send("remote_stop"); done(); };
  const bar = h("div", { class: "rd-bar" },
    h("button", { type: "button", class: "rd-b", "aria-label": "Ukončit", onclick: close }, icon("x")),
    h("span", { class: "rd-title" }, dot, "Ovládáš PC"),
    h("button", { type: "button", class: "rd-b", "aria-label": "Klávesy", onclick: () => { keys.hidden = !keys.hidden; } }, icon("command")),
    h("button", { type: "button", class: "rd-b", "aria-label": "Klávesnice", onclick: () => { typer.value = ""; typer.focus(); } }, icon("keyboard")));
  const stage = h("div", { class: "rd-stage" }, img);
  const root = h("div", { class: "rd", role: "dialog", "aria-label": "Vzdálená plocha" }, bar, stage, keys, typer);
  document.body.append(root);

  function send(m: Record<string, unknown>) { c.send("remote_input", m); }

  /** finger position → 0–1 on the PC screen (the picture is letterboxed inside the stage) */
  function norm(x: number, y: number): { x: number; y: number } | null {
    const r = img.getBoundingClientRect();
    const iw = img.naturalWidth || 16, ih = img.naturalHeight || 9;
    const scale = Math.min(r.width / iw, r.height / ih);
    const w = iw * scale, hgt = ih * scale;
    const ox = r.left + (r.width - w) / 2, oy = r.top + (r.height - hgt) / 2;
    const nx = (x - ox) / w, ny = (y - oy) / hgt;
    return nx < 0 || ny < 0 || nx > 1 || ny > 1 ? null : { x: +nx.toFixed(4), y: +ny.toFixed(4) };
  }

  let start: { x: number; y: number; t: number } | null = null;
  let moved = false, held = false, two = false, lastTap = 0, lastTwoY = 0;
  let holdTimer = 0, tapTimer = 0;
  stage.addEventListener("touchstart", (e) => {
    e.preventDefault();
    if (e.touches.length >= 2) {
      two = true; clearTimeout(holdTimer);
      lastTwoY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
      return;
    }
    const t = e.touches[0];
    start = { x: t.clientX, y: t.clientY, t: Date.now() };
    moved = held = two = false;
    holdTimer = window.setTimeout(() => {
      if (!moved && start) { const p = norm(start.x, start.y); if (p) { held = true; send({ kind: "right", ...p }); native.haptic(); } }
    }, 550);
  }, { passive: false });
  stage.addEventListener("touchmove", (e) => {
    e.preventDefault();
    if (two && e.touches.length >= 2) {
      const y = (e.touches[0].clientY + e.touches[1].clientY) / 2;
      const steps = Math.trunc((y - lastTwoY) / 28);
      if (steps) { send({ kind: "scroll", dy: steps * 3 }); lastTwoY += steps * 28; }
      return;
    }
    const t = e.touches[0];
    if (start && Math.hypot(t.clientX - start.x, t.clientY - start.y) > 12) { moved = true; clearTimeout(holdTimer); }
  }, { passive: false });
  stage.addEventListener("touchend", (e) => {
    e.preventDefault();
    clearTimeout(holdTimer);
    if (two) { if (e.touches.length === 0) two = false; return; }
    if (!start || held) { start = null; return; }
    const t = e.changedTouches[0];
    const a = norm(start.x, start.y);
    if (moved) {                                              // a drag: from where the finger started to where it let go
      const b = norm(t.clientX, t.clientY);
      if (a && b) send({ kind: "drag", x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    } else if (a) {
      const now = Date.now();
      if (now - lastTap < 300) { clearTimeout(tapTimer); lastTap = 0; send({ kind: "double", ...a }); }
      else { lastTap = now; tapTimer = window.setTimeout(() => send({ kind: "tap", ...a }), 260); }
      native.haptic();
    }
    start = null;
  }, { passive: false });

  // the phone keyboard types on the PC (letters as text, Enter / Backspace as keys)
  typer.addEventListener("input", () => {
    if (typer.value) { send({ kind: "text", text: typer.value }); typer.value = ""; }
  });
  typer.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); send({ kind: "key", key: "enter" }); }
    else if (e.key === "Backspace") { e.preventDefault(); send({ kind: "key", key: "backspace" }); }
  });
  img.onerror = () => { dot.classList.add("off"); };
  img.onload = () => { dot.classList.remove("off"); };

  const off = c.on("remote_desk", (m) => { if (!m.on) { toast("Vzdálená plocha skončila", "info"); done(); } });
  let closed = false;
  function done() {
    if (closed) return;
    closed = true;
    off?.();
    img.src = "";
    root.remove();
  }
  return done;
}
