// 3.15 Dílna (návrh C1): the 3D model as a hologram in the HUD – STL, OBJ, GLB, 3MF (STEP comes already converted by
// FreeCAD on the PC). It turns slowly on a lit ring; drag to turn, scroll to zoom; "rozlož model" (or the slider, or a
// wave of the hand) pulls the parts apart along the line from the centre – an exploded view. An STL with one mesh is
// split into its separate pieces (a box and its lid are two parts).
import type * as THREE_NS from "three";
import { h, icon } from "../shared/dom";
import { at, loop, spring } from "../shared/motion";
import type { JarvisClient } from "../shared/ws";
import { components, explodeOffsets } from "./explode";

export type ModelMsg = { url: string; format: string; title?: string; explode?: boolean };
type Viewer = { load(m: ModelMsg): Promise<void>; explode(k: number): void; turn(deg: number): void; zoom(by: number): void; reset(): void; dispose(): void };

const HOLO = 0x4fc3ff;

async function makeViewer(host: HTMLElement, client: JarvisClient, onInfo: (t: string) => void): Promise<Viewer | null> {
  let THREE: typeof THREE_NS;
  try { THREE = await import("three"); } catch { return null; }
  const { OrbitControls } = await import("three/examples/jsm/controls/OrbitControls.js");
  const canvas = document.createElement("canvas");
  host.append(canvas);
  let renderer: THREE_NS.WebGLRenderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: "high-performance" }); }
  catch { canvas.remove(); return null; }
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 200);
  camera.position.set(5.5, 3.6, 6.5);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.autoRotate = at("high");
  controls.autoRotateSpeed = 0.9;
  controls.minDistance = 1.5;
  controls.maxDistance = 30;
  scene.add(new THREE.AmbientLight(0x88ccff, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(4, 8, 6); scene.add(key);
  const rim = new THREE.DirectionalLight(HOLO, 1.2); rim.position.set(-6, 2, -5); scene.add(rim);
  // the base: a glowing ring and a faint grid
  const grid = new THREE.PolarGridHelper(3.4, 16, 6, 64, 0x1d5a7a, 0x12384d);
  grid.position.y = -2.05;
  scene.add(grid);
  const ring = new THREE.Mesh(new THREE.RingGeometry(3.3, 3.42, 96), new THREE.MeshBasicMaterial({ color: HOLO, transparent: true, opacity: 0.55, side: THREE.DoubleSide }));
  ring.rotation.x = -Math.PI / 2; ring.position.y = -2.04;
  scene.add(ring);
  const holder = new THREE.Group();
  scene.add(holder);
  let parts: { obj: THREE_NS.Object3D; home: THREE_NS.Vector3; off: THREE_NS.Vector3 }[] = [];
  let k = 0;
  let scanFrom = 0;
  const scanMat = new THREE.MeshBasicMaterial({ color: HOLO, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false });
  const scanPlane = new THREE.Mesh(new THREE.RingGeometry(0.2, 3.1, 64), scanMat);
  scanPlane.rotation.x = -Math.PI / 2;
  scene.add(scanPlane);

  const size = () => {
    const w = host.clientWidth || 600, hh = host.clientHeight || 400;
    renderer.setSize(w, hh, false);
    camera.aspect = w / hh;
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(size);
  ro.observe(host);
  size();

  function holoMaterial(): THREE_NS.Material {
    return new THREE.MeshPhongMaterial({ color: 0x0d3550, emissive: 0x0a4a6a, emissiveIntensity: 0.55, specular: 0x9fe6ff, shininess: 60,
                                         transparent: true, opacity: 0.9, side: THREE.DoubleSide });
  }
  function dress(mesh: THREE_NS.Mesh) {
    mesh.material = holoMaterial();
    const g = mesh.geometry as THREE_NS.BufferGeometry;
    if (g.attributes.position.count < 600_000) {
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(g, 40), new THREE.LineBasicMaterial({ color: 0x9fe6ff, transparent: true, opacity: 0.75 }));
      mesh.add(edges);
    }
  }
  function clear() {
    holder.traverse((o: any) => { o.geometry?.dispose?.(); (Array.isArray(o.material) ? o.material : [o.material]).forEach((m: any) => m?.dispose?.()); });
    holder.clear();
    parts = [];
  }

  async function parse(m: ModelMsg): Promise<THREE_NS.Object3D> {
    const url = client.url(m.url);
    const f = m.format.toLowerCase();
    if (f === "stl") {
      const { STLLoader } = await import("three/examples/jsm/loaders/STLLoader.js");
      const geo = await new STLLoader().loadAsync(url);
      const group = new THREE.Group();
      const pos = geo.attributes.position.array as Float32Array;
      const comps = components(pos);
      if (comps.length > 1 && comps.length <= 60) {
        for (const tris of comps) {
          const arr = new Float32Array(tris.length * 9);
          tris.forEach((t, i) => arr.set(pos.subarray(t * 9, t * 9 + 9), i * 9));
          const g = new THREE.BufferGeometry();
          g.setAttribute("position", new THREE.BufferAttribute(arr, 3));
          g.computeVertexNormals();
          group.add(new THREE.Mesh(g));
        }
        geo.dispose();
      } else {
        geo.computeVertexNormals();
        group.add(new THREE.Mesh(geo));
      }
      group.rotation.x = -Math.PI / 2;            // CAD files are Z-up
      return group;
    }
    if (f === "obj") {
      const { OBJLoader } = await import("three/examples/jsm/loaders/OBJLoader.js");
      const g = await new OBJLoader().loadAsync(url);
      g.rotation.x = -Math.PI / 2;
      return g;
    }
    if (f === "3mf") {
      const { ThreeMFLoader } = await import("three/examples/jsm/loaders/3MFLoader.js");
      const g = await new ThreeMFLoader().loadAsync(url);
      g.rotation.x = -Math.PI / 2;
      return g;
    }
    const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
    return (await new GLTFLoader().loadAsync(url)).scene;
  }

  async function load(m: ModelMsg) {
    clear();
    holder.rotation.y = 0;
    onInfo("Načítám…");
    const obj = await parse(m);
    const wrap = new THREE.Group();
    wrap.add(obj);
    wrap.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(wrap);
    const dims = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    const scale = 4 / Math.max(dims.x, dims.y, dims.z, 1e-6);
    obj.position.sub(centre);
    wrap.scale.setScalar(scale);
    holder.add(wrap);
    let tris = 0;
    const meshes: THREE_NS.Mesh[] = [];
    obj.traverse((o: any) => { if (o.isMesh) meshes.push(o); });
    for (const mesh of meshes) {
      dress(mesh);
      const g = mesh.geometry as THREE_NS.BufferGeometry;
      tris += (g.index ? g.index.count : g.attributes.position.count) / 3;
    }
    wrap.updateMatrixWorld(true);
    const centres = meshes.map((mesh) => new THREE.Box3().setFromObject(mesh).getCenter(new THREE.Vector3()));
    const offs = explodeOffsets(centres.map((c) => [c.x, c.y, c.z]), 4);
    parts = meshes.map((mesh, i) => {
      const inv = new THREE.Matrix4().copy(mesh.parent!.matrixWorld).invert();
      const o = new THREE.Vector3(...offs[i]).applyMatrix4(inv).sub(new THREE.Vector3().applyMatrix4(inv));
      return { obj: mesh, home: mesh.position.clone(), off: o };
    });
    const mm = (v: number) => (v >= 100 ? v.toFixed(0) : v.toFixed(1)).replace(".", ",");
    onInfo(`${mm(dims.x)} × ${mm(dims.z)} × ${mm(dims.y)} mm · ${Math.round(tris).toLocaleString("cs-CZ")} trojúhelníků · dílů ${parts.length}`);
    k = 0;
    if (m.explode) explode(1);
    scanFrom = performance.now();                      // the materialise sweep: a light disc rises through the model
  }

  function apply() {
    for (const p of parts) p.obj.position.copy(p.home).addScaledVector(p.off, k);
  }
  function explode(target: number) {
    void spring(k, Math.max(0, Math.min(1, target)), (v) => { k = v; apply(); }, { stiffness: 90, damping: 16 });
  }
  function turn(deg: number) {
    const from = holder.rotation.y;
    void spring(from, from + (deg * Math.PI) / 180, (v) => { holder.rotation.y = v; }, { stiffness: 80, damping: 15 });
  }
  function zoom(by: number) {
    const d0 = camera.position.length();
    void spring(d0, Math.max(1.6, Math.min(28, d0 * by)), (d) => { camera.position.setLength(d); }, { stiffness: 100, damping: 18 });
  }
  function reset() { explode(0); holder.rotation.y = 0; camera.position.set(5.5, 3.6, 6.5); controls.target.set(0, 0, 0); }

  const stop = loop((t) => {
    controls.update();
    ring.material.opacity = 0.4 + 0.2 * Math.sin(t / 600);
    const sweep = at("eco") ? (t - scanFrom) / 1100 : 2;
    scanPlane.visible = sweep >= 0 && sweep < 1;
    if (scanPlane.visible) { scanPlane.position.y = -2.1 + 4.4 * sweep; scanMat.opacity = 0.16 * Math.sin(Math.PI * sweep); }
    renderer.render(scene, camera);
  });
  return {
    load, explode, turn, zoom, reset,
    dispose() { stop(); ro.disconnect(); controls.dispose(); clear(); renderer.dispose(); canvas.remove(); },
  };
}

export function modelViewer(client: JarvisClient, sound: (name: "whoosh" | "close") => void = () => {}) {
  const stage = h("div", { class: "mv-stage" });
  const title = h("span", { class: "mv-title" });
  const info = h("span", { class: "mv-info" });
  const slider = h("input", { type: "range", min: "0", max: "100", value: "0", class: "mv-slider", "aria-label": "Rozložení modelu" }) as HTMLInputElement;
  const btn = (ic: string, label: string, f: () => void) => h("button", { class: "hbtn", type: "button", title: label, "aria-label": label, onclick: f }, icon(ic));
  let viewer: Viewer | null = null;
  let exploded = false;
  const el = h("div", { class: "mv", hidden: true, role: "dialog", "aria-label": "3D model" },
    h("header", { class: "mv-head" }, icon("cube"), h("span", {}, "MODEL"), title,
      h("div", { class: "mv-tools" },
        btn("arrows-out-simple", "Rozložit / složit", () => command("model_" + (exploded ? "collapse" : "explode"))),
        btn("arrow-counter-clockwise", "Výchozí pohled", () => command("model_reset")),
        btn("x", "Zavřít", () => close()))),
    stage,
    h("footer", { class: "mv-foot" }, info, h("label", { class: "mv-explode" }, "Rozložit", slider),
      h("span", { class: "mv-hint" }, "Táhni = otočit · kolečko = zoom · gesta: ← → otočit, ↑ ↓ zoom, zamávání = rozložit")));
  slider.addEventListener("input", () => { exploded = Number(slider.value) > 50; viewer?.explode(Number(slider.value) / 100); });

  async function open(m: ModelMsg) {
    el.hidden = false;
    sound("whoosh");
    title.textContent = m.title || "";
    if (!viewer) viewer = await makeViewer(stage, client, (t) => { info.textContent = t; });
    if (!viewer) { info.textContent = "3D tady nejde (chybí WebGL)."; return; }
    try {
      await viewer.load(m);
      exploded = !!m.explode;
      slider.value = exploded ? "100" : "0";
    } catch (e) { info.textContent = `Model nejde načíst: ${(e as Error).message || e}`; }
  }
  function close() { el.hidden = true; viewer?.dispose(); viewer = null; sound("close"); }
  function command(a: string): boolean {
    if (el.hidden || !viewer) return false;
    if (a === "model_explode" || a === "model_collapse") { exploded = a === "model_explode"; slider.value = exploded ? "100" : "0"; viewer.explode(exploded ? 1 : 0); }
    else if (a === "model_rotate_left") viewer.turn(-45);
    else if (a === "model_rotate_right") viewer.turn(45);
    else if (a === "model_zoom_in") viewer.zoom(0.75);
    else if (a === "model_zoom_out") viewer.zoom(1.33);
    else if (a === "model_reset") { viewer.reset(); exploded = false; slider.value = "0"; }
    else if (a === "model_close") close();
    else return false;
    return true;
  }
  /** 3.17 a finger gesture with a value ("rotate:12", "zoom:1.15", "fist") while the model is open. */
  function fine(kind: string, value: number): boolean {
    if (el.hidden || !viewer) return false;
    if (kind === "rotate") viewer.turn(value);
    else if (kind === "zoom" && value > 0) viewer.zoom(1 / value);
    else return false;
    return true;
  }
  /** A hand gesture while the model is open (true = used). */
  function gesture(g: string): boolean {
    if (g === "fist") return command(exploded ? "model_collapse" : "model_explode");
    const map: Record<string, string> = { left: "model_rotate_left", right: "model_rotate_right", up: "model_zoom_in", down: "model_zoom_out",
                                          wave: exploded ? "model_collapse" : "model_explode" };
    return command(map[g] || "");
  }
  client.on("hud_model" as any, (m: any) => { void open(m as ModelMsg); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !el.hidden) { e.stopPropagation(); close(); } }, true);
  return { el, open, close, command, gesture, fine, get isOpen() { return !el.hidden; } };
}
