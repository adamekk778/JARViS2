// 3.14 (návrh 21): every page of JARVIS in a real browser at three sizes – no script errors, nothing pushed off the
// screen sideways, the notch inside the window – and a screenshot of each for a look. Run by `python -m jarvis.uicheck`
// (it starts a real JARVIS server first): node web/tests/uicheck.mjs <base url> <out dir>
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

// Playwright from this folder's node_modules or a global install (CI: `npx playwright install chromium`)
const { chromium } = createRequire(import.meta.url)("playwright");

const [base, out = "uicheck-out"] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const PAGES = [
  { path: "/", name: "dashboard", sizes: [[1280, 800], [1920, 1080]] },
  { path: "/chat", name: "chat", sizes: [[1280, 800], [900, 700]] },
  { path: "/hud", name: "hud", sizes: [[1920, 1080]] },
  { path: "/notch", name: "notch", sizes: [[1000, 410]], notch: true },
  { path: "/mobile", name: "mobile", sizes: [[390, 844], [412, 915]] },
];
// what a page may log without it being a bug (no microphone in CI, the phone-only plugins)
const IGNORE = [/getUserMedia/i, /NotAllowedError/i, /Capacitor/i, /favicon/i, /WebSocket is closed/i, /ERR_CONNECTION_REFUSED/i,
  /net::ERR_/i, /Failed to load resource/i];

const browser = await chromium.launch();
const results = [];
for (const p of PAGES) {
  for (const [w, hgt] of p.sizes) {
    const page = await browser.newPage({ viewport: { width: w, height: hgt }, deviceScaleFactor: 1 });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e.message || e).slice(0, 300)));
    page.on("console", (m) => { if (m.type() === "error" && !IGNORE.some((r) => r.test(m.text()))) errors.push(m.text().slice(0, 300)); });
    let loadErr = "";
    try {
      await page.goto(base + p.path, { waitUntil: "load", timeout: 30000 });
      await page.waitForTimeout(2500);                       // the WebSocket welcome and the first render
    } catch (e) { loadErr = String(e).slice(0, 200); }
    const m = await page.evaluate((isNotch) => {
      const de = document.documentElement;
      // what the user can really scroll sideways (a body with overflow:hidden clips, it does not scroll)
      const scrolls = (el) => el && !["hidden", "clip"].includes(getComputedStyle(el).overflowX);
      const overflowX = Math.max(scrolls(de) ? de.scrollWidth : 0, scrolls(document.body) ? document.body.scrollWidth : 0) - window.innerWidth;
      // visible text pushed past the right edge of the window (a clipped button or label)
      let clipped = 0;
      for (const el of Array.from(document.querySelectorAll("button, label, h1, h2, h3, .btn"))) {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        if (r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none" && r.right > window.innerWidth + 2 && r.left < window.innerWidth) clipped++;
      }
      let notchOk = true;
      if (isNotch) {
        const n = document.querySelector("#notch, .notch, [data-notch]");
        if (n) { const r = n.getBoundingClientRect(); notchOk = r.left >= -1 && r.right <= window.innerWidth + 1 && r.top >= -1; }
      }
      return { overflowX, clipped, notchOk, title: document.title, nodes: document.querySelectorAll("*").length };
    }, !!p.notch).catch((e) => ({ overflowX: 0, clipped: 0, notchOk: true, title: "", nodes: 0, evalErr: String(e) }));
    const file = `${out}/${p.name}-${w}x${hgt}.png`;
    await page.screenshot({ path: file, fullPage: false }).catch(() => {});
    const problems = [];
    if (loadErr) problems.push(`nenačetla se: ${loadErr}`);
    if (errors.length) problems.push(...errors.map((e) => `chyba ve skriptu: ${e}`));
    if (p.name !== "notch" && m.overflowX > 2) problems.push(`stránka přetéká do strany o ${m.overflowX} px`);
    if (m.clipped > 0) problems.push(`${m.clipped} tlačítek/nadpisů je useknutých vpravo`);
    if (!m.notchOk) problems.push("notch je mimo okno");
    if (m.nodes < 10) problems.push("stránka je skoro prázdná");
    results.push({ page: p.name, size: `${w}x${hgt}`, screenshot: file, problems, ...m });
    await page.close();
  }
}
await browser.close();
writeFileSync(`${out}/report.json`, JSON.stringify(results, null, 1));
const bad = results.filter((r) => r.problems.length);
for (const r of results) console.log(`${r.problems.length ? "CHYBA" : "OK   "} ${r.page} ${r.size}${r.problems.length ? " – " + r.problems.join("; ") : ""}`);
process.exit(bad.length ? 1 : 0);
