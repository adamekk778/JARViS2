// 3.14 EDITH (návrh 6): the phone's camera, live. Point it at something and pick what you want: what it is, read it,
// translate a sign, guess the size. "Živě" describes the scene again whenever it changes (every few seconds at most).
// The frame goes to your PC's JARVIS and its AI; nothing is stored. The answer is shown and read aloud.
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import { native } from "./native";
import "./edith.css";

const MODES: [string, string, string][] = [["see", "eye", "Co vidím"], ["read", "text-aa", "Přečti"], ["translate", "translate", "Přelož"],
  ["identify", "magnifying-glass", "Co to je"], ["measure", "ruler", "Změř"]];

function say(text: string) {
  try {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "cs-CZ";
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  } catch { /* no speech on this phone: the text is on the screen */ }
}

export function openEdith(c: JarvisClient) {
  let mode = "see", live = false, busy = false, stream: MediaStream | null = null, timer = 0, reqId = "";
  let prev: Uint8ClampedArray | null = null;
  const video = h("video", { class: "ed-video", autoplay: true, playsinline: true, muted: true }) as HTMLVideoElement;
  const answer = h("p", { class: "ed-answer", "aria-live": "polite" }, "Namiř kameru a klepni na spoušť.");
  const question = h("input", { class: "input ed-q", placeholder: "Vlastní otázka (nepovinné)", "aria-label": "Otázka k obrazu" }) as HTMLInputElement;
  const chips = h("div", { class: "ed-modes", role: "radiogroup", "aria-label": "Co dělat" }, ...MODES.map(([k, ic, label]) =>
    h("button", { type: "button", role: "radio", "aria-checked": String(k === mode), class: `ed-mode ${k === mode ? "on" : ""}`, "data-k": k,
      onclick: () => { mode = k; chips.querySelectorAll("button").forEach((b) => { const on = (b as HTMLElement).dataset.k === k; b.classList.toggle("on", on); b.setAttribute("aria-checked", String(on)); }); } },
      icon(ic), label)));
  const liveBtn = h("button", { type: "button", class: "ed-live", "aria-pressed": "false", onclick: () => toggleLive() }, icon("broadcast"), "Živě");
  const shutter = h("button", { type: "button", class: "ed-shutter", "aria-label": "Zeptat se na tenhle obraz", onclick: () => ask() });
  const close = h("button", { type: "button", class: "ed-close", "aria-label": "Zavřít EDITH", onclick: () => end() }, icon("x"));
  // 3.15 EDITH in augmented reality: a scan line sweeps while it looks, then the things it talks about get brackets
  // and labels pinned right over the live picture
  const ar = h("div", { class: "ed-ar", "aria-hidden": "true" });
  const scan = h("i", { class: "ed-scan", hidden: true });
  const el = h("div", { class: "ed", role: "dialog", "aria-label": "EDITH – kamera" }, video, ar, scan,
    h("div", { class: "ed-top" }, h("strong", {}, "EDITH"), liveBtn, close),
    h("div", { class: "ed-bottom" }, answer, question, chips, shutter));
  document.body.append(el);

  const canvas = document.createElement("canvas");
  function frame(max = 1024): string {
    const w = video.videoWidth || 1280, hgt = video.videoHeight || 720;
    const k = Math.min(1, max / Math.max(w, hgt));
    canvas.width = Math.round(w * k); canvas.height = Math.round(hgt * k);
    canvas.getContext("2d")!.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.72);
  }
  function changed(): boolean {                       // a tiny grey picture compared with the last one
    const s = document.createElement("canvas");
    s.width = 48; s.height = 36;
    const g = s.getContext("2d", { willReadFrequently: true })!;
    g.drawImage(video, 0, 0, 48, 36);
    const px = g.getImageData(0, 0, 48, 36).data;
    let diff = 0;
    if (prev) for (let i = 0; i < px.length; i += 4) if (Math.abs(px[i] - prev[i]) > 30) diff++;
    const first = !prev;
    prev = new Uint8ClampedArray(px);
    return first || diff > 48 * 36 * 0.18;
  }
  function ask() {
    if (busy || !video.videoWidth) return;
    busy = true;
    reqId = Math.random().toString(36).slice(2, 9);
    answer.textContent = "Dívám se…";
    scan.hidden = false;
    ar.replaceChildren();
    native.haptic();
    c.send("edith_ask", { id: reqId, image: frame(), mode, question: question.value.trim() });
  }
  function toggleLive() {
    live = !live;
    liveBtn.classList.toggle("on", live);
    liveBtn.setAttribute("aria-pressed", String(live));
    window.clearInterval(timer);
    if (live) timer = window.setInterval(() => { if (!busy && changed()) ask(); }, 4000);
  }
  /** Normalised boxes (0–1 of the frame) → the screen, where the video is scaled to cover the whole view. */
  function drawObjects(objs: { label: string; box: number[] }[]) {
    ar.replaceChildren();
    const vw = video.videoWidth || 1280, vh = video.videoHeight || 720;
    const cw = el.clientWidth, ch = el.clientHeight;
    const k = Math.max(cw / vw, ch / vh), dw = vw * k, dh = vh * k, ox = (cw - dw) / 2, oy = (ch - dh) / 2;
    objs.forEach((o, i) => {
      const [x0, y0, x1, y1] = o.box;
      const box = h("div", { class: "ed-box", style: { left: `${ox + x0 * dw}px`, top: `${oy + y0 * dh}px`, width: `${(x1 - x0) * dw}px`,
        height: `${(y1 - y0) * dh}px`, "--i": String(i) } }, h("span", { class: "ed-tag" }, o.label));
      ar.append(box);
    });
    if (objs.length) native.haptic();
  }
  const off = c.on("edith_answer", (m: any) => {
    if (m.id && m.id !== reqId) return;
    busy = false;
    scan.hidden = true;
    if (m.error) { answer.textContent = `Nejde to: ${m.error}`; return; }
    answer.textContent = m.text || "…";
    if (Array.isArray(m.objects)) drawObjects(m.objects);
    if (m.text) say(m.text);
  });
  function end() {
    window.clearInterval(timer);
    stream?.getTracks().forEach((t) => t.stop());
    try { speechSynthesis.cancel(); } catch { /* fine */ }
    off();
    el.remove();
  }
  navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 } }, audio: false })
    .then((s) => { stream = s; video.srcObject = s; })
    .catch(() => { toast("Kamera není povolená – povol ji JARVISovi v nastavení telefonu.", "error"); end(); });
  return { end };
}
