// 3.17 Gesta prsty – the pure finger reader: pinch + up/down = zoom, open hand sideways = turn, a fist = take apart.
import assert from "node:assert/strict";
import { test } from "node:test";
import { extended, type FingerEvent, HandReader, pinching, type Pt } from "../../src/shared/handgest.ts";

/** A hand at (cx, cy): fingers out or curled, thumb and index together (pinch) or apart. */
function hand(cx: number, cy: number, open: boolean, pinch = false): Pt[] {
  const p: Pt[] = Array.from({ length: 21 }, () => ({ x: cx, y: cy }));
  p[0] = { x: cx, y: cy + 0.2 };                                  // the wrist
  p[9] = { x: cx, y: cy };                                         // the middle of the palm
  const fingers: [number, number, number][] = [[8, 6, -0.06], [12, 10, -0.02], [16, 14, 0.02], [20, 18, 0.06]];
  for (const [tip, pip, dx] of fingers) {
    p[pip] = { x: cx + dx, y: cy - 0.06 };
    p[tip] = open ? { x: cx + dx, y: cy - 0.16 } : { x: cx + dx, y: cy + 0.05 };
  }
  p[4] = pinch ? { x: p[8].x + 0.01, y: p[8].y } : { x: cx - 0.15, y: cy };
  return p;
}

test("fingers and pinch", () => {
  assert.deepEqual(extended(hand(0.5, 0.5, true)), [true, true, true, true]);
  assert.deepEqual(extended(hand(0.5, 0.5, false)), [false, false, false, false]);
  assert.ok(pinching(hand(0.5, 0.5, true, true)) && !pinching(hand(0.5, 0.5, true)));
});

test("an open hand moving sideways turns", () => {
  const r = new HandReader();
  let t = 0, got: FingerEvent | null = null;
  for (let x = 0.4; x <= 0.6 && !got; x += 0.01) got = r.push(hand(x, 0.5, true), (t += 66));
  assert.ok(got?.type === "rotate" && got.deg > 0);
});

test("pinch and move up zooms in, down zooms out", () => {
  const r = new HandReader();
  let t = 0, up: FingerEvent | null = null;
  for (let y = 0.6; y >= 0.4 && !up; y -= 0.01) up = r.push(hand(0.5, y, true, true), (t += 66));
  assert.ok(up?.type === "zoom" && up.factor > 1);
  const r2 = new HandReader();
  let down: FingerEvent | null = null;
  for (let y = 0.4; y <= 0.6 && !down; y += 0.01) down = r2.push(hand(0.5, y, true, true), (t += 66));
  assert.ok(down?.type === "zoom" && down.factor < 1);
});

test("a fist held for a moment, once", () => {
  const r = new HandReader();
  const evs: FingerEvent[] = [];
  for (let t = 0; t < 1200; t += 66) { const e = r.push(hand(0.5, 0.5, false), t); if (e) evs.push(e); }
  assert.deepEqual(evs.map((e) => e.type), ["fist"]);
  assert.equal(r.push(null, 1300), null);
});
