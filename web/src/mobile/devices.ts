// Wave 34 on the phone: photos for the PC (413 / 723 / 729), the PC's shared folders (415), places for automations
// (728 – the position never leaves the phone), command QR codes (731) and the guest remote (727).
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import { native } from "./native";

// ---------------------------------------------------------------- 731 command links
export function parseCommandLink(url: string): string | null {
  if (!url.startsWith("jarvis://cmd?")) return null;
  const text = new URLSearchParams(url.slice("jarvis://cmd?".length)).get("text") || "";
  const clean = text.replace(/\s+/g, " ").trim().slice(0, 300);
  return clean || null;
}

/** A command from a QR code is someone else's text until you say yes – it is shown first, never run on its own. */
export async function confirmCommand(c: JarvisClient, text: string) {
  if (!window.confirm(`Příkaz z QR kódu:\n\n„${text}“\n\nPoslat ho JARVISovi na PC?`)) return;
  c.send("user_text", { text, attachments: [] });
  toast("Odesláno JARVISovi", "ok", 1600);
}

// ---------------------------------------------------------------- 413 / 723 / 729 photos
function pickPhoto(): Promise<File | null> {
  return new Promise((resolve) => {
    const inp = h("input", { type: "file", accept: "image/*", capture: "environment", hidden: true }) as HTMLInputElement;
    inp.onchange = () => { resolve(inp.files?.[0] || null); inp.remove(); };
    document.body.append(inp);
    inp.click();
  });
}

export async function sendPhoto(c: JarvisClient, purpose: "shelf" | "task" | "ask", id = "") {
  const f = await pickPhoto();
  if (!f) return;
  try {
    toast("Posílám fotku…", "info", 1500);
    const att = await c.upload(f, f.name || "fotka.jpg");
    c.send("phone_photo", { attachment_id: att.id, purpose, id });
    toast(purpose === "task" ? "JARVIS z fotky vypíše úkoly" : purpose === "ask" ? "JARVIS se dívá, co to je…" : "Fotka je na PC v polici notche", "ok");
    native.haptic();
  } catch (e: any) { toast(e.message || "Fotku se nepodařilo poslat", "error"); }
}

export function photoCard(c: JarvisClient): HTMLElement {
  return h("div", { class: "card", id: "m-photo" }, h("h2", {}, "Fotka pro PC"),
    h("p", { class: "help" }, "Kamera se zapne jen ve chvíli, kdy na tlačítko klepneš."),
    h("div", { class: "ctl-grid" },
      h("button", { class: "ctl primary", type: "button", onclick: () => sendPhoto(c, "shelf") }, icon("camera"), h("span", {}, "Fotka na PC")),
      h("button", { class: "ctl", type: "button", onclick: () => sendPhoto(c, "task") }, icon("list-checks"), h("span", {}, "Fotka → úkoly")),
      h("button", { class: "ctl", type: "button", onclick: () => sendPhoto(c, "ask") }, icon("magnifying-glass"), h("span", {}, "Co to je?")),
      h("button", { class: "ctl", type: "button", onclick: () => scanCommand(c) }, icon("qr-code"), h("span", {}, "Skenovat příkaz"))));
}

export async function scanCommand(c: JarvisClient) {
  try {
    const text = await native.scanQr();
    if (!text) return;
    const cmd = parseCommandLink(text);
    if (cmd) return confirmCommand(c, cmd);
    toast("Tohle není QR kód s příkazem pro JARVISe.", "error");
  } catch (e: any) { toast(e.message || "Skenování se nepodařilo", "error"); }
}

/** The PC asks for a photo: a card with the reason, the camera opens only after "Vyfotit". */
export function photoRequests(c: JarvisClient, host: HTMLElement, onShow: () => void) {
  c.on("phone_photo_request", (m) => {
    const card = h("div", { class: "card m-ask" },
      h("div", { class: "m-ask-head" }, icon("camera", "ph-fill"), h("div", {}, h("strong", {}, "PC žádá fotku"), h("span", {}, m.reason || ""))),
      h("div", { class: "btn-row" },
        h("button", { class: "btn", type: "button", onclick: () => card.remove() }, "Odmítnout"),
        h("button", { class: "btn primary", type: "button", onclick: async () => { card.remove(); await sendPhoto(c, "shelf", m.id); } }, icon("camera"), "Vyfotit")));
    host.prepend(card);
    onShow();
    native.haptic();
    if (document.hidden) native.notify("JARVIS žádá fotku", m.reason || "Otevři aplikaci");
  });
}

// ---------------------------------------------------------------- 415 the PC's shared folders
export function pcFilesCard(c: JarvisClient): HTMLElement {
  const box = h("div", { class: "m-files" });
  let root: string | null = null, path = "";
  const fmt = (n: number) => n > 1 << 30 ? `${(n / (1 << 30)).toFixed(1)} GB` : n > 1 << 20 ? `${(n / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} kB`;
  const open = (r: string | null, p = "") => { root = r; path = p; c.send("pc_files", r == null ? {} : { root: r, path: p }); };
  c.on("pc_files", (m) => {
    if (m.error) toast(m.error, "error");
    const roots: any[] = m.roots || [];
    if (root == null || m.error) {
      box.replaceChildren(...(roots.length ? roots.map((r) => h("button", { class: "m-file", type: "button", disabled: !r.ok, onclick: () => open(r.id) },
        icon("folder", "ph-fill"), h("span", {}, r.name), r.ok ? null : h("em", {}, "nedostupná")))
        : [h("p", { class: "help" }, "Na PC zatím není žádná složka sdílená s telefonem (JARVIS → Nastavení → Telefon).")]));
      root = null;
      return;
    }
    const up = path ? path.split("/").slice(0, -1).join("/") : null;
    box.replaceChildren(
      h("button", { class: "m-file up", type: "button", onclick: () => (up == null ? open(null) : open(root, up)) }, icon("arrow-left"), h("span", {}, path || "Zpět na složky")),
      ...(m.items || []).map((f: any) => f.dir
        ? h("button", { class: "m-file", type: "button", onclick: () => open(root, path ? `${path}/${f.name}` : f.name) }, icon("folder", "ph-fill"), h("span", {}, f.name))
        : h("a", { class: "m-file", href: c.url(`/api/pc_file?root=${encodeURIComponent(root!)}&path=${encodeURIComponent(path ? `${path}/${f.name}` : f.name)}`), target: "_blank", rel: "noopener" },
          icon("file"), h("span", {}, f.name), h("em", {}, fmt(f.size)))),
      ...(m.more ? [h("p", { class: "help" }, "…a další. Ukazuji nejnovějších 300.")] : []));
  });
  return h("div", { class: "card" }, h("h2", {}, "Soubory z PC"),
    h("p", { class: "help" }, "Jen složky, které jsi na PC povolil. Soubory se dají stáhnout, nic se tu nemaže ani nemění."),
    box, h("button", { class: "btn", type: "button", onclick: () => open(null) }, icon("arrows-clockwise"), "Načíst"));
}

// ---------------------------------------------------------------- 728 places (geofences on the phone)
export interface Place { name: string; lat: number; lon: number; r: number; inside?: boolean }
const PKEY = "jarvis.places";
export function loadPlaces(): Place[] { try { return JSON.parse(localStorage.getItem(PKEY) || "[]"); } catch { return []; } }
function savePlaces(p: Place[]) { try { localStorage.setItem(PKEY, JSON.stringify(p)); } catch { /* ignore */ } }

export function distanceM(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const R = 6371000, rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad, dLon = (b.lon - a.lon) * rad;
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

/** Which places were entered / left at this position (a 30 % margin stops flapping at the edge). */
export function placeChanges(places: Place[], pos: { lat: number; lon: number; acc: number }) {
  const out: { name: string; event: "enter" | "leave" }[] = [];
  for (const p of places) {
    const d = distanceM(p, pos);
    if (pos.acc > Math.max(200, p.r * 2)) continue;              // too vague to decide
    const inside = p.inside ? d < p.r * 1.3 : d < p.r;
    if (p.inside !== undefined && inside !== p.inside) out.push({ name: p.name, event: inside ? "enter" : "leave" });
    p.inside = inside;
  }
  return out;
}

export function placesCard(c: JarvisClient): HTMLElement {
  const box = h("div", { class: "m-places" });
  const name = h("input", { class: "input", placeholder: "Název místa (Domov, Práce…)", "aria-label": "Název místa" }) as HTMLInputElement;
  const on = h("input", { type: "checkbox", role: "switch", "aria-label": "Hlídat místa" }) as HTMLInputElement;
  on.checked = localStorage.getItem("jarvis.places.on") === "1";
  let watch: number | null = null;
  const paint = () => box.replaceChildren(...loadPlaces().map((p, i) => h("div", { class: "row" },
    icon(p.inside ? "map-pin-area" : "map-pin"), h("div", { class: "row-text" }, h("strong", {}, p.name), h("span", {}, `okruh ${p.r} m${p.inside ? " · jsi tady" : ""}`)),
    h("button", { class: "icon-btn", type: "button", "aria-label": `Smazat ${p.name}`, onclick: () => { const all = loadPlaces(); all.splice(i, 1); savePlaces(all); paint(); } }, icon("trash")))));
  const start = () => {
    if (watch != null || !navigator.geolocation) return;
    watch = navigator.geolocation.watchPosition((g) => {
      const places = loadPlaces();
      for (const ch of placeChanges(places, { lat: g.coords.latitude, lon: g.coords.longitude, acc: g.coords.accuracy })) {
        c.send("phone_zone", { zone: ch.name, event: ch.event });        // only the name and enter / leave go to the PC
      }
      savePlaces(places);
      paint();
    }, () => {}, { enableHighAccuracy: false, maximumAge: 120000, timeout: 60000 });
  };
  const stop = () => { if (watch != null) navigator.geolocation.clearWatch(watch); watch = null; };
  on.onchange = () => { localStorage.setItem("jarvis.places.on", on.checked ? "1" : "0"); on.checked ? start() : stop(); };
  if (on.checked) start();
  const add = () => {
    if (!name.value.trim()) return toast("Napiš název místa", "error");
    navigator.geolocation?.getCurrentPosition((g) => {
      const all = loadPlaces().filter((p) => p.name.toLowerCase() !== name.value.trim().toLowerCase());
      all.push({ name: name.value.trim().slice(0, 40), lat: g.coords.latitude, lon: g.coords.longitude, r: 150, inside: true });
      savePlaces(all); name.value = ""; paint(); toast("Místo uloženo", "ok");
    }, () => toast("Polohu se nepodařilo zjistit (povol ji aplikaci)", "error"), { enableHighAccuracy: true, timeout: 20000 });
  };
  paint();
  return h("div", { class: "card" }, h("h2", {}, "Místa"),
    h("p", { class: "help" }, "Pro automatizace „Když přijdu domů…“. Poloha zůstává jen v telefonu – PC se dozví jen „přišel jsi na místo Domov“. Funguje, když je aplikace otevřená."),
    h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Hlídat místa"), h("span", {}, "Vypnuto = poloha se vůbec nezjišťuje")), h("label", { class: "switch" }, on, h("span"))),
    box, h("div", { class: "inline" }, name, h("button", { class: "btn", type: "button", onclick: add }, icon("map-pin"), "Uložit, kde jsem")));
}

// ---------------------------------------------------------------- 727 the guest remote
export function guestView(c: JarvisClient, guest: any): HTMLElement {
  const q = (action: string, args: any) => { native.haptic(); c.send("quick_action", { action, args }); };
  const vol = h("input", { type: "range", min: 0, max: 100, value: 50, "aria-label": "Hlasitost" }) as HTMLInputElement;
  vol.onchange = () => q("volume", { action: "set", level: Number(vol.value) });
  const yt = h("input", { class: "input", placeholder: "Co pustit na YouTube?", enterkeyhint: "go" }) as HTMLInputElement;
  yt.addEventListener("keydown", (e) => { if (e.key === "Enter" && yt.value.trim()) { q("youtube_play", { query: yt.value.trim() }); yt.value = ""; } });
  const title = h("strong", {}, "Nic nehraje");
  c.on("media", (m) => { title.textContent = m.title ? `${m.title}${m.artist ? ` – ${m.artist}` : ""}` : "Nic nehraje"; });
  const until = new Date(guest.expires * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  return h("div", { class: "m-shell m-guest" },
    h("header", { class: "m-head" }, h("div", { class: "m-title" }, icon("music-notes"), h("div", {}, h("strong", {}, `Host · ${guest.name}`), h("span", { class: "m-status" }, `přístup do ${until}`)))),
    h("section", { class: "m-view" },
      h("div", { class: "card" }, h("h2", {}, "Hraje"), title,
        h("div", { class: "media-row" },
          h("button", { class: "ctl", type: "button", onclick: () => q("media_control", { action: "previous" }) }, icon("skip-back"), h("span", {}, "Předchozí")),
          h("button", { class: "ctl primary", type: "button", onclick: () => q("media_control", { action: "play_pause" }) }, icon("play-pause"), h("span", {}, "Play / pauza")),
          h("button", { class: "ctl", type: "button", onclick: () => q("media_control", { action: "next" }) }, icon("skip-forward"), h("span", {}, "Další"))),
        h("div", { class: "vol" }, icon("speaker-low"), vol, icon("speaker-high"))),
      h("div", { class: "card" }, h("h2", {}, "Pustit"), yt),
      h("p", { class: "help" }, "Jako host ovládáš jen hudbu a hlasitost. Chat, soubory ani nastavení nevidíš.")));
}

// ---------------------------------------------------------------- 717 home network speed phone ↔ PC
export function mbps(bytes: number, ms: number): number {
  return ms > 0 ? Math.round((bytes * 8) / (ms / 1000) / 1e5) / 10 : 0;
}

export function lanSpeedCard(c: JarvisClient): HTMLElement {
  const out = h("div", { class: "m-stats" });
  const btn = h("button", { class: "btn primary", type: "button" }, icon("gauge"), "Změřit") as HTMLButtonElement;
  btn.onclick = async () => {
    btn.disabled = true;
    out.replaceChildren(h("p", { class: "help" }, "Měřím… (asi 10 s, přenese se ~30 MB jen po domácí síti)"));
    try {
      const pings: number[] = [];
      for (let i = 0; i < 5; i++) {
        const t = performance.now();
        await fetch(c.url("/api/health"), { cache: "no-store" });
        pings.push(performance.now() - t);
      }
      let t = performance.now();
      const r = await fetch(c.url("/api/speedtest?mb=20"), { cache: "no-store" });
      const down = (await r.arrayBuffer()).byteLength;
      const dMs = performance.now() - t;
      const body = new Uint8Array(10 << 20);
      for (let i = 0; i < body.length; i += 4096) body[i] = (i * 31) & 255;
      t = performance.now();
      await fetch(c.url("/api/speedtest"), { method: "POST", body, cache: "no-store" });
      const uMs = performance.now() - t;
      const ping = Math.round(pings.sort((a, b) => a - b)[2]);
      const dl = mbps(down, dMs), ul = mbps(body.length, uMs);
      out.replaceChildren(
        ...[["Do telefonu", `${dl} Mb/s`], ["Do PC", `${ul} Mb/s`], ["Odezva", `${ping} ms`]].map(([k, v]) => h("div", {}, h("strong", {}, v), h("span", { class: "muted" }, k))),
        h("p", { class: "help" }, dl < 20 ? "Pomalé – přibliž se k routeru, nebo přepni telefon na Wi-Fi 5 GHz." : dl < 100 ? "Dobré na běžné věci." : "Výborné."));
    } catch {
      out.replaceChildren(h("p", { class: "help" }, "Měření se nepovedlo – je telefon ve stejné síti jako PC?"));
    } finally {
      btn.disabled = false;
    }
  };
  return h("div", { class: "card" }, h("h2", {}, "Rychlost Wi-Fi k PC"),
    h("p", { class: "help" }, "Jak rychle si telefon a počítač posílají data po domácí síti (ne internet)."), out, btn);
}

// ---------------------------------------------------------------- 140 the PC at a glance
export function pcStatusCard(c: JarvisClient): HTMLElement {
  const out = h("div", { class: "m-stats" }, h("p", { class: "help" }, "Načítám…"));
  c.on("system", (s) => {
    const items: [string, string][] = [["Procesor", `${Math.round(s.cpu_percent ?? 0)} %`], ["Paměť", `${Math.round(s.ram_percent ?? 0)} %`],
      ["Disk volno", `${s.disk_free_gb ?? "—"} GB`], ["Zapnuto", `${s.uptime_h ?? "—"} h`]];
    if (s.battery_percent != null) items.push(["Baterie", `${s.battery_percent} %${s.charging ? " ⚡" : ""}`]);
    out.replaceChildren(...items.map(([k, v]) => h("div", {}, h("strong", {}, v), h("span", { class: "muted" }, k))));
  });
  const load = () => c.send("system_get", {});
  c.on("welcome", load);
  return h("div", { class: "card" }, h("h2", {}, "Stav PC"), out,
    h("button", { class: "btn", type: "button", onclick: load }, icon("arrows-clockwise"), "Obnovit"));
}
