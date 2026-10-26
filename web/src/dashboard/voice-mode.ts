// Focused voice conversation (spec §7): big character, live waveform, captions, hands-free follow-up.
import { Blob } from "../character/blob";
import { h, icon } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";

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
    mood = m.mood;
    face.setMood(m.mood, m);
    state.textContent = LABEL[m.mood] || "Klepni na mikrofon nebo řekni „Hey Jarvis“.";
    talk.classList.toggle("on", m.mood === "listening");
  });
  client.on("state", (m) => { if (m.state === "listening" && m.followup) state.textContent = "Poslouchám dál – můžeš navázat…"; });
  client.on("level", (m) => { face.setLevel(m.rms || 0); levels[levels.length - 1] = Math.max(levels[levels.length - 1], m.rms || 0); });
  client.on("transcript", (m) => { if (m.text) you.textContent = `„${m.text}“`; });
  client.on("user_message", (m) => { you.textContent = m.text ? `„${m.text}“` : ""; answer.textContent = ""; });
  client.on("assistant_delta", (m) => { answer.textContent += m.text; });
  client.on("assistant_done", (m) => { answer.textContent = String(m.text || "").replace(/[*_#`>]/g, ""); });
  client.on("welcome", (m) => { if (m.settings?.character) { face.setColor(m.settings.character.color, m.settings.character.glow || undefined); face.setCharacter(m.settings.character); } });

  const el = h("section", { class: "voice-mode" },
    h("div", { class: "vm-stage" }, face.el), canvas, state, you, answer,
    h("div", { class: "vm-controls" }, talk, stop),
    h("p", { class: "help" }, "V hlasovém režimu JARVIS po odpovědi ještě chvíli poslouchá, takže můžeš rovnou navázat. Ukončíš „díky, to je vše“."));
  return {
    el,
    show() { active = true; client.send("voice_mode", { on: true }); if (!raf) draw(); void mood; },
    hide() { if (active) client.send("voice_mode", { on: false }); active = false; },
  };
}
