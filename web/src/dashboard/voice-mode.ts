// Focused voice conversation (spec §7): big character, live waveform, captions, hands-free follow-up.
// 3.15 (návrh 27): the 3D reactor behind Mochi, captions word by word (the spoken word lights up), full screen.
import { Blob } from "../character/blob";
import { h, icon } from "../shared/dom";
import { at } from "../shared/motion";
import type { JarvisClient } from "../shared/ws";
import { mountReactor3d } from "../hud/reactor3d";

export function buildVoiceMode(client: JarvisClient) {
  const face = new Blob({ size: 280 });
  const canvas = h("canvas", { class: "vm-wave", width: 640, height: 90, "aria-hidden": "true" }) as HTMLCanvasElement;
  const you = h("p", { class: "vm-you" });
  const answer = h("p", { class: "vm-answer" });
  const state = h("p", { class: "vm-state" }, "Klepni na mikrofon nebo řekni „Hey Jarvis“.");
  const talk = h("button", { class: "vm-talk", type: "button", "aria-label": "Mluvit", onclick: () => client.send("push_to_talk") }, icon("microphone", "ph-fill"));
  const stop = h("button", { class: "btn ghost", type: "button", onclick: () => client.send("stop_all") }, icon("hand-palm"), "Stop");
  const levels: number[] = new Array(64).fill(0);
  let active = false;
  let raf = 0;
  let mood = "idle";

  const draw = () => {
    raf = active ? requestAnimationFrame(draw) : 0;
    const g = canvas.getContext("2d");
    if (!g) return;
    const w = canvas.width, hh = canvas.height, bw = w / levels.length;
    g.clearRect(0, 0, w, hh);
    g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent") || "#4f8dff";
    levels.forEach((v, i) => {
      const bar = Math.max(3, v * hh * 2.4);
      g.globalAlpha = 0.35 + Math.min(0.65, v * 3);
      g.fillRect(i * bw + 2, (hh - bar) / 2, bw - 4, bar);
    });
    levels.push(levels.shift()! * 0.9);
    levels[levels.length - 1] *= 0.92;
  };

  const LABEL: Record<string, string> = {
    listening: "Poslouchám…", thinking: "Přemýšlím…", working: "Pracuji…", speaking: "Mluvím…", waiting: "Potřebuji potvrzení",
  };
  client.on("mood", (m) => {
    if (m.mood === "speaking" && mood !== "speaking") { speakT = 0; window.setTimeout(speakNext, 250); }
    if (m.mood !== "speaking") { window.clearTimeout(speakT); speakT = 0; words.forEach((w) => w.classList.remove("now")); }
    mood = m.mood;
    face.setMood(m.mood, m);
    state.textContent = LABEL[m.mood] || "Klepni na mikrofon nebo řekni „Hey Jarvis“.";
    talk.classList.toggle("on", m.mood === "listening");
  });
  client.on("state", (m) => { if (m.state === "listening" && m.followup) state.textContent = "Poslouchám dál – můžeš navázat…"; });
  client.on("level", (m) => { face.setLevel(m.rms || 0); levels[levels.length - 1] = Math.max(levels[levels.length - 1], m.rms || 0); });
  client.on("transcript", (m) => { if (m.text) you.textContent = `„${m.text}“`; });
  client.on("user_message", (m) => { you.textContent = m.text ? `„${m.text}“` : ""; resetWords(); });
  // captions word by word: new words fade in; while JARVIS speaks, the word he is saying lights up
  let words: HTMLElement[] = [], said = 0, pending = "", speakT = 0;
  const addWords = (text: string) => {
    pending += text;
    const parts = pending.split(/(\s+)/);
    pending = parts.pop() || "";
    for (const p of parts) {
      if (!p.trim()) { answer.append(p); continue; }
      const w = h("span", { class: "vm-w" }, p.replace(/[*_#`>]/g, ""));
      words.push(w);
      answer.append(w);
    }
  };
  const resetWords = () => { words = []; said = 0; pending = ""; answer.replaceChildren(); window.clearTimeout(speakT); };
  const speakNext = () => {
    if (mood !== "speaking" || said >= words.length) return;
    words[said - 1]?.classList.remove("now");
    const w = words[said++];
    w.classList.add("now", "said");
    speakT = window.setTimeout(speakNext, 140 + (w.textContent || "").length * 62);   // about the pace of the voice
  };
  client.on("assistant_delta", (m) => { addWords(m.text || ""); if (mood === "speaking" && !speakT) speakNext(); });
  client.on("assistant_done", (m) => {
    if (!words.length) { resetWords(); addWords(String(m.text || "") + " "); } else addWords(" ");
  });
  client.on("welcome", (m) => { if (m.settings?.character) { face.setColor(m.settings.character.color, m.settings.character.glow || undefined); face.setCharacter(m.settings.character); } });

  const rxHost = h("div", { class: "vm-reactor", "aria-hidden": "true" });
  let rxOff: (() => void) | null = null;
  const full = h("button", { class: "btn ghost", type: "button", onclick: () => {
    if (document.fullscreenElement) void document.exitFullscreen(); else void el.requestFullscreen?.().catch(() => {});
  } }, icon("corners-out"), "Celá obrazovka");
  const el = h("section", { class: "voice-mode" },
    h("div", { class: "vm-stage" }, rxHost, face.el), canvas, state, you, answer,
    h("div", { class: "vm-controls" }, talk, stop, full),
    h("p", { class: "help" }, "V hlasovém režimu JARVIS po odpovědi ještě chvíli poslouchá, takže můžeš rovnou navázat. Ukončíš „díky, to je vše“."));
  return {
    el,
    show() {
      active = true; client.send("voice_mode", { on: true }); if (!raf) draw(); void mood;
      if (!rxOff && at("high")) void mountReactor3d(rxHost, () => ({ mood, level: levels[levels.length - 1] * 6 })).then((d) => { rxOff = d; });
    },
    hide() {
      if (active) client.send("voice_mode", { on: false }); active = false;
      rxOff?.(); rxOff = null;
      if (document.fullscreenElement === el) void document.exitFullscreen();
    },
  };
}
