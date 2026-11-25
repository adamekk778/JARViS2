// 3.20 Vzhled+ in the HUD page:
//  (114) ?obs=1 – a see-through overlay for OBS (Zdroj → Prohlížeč): what JARVIS hears, thinks and says, nothing else.
//  (117) ?avatar=1 – a 3D character of JARVIS's own (an original glossy drop with eyes, no film assets) for the corner
//        of the screen instead of the notch: it floats, listens, thinks and talks with the voice's level.
import type * as THREE_NS from "three";

type Client = { on: (t: any, f: (m: any) => void) => void };
const q = new URLSearchParams(location.search);

export function isObs(): boolean { return q.get("obs") === "1"; }
export function isAvatar(): boolean { return q.get("avatar") === "1"; }
export function isGlasses(): boolean { return q.get("glasses") === "1"; }

/** 3.20 (159) ?glasses=1 – captions for smart glasses / a HUD browser: big white text on black (black = see-through on
 *  most glasses), only the last line you said and JARVIS's answer, nothing else. */
export function mountGlasses(client: Client, hide: HTMLElement): void {
  hide.style.display = "none";
  document.documentElement.classList.add("glasses");
  document.body.style.background = "#000";
  const said = document.createElement("div");
  said.className = "gl-said";
  const ans = document.createElement("div");
  ans.className = "gl-ans";
  const st = document.createElement("div");
  st.className = "gl-state";
  document.body.append(st, said, ans);
  let answer = "";
  const tail = (t: string, n: number) => (t.length > n ? "…" + t.slice(-n) : t);
  client.on("state", (m) => { st.textContent = STATE_TEXT[m.state] ?? ""; });
  client.on("transcript", (m) => { if (m.text) said.textContent = tail(String(m.text), 90); });
  client.on("user_message", (m) => { said.textContent = tail(String(m.text || ""), 90); answer = ""; ans.textContent = ""; });
  client.on("assistant_delta", (m) => { answer += m.text; ans.textContent = tail(answer.replace(/[#*_`>|]/g, ""), 160); });
  client.on("assistant_done", (m) => { answer = String(m.text || answer); ans.textContent = tail(answer.replace(/[#*_`>|]/g, ""), 160); });
  const style = document.createElement("style");
  style.textContent = `
    html.glasses,html.glasses body{background:#000;margin:0;height:100%;overflow:hidden}
    .gl-state{position:fixed;top:4vh;left:5vw;color:#4fc3ff;font:700 3.2vh/1 system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase}
    .gl-said{position:fixed;left:5vw;right:5vw;top:12vh;color:#9fb4c8;font:600 4.2vh/1.25 system-ui,sans-serif}
    .gl-ans{position:fixed;left:5vw;right:5vw;bottom:8vh;color:#fff;font:700 6vh/1.2 system-ui,sans-serif}`;
  document.head.append(style);
}

const STATE_TEXT: Record<string, string> = { listening: "Poslouchám", thinking: "Přemýšlím", acting: "Pracuji", speaking: "Mluvím", idle: "" };

export function mountObs(client: Client, hide: HTMLElement): void {
  hide.style.display = "none";
  document.documentElement.classList.add("obs");
  document.body.style.background = "transparent";
  const card = document.createElement("div");
  card.className = "obs-card";
  const st = document.createElement("div");
  st.className = "obs-state";
  const heard = document.createElement("div");
  heard.className = "obs-heard";
  const said = document.createElement("div");
  said.className = "obs-said";
  card.append(st, heard, said);
  document.body.append(card);
  let answer = "";
  client.on("state", (m) => { st.textContent = STATE_TEXT[m.state] ?? ""; card.dataset.state = m.state; });
  client.on("transcript", (m) => { if (m.text) heard.textContent = `„${String(m.text).slice(0, 160)}“`; });
  client.on("user_message", (m) => { heard.textContent = `„${String(m.text || "").slice(0, 160)}“`; answer = ""; said.textContent = ""; });
  client.on("assistant_delta", (m) => { answer += m.text; said.textContent = answer.replace(/[#*_`>]/g, "").slice(-280); });
  client.on("assistant_done", (m) => { answer = String(m.text || ""); said.textContent = answer.replace(/[#*_`>]/g, "").slice(0, 280); });
  const style = document.createElement("style");
  style.textContent = `
    .obs-card{position:fixed;left:24px;bottom:24px;max-width:min(560px,90vw);padding:14px 18px;border-radius:16px;
      background:rgba(6,10,16,.72);color:#e8f4ff;font:600 18px/1.35 Rajdhani,system-ui,sans-serif;
      box-shadow:0 0 0 1px rgba(79,195,255,.35) inset,0 0 30px rgba(79,195,255,.18)}
    .obs-state{color:#4fc3ff;font-size:13px;letter-spacing:.18em;text-transform:uppercase;min-height:16px}
    .obs-card[data-state="idle"] .obs-state{opacity:.4}
    .obs-heard{opacity:.75;font-size:15px;margin:4px 0}
    .obs-said:empty,.obs-heard:empty{display:none}`;
  document.head.append(style);
}

export async function mountAvatar(client: Client, hide: HTMLElement): Promise<boolean> {
  let THREE: typeof THREE_NS;
  try { THREE = await import("three"); } catch { return false; }
  hide.style.display = "none";
  document.body.style.background = "transparent";
  const canvas = document.createElement("canvas");
  canvas.className = "avatar3d";
  canvas.style.cssText = "position:fixed;inset:0;width:100vw;height:100vh";
  document.body.append(canvas);
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(35, 1, 0.1, 50);
  cam.position.set(0, 0.2, 5.2);
  scene.add(new THREE.HemisphereLight(0xcfe8ff, 0x101820, 1.2));
  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(2, 3, 4);
  scene.add(key);
  const bodyMat = new THREE.MeshPhysicalMaterial({ color: 0x4fc3ff, roughness: 0.18, metalness: 0.1, clearcoat: 1, transmission: 0.15,
    emissive: 0x0a2a44, emissiveIntensity: 0.6 });
  const body = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 48), bodyMat);
  body.scale.set(1, 1.08, 1);
  const eyeMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
  const eyes = [-0.33, 0.33].map((x) => {
    const e = new THREE.Mesh(new THREE.SphereGeometry(0.12, 24, 16), eyeMat);
    e.position.set(x, 0.18, 0.92);
    e.scale.set(1, 1.35, 0.5);
    body.add(e);
    return e;
  });
  const mouth = new THREE.Mesh(new THREE.TorusGeometry(0.16, 0.03, 12, 32, Math.PI), new THREE.MeshBasicMaterial({ color: 0x0b1a2a }));
  mouth.position.set(0, -0.22, 0.95);
  mouth.rotation.z = Math.PI;
  body.add(mouth);
  const orbit = new THREE.Group();
  for (let i = 0; i < 3; i++) {
    const d = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 8), new THREE.MeshBasicMaterial({ color: 0x9fe2ff }));
    d.position.set(Math.cos((i / 3) * Math.PI * 2) * 1.5, 0, Math.sin((i / 3) * Math.PI * 2) * 1.5);
    orbit.add(d);
  }
  orbit.visible = false;
  scene.add(body, orbit);
  let state = "idle", level = 0, blink = 0;
  const MOOD: Record<string, number> = { happy: 0x5fe08a, sad: 0x6d8cff, angry: 0xff5a4f, sleeping: 0x5a6a80, excited: 0xffc94f };
  client.on("state", (m) => { state = String(m.state || "idle"); });
  client.on("level", (m) => { level = Math.max(0, Math.min(1, Number(m.rms) * 6 || 0)); });
  client.on("mood", (m) => { bodyMat.color.setHex(MOOD[String(m.mood)] ?? 0x4fc3ff); });
  const resize = () => {
    const w = window.innerWidth, h = window.innerHeight;
    renderer.setSize(w, h, false);
    cam.aspect = w / Math.max(1, h);
    cam.updateProjectionMatrix();
  };
  window.addEventListener("resize", resize);
  resize();
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const t0 = performance.now();
  const frame = () => {
    const t = (performance.now() - t0) / 1000;
    body.position.y = reduce ? 0 : Math.sin(t * 1.4) * 0.08;
    const talk = state === "speaking" ? level : 0;
    body.scale.set(1 + talk * 0.06, 1.08 + talk * 0.1, 1 + talk * 0.06);
    mouth.scale.set(1, 0.6 + talk * 2.2, 1);
    body.rotation.y = state === "thinking" || state === "acting" ? Math.sin(t * 0.8) * 0.35 : body.rotation.y * 0.9;
    body.rotation.x = state === "listening" ? -0.12 : body.rotation.x * 0.9;
    orbit.visible = state === "thinking" || state === "acting";
    orbit.rotation.y = t * 1.6;
    bodyMat.emissiveIntensity = state === "listening" ? 1.2 + Math.sin(t * 6) * 0.3 : 0.6;
    blink -= 1 / 60;
    if (blink < -3.5 + Math.random()) blink = 0.12;
    for (const e of eyes) e.scale.y = blink > 0 ? 0.15 : 1.35;
    renderer.render(scene, cam);
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
  return true;
}
