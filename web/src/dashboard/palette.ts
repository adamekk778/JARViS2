import { h, icon } from "../shared/dom";

export interface PaletteItem { icon: string; label: string; run: () => void }

const norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

/** Ctrl+K: jump to any page, run a quick action, or search the settings. */
export function commandPalette(opts: { nav: PaletteItem[]; actions: PaletteItem[]; search: (q: string) => void }) {
  const input = h("input", { class: "pal-input", type: "text", placeholder: "Kam chceš jít nebo co udělat?", "aria-label": "Hledat" }) as HTMLInputElement;
  const list = h("div", { class: "pal-list", role: "listbox" });
  const box = h("div", { class: "pal-box", role: "dialog", "aria-modal": "true", "aria-label": "Rychlé hledání" },
    h("div", { class: "pal-head" }, icon("magnifying-glass"), input, h("kbd", {}, "Esc")), list);
  const root = h("div", { class: "palette", hidden: true, onclick: (e: MouseEvent) => { if (e.target === root) close(); } }, box);
  document.body.append(root);

  let items: PaletteItem[] = [];
  let sel = 0;

  function render() {
    const q = norm(input.value.trim());
    const match = (it: PaletteItem) => !q || norm(it.label).includes(q);
    const groups: [string, PaletteItem[]][] = [["Akce", opts.actions.filter(match)], ["Přejít na", opts.nav.filter(match)]];
    if (q) groups.push(["Nastavení", [{ icon: "sliders", label: `Hledat v nastavení: „${input.value.trim()}“`, run: () => opts.search(input.value.trim()) }]]);
    items = groups.flatMap(([, g]) => g);
    sel = Math.min(sel, Math.max(0, items.length - 1));
    let i = 0;
    list.replaceChildren(...groups.filter(([, g]) => g.length).flatMap(([title, g]) => [
      h("div", { class: "pal-group" }, title),
      ...g.map((it) => {
        const idx = i++;
        return h("button", { class: `pal-item ${idx === sel ? "on" : ""}`, type: "button", role: "option", "aria-selected": String(idx === sel),
          onmousemove: () => { if (sel !== idx) { sel = idx; render(); } }, onclick: () => run(idx) }, icon(it.icon), h("span", {}, it.label));
      })]));
    list.querySelector(".pal-item.on")?.scrollIntoView({ block: "nearest" });
  }

  function run(idx: number) {
    const it = items[idx];
    close();
    it?.run();
  }

  function open() {
    input.value = "";
    sel = 0;
    render();
    root.hidden = false;
    requestAnimationFrame(() => { root.classList.add("show"); input.focus(); });
  }

  function close() {
    root.classList.remove("show");
    root.hidden = true;
  }

  input.addEventListener("input", () => { sel = 0; render(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); sel = (sel + 1) % Math.max(1, items.length); render(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = (sel - 1 + items.length) % Math.max(1, items.length); render(); }
    else if (e.key === "Enter") { e.preventDefault(); run(sel); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
  });

  return { open, close };
}
