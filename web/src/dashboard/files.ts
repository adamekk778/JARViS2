// Dashboard → Soubory (OMEGA §27 Intelligent File Universe): duplicates, similar photos, sorting a folder, bulk and
// content-based renaming (with undo), archives, conversion, metadata, folder fingerprints, lost files and a verified
// backup. Buttons run the same tools as the voice; anything that changes files shows its preview and waits for approval.
import { hero, HEROES } from "../shared/hero";
import { fmtSize, h, icon, toast } from "../shared/dom";
import { TaskCard } from "../shared/taskcard";
import type { JarvisClient } from "../shared/ws";

export function buildFiles(client: JarvisClient) {
  const card = new TaskCard(client, { compact: true, hideWhenIdle: true });
  const out = h("div", { class: "rs-out fl-out", "aria-live": "polite" }, h("p", { class: "muted" }, "Vyber, co chceš udělat. Co mění soubory, ukáže nejdřív náhled a počká na schválení."));
  const field = (ph: string, label: string, value = "") => h("input", { class: "input", placeholder: ph, "aria-label": label, value }) as HTMLInputElement;
  const run = (tool: string, args: any = {}) => {
    out.replaceChildren(h("p", { class: "muted" }, "Pracuju…"));
    client.send("files_run", { tool, args });
  };
  const need = (inp: HTMLInputElement, fn: () => void) => () => { if (!inp.value.trim()) { inp.focus(); toast("Vyplň cestu", "error"); return; } fn(); };

  const renderData = (tool: string, d: any): (HTMLElement | string)[] => {
    if (!d) return [];
    if (tool === "find_duplicates" && Array.isArray(d) && d.length) return [h("ul", { class: "rs-list" }, ...d.slice(0, 30).map((g: any) => h("li", { class: "fl-group" },
      h("strong", {}, `${fmtSize(g.size)} × ${g.extra.length + 1}`), h("span", {}, `ponechám ${g.keep}`), h("span", { class: "muted" }, `navíc: ${g.extra.join(", ")}`))))];
    if (tool === "find_similar_photos" && Array.isArray(d) && d.length) return [h("ul", { class: "rs-list" }, ...d.slice(0, 30).map((g: string[]) => h("li", { class: "fl-group" },
      h("strong", {}, `${g.length} podobných`), h("span", { class: "muted" }, g.join(", "))))) ];
    if ((tool === "recent_files" || tool === "find_in_files") && Array.isArray(d)) return [h("ul", { class: "rs-list" }, ...d.slice(0, 30).map((f: any) => h("li", { class: "fl-group" },
      h("span", {}, f.path), f.snippet ? h("span", { class: "muted" }, `…${f.snippet}…`) : f.mtime ? h("span", { class: "muted" }, new Date(f.mtime * 1000).toLocaleString("cs-CZ")) : "")))];
    if (tool === "archive_contents" && d.items) return [h("ul", { class: "rs-list" }, ...d.items.slice(0, 40).map((i: any) => h("li", {}, h("span", {}, i.name), h("span", { class: "muted" }, fmtSize(i.bytes)))))];
    if (tool === "folder_check") return [h("ul", { class: "rs-list" },
      ...d.missing.slice(0, 20).map((x: string) => h("li", { class: "rs-f bad" }, `chybí: ${x}`)),
      ...d.changed.slice(0, 20).map((x: string) => h("li", { class: "rs-f warn" }, `změněno: ${x}`)),
      ...d.added.slice(0, 20).map((x: string) => h("li", {}, `nové: ${x}`)))];
    if (tool === "backup_plan" && Array.isArray(d)) return [h("ol", { class: "rs-trace" }, ...d.map((p: any) => h("li", {}, `${p.folder} – ${fmtSize(p.bytes)}, ${p.files} souborů${p.note ? ` (${p.note})` : ""}`)))];
    if (tool === "file_metadata" && typeof d === "object") return [h("table", { class: "task-actions" }, h("tbody", {}, ...Object.entries(d).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, String(v))))))];
    return [];
  };
  client.on("files_result", (m) => {
    out.replaceChildren(h("p", { class: m.ok ? "" : "rs-f bad" }, m.summary), ...renderData(m.tool, m.data));
  });

  // ---- tidy up
  const dupDir = field("složka (prázdné = Plocha, Dokumenty, Stažené, Obrázky…)", "Složka pro duplicity");
  const photoDir = field("složka s fotkami", "Složka s fotkami", "Obrázky");
  const sortDir = field("složka k roztřídění", "Složka k roztřídění", "Stažené");
  const tidy = h("div", { class: "card sec-card" },
    h("div", { class: "list-add" }, dupDir,
      h("button", { class: "btn", type: "button", onclick: () => run("find_duplicates", { folder: dupDir.value.trim() }) }, icon("copy"), "Najít duplicity"),
      h("button", { class: "btn", type: "button", onclick: () => run("remove_duplicates", { folder: dupDir.value.trim() }) }, icon("trash"), "Do koše")),
    h("div", { class: "list-add" }, photoDir, h("button", { class: "btn", type: "button", onclick: () => run("find_similar_photos", { folder: photoDir.value.trim() }) }, icon("images"), "Podobné fotky")),
    h("div", { class: "list-add" }, sortDir, h("button", { class: "btn", type: "button", onclick: need(sortDir, () => run("sort_documents", { folder: sortDir.value.trim() })) }, icon("folders"), "Roztřídit")),
    h("p", { class: "help" }, "Duplicity jdou jen do koše a z každé skupiny zůstane nejstarší kopie. Třídění podle obsahu (faktury, smlouvy, výpisy…) jde vrátit."));

  // ---- names
  const renDir = field("složka", "Složka k přejmenování");
  const pattern = field("vzor, např. Dovolená_{date}_{n}", "Vzor názvu", "{date}_{n}");
  const onlyExt = h("input", { class: "input sm", placeholder: "jpg,png", "aria-label": "Jen přípony" }) as HTMLInputElement;
  const names = h("div", { class: "card sec-card" },
    h("div", { class: "list-add" }, renDir, pattern, onlyExt,
      h("button", { class: "btn", type: "button", onclick: need(renDir, () => run("rename_files", { folder: renDir.value.trim(), pattern: pattern.value.trim() || "{date}_{n}", only_ext: onlyExt.value.trim() })) }, icon("textbox"), "Přejmenovat")),
    h("div", { class: "btn-row" },
      h("button", { class: "btn", type: "button", onclick: need(renDir, () => run("smart_rename", { path: renDir.value.trim() })) }, icon("magic-wand"), "Pojmenovat podle obsahu"),
      h("button", { class: "btn ghost", type: "button", onclick: () => run("undo_rename") }, icon("arrow-counter-clockwise"), "Vrátit poslední přejmenování / třídění")),
    h("p", { class: "help" }, "{date} datum pořízení fotky (nebo změny), {time}, {n} pořadí, {name} původní název, {folder} složka. Před provedením uvidíš celý náhled."));

  // ---- archives & conversion
  const arch = field("cesta k archivu (.zip, .tar, .7z, .rar)", "Archiv");
  const conv = field("soubor nebo složka", "Soubor k převodu");
  const to = h("select", { class: "input sm", "aria-label": "Cílový formát" }, ...["jpg", "png", "webp", "pdf", "txt", "md", "docx", "csv", "xlsx"].map((f) => h("option", { value: f }, f))) as HTMLSelectElement;
  const side = h("input", { class: "input sm", type: "number", min: 0, step: 100, placeholder: "max px", "aria-label": "Zmenšit na" }) as HTMLInputElement;
  const meta = field("fotka, Word nebo PDF", "Soubor s metadaty");
  const convert = h("div", { class: "card sec-card" },
    h("div", { class: "list-add" }, arch,
      h("button", { class: "btn", type: "button", onclick: need(arch, () => run("archive_contents", { path: arch.value.trim() })) }, icon("file-zip"), "Obsah"),
      h("button", { class: "btn", type: "button", onclick: need(arch, () => run("extract_archive", { path: arch.value.trim() })) }, icon("arrow-square-out"), "Rozbalit")),
    h("div", { class: "list-add" }, conv, to, side,
      h("button", { class: "btn", type: "button", onclick: need(conv, () => run("convert_file", { path: conv.value.trim(), to: to.value, max_side: +side.value || 0 })) }, icon("arrows-left-right"), "Převést")),
    h("div", { class: "list-add" }, meta,
      h("button", { class: "btn", type: "button", onclick: need(meta, () => run("file_metadata", { path: meta.value.trim() })) }, icon("info"), "Co prozrazuje"),
      h("button", { class: "btn", type: "button", onclick: need(meta, () => run("clean_metadata", { path: meta.value.trim() })) }, icon("eraser"), "Čistá kopie")),
    h("p", { class: "help" }, "Převod i čištění vytvoří nový soubor, originál zůstane. Archivy se rozbalují jen do nové složky."));

  // ---- find & protect
  const findQ = field("co v souboru je, např. nájemní smlouva Brno", "Hledaný text");
  const fpDir = field("složka (fotky, dokumenty…)", "Složka pro otisky");
  const bSrc = field("co zálohovat, např. Dokumenty", "Zdroj zálohy"), bDst = field("kam, např. E:\\Záloha", "Cíl zálohy");
  const protect = h("div", { class: "card sec-card" },
    h("div", { class: "btn-row" },
      h("button", { class: "btn", type: "button", onclick: () => run("recent_files", { hours: 48 }) }, icon("clock"), "Na čem jsem pracoval (48 h)")),
    h("div", { class: "list-add" }, findQ, h("button", { class: "btn", type: "button", onclick: need(findQ, () => run("find_in_files", { query: findQ.value.trim() })) }, icon("magnifying-glass"), "Hledat v obsahu")),
    h("div", { class: "list-add" }, fpDir,
      h("button", { class: "btn", type: "button", onclick: need(fpDir, () => run("folder_fingerprint", { folder: fpDir.value.trim() })) }, icon("fingerprint"), "Uložit otisky"),
      h("button", { class: "btn", type: "button", onclick: need(fpDir, () => run("folder_check", { folder: fpDir.value.trim() })) }, icon("check-circle"), "Co se změnilo?")),
    h("div", { class: "btn-row" }, h("button", { class: "btn", type: "button", onclick: () => run("backup_plan") }, icon("list-numbers"), "Co zálohovat?")),
    h("div", { class: "list-add" }, bSrc, bDst,
      h("button", { class: "btn primary", type: "button", onclick: need(bDst, () => run("backup_folder", { source: bSrc.value.trim(), destination: bDst.value.trim() })) }, icon("floppy-disk"), "Zálohovat a ověřit")),
    h("p", { class: "help" }, "Záloha kopíruje jen nové a změněné soubory a každý zkopírovaný ověří otiskem SHA-256. Nic nemaže."));

  const el = h("section", { class: "tasks-view files-view" },
    hero(HEROES.files, "Soubory", "Duplicity, podobné fotky, úklid složek, přejmenování, převody, archivy, metadata a záloha s ověřením. Nic se nesmaže natrvalo a hromadné změny jdou vrátit.", []),
    card.el,
    h("h2", { class: "group-label" }, "Výsledek"), h("div", { class: "card sec-card" }, out),
    h("h2", { class: "group-label" }, "Úklid"), tidy,
    h("h2", { class: "group-label" }, "Názvy"), names,
    h("h2", { class: "group-label" }, "Archivy, převody, metadata"), convert,
    h("h2", { class: "group-label" }, "Najít a ochránit"), protect);
  return { el };
}
