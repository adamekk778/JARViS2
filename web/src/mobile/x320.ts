// 3.20 Telefon + Hodinky in the phone app (nápady 121–160):
//  (123) režim v autě – big buttons when the phone joins the car's Bluetooth
//  (124) telefon jako touchpad, (126) diktování do PC (the phone as the PC's microphone)
//  (129) offline povely – a few rules the phone does by itself when neither the PC nor the internet answers (no AI)
//  (135) sken dokumentu do PDF, (136) webkamera pro PC
import { h, icon, toast } from "../shared/dom";
import { Recorder } from "../shared/recorder";
import type { JarvisClient } from "../shared/ws";
import { native } from "./native";
import { offlineRule as rule, type OfflineAnswer } from "./offlinerules";
import "./x320.css";

// ------------------------------------------------------------------ (129) offline rules (pure logic in offlinerules.ts)
export function offlineRule(text: string, now = new Date()): OfflineAnswer | null {
  return rule(text, (title, body, at) => { void native.notifyAt(title, body, at); }, now);
}

// ------------------------------------------------------------------ (123) režim v autě
export function drivingMode(c: JarvisClient, talk: () => void): void {
  let box: HTMLElement | null = null;
  const close = () => { box?.remove(); box = null; };
  c.on("driving", (m: any) => {
    if (!m.on) { close(); return; }
    if (box) return;
    const big = (label: string, ic: string, fn: () => void) =>
      h("button", { class: "x-drive-btn", type: "button", onclick: () => { native.haptic(); fn(); } }, icon(ic, "ph-fill"), h("span", {}, label));
    box = h("div", { class: "x-drive", role: "dialog", "aria-label": "Režim v autě" },
      h("div", { class: "x-drive-title" }, icon("steering-wheel"), "Režim v autě", m.car ? h("small", {}, ` · ${m.car}`) : ""),
      big("Mluvit", "microphone", talk),
      big("Přečti zprávy", "chat-text", () => c.send("user_text", { text: "Přečti mi nahlas nové zprávy z telefonu, krátce." })),
      big("Cesta domů", "navigation-arrow", () => c.send("user_text", { text: "Kdy budu doma a jaká je doprava?" })),
      big("Konec", "x", close));
    document.body.append(box);
  });
}

// ------------------------------------------------------------------ (124) touchpad
function openTouchpad(c: JarvisClient): void {
  c.send("remote_start");
  const pad = h("div", { class: "x-pad", "aria-label": "Touchpad PC" }, h("span", {}, "Táhni prstem · ťukni = klik · dva prsty = posun"));
  const bar = h("div", { class: "x-pad-bar" },
    h("button", { class: "btn", type: "button", onclick: () => c.send("remote_input", { kind: "right_here" }) }, "Pravé tlačítko"),
    h("button", { class: "btn", type: "button", onclick: () => c.send("remote_input", { kind: "double_here" }) }, "Dvojklik"),
    h("button", { class: "btn danger", type: "button", onclick: () => done() }, "Konec"));
  const shell = h("div", { class: "x-pad-shell" }, pad, bar);
  let lx = 0, ly = 0, moved = 0, two = false, lastY = 0, acc = { x: 0, y: 0 }, raf = 0, startAt = 0;
  const flush = () => {
    raf = 0;
    if (Math.abs(acc.x) + Math.abs(acc.y) < 1) return;
    c.send("remote_input", { kind: "rel", dx: Math.round(acc.x), dy: Math.round(acc.y) });
    acc = { x: 0, y: 0 };
  };
  pad.addEventListener("touchstart", (e) => {
    e.preventDefault();
    two = e.touches.length >= 2;
    lx = e.touches[0].clientX; ly = e.touches[0].clientY; lastY = ly; moved = 0; startAt = Date.now();
  }, { passive: false });
  pad.addEventListener("touchmove", (e) => {
    e.preventDefault();
    const t = e.touches[0];
    if (two) {
      const dy = t.clientY - lastY;
      if (Math.abs(dy) > 12) { c.send("remote_input", { kind: "scroll", dy: dy > 0 ? -2 : 2 }); lastY = t.clientY; }
      return;
    }
    const dx = t.clientX - lx, dy = t.clientY - ly;
    lx = t.clientX; ly = t.clientY;
    moved += Math.abs(dx) + Math.abs(dy);
    const speed = Math.hypot(dx, dy) > 12 ? 2.4 : 1.4;            // a quick swipe goes further
    acc.x += dx * speed; acc.y += dy * speed;
    if (!raf) raf = requestAnimationFrame(flush);
  }, { passive: false });
  pad.addEventListener("touchend", () => {
    if (!two && moved < 8 && Date.now() - startAt < 300) { c.send("remote_input", { kind: "click_here" }); native.haptic(); }
    two = false;
  });
  const done = () => { c.send("remote_stop"); shell.remove(); };
  document.body.append(shell);
}

// ------------------------------------------------------------------ (135) sken, (136) webkamera
async function scanDocument(c: JarvisClient): Promise<void> {
  const input = h("input", { type: "file", accept: "image/*", capture: "environment", multiple: true }) as HTMLInputElement;
  input.onchange = async () => {
    const files = Array.from(input.files || []);
    if (!files.length) return;
    toast(`Nahrávám ${files.length} ${files.length === 1 ? "stránku" : "stránky"}…`, "info", 2000);
    try {
      const aids: string[] = [];
      for (const f of files) aids.push((await c.upload(f, f.name || "stranka.jpg")).id);
      const r = await fetch(c.url("/api/phone/scan"), { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ aids, mode: "doc" }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || "Sken se nepovedl");
      toast(`PDF z ${j.pages} stránek je v souborech na PC.`, "ok", 4000);
      window.open(c.url(`/api/files/${j.id}`, true), "_blank");
    } catch (e: any) { toast(e.message || "Sken se nepovedl", "error"); }
  };
  input.click();
}

function webcam(c: JarvisClient, btn: HTMLButtonElement): () => void {
  let stream: MediaStream | null = null, timer = 0;
  const video = h("video", { class: "x-cam", muted: true, playsinline: true, autoplay: true }) as HTMLVideoElement;
  const canvas = document.createElement("canvas");
  const stop = () => {
    window.clearInterval(timer);
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
    video.remove();
    btn.textContent = "Webkamera pro PC";
  };
  return () => {
    if (stream) { stop(); return; }
    void (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: 1280, height: 720 }, audio: false });
      } catch { toast("Nemám přístup ke kameře", "error"); return; }
      video.srcObject = stream;
      btn.after(video);
      btn.textContent = "Vypnout webkameru";
      toast("Na PC: http://localhost:8765/api/phonecam.mjpg (OBS → Zdroj → Prohlížeč)", "info", 6000);
      let busy = false;
      timer = window.setInterval(() => {
        if (busy || !video.videoWidth) return;
        busy = true;
        canvas.width = Math.min(960, video.videoWidth);
        canvas.height = Math.round(canvas.width * video.videoHeight / video.videoWidth);
        canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((b) => {
          if (!b) { busy = false; return; }
          fetch(c.url("/api/phone/cam"), { method: "POST", body: b, headers: { "Content-Type": "image/jpeg" } })
            .catch(() => {}).finally(() => { busy = false; });
        }, "image/jpeg", 0.7);
      }, 125);                                                   // ~8 frames a second over the home network
    })();
  };
}

// ------------------------------------------------------------------ the card in "Více"
export function phoneToolsCard(c: JarvisClient): HTMLElement {
  const rec = new Recorder();
  const dictate = h("button", { class: "btn", type: "button" }, icon("microphone"), "Diktovat do PC (podrž)") as HTMLButtonElement;
  dictate.addEventListener("pointerdown", async (e) => {
    e.preventDefault();
    try { await rec.start(); dictate.classList.add("rec"); native.haptic(); } catch { toast("Nemám přístup k mikrofonu", "error"); }
  });
  const stopRec = async () => {
    if (!rec.active) return;
    dictate.classList.remove("rec");
    const blob = await rec.stop();
    if (!blob || blob.size < 1500) return;
    try {
      const att = await c.upload(blob, `diktat.${blob.type.includes("mp4") ? "m4a" : "webm"}`);
      c.send("voice_upload", { attachment_id: att.id, dictate: true });
      toast("Píšu na PC tam, kde je kurzor.", "ok", 1500);
    } catch (err: any) { toast(err.message || "Neodesláno", "error"); }
  };
  dictate.addEventListener("pointerup", stopRec);
  dictate.addEventListener("pointerleave", stopRec);
  const cam = h("button", { class: "btn", type: "button" }, icon("webcam"), "Webkamera pro PC") as HTMLButtonElement;
  cam.onclick = webcam(c, cam);
  return h("div", { class: "card" }, h("h2", {}, "Telefon jako…"),
    h("p", { class: "help" }, "Touchpad a diktování potřebují na PC povolené „Myš a klávesnice“ pro tenhle telefon."),
    h("div", { class: "btn-row x-tools" },
      h("button", { class: "btn", type: "button", onclick: () => openTouchpad(c) }, icon("hand-pointing"), "Touchpad"),
      dictate,
      h("button", { class: "btn", type: "button", onclick: () => { void scanDocument(c); } }, icon("scan"), "Skenovat do PDF"),
      cam));
}
