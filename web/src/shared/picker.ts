/* Nicer option pickers for the dashboard. Every <select> keeps working as it is (its value, its change handlers, its place in
   the layout), only the plain system list is replaced by a JARVIS-styled one: a check at the chosen option, a short
   description under the name ("Kamarád (tyká, uvolněný)" → "Kamarád" + "tyká, uvolněný"), a search box for long lists,
   arrows / Enter / Esc / typing a letter. Sliders get a filled track. Turned on once with autoControls(document.body). */
import "./picker.css";
import { h } from "./dom";

let open: { sel: HTMLSelectElement; pop: HTMLElement; close: (focus?: boolean) => void } | null = null;
const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** "Name (what it means)" or "Name – what it means" → ["Name", "what it means"]; an explicit data-desc wins. */
export function splitLabel(text: string, desc = ""): [string, string] {
  if (desc) return [text, desc];
  const t = text.trim();
  const m = /^(.+?)\s+\(([^()]+)\)$/.exec(t) || /^(.{2,40}?)\s+[–—]\s+(.+)$/.exec(t);   // "Name (detail)" or "Name – detail"
  return m ? [m[1], m[2]] : [t, ""];
}

function choose(sel: HTMLSelectElement, value: string) {
  if (sel.value === value) return;
  sel.value = value;
  sel.dispatchEvent(new Event("input", { bubbles: true }));
  sel.dispatchEvent(new Event("change", { bubbles: true }));
}

function openPicker(sel: HTMLSelectElement) {
  if (open?.sel === sel) return open.close(true);
  open?.close();
  const opts = [...sel.options];
  const search = opts.length > 8 ? h("input", { class: "pk-search", type: "text", placeholder: "Hledat…", "aria-label": "Hledat v možnostech" }) as HTMLInputElement : null;
  const list = h("div", { class: "pk-list", role: "listbox", "aria-label": sel.getAttribute("aria-label") || "" });
  const pop = h("div", { class: "pk-pop" }, search ? h("div", { class: "pk-search-row" }, h("i", { class: "ph ph-magnifying-glass" }), search) : null, list);
  let items: { el: HTMLElement; value: string; text: string }[] = [];
  let active = -1;

  const render = () => {
    const q = norm(search?.value || "");
    list.replaceChildren();
    items = [];
    let group: HTMLOptGroupElement | null = null;
    for (const o of opts) {
      if (o.hidden) continue;
      const [name, desc] = splitLabel(o.textContent || o.value, o.dataset.desc || "");
      if (q && !norm(`${name} ${desc}`).includes(q)) continue;
      const g = o.parentElement instanceof HTMLOptGroupElement ? o.parentElement : null;
      if (g && g !== group) list.append(h("div", { class: "pk-group" }, g.label));
      group = g;
      const on = o.value === sel.value;
      const el = h("div", { class: `pk-opt${on ? " on" : ""}${o.disabled ? " off" : ""}`, role: "option", "aria-selected": String(on), "aria-disabled": o.disabled ? "true" : null },
        h("i", { class: "ph ph-check pk-check", "aria-hidden": "true" }),
        h("span", { class: "pk-text" }, h("span", { class: "pk-name" }, name), desc ? h("span", { class: "pk-desc" }, desc) : null));
      if (!o.disabled) {
        const idx = items.length;
        el.onmouseenter = () => setActive(idx, false);
        el.onclick = () => { choose(sel, o.value); close(true); };
        items.push({ el, value: o.value, text: norm(name) });
      }
      list.append(el);
    }
    if (!items.length) list.append(h("div", { class: "pk-empty" }, "Nic nenalezeno"));
    setActive(Math.max(0, items.findIndex((i) => i.value === sel.value)), true);
  };
  const setActive = (i: number, scroll = true) => {
    items[active]?.el.classList.remove("act");
    active = items.length ? (i + items.length) % items.length : -1;
    const it = items[active];
    if (!it) return;
    it.el.classList.add("act");
    if (scroll) it.el.scrollIntoView({ block: "nearest" });
  };
  const place = () => {
    const r = sel.getBoundingClientRect();
    const vw = innerWidth, vh = innerHeight;
    const width = Math.min(Math.max(r.width, 240), vw - 16);
    const below = vh - r.bottom - 12, above = r.top - 12;
    const up = below < 220 && above > below;
    pop.style.width = `${width}px`;
    pop.style.left = `${Math.min(Math.max(8, r.left), vw - width - 8)}px`;
    pop.style.maxHeight = `${Math.max(160, Math.min(360, up ? above : below))}px`;
    pop.style.top = up ? "" : `${r.bottom + 6}px`;
    pop.style.bottom = up ? `${vh - r.top + 6}px` : "";
    pop.classList.toggle("up", up);
  };
  let typed = "", typedAt = 0;
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") setActive(active + 1);
    else if (e.key === "ArrowUp") setActive(active - 1);
    else if (e.key === "Home" && !search) setActive(0);
    else if (e.key === "End" && !search) setActive(items.length - 1);
    else if (e.key === "Enter" || (e.key === " " && !search)) { const it = items[active]; if (it) choose(sel, it.value); close(true); }
    else if (e.key === "Escape") close(true);
    else if (e.key === "Tab") return close();
    else if (!search && e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {   // type a letter → jump to it
      typed = (Date.now() - typedAt > 700 ? "" : typed) + norm(e.key);
      typedAt = Date.now();
      const i = items.findIndex((it) => it.text.startsWith(typed));
      if (i >= 0) setActive(i);
    } else return;
    e.preventDefault();
    e.stopPropagation();
  };
  const onDown = (e: Event) => { if (!pop.contains(e.target as Node) && e.target !== sel) close(); };
  const onScroll = (e: Event) => { if (!pop.contains(e.target as Node)) close(); };
  const close = (focus = false) => {
    if (open?.pop !== pop) return;
    open = null;
    sel.classList.remove("pk-open");
    sel.setAttribute("aria-expanded", "false");
    window.removeEventListener("keydown", onKey, true);
    window.removeEventListener("pointerdown", onDown, true);
    window.removeEventListener("scroll", onScroll, true);
    window.removeEventListener("resize", onResize);
    pop.classList.add("bye");
    setTimeout(() => pop.remove(), 140);
    if (focus) sel.focus({ preventScroll: true });
  };
  const onResize = () => close();

  render();
  document.body.append(pop);
  place();
  open = { sel, pop, close };
  sel.classList.add("pk-open");
  sel.setAttribute("aria-expanded", "true");
  search?.addEventListener("input", render);
  search?.focus({ preventScroll: true });
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("pointerdown", onDown, true);
  window.addEventListener("scroll", onScroll, true);
  window.addEventListener("resize", onResize);
}

export function enhanceSelect(sel: HTMLSelectElement) {
  if (sel.dataset.picker || sel.multiple || sel.size > 1 || sel.dataset.native !== undefined) return;
  sel.dataset.picker = "1";
  sel.setAttribute("aria-haspopup", "listbox");
  sel.addEventListener("mousedown", (e) => {
    if (e.button !== 0 || sel.disabled) return;
    e.preventDefault();                         // no system list: ours opens instead
    sel.focus({ preventScroll: true });
    openPicker(sel);
  });
  sel.addEventListener("keydown", (e) => {
    if (open?.sel === sel || sel.disabled) return;
    if (["ArrowDown", "ArrowUp", "Enter", " ", "F4"].includes(e.key)) { e.preventDefault(); openPicker(sel); }
  });
}

/** A slider shows how far it is: the track left of the knob is filled with the accent colour. */
export function fillRange(inp: HTMLInputElement) {
  const min = Number(inp.min || 0), max = Number(inp.max || 100);
  const p = max > min ? ((Number(inp.value) - min) / (max - min)) * 100 : 0;
  inp.style.setProperty("--p", `${Math.min(100, Math.max(0, p))}%`);
}

export function autoControls(root: HTMLElement) {
  const scan = (n: ParentNode) => {
    n.querySelectorAll?.("select").forEach((s) => enhanceSelect(s as HTMLSelectElement));
    n.querySelectorAll?.('input[type="range"]').forEach((r) => fillRange(r as HTMLInputElement));
  };
  scan(root);
  new MutationObserver((muts) => {
    for (const m of muts) m.addedNodes.forEach((n) => {
      if (n instanceof HTMLSelectElement) enhanceSelect(n);
      else if (n instanceof HTMLInputElement && n.type === "range") fillRange(n);
      else if (n instanceof HTMLElement) scan(n);
    });
  }).observe(root, { childList: true, subtree: true });
  root.addEventListener("input", (e) => { const t = e.target; if (t instanceof HTMLInputElement && t.type === "range") fillRange(t); });
}
