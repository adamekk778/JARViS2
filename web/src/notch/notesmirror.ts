/* 3.12 two small tools of the notch:
   Poznámky – sticky notes you just type into (saved by themselves, colours, pin, delete), kept on this PC.
   Zrcátko – a quick look at yourself through the camera before a video call. The camera turns on only while the
   mirror is on screen and stops by itself when you leave it, close the notch, or after two minutes. Nothing is
   recorded or sent anywhere, and the microphone is never used. */
import { h, icon } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import "./notesmirror.css";

const COLORS = ["yellow", "blue", "green", "pink", "violet"] as const;

export function createNotesView(client: JarvisClient) {
  let items: { id: number; text: string; color: string; ts: number; pinned: boolean }[] = [];
  let focusId = 0;
  const saveTimers = new Map<number, number>();
  const grid = h("div", { class: "qn-grid" });
  const el = h("div", { class: "qn" },
    h("div", { class: "sh-top" }, h("div", { class: "sh-title" }, icon("note", "ph-fill"), h("strong", {}, "Poznámky"),
      h("span", {}, "piš rovnou – ukládá se samo"))), grid);

  const add = () => { client.send("qnote_set", { text: "", ref: "new" }); };
  function card(n: (typeof items)[number]) {
    const ta = h("textarea", { class: "qn-text", placeholder: "Napiš poznámku…", "aria-label": "Poznámka", spellcheck: "true" }) as HTMLTextAreaElement;
    ta.value = n.text;
    ta.oninput = () => {
      window.clearTimeout(saveTimers.get(n.id));
      saveTimers.set(n.id, window.setTimeout(() => { n.text = ta.value; client.send("qnote_set", { id: n.id, text: ta.value }); }, 500));
    };
    ta.onblur = () => { if (saveTimers.has(n.id)) { window.clearTimeout(saveTimers.get(n.id)); saveTimers.delete(n.id); if (ta.value !== n.text) client.send("qnote_set", { id: n.id, text: ta.value }); } };
    const c = h("div", { class: `qn-card c-${n.color} ${n.pinned ? "pinned" : ""}`, "data-id": String(n.id) }, ta,
      h("div", { class: "qn-foot" },
        h("span", { class: "qn-dots" }, ...COLORS.map((col) => h("button", { type: "button", class: `qn-dot c-${col} ${col === n.color ? "on" : ""}`, "aria-label": `Barva ${col}`,
          onclick: () => client.send("qnote_set", { id: n.id, color: col }) }))),
        h("button", { type: "button", class: `sh-b ${n.pinned ? "on" : ""}`, title: n.pinned ? "Odepnout" : "Připnout nahoru", "aria-label": "Připnout",
          onclick: () => client.send("qnote_set", { id: n.id, pinned: !n.pinned }) }, icon("push-pin", n.pinned ? "ph-fill" : "")),
        h("button", { type: "button", class: "sh-b", title: "Smazat poznámku", "aria-label": "Smazat poznámku",
          onclick: () => { c.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: "scale(.9)" }], { duration: 180 }).onfinish = () => client.send("qnote_delete", { id: n.id }); } }, icon("trash"))));
    return c;
  }
  function paint() {
    const active = document.activeElement as HTMLElement | null;
    const typing = active?.classList.contains("qn-text") ? Number(active.closest(".qn-card")?.getAttribute("data-id")) : 0;
    if (typing && !focusId) return;              // never re-draw under your fingers; the list catches up on blur
    grid.replaceChildren(h("button", { type: "button", class: "qn-add", onclick: add }, icon("plus"), h("span", {}, "Nová poznámka")), ...items.map(card));
    if (focusId) {
      const ta = grid.querySelector(`.qn-card[data-id="${focusId}"] textarea`) as HTMLTextAreaElement | null;
      ta?.focus();
      focusId = 0;
    }
  }
  client.on("qnotes", (m) => { items = m.items || []; paint(); });
  client.on("qnote_saved", (m) => { focusId = Number(m.id) || 0; client.send("qnotes_get"); });
  grid.addEventListener("focusout", () => window.setTimeout(() => { if (!grid.contains(document.activeElement)) paint(); }, 50));
  return { el, refresh: () => client.send("qnotes_get"), add };
}

export function createMirror() {
  let stream: MediaStream | null = null, stopAt = 0, watch = 0;
  const video = h("video", { class: "mr-video", autoplay: true, muted: true, playsinline: true }) as HTMLVideoElement;
  const note = h("div", { class: "mr-note" });
  const live = h("span", { class: "mr-live", hidden: true }, h("i"), "Kamera zapnutá");
  const btn = h("button", { type: "button", class: "mr-btn" });
  const el = h("div", { class: "mr" }, h("div", { class: "mr-frame" }, video, note, live), h("div", { class: "mr-bar" },
    h("span", {}, "Kamera běží jen tady a sama se vypne. Nic se nenahrává."), btn));

  async function start() {
    if (stream) return;
    note.replaceChildren(h("i", { class: "mh-spin" }), h("span", {}, "Zapínám kameru…"));
    note.hidden = false;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" }, audio: false });
      if (!el.isConnected) { stop(); return; }       // you already left
      video.srcObject = stream;
      note.hidden = true;
      live.hidden = false;
      stopAt = Date.now() + 120_000;
      window.clearInterval(watch);
      watch = window.setInterval(() => {               // off when hidden (notch closed / another section) or after 2 min
        if (!el.isConnected || el.offsetParent === null || document.hidden || Date.now() > stopAt) stop();
      }, 800);
    } catch (e: any) {
      stream = null;
      note.replaceChildren(icon("camera-slash"), h("strong", {}, "Kamera nejde zapnout"),
        h("span", {}, /denied|allowed|permission/i.test(String(e?.name || e?.message)) ? "Povol JARVISovi kameru, až se Windows zeptá (nebo v Nastavení → Soukromí → Kamera)." : "Žádná kamera nebo ji teď používá jiná aplikace."));
      note.hidden = false;
    }
    paintBtn();
  }
  function stop() {
    window.clearInterval(watch);
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
    video.srcObject = null;
    live.hidden = true;
    if (el.isConnected) { note.replaceChildren(icon("camera"), h("strong", {}, "Zrcátko"), h("span", {}, "Podívej se, jak vypadáš, než se připojíš do hovoru.")); note.hidden = false; }
    paintBtn();
  }
  function paintBtn() {
    btn.replaceChildren(icon(stream ? "stop" : "camera", "ph-fill"), h("span", {}, stream ? "Vypnout" : "Zapnout"));
    btn.onclick = () => (stream ? stop() : start());
  }
  stop();
  return { el, start, stop };
}
