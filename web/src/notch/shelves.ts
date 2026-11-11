/* 3.12 two sections of the notch: Schránka (what you copied with Ctrl+C – click = copy again, pin, your folders) and
   Snímky (your screenshots and screen clips – click = open, pin, folders, show in the folder, hide). The lists come
   from JARVIS (clipshelf.py) and update by themselves when you copy something or take a screenshot. */
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import "./shelves.css";

type Filter = { kind: "all" } | { kind: "pinned" } | { kind: "folder"; name: string };

const ago = (ts: number) => {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "teď";
  if (s < 3600) return `před ${Math.round(s / 60)} min`;
  if (s < 86400) return `před ${Math.round(s / 3600)} h`;
  return new Date(ts * 1000).toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" });
};

/** the row of filters: Vše · Připnuté · your folders · + Složka (typed right there, no dialog) */
function filterBar(getFolders: () => string[], current: () => Filter, set: (f: Filter) => void, addFolder: (n: string) => void, delFolder: (n: string) => void) {
  const bar = h("div", { class: "sh-filters" });
  const paint = () => {
    const f = current(), fs = getFolders();
    const chip = (label: Node | string, on: boolean, fn: () => void, extra?: Node) =>
      h("button", { type: "button", class: `sh-chip ${on ? "on" : ""}`, onclick: fn }, label, extra || "");
    const input = h("input", { class: "sh-new", placeholder: "Název složky", maxlength: 40, "aria-label": "Název nové složky" }) as HTMLInputElement;
    const add = h("button", { type: "button", class: "sh-chip add", title: "Nová složka", onclick: () => {
      add.replaceWith(input); input.focus();
    } }, icon("folder-plus"), "Složka");
    input.onkeydown = (e) => {
      if (e.key === "Enter" && input.value.trim()) { addFolder(input.value.trim()); }
      if (e.key === "Escape") paint();
    };
    input.onblur = () => window.setTimeout(paint, 120);
    bar.replaceChildren(
      chip("Vše", f.kind === "all", () => set({ kind: "all" })),
      chip(h("span", {}, icon("push-pin", "ph-fill"), " Připnuté"), f.kind === "pinned", () => set({ kind: "pinned" })),
      ...fs.map((n) => chip(h("span", {}, icon("folder-simple", "ph-fill"), ` ${n}`), f.kind === "folder" && f.name === n, () => set({ kind: "folder", name: n }),
        f.kind === "folder" && f.name === n ? h("i", { class: "ph ph-x sh-chip-x", title: "Smazat složku (obsah zůstane)", onclick: (e: Event) => {
          e.stopPropagation(); delFolder(n); set({ kind: "all" });
        } }) : undefined)),
      add);
  };
  return { el: bar, paint };
}

/** a small menu next to an item: move it into one of your folders (or out) */
function folderMenu(anchor: HTMLElement, folders: string[], currentFolder: string, pick: (f: string) => void) {
  document.querySelectorAll(".sh-menu").forEach((m) => m.remove());
  const input = h("input", { class: "sh-new", placeholder: "Nová složka…", maxlength: 40 }) as HTMLInputElement;
  const menu = h("div", { class: "sh-menu", role: "menu" },
    ...folders.map((f) => h("button", { type: "button", role: "menuitem", class: f === currentFolder ? "on" : "", onclick: () => { pick(f); menu.remove(); } },
      icon("folder-simple", "ph-fill"), f)),
    currentFolder ? h("button", { type: "button", role: "menuitem", onclick: () => { pick(""); menu.remove(); } }, icon("folder-minus"), "Vyndat ze složky") : "",
    input);
  input.onkeydown = (e) => { if (e.key === "Enter" && input.value.trim()) { pick(input.value.trim()); menu.remove(); } if (e.key === "Escape") menu.remove(); };
  const card = anchor.closest(".sh-item") as HTMLElement;
  card.append(menu);
  const off = (e: MouseEvent) => { if (!menu.contains(e.target as Node) && e.target !== anchor) { menu.remove(); document.removeEventListener("pointerdown", off, true); } };
  document.addEventListener("pointerdown", off, true);
  window.setTimeout(() => (folders.length ? (menu.querySelector("button") as HTMLElement)?.focus() : input.focus()), 20);
}

export function createClipsView(client: JarvisClient) {
  let st: { items: any[]; folders: string[]; enabled: boolean } = { items: [], folders: [], enabled: true };
  let filter: Filter = { kind: "all" };
  let query = "";
  const act = (action: string, extra: any = {}) => client.send("clip_action", { action, ...extra });
  const search = h("input", { class: "sh-search", type: "search", placeholder: "Hledat ve schránce…", "aria-label": "Hledat ve schránce" }) as HTMLInputElement;
  search.oninput = () => { query = search.value.trim().toLowerCase(); paint(); };
  const fb = filterBar(() => st.folders, () => filter, (f) => { filter = f; paint(); fb.paint(); },
    (n) => act("folder_add", { name: n }), (n) => act("folder_delete", { name: n }));
  const list = h("div", { class: "sh-list clips" });
  const clear = h("button", { type: "button", class: "sh-tool", title: "Vymazat nepřipnuté (připnuté a ve složkách zůstanou)",
    onclick: () => act("clear") }, icon("broom"), "Vyčistit");
  const el = h("div", { class: "sh" },
    h("div", { class: "sh-top" }, h("div", { class: "sh-title" }, icon("clipboard-text", "ph-fill"), h("strong", {}, "Schránka"),
      h("span", {}, "Ctrl+C a je to tady · klik = zkopírovat")), search, clear),
    fb.el, list);

  function paint() {
    let items = st.items;
    if (filter.kind === "pinned") items = items.filter((i) => i.pinned);
    if (filter.kind === "folder") items = items.filter((i) => i.folder === (filter as any).name);
    if (query) items = items.filter((i) => i.text.toLowerCase().includes(query));
    if (!st.enabled) { list.replaceChildren(h("div", { class: "sh-empty" }, icon("clipboard"), h("strong", {}, "Historie schránky je vypnutá"),
      h("span", {}, "Zapneš ji v Nastavení → Schopnosti → Historie schránky."))); return; }
    if (!items.length) { list.replaceChildren(h("div", { class: "sh-empty" }, icon("copy"), h("strong", {}, query ? "Nic nenalezeno" : filter.kind === "all" ? "Zatím nic" : "Tady zatím nic není"),
      h("span", {}, filter.kind === "all" ? "Zkopíruj cokoli (Ctrl+C) – hned se to tu objeví. Hesla se neukládají." : "Připni si položku špendlíkem nebo ji dej do složky."))); return; }
    list.replaceChildren(...items.map((it) => {
      const isUrl = /^https?:\/\/\S+$/.test(it.text);
      const pinBtn = h("button", { type: "button", class: `sh-b ${it.pinned ? "on" : ""}`, title: it.pinned ? "Odepnout" : "Připnout", "aria-label": it.pinned ? "Odepnout" : "Připnout",
        onclick: (e: Event) => { e.stopPropagation(); act(it.pinned ? "unpin" : "pin", { id: it.id }); } }, icon("push-pin", it.pinned ? "ph-fill" : ""));
      const folderBtn = h("button", { type: "button", class: "sh-b", title: "Do složky", "aria-label": "Do složky",
        onclick: (e: Event) => { e.stopPropagation(); folderMenu(folderBtn, st.folders, it.folder, (f) => act("move", { id: it.id, folder: f })); } }, icon("folder-simple-plus"));
      const del = h("button", { type: "button", class: "sh-b", title: "Smazat", "aria-label": "Smazat",
        onclick: (e: Event) => { e.stopPropagation(); act("delete", { id: it.id }); } }, icon("trash"));
      return h("div", { class: `sh-item clip ${it.pinned ? "pinned" : ""}`, role: "button", tabindex: "0", title: "Klikni a zkopíruje se",
        onclick: () => { act("copy", { id: it.id }); toast("Zkopírováno do schránky", "ok", 1400); },
        onkeydown: (e: KeyboardEvent) => { if (e.key === "Enter") (e.currentTarget as HTMLElement).click(); } },
        h("div", { class: `sh-text ${isUrl ? "url" : ""}` }, it.text.length > 400 ? `${it.text.slice(0, 400)}…` : it.text),
        h("div", { class: "sh-meta" },
          it.folder ? h("span", { class: "sh-tag" }, icon("folder-simple", "ph-fill"), it.folder) : "",
          h("span", {}, [it.app, ago(it.ts)].filter(Boolean).join(" · ")),
          h("span", { class: "sh-acts" }, pinBtn, folderBtn, del)));
    }));
  }
  client.on("clips", (m) => { st = { items: m.items || [], folders: m.folders || [], enabled: m.enabled !== false };
    if (filter.kind === "folder" && !st.folders.includes(filter.name)) filter = { kind: "all" }; fb.paint(); paint(); });
  fb.paint();
  return { el, refresh: () => client.send("clips_get") };
}

export function createShotsView(client: JarvisClient) {
  let st: { items: any[]; folders: string[] } = { items: [], folders: [] };
  let filter: Filter = { kind: "all" };
  const act = (action: string, extra: any = {}) => client.send("shot_action", { action, ...extra });
  const fb = filterBar(() => st.folders, () => filter, (f) => { filter = f; paint(); fb.paint(); },
    (n) => act("folder_add", { name: n }), (n) => act("folder_delete", { name: n }));
  const grid = h("div", { class: "sh-list shots" });
  const el = h("div", { class: "sh" },
    h("div", { class: "sh-top" }, h("div", { class: "sh-title" }, icon("image", "ph-fill"), h("strong", {}, "Snímky"),
      h("span", {}, "Win+Shift+S nebo PrintScreen · klik = otevřít"))),
    fb.el, grid);

  function paint() {
    let items = st.items;
    if (filter.kind === "pinned") items = items.filter((i) => i.pinned);
    if (filter.kind === "folder") items = items.filter((i) => i.folder === (filter as any).name);
    if (!items.length) { grid.replaceChildren(h("div", { class: "sh-empty" }, icon("selection-plus"), h("strong", {}, filter.kind === "all" ? "Zatím žádné snímky" : "Tady zatím nic není"),
      h("span", {}, filter.kind === "all" ? "Udělej snímek (Win+Shift+S, PrintScreen) – uloží se do Obrázky\\Snímky obrazovky a objeví se tady." : "Připni si snímek nebo ho dej do složky."))); return; }
    grid.replaceChildren(...items.map((it) => {
      const btn = (ic: string, label: string, fn: () => void, on = false, fill = false) => h("button", { type: "button", class: `sh-b ${on ? "on" : ""}`, title: label, "aria-label": label,
        onclick: (e: Event) => { e.stopPropagation(); fn(); } }, icon(ic, fill ? "ph-fill" : ""));
      const folderBtn = btn("folder-simple-plus", "Do složky", () => folderMenu(folderBtn, st.folders, it.folder, (f) => act("move", { path: it.path, folder: f })));
      const media = it.video
        ? h("div", { class: "sh-vid" }, icon("film-strip", "ph-fill"), h("span", {}, it.name))
        : h("img", { src: client.url(it.url), alt: it.name, loading: "lazy", decoding: "async" });
      return h("div", { class: `sh-item shot ${it.pinned ? "pinned" : ""}`, role: "button", tabindex: "0", title: `${it.name} – klikni pro otevření`,
        onclick: () => act("open", { path: it.path }), onkeydown: (e: KeyboardEvent) => { if (e.key === "Enter") act("open", { path: it.path }); } },
        media,
        it.pinned ? h("span", { class: "sh-pin-badge" }, icon("push-pin", "ph-fill")) : "",
        h("div", { class: "sh-shot-bar" },
          h("span", { class: "sh-shot-meta" }, it.folder ? `${it.folder} · ` : "", ago(it.ts)),
          h("span", { class: "sh-acts" },
            btn("push-pin", it.pinned ? "Odepnout" : "Připnout", () => act(it.pinned ? "unpin" : "pin", { path: it.path }), it.pinned, it.pinned),
            folderBtn,
            btn("folder-open", "Ukázat ve složce", () => act("reveal", { path: it.path })),
            btn("eye-slash", "Skrýt ze seznamu (soubor zůstane)", () => act("hide", { path: it.path })))));
    }));
  }
  client.on("shots", (m) => { st = { items: m.items || [], folders: m.folders || [] };
    if (filter.kind === "folder" && !st.folders.includes(filter.name)) filter = { kind: "all" }; fb.paint(); paint(); });
  fb.paint();
  return { el, refresh: () => client.send("shots_get") };
}
