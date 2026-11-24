// 3.17 STEP v prohlížeči: the real OpenCascade importer (WebAssembly, run here in Node) → our three.js parts.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import * as THREE from "three";
import { MAX_PARTS, toGroup, type OcctResult } from "../../src/hud/stepload.ts";

const require = createRequire(import.meta.url);
const dir = "node_modules/occt-import-js/test/testfiles/";
type Occt = { ReadStepFile(c: Uint8Array, p: object | null): OcctResult };
const occt: Promise<Occt> = require("occt-import-js")();

function size(g: THREE.Object3D) {
  g.updateMatrixWorld(true);
  return new THREE.Box3().setFromObject(g).getSize(new THREE.Vector3());
}

test("a 10 mm cube becomes one closed part, Z-up turned to Y-up", async () => {
  const o = await occt;
  const g = toGroup(THREE, o.ReadStepFile(readFileSync(dir + "cube-10x10mm/Cube 10x10.stp"), null));
  assert.equal(g.children.length, 1);
  const s = size(g);
  for (const v of [s.x, s.y, s.z]) assert.ok(Math.abs(v - 10) < 0.01, `${v}`);
  const geo = (g.children[0] as THREE.Mesh).geometry;
  assert.ok(geo.index && geo.index.count >= 36 && geo.attributes.normal);
});

test("an assembly keeps its solids apart (for the exploded view)", async () => {
  const o = await occt;
  assert.ok(readdirSync(dir + "cax-if").includes("as1-oc-214.stp"));
  const g = toGroup(THREE, o.ReadStepFile(readFileSync(dir + "cax-if/as1-oc-214.stp"), null));
  assert.equal(g.children.length, 18);                       // the sample assembly: 18 solids
  assert.ok(g.children.length <= MAX_PARTS);
});

test("garbage is an error, not an empty hologram", async () => {
  const o = await occt;
  assert.throws(() => toGroup(THREE, o.ReadStepFile(new TextEncoder().encode("ISO-10303-21; nonsense"), null)), /STEP/);
  assert.throws(() => toGroup(THREE, { success: true, meshes: [] }), /STEP/);
});
