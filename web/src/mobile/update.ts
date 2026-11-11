/* 3.12 Aktualizace jedním ťuknutím: the app looks for a newer JARVIS on GitHub (at start and every few hours) and
   shows a small bar "Nová verze · Aktualizovat". A tap downloads it and opens Android's own install dialog. */
import { h, icon, toast } from "../shared/dom";
import { native } from "./native";
import "./update.css";

const LATEST = "https://api.github.com/repos/adamekk778/JARViS2/releases/latest";
const SKIP_KEY = "jarvis.update.skip";

async function latest(): Promise<{ build: number; tag: string; url: string } | null> {
  try {
    const r = await fetch(LATEST, { headers: { Accept: "application/vnd.github+json" } });
    if (!r.ok) return null;
    const d = await r.json();
    const tag = String(d.tag_name || "");
    const build = Number(tag.split(".").pop());               // v3.10.170 → 170 (= the app's versionCode)
    const url = (d.assets || []).find((a: any) => a.name === "JARVIS.apk")?.browser_download_url || "";
    return build && url ? { build, tag: tag.replace(/^v/, ""), url } : null;
  } catch { return null; }
}

export function startUpdateCheck() {
  if (!native.isNative) return;
  let bar: HTMLElement | null = null;
  const check = async () => {
    const [st, rel] = await Promise.all([native.phone.status().catch(() => null), latest()]);
    const mine = Number(st?.versionCode) || 0;
    let skipped = "";
    try { skipped = localStorage.getItem(SKIP_KEY) || ""; } catch { /* private mode */ }
    if (!rel || !mine || rel.build <= mine || skipped === rel.tag || bar) return;
    const label = h("span", { class: "up-t" }, h("strong", {}, "Nová verze JARVISe"), h("span", {}, rel.tag));
    const fill = h("i", { class: "up-fill" });
    const go = h("button", { type: "button", class: "up-go" }, "Aktualizovat") as HTMLButtonElement;
    const later = h("button", { type: "button", class: "up-x", "aria-label": "Později" }, icon("x")) as HTMLButtonElement;
    bar = h("div", { class: "up-bar", role: "status" }, fill, h("span", { class: "up-ico" }, icon("arrow-circle-up", "ph-fill")), label, go, later);
    document.body.append(bar);
    later.onclick = () => { try { localStorage.setItem(SKIP_KEY, rel.tag); } catch { /* fine */ } bar?.remove(); bar = null; };
    go.onclick = async () => {
      go.disabled = true;
      go.textContent = "Stahuji…";
      try {
        await native.phone.installUpdate(rel.url, (p) => { fill.style.transform = `scaleX(${p.toFixed(3)})`; go.textContent = `${Math.round(p * 100)} %`; });
        go.textContent = "Instaluj";                         // Android's dialog is open now
      } catch (e: any) {
        toast(String(e?.message || e || "Aktualizace se nepovedla"), "error", 5000);
        go.disabled = false;
        go.textContent = "Zkusit znovu";
      }
    };
  };
  window.setTimeout(check, 4000);
  window.setInterval(check, 4 * 3600_000);
}
