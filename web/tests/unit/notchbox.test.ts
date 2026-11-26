// The notch box (.notch) has square corners and is a few px taller than the island; the visible shape is a clip-path
// inside it. An outline / box-shadow / scale on the box itself drew a frame around the island (seen on Windows CI:
// a thin brown rectangle from the autumn tint) – the 3.20 extras must draw inside the clipped shape instead.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const css = readFileSync(new URL("../../src/notch/x320.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

test("nothing in the 3.20 notch styles draws on the square box", () => {
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const sel = m[1].trim(), body = m[2];
    if (sel.startsWith("@") || !/(outline|box-shadow|scale|border)\s*:/.test(body)) continue;
    for (const one of sel.split(",")) {
      const last = one.trim().split(/\s+/).pop() || "";
      assert.ok(!/^\.notch(\.|\[|:|$)/.test(last), `"${one.trim()}" styles the notch box: ${body.trim()}`);
    }
  }
});

test("the island is sized by the monitor in the script, not scaled by CSS (the window region would clip it)", () => {
  assert.ok(!/--x-notch-scale/.test(css));
  const main = readFileSync(new URL("../../src/notch/main.ts", import.meta.url), "utf8");
  assert.match(main, /dataset\.sizek/);
});

test("the weather and the day line stay on the small island, never over an answer card", () => {
  assert.match(css, /:not\(\[data-mode="bar"\]\)\s*:is\(\.x-timeline,\s*\.x-weather\)\s*\{\s*display:\s*none/);
});
