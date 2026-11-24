// 3.17 STEP v prohlížeči (návrh 18): without FreeCAD on the PC the HUD reads a STEP file itself with occt-import-js
// (OpenCascade compiled to WebAssembly, LGPL-2.1). It is its own file (a separate chunk + .wasm), loaded only when a STEP
// is opened, never bundled into JARVIS's code – so it can be replaced; the licence texts are in /licenses.
import type * as THREE_NS from "three";

type OcctMesh = { name?: string; attributes: { position: { array: number[] }; normal?: { array: number[] } }; index: { array: number[] } };
export type OcctResult = { success: boolean; meshes: OcctMesh[] };
type Occt = { ReadStepFile(content: Uint8Array, params: object | null): OcctResult };

export const MAX_PARTS = 400;
let engine: Promise<Occt> | null = null;

function occt(): Promise<Occt> {
  engine ??= (async () => {
    const [mod, wasm] = await Promise.all([import("occt-import-js"), import("occt-import-js/dist/occt-import-js.wasm?url")]);
    const init = (mod as any).default ?? mod;
    return init({ locateFile: () => wasm.default }) as Promise<Occt>;
  })();
  engine.catch(() => { engine = null; });
  return engine;
}

/** The importer's meshes → a three.js group, one mesh per solid (so the exploded view takes the assembly apart). */
export function toGroup(THREE: typeof THREE_NS, res: OcctResult): THREE_NS.Group {
  if (!res?.success || !res.meshes?.length) throw new Error("STEP se nepodařilo přečíst");
  const group = new THREE.Group();
  for (const m of res.meshes.slice(0, MAX_PARTS)) {
    const pos = m.attributes?.position?.array;
    const idx = m.index?.array;
    if (!pos?.length || !idx?.length) continue;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    if (m.attributes.normal?.array?.length === pos.length) g.setAttribute("normal", new THREE.Float32BufferAttribute(m.attributes.normal.array, 3));
    else g.computeVertexNormals();
    g.setIndex(Array.from(idx));
    const mesh = new THREE.Mesh(g);
    mesh.name = m.name || "";
    group.add(mesh);
  }
  if (!group.children.length) throw new Error("STEP neobsahuje žádné těleso");
  group.rotation.x = -Math.PI / 2;                   // CAD files are Z-up
  return group;
}

export async function readStep(THREE: typeof THREE_NS, url: string): Promise<THREE_NS.Group> {
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) throw new Error(`soubor nejde načíst (${r.status})`);
  const data = new Uint8Array(await r.arrayBuffer());
  const o = await occt();
  return toGroup(THREE, o.ReadStepFile(data, { linearUnit: "millimeter", linearDeflectionType: "bounding_box_ratio", linearDeflection: 0.001, angularDeflection: 0.5 }));
}
