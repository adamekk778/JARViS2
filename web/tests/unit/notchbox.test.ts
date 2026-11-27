// The notch box (.notch) has square corners and is a few px taller than the island; the visible shape is a clip-path
// inside it. An outline / box-shadow / scale on the box itself drew a frame around the island (seen on Windows CI:
// a thin brown rectangle from the autumn tint) – the 3.20 extras must draw inside the clipped shape instead.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
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

// The notch is an always-on-top, per-pixel transparent window: an endless animation of a paint property (box-shadow,
// filter, background-position) repaints the whole window every frame and Windows recomposes the desktop with it – the
// stutter people felt. Endless animations there must use transform / opacity, or steps() at a few frames a second.
test("endless notch animations run on the GPU (or step a few times a second)", () => {
  const dir = new URL("../../src/notch/", import.meta.url);
  const files = readdirSync(dir).filter((f) => f.endsWith(".css")).map((f) => readFileSync(new URL(f, dir), "utf8"));
  files.push(readFileSync(new URL("../../src/shared/theme.css", import.meta.url), "utf8"));
  const all = files.join("\n").replace(/\/\*[\s\S]*?\*\//g, "");
  const frames = new Map<string, string>();
  for (const m of all.matchAll(/@keyframes\s+([\w-]+)\s*\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}/g)) frames.set(m[1], m[2]);
  const bad: string[] = [];
  for (const m of all.matchAll(/animation\s*:\s*([^;}]+)/g)) {
    for (const part of m[1].split(",")) {
      if (!/\binfinite\b/.test(part) || /steps\(/.test(part)) continue;
      const name = part.trim().split(/\s+/).find((w) => frames.has(w));
      if (name && /(box-shadow|filter|background-position)\s*:/.test(frames.get(name) || "")) bad.push(`${name}: ${part.trim()}`);
    }
  }
  assert.deepEqual(bad, []);
});
