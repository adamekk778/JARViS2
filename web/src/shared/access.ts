// 3.20 Přístupnost+ in every window: one-switch control (474), keyboard-only mode with a skip link (464) and light by
// day / dark in the evening (479). The look itself (dyslexia, colour-blind, simple) is CSS on data-* attributes.

const FOCUSABLE = "button:not([disabled]), a[href], input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

let scanTimer: number | null = null;
let scanIdx = -1;
let scanEls: HTMLElement[] = [];

function visible(el: HTMLElement): boolean {
  const r = el.getBoundingClientRect();
  return r.width > 2 && r.height > 2 && getComputedStyle(el).visibility !== "hidden";
}

/** The next element the scan stops on (wraps around); exported for the tests. */
export function nextIndex(cur: number, count: number): number {
  return count ? (cur + 1) % count : -1;
}

function step(): void {
  scanEls.forEach((e) => e.classList.remove("scan-on"));
  scanEls = Array.from(document.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(visible);
  scanIdx = nextIndex(scanIdx, scanEls.length);
  const el = scanEls[scanIdx];
  if (el) {
    el.classList.add("scan-on");
    el.scrollIntoView({ block: "nearest" });
  }
}

function onKey(e: KeyboardEvent): void {
  if (e.code !== "Space" && e.code !== "Enter") return;
  const el = scanEls[scanIdx];
  if (!el || (e.target instanceof HTMLElement && e.target.matches("input, textarea") && e.code === "Space")) return;
  e.preventDefault();
  if (el.matches("input, textarea, select")) el.focus();
  else el.click();
  scanIdx = -1;                                   // after a choice the scan starts from the top of what is now shown
}

/** One switch (a big button that acts as Space): the highlight moves on by itself every `ms`; Space or Enter chooses. */
export function setSwitchScan(ms: number): void {
  if (scanTimer !== null) {
    clearInterval(scanTimer);
    scanTimer = null;
    document.removeEventListener("keydown", onKey, true);
    scanEls.forEach((e) => e.classList.remove("scan-on"));
  }
  if (ms >= 400) {
    scanTimer = window.setInterval(step, ms);
    document.addEventListener("keydown", onKey, true);
  }
}

export function setKeyboardOnly(on: boolean): void {
  const have = document.querySelector(".skip-link");
  if (on && !have && document.body) {
    const a = document.createElement("a");
    a.className = "skip-link";
    a.href = "#main";
    a.textContent = "Přeskočit na obsah";
    a.onclick = (e) => {
      e.preventDefault();
      const main = document.querySelector<HTMLElement>("main, [role=main], .content, #app");
      if (main) {
        if (!main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1");
        main.focus();
      }
    };
    document.body.prepend(a);
  } else if (!on && have) have.remove();
}

/** Light between 7:00 and 19:00 (or sunrise / sunset when known), dark otherwise. */
export function isDay(now: Date, sunrise?: number, sunset?: number): boolean {
  const h = now.getHours() + now.getMinutes() / 60;
  return h >= (sunrise ?? 7) && h < (sunset ?? 19);
}

let autoTimer: number | null = null;
export function setAutoDark(on: boolean, apply: (theme: "light" | "dark") => void): void {
  if (autoTimer !== null) {
    clearInterval(autoTimer);
    autoTimer = null;
  }
  if (!on) return;
  const run = () => apply(isDay(new Date()) ? "light" : "dark");
  run();
  autoTimer = window.setInterval(run, 10 * 60 * 1000);
}
