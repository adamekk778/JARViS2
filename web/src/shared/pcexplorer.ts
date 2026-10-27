// OMEGA 193: the parts of the PC as a little 3D "case" you can turn with the mouse or finger: processor, memory, graphics,
// disks, network, battery – each box sized by capacity and coloured by how loaded it is. Click a part for details.
import "./pcexplorer.css";
import { h, icon } from "./dom";
import type { JarvisClient } from "./ws";

const ICON: Record<string, string> = { cpu: "cpu", ram: "memory", gpu: "graphics-card", disk: "hard-drives", net: "wifi-high", battery: "battery-high" };
const LABEL: Record<string, string> = { cpu: "Procesor", ram: "Paměť", gpu: "Grafika", disk: "Disk", net: "Síť", battery: "Baterie" };

function loadColor(load: number | null): string {
  if (load == null) return "var(--accent)";
  return load > 90 ? "#ef4444" : load > 70 ? "#f59e0b" : "#22c55e";
}

export function pcExplorer(client: JarvisClient): { el: HTMLElement; refresh: () => void } {
  const scene = h("div", { class: "pcx-scene" });
  const box = h("div", { class: "pcx-case" }, scene);
  const info = h("div", { class: "pcx-info" }, h("span", { class: "muted" }, "Klikni na součástku. Otáčíš tažením."));
  let rx = -18, ry = 32;
  const turn = () => { scene.style.transform = `rotateX(${rx}deg) rotateY(${ry}deg)`; };
  let drag: { x: number; y: number; moved: boolean } | null = null;
  box.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, moved: false }; });
  box.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (!drag.moved) {                       // a click on a part stays a click; only a real drag turns the case
      if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) < 5) return;
      drag.moved = true;
      box.setPointerCapture(e.pointerId);
    }
    ry += (e.clientX - drag.x) * 0.4;
    rx = Math.max(-70, Math.min(70, rx - (e.clientY - drag.y) * 0.4));
    drag = { x: e.clientX, y: e.clientY, moved: true };
    turn();
  });
  box.addEventListener("pointerup", () => { drag = null; });
  client.on("hardware", (m) => {
    const parts: any[] = m.parts || [];
    const kinds = ["cpu", "ram", "gpu", "disk", "net", "battery"];
    scene.replaceChildren(...parts.map((p, i) => {
      const row = kinds.indexOf(p.kind);
      const same = parts.filter((q) => q.kind === p.kind);
      const col = same.indexOf(p);
      const w = Math.max(40, Math.min(110, 36 + Math.log2(1 + (p.size || 1)) * 12));
      const el = h("button", {
        class: `pcx-part k-${p.kind}`, type: "button", title: `${LABEL[p.kind] || p.kind}: ${p.name}`,
        style: `--w:${w}px;--c:${loadColor(p.load)};transform: translate3d(${(col - (same.length - 1) / 2) * 120}px, ${(row - 2.5) * 46}px, ${(i % 2) * 30}px)`,
        onclick: (e: Event) => {
          e.stopPropagation();
          info.replaceChildren(icon(ICON[p.kind] || "cube"), h("div", {}, h("strong", {}, `${LABEL[p.kind] || p.kind}: ${p.name}`),
            h("span", {}, p.detail + (p.load != null ? ` · vytížení ${Math.round(p.load)} %` : ""))));
        } },
        h("i", { class: "pcx-face top" }), h("i", { class: "pcx-face side" }), h("span", {}, icon(ICON[p.kind] || "cube"), LABEL[p.kind] || p.kind));
      return el;
    }));
    turn();
  });
  const el = h("div", { class: "card pcx" }, h("div", { class: "pcx-head" }, h("h3", {}, "Počítač zevnitř"),
    h("button", { class: "btn ghost sm", type: "button", onclick: () => client.send("hardware_get") }, icon("arrows-clockwise"), "Obnovit")), box, info);
  return { el, refresh: () => client.send("hardware_get") };
}
