// 3.14 Mapa světa v HUD (návrh 49): the rain radar (RainViewer), your home, the car, where your trips go and the planes
// over the house – on a dark map like in Tony's lab. Leaflet loads only when the map opens.
import { h, icon } from "../shared/dom";
import { at } from "../shared/motion";
import { play as sound } from "../shared/sounds";
import type { JarvisClient } from "../shared/ws";
import { mountGlobe, type Globe } from "./globe3d";

type MapData = {
  home: { lat: number; lon: number; name: string } | null;
  car: { lat: number; lon: number; text: string } | null;
  trips: { text: string; kind: string; points: { code: string; name: string; lat: number; lon: number }[] }[];
  planes: { lat: number; lon: number; callsign: string; alt_m?: number }[];
};

export function worldMap(client: JarvisClient) {
  let L: typeof import("leaflet") | null = null;
  let map: import("leaflet").Map | null = null;
  let layers: import("leaflet").LayerGroup | null = null;
  let radar: import("leaflet").TileLayer | null = null;
  let frames: { time: number; path: string }[] = [];
  let host = "";
  let frame = 0, timer = 0, showPlanes = true, showRadar = true;
  let globe: Globe | null = null, threeD = at("high"), last: MapData | null = null;   // 3.15 the 3D globe (from the high tier)
  const box = h("div", { class: "wm-map", role: "application", "aria-label": "Mapa světa" });
  const gbox = h("div", { class: "wm-globe", role: "application", "aria-label": "3D glóbus – táhni myší, kolečkem přibliž", hidden: true });
  const when = h("span", { class: "wm-when" });
  const legend = h("ul", { class: "wm-legend" });
  const btn = (label: string, ic: string, on: boolean, act: (b: HTMLButtonElement) => void) => {
    const b = h("button", { type: "button", class: `hbtn wm-btn ${on ? "on" : ""}`, "aria-pressed": String(on) }, icon(ic), label) as HTMLButtonElement;
    b.onclick = () => act(b);
    return b;
  };
  const toggle = (b: HTMLButtonElement, v: boolean) => { b.classList.toggle("on", v); b.setAttribute("aria-pressed", String(v)); };
  const radarBtn = btn("Radar", "cloud-rain", true, (b) => { showRadar = !showRadar; toggle(b, showRadar); paintRadar(); });
  const playBtn = btn("Přehrát", "play", false, (b) => { if (timer) stop(); else play(); toggle(b, !!timer); });
  const planeBtn = btn("Letadla", "airplane-tilt", true, (b) => { showPlanes = !showPlanes; toggle(b, showPlanes); ask(); });
  const dimBtn = btn("3D", "globe", threeD, (b) => { threeD = !threeD; toggle(b, threeD); void setView(); });
  const el = h("div", { class: "wm", hidden: true, role: "dialog", "aria-label": "Mapa světa" },
    h("header", { class: "wm-head" }, icon("globe-hemisphere-west"), h("span", {}, "MAPA SVĚTA"), when,
      h("div", { class: "wm-tools" }, dimBtn, radarBtn, playBtn, planeBtn,
        h("button", { type: "button", class: "hbtn", "aria-label": "Zavřít mapu", onclick: () => close() }, icon("x")))),
    box, gbox, legend);

  async function setView() {
    box.hidden = threeD;
    gbox.hidden = !threeD;
    if (threeD && !globe) {
      globe = await mountGlobe(gbox);
      if (!globe) { threeD = false; toggle(dimBtn, false); box.hidden = false; gbox.hidden = true; return; }
    }
    if (threeD && globe && last) { globe.update(last); paintRadar(); }
    if (!threeD) { await ensure(); map?.invalidateSize(); if (last) paint(last); }
  }

  async function ensure() {
    if (map) return;
    L = await import("leaflet");
    await import("leaflet/dist/leaflet.css");
    map = L.map(box, { zoomControl: false, attributionControl: true, worldCopyJump: true }).setView([49.8, 15.5], 6);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {          // OpenStreetMap, darkened in CSS (.wm-base)
      maxZoom: 18, className: "wm-base",
      attribution: "© <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> · radar <a href=\"https://www.rainviewer.com/\">RainViewer</a>",
    }).addTo(map);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    layers = L.layerGroup().addTo(map);
  }

  async function loadRadar() {
    try {
      const j = await (await fetch("https://api.rainviewer.com/public/weather-maps.json")).json();
      host = j.host || "https://tilecache.rainviewer.com";
      frames = (j.radar?.past || []).slice(-12);
      frame = frames.length - 1;
      paintRadar();
    } catch { when.textContent = "radar teď nejde načíst"; }
  }

  function paintRadar() {
    const f0 = frames[frame];
    if (globe && threeD) globe.radar(host, showRadar && f0 ? f0.path : null);
    if (!L || !map) {
      if (f0 && showRadar) when.textContent = `radar ${new Date(f0.time * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}`;
      return;
    }
    if (radar) { map.removeLayer(radar); radar = null; }
    const f = frames[frame];
    if (!showRadar || !f) { when.textContent = ""; return; }
    radar = L.tileLayer(`${host}${f.path}/256/{z}/{x}/{y}/2/1_1.png`, { opacity: 0.7, maxNativeZoom: 7, maxZoom: 18, zIndex: 5 }).addTo(map);
    when.textContent = `radar ${new Date(f.time * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}`;
  }
  function play() {
    if (!frames.length) return;
    timer = window.setInterval(() => { frame = (frame + 1) % frames.length; paintRadar(); }, 700);
  }
  function stop() { window.clearInterval(timer); timer = 0; frame = frames.length - 1; paintRadar(); }

  function paint(d: MapData) {
    last = d;
    if (globe && threeD) globe.update(showPlanes ? d : { ...d, planes: [] });
    if (!L || !map || !layers) { legend.replaceChildren(...legendItems(d)); return; }
    layers.clearLayers();
    const items: HTMLElement[] = [];
    const pts: [number, number][] = [];
    const dot = (lat: number, lon: number, color: string, label: string, r = 7) => {
      L!.circleMarker([lat, lon], { radius: r, color, weight: 2, fillColor: color, fillOpacity: 0.55 }).bindTooltip(label).addTo(layers!);
      pts.push([lat, lon]);
    };
    if (d.home) { dot(d.home.lat, d.home.lon, "#7fe3ff", `Domov – ${d.home.name}`, 9); items.push(h("li", { class: "home" }, `Domov · ${d.home.name}`)); }
    if (d.car) { dot(d.car.lat, d.car.lon, "#f5b942", d.car.text); items.push(h("li", { class: "car" }, d.car.text)); }
    for (const t of d.trips) {
      t.points.forEach((p) => dot(p.lat, p.lon, "#c084fc", `${p.name} (${p.code})`, 6));
      if (t.points.length === 2) L.polyline(t.points.map((p) => [p.lat, p.lon] as [number, number]), { color: "#c084fc", weight: 2, dashArray: "6 6", opacity: 0.8 }).addTo(layers);
      items.push(h("li", { class: "trip" }, t.text));
    }
    for (const p of showPlanes ? d.planes : []) {
      L.circleMarker([p.lat, p.lon], { radius: 4, color: "#ffffff", weight: 1, fillColor: "#ffffff", fillOpacity: 0.9 })
        .bindTooltip(`${p.callsign}${p.alt_m ? ` · ${(p.alt_m / 1000).toFixed(1)} km` : ""}`).addTo(layers);
    }
    if (showPlanes && d.planes.length) items.push(h("li", { class: "plane" }, `${d.planes.length} letadel nad domem`));
    legend.replaceChildren(...items);
    if (pts.length > 1) map.fitBounds(pts, { padding: [60, 60], maxZoom: 9 });
    else if (pts.length === 1) map.setView(pts[0], 8);
  }

  const ask = () => client.send("world_map_get" as any, { planes: showPlanes });
  client.on("world_map" as any, (m: any) => { (threeD ? Promise.resolve() : ensure()).then(() => paint(m as MapData)).catch(() => {}); });

  function legendItems(d: MapData): HTMLElement[] {
    const items: HTMLElement[] = [];
    if (d.home) items.push(h("li", { class: "home" }, `Domov · ${d.home.name}`));
    if (d.car) items.push(h("li", { class: "car" }, d.car.text));
    for (const t of d.trips) items.push(h("li", { class: "trip" }, t.text));
    if (showPlanes && d.planes.length) items.push(h("li", { class: "plane" }, `${d.planes.length} letadel nad domem`));
    return items;
  }

  async function open() {
    el.hidden = false;
    sound("whoosh");
    await setView();
    if (!threeD) map!.invalidateSize();
    ask();
    void loadRadar();
  }
  function close() { el.hidden = true; stop(); toggle(playBtn, false); sound("close"); }
  /** 3.15 voice: "přibliž mapu", "oddal", "přepni na glóbus / mapu", "pusť radar" */
  function command(action: string) {
    if (el.hidden && action !== "close_map") void open();
    if (action === "zoom_in") { if (threeD) globe?.zoom(0.75); else map?.zoomIn(); }
    else if (action === "zoom_out") { if (threeD) globe?.zoom(1.33); else map?.zoomOut(); }
    else if (action === "globe" && !threeD) { threeD = true; toggle(dimBtn, true); void setView(); }
    else if (action === "flat" && threeD) { threeD = false; toggle(dimBtn, false); void setView(); }
    else if (action === "radar_play" && !timer) { play(); toggle(playBtn, true); }
    else if (action === "close_map") close();
  }
  client.on("hud_map" as any, () => { open().catch(() => {}); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !el.hidden) { e.stopPropagation(); close(); } }, true);
  return { el, open, close, command };
}
