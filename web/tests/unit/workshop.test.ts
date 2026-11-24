// 3.15 Dílna – the model viewer's pure parts: splitting an STL into its pieces, and the exploded view.
import assert from "node:assert/strict";
import { test } from "node:test";
import { components, explodeOffsets } from "../../src/hud/explode.ts";

function cubeTris(x: number, y: number, z: number, s: number): number[] {
  const p = (i: number, j: number, k: number) => [x + i * s, y + j * s, z + k * s];
  const quads = [[p(0, 0, 0), p(1, 0, 0), p(1, 1, 0), p(0, 1, 0)], [p(0, 0, 1), p(1, 0, 1), p(1, 1, 1), p(0, 1, 1)],
                 [p(0, 0, 0), p(1, 0, 0), p(1, 0, 1), p(0, 0, 1)], [p(0, 1, 0), p(1, 1, 0), p(1, 1, 1), p(0, 1, 1)],
                 [p(0, 0, 0), p(0, 1, 0), p(0, 1, 1), p(0, 0, 1)], [p(1, 0, 0), p(1, 1, 0), p(1, 1, 1), p(1, 0, 1)]];
  return quads.flatMap(([a, b, c, d]) => [...a, ...b, ...c, ...a, ...c, ...d]);
}

test("an STL with a box and its lid splits into two parts", () => {
  const pos = new Float32Array([...cubeTris(0, 0, 0, 10), ...cubeTris(20, 0, 0, 5)]);
  const parts = components(pos);
  assert.equal(parts.length, 2);
  assert.equal(parts[0].length, 12);
  assert.equal(parts[1].length, 12);
  assert.equal(components(new Float32Array(cubeTris(0, 0, 0, 1))).length, 1);
});

test("the exploded view pushes parts away from the centre", () => {
  const offs = explodeOffsets([[-1, 0, 0], [1, 0, 0], [0, 0, 0]], 4);
  assert.ok(offs[0][0] < 0 && offs[1][0] > 0, "left part goes left, right part goes right");
  assert.ok(Math.hypot(...offs[2]) > 1, "a part in the very centre still moves");
  for (const o of offs) assert.ok(o.every(Number.isFinite));
});
