// OMEGA 080: a small game with the character – "Chyť hvězdy". He follows the mouse (or ←/→), stars fall,
// catch them and dodge the storm clouds. Everything stays in this window; the best score is remembered here.
import { Blob } from "../character/blob";
import { h, icon } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";

export interface Drop { x: number; y: number; vy: number; kind: "star" | "gold" | "storm"; el?: HTMLElement }

export const W = 640, H = 380, CATCHER_W = 70;

/** One step of the game: moves drops, returns what was caught / missed (pure, so it can be tested). */
export function step(drops: Drop[], px: number, dt: number) {
  const caught: Drop[] = [], missed: Drop[] = [], keep: Drop[] = [];
  for (const d of drops) {
    d.y += d.vy * dt;
    if (d.y >= H - 70 && d.y <= H - 20 && Math.abs(d.x - px) < CATCHER_W / 2 + 10) caught.push(d);
    else if (d.y > H) missed.push(d);
    else keep.push(d);
  }
  return { keep, caught, missed };
}

/** What falls next: storms get commoner and everything faster as the score grows. */
export function spawn(score: number, rnd: () => number = Math.random): Drop {
  const r = rnd();
  const kind: Drop["kind"] = r < Math.min(0.32, 0.08 + score / 200) ? "storm" : r > 0.93 ? "gold" : "star";
  return { x: 30 + rnd() * (W - 60), y: -20, vy: 110 + Math.min(260, score * 4) + rnd() * 60, kind };
}

const BEST = "jarvis.play.best";

export function buildPlay(_client: JarvisClient) {
  const field = h("div", { class: "play-field", tabindex: "0", "aria-label": "Herní plocha – pohybuj myší nebo šipkami" });
  const face = new Blob({ size: 64, trackCursor: false });
  face.setMood("idle");
  const catcher = h("div", { class: "play-catcher" }, face.el);
  const scoreEl = h("b", {}, "0");
  const livesEl = h("span", { class: "play-lives" });
  let best = 0;
  try { best = Number(localStorage.getItem(BEST)) || 0; } catch { /* private window */ }
  const bestEl = h("span", {}, `Rekord: ${best}`);
  const overlay = h("div", { class: "play-over" });
  field.append(catcher, overlay);

  let drops: Drop[] = [], score = 0, lives = 3, px = W / 2, target = W / 2, running = false, raf = 0, last = 0, nextSpawn = 0;
  const keys = { left: false, right: false };

  const paintLives = () => livesEl.replaceChildren(...Array.from({ length: 3 }, (_, i) => icon(i < lives ? "heart" : "heart-break", i < lives ? "ph-fill" : "ph")));
  const showOver = (title: string, sub: string) => {
    overlay.hidden = false;
    overlay.replaceChildren(h("strong", {}, title), h("span", {}, sub),
      h("button", { class: "btn", type: "button", onclick: start }, icon("play"), score ? "Hrát znovu" : "Hrát"));
  };
  function start() {
    for (const d of drops) d.el?.remove();
    drops = []; score = 0; lives = 3; running = true; overlay.hidden = true;
    scoreEl.textContent = "0"; paintLives(); face.setMood("idle");
    field.focus();
    last = performance.now(); nextSpawn = 0;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(loop);
  }
  function end() {
    running = false;
    face.setMood("dizzy");
    if (score > best) {
      best = score;
      try { localStorage.setItem(BEST, String(best)); } catch { /* ignore */ }
      bestEl.textContent = `Rekord: ${best}`;
      showOver("Nový rekord!", `${score} hvězd`);
      face.setMood("joy");
    } else showOver("Konec hry", `${score} hvězd · rekord ${best}`);
  }
  function loop(now: number) {
    if (!running) return;
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (keys.left) target -= 420 * dt;
    if (keys.right) target += 420 * dt;
    target = Math.max(CATCHER_W / 2, Math.min(W - CATCHER_W / 2, target));
    px += (target - px) * Math.min(1, dt * 14);
    catcher.style.transform = `translateX(${(px - 32).toFixed(1)}px)`;
    face.face((target - px) / 60, -0.4);
    if (now > nextSpawn) {
      const d = spawn(score);
      d.el = h("i", { class: `play-drop ${d.kind} ph-fill ph-${d.kind === "storm" ? "cloud-lightning" : d.kind === "gold" ? "star-four" : "star"}` });
      field.append(d.el);
      drops.push(d);
      nextSpawn = now + Math.max(320, 900 - score * 12);
    }
    const r = step(drops, px, dt);
    drops = r.keep;
    for (const d of r.caught) {
      d.el?.remove();
      if (d.kind === "storm") { lives--; face.setMood("annoyed"); face.wobble(2.6); setTimeout(() => running && face.setMood("idle"), 700); }
      else { score += d.kind === "gold" ? 5 : 1; face.wobble(-1.2); if (d.kind === "gold") { face.setMood("joy"); setTimeout(() => running && face.setMood("idle"), 900); } }
    }
    for (const d of r.missed) {
      d.el?.remove();
      if (d.kind !== "storm") lives--;
    }
    for (const d of drops) d.el!.style.transform = `translate(${d.x.toFixed(1)}px, ${d.y.toFixed(1)}px)`;
    scoreEl.textContent = String(score);
    paintLives();
    if (lives <= 0) { end(); return; }
    raf = requestAnimationFrame(loop);
  }

  field.addEventListener("pointermove", (e) => {
    const r = field.getBoundingClientRect();
    target = ((e.clientX - r.left) / r.width) * W;
  });
  field.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") { keys.left = true; e.preventDefault(); }
    if (e.key === "ArrowRight") { keys.right = true; e.preventDefault(); }
    if ((e.key === " " || e.key === "Enter") && !running) { e.preventDefault(); start(); }
  });
  field.addEventListener("keyup", (e) => {
    if (e.key === "ArrowLeft") keys.left = false;
    if (e.key === "ArrowRight") keys.right = false;
  });

  paintLives();
  showOver("Chyť hvězdy", "Pohybuj myší nebo šipkami. Hvězdy chytej, bouřkovým mrakům se vyhni. Zlatá hvězda = 5 bodů.");
  const el = h("section", { class: "tasks-view play-view" },
    h("h2", { class: "group-label" }, "Hra s postavičkou"),
    h("div", { class: "play-hud" }, h("span", {}, "Skóre: ", scoreEl), livesEl, bestEl),
    field);
  return {
    el,
    show: () => field.focus(),
    hide: () => { if (running) { running = false; cancelAnimationFrame(raf); showOver("Pauza", `${score} hvězd`); } },
  };
}
