// 3.15 Mega animace (návrh 7): the world as a holographic 3D globe – land as glowing dots (Natural Earth, public
// domain), an atmosphere rim, the live rain radar (RainViewer) wrapped around it, your home and car as beacons, trips
// as animated arcs and the planes over the house. Drag to turn it, scroll to zoom; it turns slowly by itself.
import type * as THREE_NS from "three";
import { at, loop, spring } from "../shared/motion";

export type GlobeData = {
  home: { lat: number; lon: number; name: string } | null;
  car: { lat: number; lon: number; text: string } | null;
  trips: { text: string; kind: string; points: { code: string; name: string; lat: number; lon: number }[] }[];
  planes: { lat: number; lon: number; callsign: string; alt_m?: number }[];
};
export type Globe = { update(d: GlobeData): void; radar(host: string, path: string | null): void; zoom(by: number): void; focus(lat: number, lon: number): void; dispose(): void };

const R = 2;

/** Latitude / longitude → a point on the sphere (y up, longitude 0 facing +z). */
export function toXYZ(lat: number, lon: number, r = R): [number, number, number] {
  const phi = (lat * Math.PI) / 180, lam = (lon * Math.PI) / 180;
  return [r * Math.cos(phi) * Math.sin(lam), r * Math.sin(phi), r * Math.cos(phi) * Math.cos(lam)];
}

/** Points along the great circle between two places (for the trip arcs), lifted in the middle. */
export function arc(a: [number, number], b: [number, number], n = 64, lift = 0.35): [number, number, number][] {
  const va = toXYZ(a[0], a[1], 1), vb = toXYZ(b[0], b[1], 1);
  const dot = Math.max(-1, Math.min(1, va[0] * vb[0] + va[1] * vb[1] + va[2] * vb[2]));
  const om = Math.acos(dot) || 1e-6;
  const out: [number, number, number][] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const s1 = Math.sin((1 - t) * om) / Math.sin(om), s2 = Math.sin(t * om) / Math.sin(om);
    const h = R * (1 + lift * Math.sin(Math.PI * t) * Math.min(1, om));
    out.push([(va[0] * s1 + vb[0] * s2) * h, (va[1] * s1 + vb[1] * s2) * h, (va[2] * s1 + vb[2] * s2) * h]);
  }
  return out;
}

function inRing(lon: number, lat: number, ring: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** The land as evenly spaced dots (lat/lon pairs). */
export function landDots(polys: number[][][][], step = 1.6): [number, number][] {
  const out: [number, number][] = [];
  const boxes = polys.map((p) => {
    let a = 180, b = -180, c = 90, d = -90;
    for (const [x, y] of p[0]) { a = Math.min(a, x); b = Math.max(b, x); c = Math.min(c, y); d = Math.max(d, y); }
    return [a, b, c, d];
  });
  for (let lat = -84; lat <= 84; lat += step) {
    const dl = step / Math.max(0.15, Math.cos((lat * Math.PI) / 180));
    for (let lon = -180; lon < 180; lon += dl) {
      for (let k = 0; k < polys.length; k++) {
        const bx = boxes[k];
        if (lon < bx[0] || lon > bx[1] || lat < bx[2] || lat > bx[3]) continue;
        const p = polys[k];
        if (inRing(lon, lat, p[0]) && !p.slice(1).some((hole) => inRing(lon, lat, hole))) { out.push([lat, lon]); break; }
      }
    }
  }
  return out;
}

async function loadLand(): Promise<[number, number][]> {
  const KEY = "jarvis.globe.dots.v1";
  try { const c = localStorage.getItem(KEY); if (c) return JSON.parse(c); } catch { /* no storage */ }
  const [{ feature }, topo] = await Promise.all([import("topojson-client"), import("world-atlas/land-110m.json")]);
  const t: any = (topo as any).default || topo;
  const geo: any = feature(t, t.objects.land);
  const polys: number[][][][] = [];
  for (const f of geo.features || [geo]) {
    const g = f.geometry || f;
    if (g.type === "Polygon") polys.push(g.coordinates);
    else if (g.type === "MultiPolygon") polys.push(...g.coordinates);
  }
  const dots = landDots(polys, at("ultra") ? 1.25 : 1.8);
  try { localStorage.setItem(KEY, JSON.stringify(dots.map(([a, b]) => [Math.round(a * 100) / 100, Math.round(b * 100) / 100]))); } catch { /* full */ }
  return dots;
}

export async function mountGlobe(host: HTMLElement): Promise<Globe | null> {
  if (!at("eco")) return null;
  let THREE: typeof THREE_NS;
  try { THREE = await import("three"); } catch { return null; }
  const canvas = document.createElement("canvas");
  canvas.className = "globe3d";
  let renderer: THREE_NS.WebGLRenderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true }); } catch { return null; }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, at("ultra") ? 2 : 1.25));
  renderer.setClearColor(0x000000, 0);
  host.append(canvas);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
  let dist = 7.5;
  camera.position.set(0, 0, dist);
  const world = new THREE.Group();
  scene.add(world);
  const holo = new THREE.Color("#7fe3ff");

  world.add(new THREE.Mesh(new THREE.SphereGeometry(R * 0.995, 64, 64),
    new THREE.MeshBasicMaterial({ color: 0x031018, transparent: true, opacity: 0.92 })));
  const atmo = new THREE.Mesh(new THREE.SphereGeometry(R * 1.12, 64, 64), new THREE.ShaderMaterial({
    transparent: true, side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false,
    uniforms: { color: { value: holo } },
    vertexShader: "varying vec3 vN; void main(){ vN = normalize(normalMatrix*normal); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }",
    fragmentShader: "uniform vec3 color; varying vec3 vN; void main(){ float i = pow(0.72 - dot(vN, vec3(0.0,0.0,1.0)), 3.0); gl_FragColor = vec4(color, 1.0) * i; }",
  }));
  scene.add(atmo);
  // the graticule: thin lines every 30°
  const grat: number[] = [];
  for (let lat = -60; lat <= 60; lat += 30) for (let lon = -180; lon < 180; lon += 4) grat.push(...toXYZ(lat, lon, R * 1.001), ...toXYZ(lat, lon + 4, R * 1.001));
  for (let lon = -180; lon < 180; lon += 30) for (let lat = -84; lat < 84; lat += 4) grat.push(...toXYZ(lat, lon, R * 1.001), ...toXYZ(lat + 4, lon, R * 1.001));
  const gg = new THREE.BufferGeometry();
  gg.setAttribute("position", new THREE.Float32BufferAttribute(grat, 3));
  world.add(new THREE.LineSegments(gg, new THREE.LineBasicMaterial({ color: holo, transparent: true, opacity: 0.12 })));

  loadLand().then((dots) => {
    const p = new Float32Array(dots.length * 3);
    dots.forEach(([la, lo], i) => p.set(toXYZ(la, lo, R * 1.004), i * 3));
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(p, 3));
    world.add(new THREE.Points(g, new THREE.PointsMaterial({ color: holo, size: at("ultra") ? 0.022 : 0.03, transparent: true, opacity: 0.85,
      blending: THREE.AdditiveBlending, depthWrite: false })));
  }).catch(() => { /* no land data: the grid and the markers still work */ });

  // the radar as a texture: RainViewer's Mercator tiles at zoom 2, re-projected to latitude / longitude
  const radarCanvas = document.createElement("canvas");
  radarCanvas.width = 1024; radarCanvas.height = 512;
  const radarTex = new THREE.CanvasTexture(radarCanvas);
  radarTex.colorSpace = THREE.SRGBColorSpace;
  radarTex.wrapS = THREE.RepeatWrapping;
  radarTex.offset.x = 0.25;                            // three's sphere starts at longitude -90°, the picture at -180°
  const radarMesh = new THREE.Mesh(new THREE.SphereGeometry(R * 1.008, 96, 64),
    new THREE.MeshBasicMaterial({ map: radarTex, transparent: true, opacity: 0.85, depthWrite: false }));
  radarMesh.visible = false;
  world.add(radarMesh);

  const marks = new THREE.Group();
  world.add(marks);
  const beacons: { m: THREE_NS.Mesh; t0: number }[] = [];
  const arcs: { line: THREE_NS.Line; head: THREE_NS.Mesh; pts: [number, number, number][]; t: number }[] = [];

  const resize = () => {
    const w = host.clientWidth || 800, hgt = host.clientHeight || 500;
    renderer.setSize(w, hgt, false);
    camera.aspect = w / hgt;
    camera.updateProjectionMatrix();
  };
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
  ro?.observe(host);
  resize();

  // turning by hand, zooming, turning by itself when left alone
  let rotX = 0.35, rotY = 0, vY = 0.08, dragging = false, lastX = 0, lastY = 0, idleAt = 0;
  canvas.addEventListener("pointerdown", (e) => { dragging = true; lastX = e.clientX; lastY = e.clientY; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    rotY += (e.clientX - lastX) * 0.006; rotX = Math.max(-1.2, Math.min(1.2, rotX + (e.clientY - lastY) * 0.006));
    lastX = e.clientX; lastY = e.clientY; idleAt = performance.now();
  });
  canvas.addEventListener("pointerup", () => { dragging = false; idleAt = performance.now(); });
  canvas.addEventListener("wheel", (e) => { e.preventDefault(); zoom(e.deltaY > 0 ? 1.1 : 0.9); }, { passive: false });
  function zoom(by: number) { void spring(dist, Math.max(3.2, Math.min(14, dist * by)), (v) => { dist = v; }, { stiffness: 120, damping: 20 }); }

  const stop = loop((t, dt) => {
    if (!dragging && t - idleAt > 4000) rotY += vY * dt;
    world.rotation.set(rotX, rotY, 0);
    camera.position.set(0, 0, dist);
    for (const b of beacons) {
      const k = ((t - b.t0) % 1600) / 1600;
      b.m.scale.setScalar(1 + k * 2.5);
      (b.m.material as THREE_NS.MeshBasicMaterial).opacity = 0.9 * (1 - k);
    }
    for (const a of arcs) {
      a.t = (a.t + dt * 0.25) % 1;
      const i = Math.floor(a.t * (a.pts.length - 1));
      a.head.position.set(...a.pts[i]);
      a.line.geometry.setDrawRange(0, Math.max(2, i + 1));
    }
    renderer.render(scene, camera);
  });

  function clearMarks() {
    for (const o of [...marks.children]) {
      marks.remove(o);
      const m = o as THREE_NS.Mesh;
      m.geometry?.dispose?.();
      (m.material as THREE_NS.Material)?.dispose?.();
    }
    beacons.length = 0;
    arcs.length = 0;
  }
  function dot(lat: number, lon: number, color: string, size: number, pulse = false) {
    const m = new THREE.Mesh(new THREE.SphereGeometry(size, 16, 16), new THREE.MeshBasicMaterial({ color }));
    m.position.set(...toXYZ(lat, lon, R * 1.012));
    marks.add(m);
    if (pulse) {
      const ring = new THREE.Mesh(new THREE.RingGeometry(size * 1.4, size * 1.8, 32),
        new THREE.MeshBasicMaterial({ color, transparent: true, side: THREE.DoubleSide, depthWrite: false }));
      ring.position.copy(m.position);
      ring.lookAt(0, 0, 0);
      marks.add(ring);
      beacons.push({ m: ring, t0: performance.now() + Math.random() * 800 });
    }
  }

  const api: Globe = {
    update(d) {
      clearMarks();
      if (d.home) dot(d.home.lat, d.home.lon, "#7fe3ff", 0.035, true);
      if (d.car) dot(d.car.lat, d.car.lon, "#f5b942", 0.028, true);
      for (const tr of d.trips) {
        tr.points.forEach((p) => dot(p.lat, p.lon, "#c084fc", 0.022));
        if (tr.points.length === 2) {
          const pts = arc([tr.points[0].lat, tr.points[0].lon], [tr.points[1].lat, tr.points[1].lon]);
          const g = new THREE.BufferGeometry().setFromPoints(pts.map((p) => new THREE.Vector3(...p)));
          const line = new THREE.Line(g, new THREE.LineBasicMaterial({ color: "#c084fc", transparent: true, opacity: 0.9 }));
          const head = new THREE.Mesh(new THREE.SphereGeometry(0.03, 12, 12), new THREE.MeshBasicMaterial({ color: "#ffffff" }));
          marks.add(line, head);
          arcs.push({ line, head, pts, t: Math.random() });
        }
      }
      for (const p of d.planes.slice(0, 60)) {
        const m = new THREE.Mesh(new THREE.SphereGeometry(0.009, 8, 8), new THREE.MeshBasicMaterial({ color: "#ffffff" }));
        m.position.set(...toXYZ(p.lat, p.lon, R * (1.02 + Math.min(12000, p.alt_m || 0) / 12000 * 0.03)));
        marks.add(m);
      }
      if (d.home) api.focus(d.home.lat, d.home.lon);
    },
    radar(tileHost, path) {
      if (!path) { radarMesh.visible = false; return; }
      const z = 2, n = 4, ts = 256;
      const merc = document.createElement("canvas");
      merc.width = n * ts; merc.height = n * ts;
      const mc = merc.getContext("2d")!;
      let left = n * n;
      for (let x = 0; x < n; x++) for (let y = 0; y < n; y++) {
        const img = new Image();
        img.crossOrigin = "anonymous";
        img.onload = img.onerror = () => {
          try { if (img.naturalWidth) mc.drawImage(img, x * ts, y * ts); } catch { /* skip that tile */ }
          if (--left === 0) reproject(merc);
        };
        img.src = `${tileHost}${path}/256/${z}/${x}/${y}/2/1_1.png`;
      }
    },
    zoom,
    focus(lat, lon) {
      const ty = -(lon * Math.PI) / 180, tx = (lat * Math.PI) / 180 * 0.9;
      const fy = rotY, fx = rotX;
      void spring(0, 1, (k) => { rotY = fy + (ty - fy) * k; rotX = fx + (tx - fx) * k; }, { stiffness: 60, damping: 14 });
      idleAt = performance.now() + 6000;
    },
    dispose() {
      stop();
      ro?.disconnect();
      clearMarks();
      scene.traverse((o) => { const m = o as THREE_NS.Mesh; m.geometry?.dispose?.(); (m.material as THREE_NS.Material)?.dispose?.(); });
      radarTex.dispose();
      renderer.dispose();
      canvas.remove();
    },
  };

  function reproject(merc: HTMLCanvasElement) {
    let src: ImageData;
    try { src = merc.getContext("2d")!.getImageData(0, 0, merc.width, merc.height); } catch { return; }
    const ctx = radarCanvas.getContext("2d")!;
    const out = ctx.createImageData(radarCanvas.width, radarCanvas.height);
    const W = merc.width;
    for (let y = 0; y < radarCanvas.height; y++) {
      const lat = 90 - (y / radarCanvas.height) * 180;
      if (Math.abs(lat) > 85) continue;
      const my = Math.floor(((1 - Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) / Math.PI) / 2) * W);
      for (let x = 0; x < radarCanvas.width; x++) {
        const mx = Math.floor((x / radarCanvas.width) * W);
        const si = (my * W + mx) * 4, di = (y * radarCanvas.width + x) * 4;
        out.data[di] = src.data[si]; out.data[di + 1] = src.data[si + 1]; out.data[di + 2] = src.data[si + 2]; out.data[di + 3] = src.data[si + 3];
      }
    }
    ctx.putImageData(out, 0, 0);
    radarTex.needsUpdate = true;
    radarMesh.visible = true;
  }
  return api;
}
