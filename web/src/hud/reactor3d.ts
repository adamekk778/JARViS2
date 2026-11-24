// 3.15 Mega animace (návrhy 1, 4): the holographic reactor in 3D – glowing rings, segmented arcs, a core with a soft
// rim light and a field of particles. It listens: your voice (the microphone level) and JARVIS's voice push the rings
// and the particles out, "thinking" spins them faster, each mood has its colour. Only from the "high" tier up and only
// with WebGL; otherwise the flat SVG reactor stays. Three.js loads only when this runs.
import type * as THREE_NS from "three";
import { at, loop, onTier, spring } from "../shared/motion";

type Three = typeof THREE_NS;
export type ReactorState = { mood: string; level: number };

const SPEED: Record<string, number> = { thinking: 2.6, working: 2.2, listening: 1.4, speaking: 1.6, error: 0.6, sleeping: 0.25, offline: 0.15 };

export async function mountReactor3d(host: HTMLElement, state: () => ReactorState): Promise<(() => void) | null> {
  if (!at("high")) return null;
  let THREE: Three;
  try { THREE = await import("three"); } catch { return null; }
  const canvas = document.createElement("canvas");
  canvas.className = "rx3d";
  canvas.setAttribute("aria-hidden", "true");
  let renderer: THREE_NS.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: at("ultra"), powerPreference: "high-performance" });
  } catch { return null; }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, at("ultra") ? 2 : 1.25));
  renderer.setClearColor(0x000000, 0);
  host.append(canvas);
  host.classList.add("gl");

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  camera.position.set(0, 0, 11.2);
  const group = new THREE.Group();
  group.rotation.x = -0.28;
  scene.add(group);

  const holo = new THREE.Color("#7fe3ff");
  const mats: THREE_NS.Material[] = [];
  const basic = (opacity: number) => {
    const m = new THREE.MeshBasicMaterial({ color: holo.clone(), transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide });
    mats.push(m);
    return m;
  };
  // rings: [radius, tube, segments of arc (0 = full ring), opacity, tilt]
  const RINGS: [number, number, number, number, number][] = [[3.2, 0.012, 0, 0.5, 0], [2.95, 0.05, 10, 0.75, 0.12], [2.6, 0.02, 3, 0.9, -0.2],
    [2.25, 0.008, 0, 0.45, 0.35], [1.9, 0.07, 3, 0.85, 0], [1.45, 0.015, 0, 0.6, -0.4]];
  const rings: THREE_NS.Object3D[] = [];
  for (const [r, tube, segs, op, tilt] of RINGS) {
    const g = new THREE.Group();
    if (!segs) g.add(new THREE.Mesh(new THREE.TorusGeometry(r, tube, 8, 160), basic(op)));
    else for (let i = 0; i < segs; i++) {
      const arc = (Math.PI * 2) / segs;
      const m = new THREE.Mesh(new THREE.TorusGeometry(r, tube, 6, 48, arc * 0.78), basic(op));
      m.rotation.z = i * arc;
      g.add(m);
    }
    g.rotation.x = tilt;
    group.add(g);
    rings.push(g);
  }
  // the ticks around the outside
  const tickGeo = new THREE.BufferGeometry();
  const tp: number[] = [];
  for (let i = 0; i < 120; i++) {
    const a = (i / 120) * Math.PI * 2, r0 = 3.45, r1 = i % 10 === 0 ? 3.75 : 3.58;
    tp.push(Math.cos(a) * r0, Math.sin(a) * r0, 0, Math.cos(a) * r1, Math.sin(a) * r1, 0);
  }
  tickGeo.setAttribute("position", new THREE.Float32BufferAttribute(tp, 3));
  const tickMat = new THREE.LineBasicMaterial({ color: holo.clone(), transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending });
  mats.push(tickMat);
  const ticks = new THREE.LineSegments(tickGeo, tickMat);
  group.add(ticks);

  // the core: a sphere with a rim (fresnel) glow and a bright centre, a triangle inside
  const coreMat = new THREE.ShaderMaterial({
    transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    uniforms: { color: { value: holo.clone() }, pulse: { value: 0 } },
    vertexShader: "varying vec3 vN; varying vec3 vV; void main(){ vec4 mv = modelViewMatrix * vec4(position,1.0); vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix*mv; }",
    fragmentShader: "uniform vec3 color; uniform float pulse; varying vec3 vN; varying vec3 vV; void main(){ float rim = pow(1.0 - max(dot(vN, vV), 0.0), 2.2); float core = pow(max(dot(vN, vV), 0.0), 6.0); vec3 c = color * (rim * (1.2 + pulse)) + vec3(1.0) * core * (0.9 + pulse * 0.8); gl_FragColor = vec4(c, clamp(rim + core, 0.0, 1.0)); }",
  });
  mats.push(coreMat);
  const core = new THREE.Mesh(new THREE.SphereGeometry(0.95, 48, 48), coreMat);
  group.add(core);
  const triShape = new THREE.Shape();
  [0, 1, 2, 0].forEach((k, i) => { const a = Math.PI / 2 + (k * Math.PI * 2) / 3; (i ? triShape.lineTo : triShape.moveTo).call(triShape, Math.cos(a) * 0.72, Math.sin(a) * 0.72); });
  const triMat = new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending });
  mats.push(triMat);
  const tri = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(triShape.getPoints()), triMat);
  tri.position.z = 0.96;
  group.add(tri);

  // the particles: a slowly orbiting dust that the voice pushes outwards
  const N = at("ultra") ? 1400 : 600;
  const base = new Float32Array(N * 3), pos = new Float32Array(N * 3), speed = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    const r = 1.2 + Math.pow(Math.random(), 0.6) * 3.4, a = Math.random() * Math.PI * 2, y = (Math.random() - 0.5) * 0.9;
    base[i * 3] = Math.cos(a) * r; base[i * 3 + 1] = y; base[i * 3 + 2] = Math.sin(a) * r;
    speed[i] = (0.05 + Math.random() * 0.18) / r;
  }
  const pGeo = new THREE.BufferGeometry();
  pGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const pMat = new THREE.PointsMaterial({ color: holo.clone(), size: 0.035, transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false });
  mats.push(pMat);
  const dust = new THREE.Points(pGeo, pMat);
  dust.rotation.x = Math.PI / 2 - 0.28;
  scene.add(dust);

  // ripples while you speak: rings that grow and fade
  const ripples: { m: THREE_NS.Mesh; t: number }[] = [];
  const rippleGeo = new THREE.RingGeometry(0.98, 1.0, 96);
  let lastRipple = 0;

  const resize = () => {
    const w = host.clientWidth || 520, hgt = host.clientHeight || 520;
    renderer.setSize(w, hgt, false);
    camera.aspect = w / hgt;
    camera.updateProjectionMatrix();
  };
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
  ro?.observe(host);
  resize();

  // power-up: the whole thing grows in on a spring
  let scale = 0.01;
  void spring(0.01, 1, (v) => { scale = v; }, { stiffness: 90, damping: 11 });

  let lvl = 0, spin = 0, frameN = 0;
  const colorNow = holo.clone();
  const target = new THREE.Color();
  const stop = loop((t, dt) => {
    const s = state();
    lvl += (Math.min(1, s.level) - lvl) * Math.min(1, dt * 14);
    const sp = (SPEED[s.mood] ?? 1) * (1 + lvl * 1.5);
    spin += dt * sp;
    rings.forEach((r, i) => { r.rotation.z = spin * (i % 2 ? -0.35 : 0.5) * (1 + i * 0.12); r.scale.setScalar(1 + lvl * 0.05 * (i + 1) / rings.length); });
    ticks.rotation.z = -spin * 0.08;
    if (++frameN % 30 === 1) {                     // the mood's colour, read twice a second (not every frame)
      const cssHolo = getComputedStyle(host).getPropertyValue("--holo").trim();
      if (cssHolo) { try { target.set(cssHolo); } catch { /* a colour three.js cannot read */ } }
    }
    colorNow.lerp(target, Math.min(1, dt * 3));
    for (const m of mats) {
      const mm = m as any;
      if (mm.uniforms?.color) mm.uniforms.color.value.copy(colorNow);
      else if (mm.color && m !== triMat) mm.color.copy(colorNow);
    }
    coreMat.uniforms.pulse.value = lvl * 1.4 + (s.mood === "thinking" ? 0.25 + 0.25 * Math.sin(t / 180) : 0.08 * Math.sin(t / 600));
    core.scale.setScalar(1 + lvl * 0.18);
    tri.rotation.z = -spin * 0.6;
    const push = 1 + lvl * 0.35;
    for (let i = 0; i < N; i++) {
      const a = spin * speed[i] * 6;
      const x = base[i * 3], z = base[i * 3 + 2];
      const ca = Math.cos(a), sa = Math.sin(a);
      pos[i * 3] = (x * ca - z * sa) * push;
      pos[i * 3 + 1] = base[i * 3 + 1] * (1 + lvl);
      pos[i * 3 + 2] = (x * sa + z * ca) * push;
    }
    pGeo.attributes.position.needsUpdate = true;
    if ((s.mood === "listening" || s.mood === "speaking") && lvl > 0.12 && t - lastRipple > 260) {
      lastRipple = t;
      const m = new THREE.Mesh(rippleGeo, basic(0.6));
      group.add(m);
      ripples.push({ m, t: 0 });
    }
    for (let i = ripples.length - 1; i >= 0; i--) {
      const r = ripples[i];
      r.t += dt;
      r.m.scale.setScalar(1 + r.t * 2.6);
      (r.m.material as THREE_NS.MeshBasicMaterial).opacity = Math.max(0, 0.6 - r.t * 0.6);
      if (r.t > 1) { group.remove(r.m); (r.m.material as THREE_NS.Material).dispose(); mats.splice(mats.indexOf(r.m.material as THREE_NS.Material), 1); ripples.splice(i, 1); }
    }
    group.scale.setScalar(scale);
    group.rotation.y = Math.sin(t / 4000) * 0.15;
    renderer.render(scene, camera);
  });

  const offTier = onTier((tr) => { if (tr === "eco" || tr === "off") dispose(); });
  function dispose() {
    stop();
    offTier();
    ro?.disconnect();
    scene.traverse((o) => { const m = o as THREE_NS.Mesh; m.geometry?.dispose?.(); });
    mats.forEach((m) => m.dispose());
    renderer.dispose();
    canvas.remove();
    host.classList.remove("gl");
  }
  return dispose;
}
