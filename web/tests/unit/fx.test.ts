// 3.15 Mega animace – the pure parts of the motion engine and the sound recipes.
// Run: npm test   (node --experimental-strip-types --test)
import assert from "node:assert/strict";
import { test } from "node:test";
import { pickTier, springStep, tierForRenderer } from "../../src/shared/motion.ts";
import { RECIPES, SOUNDS } from "../../src/shared/sounds.ts";

test("the graphics card decides the tier", () => {
  assert.equal(tierForRenderer("ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0)"), "ultra");
  assert.equal(tierForRenderer("ANGLE (AMD, AMD Radeon RX 7800 XT Direct3D11)"), "ultra");
  assert.equal(tierForRenderer("ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11)"), "high");
  assert.equal(tierForRenderer("ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)))"), "eco");
  assert.equal(tierForRenderer(""), "high");
});

test("battery, load, reduced motion and the frame-rate watch", () => {
  const base = { pref: "auto" as const, gpu: "ultra" as const, battery: false, heavy: false, reduced: false };
  assert.equal(pickTier(base), "ultra");
  assert.equal(pickTier({ ...base, battery: true }), "high");
  assert.equal(pickTier({ ...base, gpu: "high", heavy: true }), "eco");
  assert.equal(pickTier({ ...base, reduced: true }), "off");
  assert.equal(pickTier({ ...base, stepDown: 1 }), "high");
  assert.equal(pickTier({ ...base, stepDown: 9 }), "eco");             // the watch never switches effects off
  assert.equal(pickTier({ ...base, pref: "eco" }), "eco");               // your choice wins over the card
});

test("a spring settles on its target without overshooting forever", () => {
  let x = 0, v = 0;
  for (let i = 0; i < 240; i++) [x, v] = springStep(x, v, 100, 1 / 120);
  assert.ok(Math.abs(x - 100) < 0.5, `ended at ${x}`);
  let peak = 0;
  [x, v] = [0, 0];
  for (let i = 0; i < 240; i++) { [x, v] = springStep(x, v, 100, 1 / 120, { stiffness: 300, damping: 10 }); peak = Math.max(peak, x); }
  assert.ok(peak > 100 && peak < 160, "a bouncy spring overshoots a little");
});

test("every sound has a short recipe", () => {
  for (const s of SOUNDS) {
    const r = RECIPES[s];
    assert.ok(r && ((r.tones?.length ?? 0) + (r.noise?.length ?? 0)) > 0, s);
    const end = Math.max(...[...(r.tones || []), ...(r.noise || [])].map((p) => p.t + p.d));
    assert.ok(end <= 1.7, `${s} lasts ${end} s`);
  }
});
