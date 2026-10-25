"""OMEGA wave 3 by voice: duplicates, similar photos, bulk rename with undo, document sorting and naming, archives,
conversion, metadata, file versions, folder fingerprints, lost files and a verified backup. Every bulk change shows a
preview first and can be undone; duplicates only ever go to the Recycle Bin."""
from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path
from typing import Annotated

from .base import ToolResult, tool
from .files import resolve, user_roots


def _size(n: float) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "?"


def _folders(ctx, folder: str) -> list[Path]:
    if folder:
        p = resolve(folder)
        if not p.is_dir():
            raise ValueError(f"Složka neexistuje: {p}")
        return [p]
    return user_roots(ctx)


def _files(folder: str, ext: str = "") -> list[Path]:
    p = resolve(folder)
    if p.is_file():
        return [p]
    if not p.is_dir():
        raise ValueError(f"Složka neexistuje: {p}")
    exts = {("." + e.strip().lower().lstrip(".")) for e in ext.split(",") if e.strip()}
    return sorted(q for q in p.iterdir() if q.is_file() and not q.name.startswith(".") and (not exts or q.suffix.lower() in exts))


# ---------------------------------------------------------------------------------------------- duplicates, photos
@tool("find_duplicates", "Najde duplicitní soubory (stejný obsah, i když mají jiný název) a kolik místa zabírají navíc. "
      "Nic nemaže. Na „najdi duplicity“, „mám fotky dvakrát?“.", category="soubory", perm="files_read")
async def find_duplicates(ctx, folder: Annotated[str, "složka (prázdné = Plocha, Dokumenty, Stažené, Obrázky…)"] = "",
                          min_kb: int = 1) -> ToolResult:
    from .. import fileuniverse as fu

    groups = await asyncio.to_thread(fu.duplicates, _folders(ctx, folder), max(0, min_kb) * 1024)
    if not groups:
        return ToolResult(True, "Žádné duplicity jsem nenašel.", data=[])
    ex = "; ".join(f"{Path(g['keep']).name} ×{len(g['extra']) + 1}" for g in groups[:4])
    return ToolResult(True, f"{len(groups)} skupin duplicit, navíc zabírají {_size(fu.wasted(groups))} (např. {ex}). "
                      "Můžu je přesunout do koše – ponechám vždy nejstarší kopii.", data=groups[:200])


def _dup_details(a: dict, ctx=None) -> list[str]:
    from .. import fileuniverse as fu

    try:
        groups = fu.duplicates(_folders(ctx, a.get("folder", "")), 1024)
    except ValueError as e:
        return [str(e)]
    lines = [f"Do koše: {sum(len(g['extra']) for g in groups)} souborů ({_size(fu.wasted(groups))}), z každé skupiny zůstane nejstarší."]
    for g in groups[:12]:
        lines.append(f"ponechám {g['keep']}, smažu {', '.join(Path(x).name for x in g['extra'][:3])}")
    return lines


@tool("remove_duplicates", "Přesune duplicitní soubory do koše; z každé skupiny ponechá nejstarší kopii a před smazáním "
      "ověří, že ponechaná kopie existuje a sedí otisk. Vždy se nejdřív zeptá.", danger=True, category="soubory",
      perm="files_write", details=_dup_details)
async def remove_duplicates(ctx, folder: str = "") -> ToolResult:
    from .. import fileuniverse as fu

    groups = await asyncio.to_thread(fu.duplicates, _folders(ctx, folder), 1024)
    keep = {x: (g["keep"], g["sha256"]) for g in groups for x in g["extra"]}
    done, failed = await asyncio.to_thread(fu.trash, list(keep), keep)
    ctx.tasks.add_evidence("send2trash", "duplicity v koši", f"{len(done)} souborů", not failed)
    msg = f"Do koše jsem přesunul {len(done)} duplicit ({_size(sum(g['size'] * len([x for x in g['extra'] if x in done]) for g in groups))})."
    if failed:
        msg += f" {len(failed)} se nepovedlo: {failed[0]}"
    return ToolResult(not failed, msg + " Když něco chybí, obnovíš to z koše.", data={"trashed": done, "failed": failed})


@tool("find_similar_photos", "Najde podobné fotky (série, stejná fotka zmenšená nebo upravená) – pro výběr té nejlepší. "
      "Nic nemaže.", category="soubory", perm="files_read")
async def find_similar_photos(ctx, folder: Annotated[str, "složka s fotkami"] = "Obrázky", strictness: int = 6) -> ToolResult:
    from .. import fileuniverse as fu

    groups = await asyncio.to_thread(fu.similar_images, _folders(ctx, folder), max(0, min(20, strictness)))
    if not groups:
        return ToolResult(True, "Žádné podobné fotky jsem nenašel.", data=[])
    ex = "; ".join(", ".join(Path(x).name for x in g[:3]) for g in groups[:3])
    return ToolResult(True, f"{len(groups)} skupin podobných fotek ({sum(len(g) for g in groups)} fotek), např. {ex}.", data=groups[:100])


# ---------------------------------------------------------------------------------------------- rename, sort, names
def _rename_details(a: dict) -> list[str]:
    from .. import fileuniverse as fu

    try:
        plan = fu.plan_rename(_files(a.get("folder", ""), a.get("only_ext", "")), a.get("pattern") or "{date}_{n}",
                              a.get("find", ""), a.get("replace", ""), int(a.get("start") or 1))
    except (ValueError, KeyError, IndexError) as e:
        return [f"Nelze: {e}"]
    return [f"{len(plan)} souborů, jde to vrátit (undo_rename)"] + [f"{Path(m['src']).name} → {Path(m['dst']).name}" for m in plan[:20]]


@tool("rename_files", "Hromadně přejmenuje soubory ve složce podle vzoru: {date} datum pořízení fotky / změny, {time}, {n} "
      "pořadové číslo, {name} původní název, {folder}. Volitelně najdi→nahraď. Uživatel uvidí náhled; jde vrátit "
      "(undo_rename). Např. pattern „Dovolená_{date}_{n}“.", danger=True, category="soubory", perm="files_write",
      details=_rename_details)
async def rename_files(ctx, folder: Annotated[str, "složka"], pattern: Annotated[str, "vzor názvu bez přípony"] = "{date}_{n}",
                       find: str = "", replace: str = "", only_ext: Annotated[str, "jen přípony, např. jpg,png"] = "",
                       start: int = 1) -> ToolResult:
    from .. import fileuniverse as fu

    try:
        plan = await asyncio.to_thread(fu.plan_rename, _files(folder, only_ext), pattern, find, replace, start)
    except (KeyError, IndexError) as e:
        return ToolResult(False, f"Neplatný vzor ({e}). Použij {{date}}, {{time}}, {{n}}, {{name}}, {{folder}}.")
    if not plan:
        return ToolResult(True, "Není co přejmenovat – názvy už odpovídají.")
    r = await asyncio.to_thread(fu.apply_rename, plan)
    ok = all(Path(m["dst"]).exists() for m in plan)
    ctx.tasks.add_evidence("rename", "všechny nové názvy existují", f"{r['renamed']} souborů", ok)
    return ToolResult(ok, f"Přejmenováno {r['renamed']} souborů (např. {Path(plan[0]['dst']).name}). Vrátit: „vrať přejmenování“.",
                      data={**r, "plan": plan[:50]})


@tool("undo_rename", "Vrátí poslední hromadné přejmenování nebo roztřídění souborů zpět.", danger=True, category="soubory",
      perm="files_write", details=lambda a: ["Vrátí poslední hromadnou změnu názvů / třídění."])
async def undo_rename(ctx) -> ToolResult:
    from .. import fileuniverse as fu

    log = fu.last_undo()
    if not log:
        return ToolResult(False, "Nemám žádné přejmenování, které by šlo vrátit.")
    r = await asyncio.to_thread(fu.undo_rename, log)
    return ToolResult(True, f"Vráceno {r['restored']} souborů" + (f", {r['skipped']} už mezitím někdo změnil" if r["skipped"] else "") + ".", data=r)


def _sort_details(a: dict) -> list[str]:
    from .. import fileuniverse as fu

    try:
        plan = fu.sort_plan(resolve(a.get("folder", "")))
    except OSError as e:
        return [f"Nelze: {e}"]
    cats: dict[str, int] = {}
    for m in plan:
        cats[m["category"]] = cats.get(m["category"], 0) + 1
    return [", ".join(f"{k}: {v}" for k, v in sorted(cats.items(), key=lambda kv: -kv[1]))] + \
        [f"{Path(m['src']).name} → {m['category']}/ ({m['why']})" for m in plan[:20]]


@tool("sort_documents", "Roztřídí soubory ve složce do podsložek podle obsahu a typu (Faktury, Smlouvy, Banka a výpisy, "
      "Úřady a daně, Zdraví, Práce, Pojištění, Účtenky, Škola, Fotky, Videa, Instalačky, Archivy…). Náhled, schválení, "
      "jde vrátit (undo_rename). Na „ukliď mi Stažené“, „roztřiď dokumenty“.", danger=True, category="soubory",
      perm="files_write", details=_sort_details)
async def sort_documents(ctx, folder: Annotated[str, "složka, např. Stažené"]) -> ToolResult:
    from .. import fileuniverse as fu

    p = resolve(folder)
    if not p.is_dir():
        return ToolResult(False, f"Složka neexistuje: {p}")
    plan = await asyncio.to_thread(fu.sort_plan, p)
    if not plan:
        return ToolResult(True, "Ve složce nejsou žádné soubory k roztřídění.")
    r = await asyncio.to_thread(fu.apply_rename, [{"src": m["src"], "dst": m["dst"]} for m in plan])
    cats: dict[str, int] = {}
    for m in plan:
        cats[m["category"]] = cats.get(m["category"], 0) + 1
    return ToolResult(True, f"Roztříděno {r['renamed']} souborů: " + ", ".join(f"{k} {v}" for k, v in cats.items()) + ". Jde to vrátit.",
                      data={**r, "categories": cats})


def _smart_details(a: dict) -> list[str]:
    from .. import fileuniverse as fu

    try:
        files = [q for q in _files(a.get("path", "")) if q.suffix.lower() in (".pdf", ".docx", ".txt", ".md")]
    except ValueError as e:
        return [str(e)]
    return [f"{q.name} → {fu.smart_name(q)}" for q in files[:20]] or ["Žádné dokumenty (PDF, Word, text)."]


@tool("smart_rename", "Pojmenuje dokumenty podle obsahu: typ_datum_firma (např. Faktura_2026-10-03_Alza.pdf). Náhled, "
      "schválení, jde vrátit. Na „pojmenuj ty faktury rozumně“.", danger=True, category="soubory", perm="files_write",
      details=_smart_details)
async def smart_rename(ctx, path: Annotated[str, "soubor nebo složka"]) -> ToolResult:
    from .. import fileuniverse as fu

    files = [q for q in _files(path) if q.suffix.lower() in (".pdf", ".docx", ".txt", ".md")]
    plan, used = [], set()
    for q in files:
        name = fu.smart_name(q)
        new = q if q.name == name else fu.free_name(q.with_name(name))
        k = 2
        while str(new).lower() in used:
            new, k = fu.free_name(q.with_name(f"{Path(name).stem} ({k}){q.suffix.lower()}")), k + 1
        used.add(str(new).lower())
        if new != q:
            plan.append({"src": str(q), "dst": str(new)})
    if not plan:
        return ToolResult(True, "Názvy už odpovídají obsahu (nebo jsem v dokumentech nic nenašel).")
    r = await asyncio.to_thread(fu.apply_rename, plan)
    return ToolResult(True, f"Přejmenováno {r['renamed']} dokumentů, např. {Path(plan[0]['dst']).name}. Jde to vrátit.", data=plan)


# ---------------------------------------------------------------------------------------------- archives, conversion
@tool("archive_contents", "Ukáže, co je v archivu (ZIP, TAR; 7Z a RAR se 7-Zipem) bez rozbalení: počet souborů, velikost, "
      "šifrování, seznam.", category="soubory", perm="files_read")
async def archive_contents(ctx, path: Annotated[str, "archiv"]) -> ToolResult:
    from .. import fileuniverse as fu

    p = resolve(path)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    r = await asyncio.to_thread(fu.archive_list, p)
    if "error" in r:
        return ToolResult(False, r["error"])
    names = ", ".join(i["name"] for i in r["items"][:8])
    return ToolResult(True, f"{r['type']}: {r['files']} souborů, rozbaleno {_size(r['bytes'])}" + (", ZAHESLOVANÝ" if r["encrypted"] else "")
                      + f". Obsah: {names}{'…' if r['files'] > 8 else ''}", data=r)


@tool("extract_archive", "Rozbalí archiv do NOVÉ složky vedle něj (nic nepřepíše; položky mířící mimo složku odmítne).",
      category="soubory", perm="files_write")
async def extract_archive(ctx, path: Annotated[str, "archiv"], destination: str = "") -> ToolResult:
    from .. import fileuniverse as fu

    p = resolve(path)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    dest = resolve(destination) if destination else fu.free_name(p.with_name(p.name.split(".")[0]))
    try:
        r = await asyncio.to_thread(fu.safe_extract, p, dest)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    msg = f"Rozbaleno {r['files']} souborů do {r['folder']}."
    if r["skipped"]:
        msg += f" {len(r['skipped'])} položek jsem odmítl (mířily mimo složku – typický trik škodlivých archivů)."
    return ToolResult(True, msg, data=r)


@tool("create_zip", "Zabalí soubory nebo složky do ZIPu a ověří, že archiv jde přečíst.", category="soubory", perm="files_write")
async def create_zip(ctx, paths: Annotated[list[str], "soubory/složky"], destination: Annotated[str, "cesta k .zip"] = "") -> ToolResult:
    from .. import fileuniverse as fu

    srcs = [resolve(x) for x in paths]
    missing = [str(s) for s in srcs if not s.exists()]
    if missing or not srcs:
        return ToolResult(False, f"Neexistuje: {', '.join(missing) or 'nic nezadáno'}")
    dest = resolve(destination) if destination else fu.free_name(srcs[0].with_suffix(".zip") if srcs[0].is_file() else srcs[0].parent / f"{srcs[0].name}.zip")
    try:
        r = await asyncio.to_thread(fu.make_zip, srcs, dest)
    except (ValueError, OSError) as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Zabaleno {r['files']} souborů do {r['path']} ({_size(r['bytes'])}), archiv ověřen.", data=r)


@tool("convert_file", "Převede soubor do jiného formátu (vznikne nový soubor, originál zůstane): obrázky mezi sebou "
      "(png, jpg, webp, bmp, gif, tiff) i do PDF a se zmenšením, PDF → txt, Word → txt/md, Excel → CSV, CSV → Excel, "
      "txt/md → Word. Jde i celá složka.", category="soubory", perm="files_write")
async def convert_file(ctx, path: Annotated[str, "soubor nebo složka"], to: Annotated[str, "cílový formát, např. jpg"],
                       max_side: Annotated[int, "u obrázků: delší strana v px (0 = beze změny)"] = 0) -> ToolResult:
    from .. import fileuniverse as fu

    files = _files(path)
    out, failed = [], []
    for f in files:
        if f.suffix.lower().lstrip(".") == to.lower().lstrip(".") and not max_side:
            continue
        try:
            out.append(str(await asyncio.to_thread(fu.convert, f, to, max_side)))
        except Exception as e:  # noqa: BLE001 – reported per file
            failed.append(f"{f.name}: {e}")
    if not out:
        return ToolResult(False, failed[0] if failed else "Nebylo co převést.")
    return ToolResult(not failed, f"Převedeno {len(out)} souborů (např. {Path(out[0]).name})" + (f", {len(failed)} nešlo: {failed[0]}" if failed else "") + ".",
                      data={"created": out, "failed": failed})


# ---------------------------------------------------------------------------------------------- metadata, versions
@tool("file_metadata", "Ukáže skrytá metadata souboru: u fotek fotoaparát, datum a GPS poloha, u Wordu a PDF autor, firma, "
      "program.", category="soubory", perm="files_read")
async def file_metadata(ctx, path: Annotated[str, "soubor"]) -> ToolResult:
    from .. import fileuniverse as fu

    p = resolve(path)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    md = await asyncio.to_thread(fu.read_metadata, p)
    if not md:
        return ToolResult(True, "Žádná metadata jsem nenašel.", data={})
    warn = " Pozor: fotka obsahuje GPS polohu." if "GPS" in md else ""
    return ToolResult(True, ", ".join(f"{k}: {v}" for k, v in list(md.items())[:10]) + "." + warn, data=md)


@tool("clean_metadata", "Odstraní z fotek, Wordu a PDF metadata (GPS polohu, autora, fotoaparát, program) – vytvoří čistou "
      "kopii „_bez_metadat“, nebo s overwrite přepíše originál (předtím uloží jeho verzi). Před sdílením fotek.",
      danger_if=lambda a: bool(a.get("overwrite")), category="soubory", perm="files_write",
      details=lambda a: [f"{resolve(a.get('path', ''))}: " + ("přepíše originál (verze se uloží)" if a.get("overwrite") else "vytvoří čistou kopii")])
async def clean_metadata(ctx, path: Annotated[str, "soubor nebo složka"], overwrite: bool = False) -> ToolResult:
    from .. import fileuniverse as fu

    out, failed = [], []
    for f in _files(path):
        try:
            dst = await asyncio.to_thread(fu.clean_metadata, f, overwrite)
            left = await asyncio.to_thread(fu.read_metadata, dst)
            if "GPS" in left or left.get("author"):
                raise ValueError("po vyčištění tam pořád něco zůstalo")
            out.append(str(dst))
        except Exception as e:  # noqa: BLE001
            failed.append(f"{f.name}: {e}")
    if not out:
        return ToolResult(False, failed[0] if failed else "Nic k vyčištění.")
    return ToolResult(not failed, f"Vyčištěno {len(out)} souborů (ověřeno: bez GPS a autora)" + (f", {len(failed)} nešlo" if failed else "") + ".",
                      data={"files": out, "failed": failed})


@tool("save_file_version", "Uloží verzi souboru (záloha jeho současného stavu), ke které se jde vrátit.", category="soubory",
      perm="files_read")
async def save_file_version(ctx, path: Annotated[str, "soubor"], note: str = "") -> ToolResult:
    from .. import fileuniverse as fu

    p = resolve(path)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    v = await asyncio.to_thread(fu.save_version, p, note)
    return ToolResult(True, "Soubor se od poslední verze nezměnil." if v.get("unchanged") else f"Verze uložena ({_size(v['bytes'])}).", data=v)


@tool("file_versions", "Seznam uložených verzí souboru.", category="soubory", perm="files_read")
async def file_versions(ctx, path: Annotated[str, "soubor"]) -> ToolResult:
    from .. import fileuniverse as fu

    vs = fu.list_versions(resolve(path))
    if not vs:
        return ToolResult(True, "Žádné uložené verze.", data=[])
    lines = [f"{i}: {dt.datetime.fromtimestamp(v['ts']):%d. %m. %H:%M} ({_size(v['bytes'])}){' – ' + v['note'] if v['note'] else ''}" for i, v in enumerate(vs[:10])]
    return ToolResult(True, "Verze (0 = nejnovější): " + "; ".join(lines), data=vs)


@tool("restore_file_version", "Vrátí soubor na uloženou verzi (0 = nejnovější). Současný stav se předtím uloží jako verze.",
      danger=True, category="soubory", perm="files_write",
      details=lambda a: [f"{resolve(a.get('path', ''))} → verze {a.get('index', 0)} (současný stav se uloží)"])
async def restore_file_version(ctx, path: Annotated[str, "soubor"], index: int = 0) -> ToolResult:
    from .. import fileuniverse as fu

    p = resolve(path)
    try:
        v = await asyncio.to_thread(fu.restore_version, p, index)
    except ValueError as e:
        return ToolResult(False, str(e))
    ok = fu.sha256(p) == v["sha256"]
    return ToolResult(ok, f"Obnoveno na verzi z {dt.datetime.fromtimestamp(v['ts']):%d. %m. %Y %H:%M}" + (" (ověřeno)." if ok else ", ale otisk nesedí!"))


# ---------------------------------------------------------------------------------------------- integrity, lost files
@tool("folder_fingerprint", "Uloží otisky (SHA-256) všech souborů ve složce – později jde zjistit, co se změnilo, chybí "
      "nebo přibylo (folder_check). Pro zálohy, fotky, důležité dokumenty.", category="soubory", perm="files_read")
async def folder_fingerprint(ctx, folder: Annotated[str, "složka"]) -> ToolResult:
    from .. import fileuniverse as fu

    p = resolve(folder)
    if not p.is_dir():
        return ToolResult(False, f"Složka neexistuje: {p}")
    r = await asyncio.to_thread(fu.integrity_save, p)
    return ToolResult(True, f"Otisky uloženy: {r['files']} souborů ({_size(r['bytes'])}).", data=r)


@tool("folder_check", "Porovná složku s uloženými otisky: co se změnilo, co chybí, co přibylo.", category="soubory", perm="files_read")
async def folder_check(ctx, folder: Annotated[str, "složka"]) -> ToolResult:
    from .. import fileuniverse as fu

    try:
        r = await asyncio.to_thread(fu.integrity_check, resolve(folder))
    except ValueError as e:
        return ToolResult(False, str(e))
    when = dt.datetime.fromtimestamp(r["since"]).strftime("%d. %m. %Y")
    if not (r["changed"] or r["missing"] or r["added"]):
        return ToolResult(True, f"Od {when} beze změny: všech {r['same']} souborů sedí.", data=r)
    parts = [f"změněno {len(r['changed'])}" if r["changed"] else "", f"chybí {len(r['missing'])}" if r["missing"] else "",
             f"přibylo {len(r['added'])}" if r["added"] else ""]
    ex = (r["missing"] + r["changed"])[:3]
    return ToolResult(not r["missing"], f"Od {when}: " + ", ".join(x for x in parts if x) + (f" (např. {', '.join(ex)})" if ex else "") + ".", data=r)


@tool("recent_files", "Soubory, se kterými se nedávno pracovalo (posledních N hodin) – na „kam jsem to uložil“, "
      "„ztratil se mi soubor“. kind: dokumenty, fotky, videa, tabulky nebo nic.", category="soubory", perm="files_read")
async def recent_files(ctx, hours: float = 48, kind: str = "") -> ToolResult:
    from .. import fileuniverse as fu

    kinds = {"dokumenty": {".pdf", ".docx", ".doc", ".txt", ".odt", ".md", ".rtf"}, "fotky": fu.IMAGE_EXT,
             "videa": {".mp4", ".mov", ".mkv", ".avi"}, "tabulky": {".xlsx", ".xls", ".csv", ".ods"}}.get(kind.lower().strip())
    items = await asyncio.to_thread(fu.recent_files, user_roots(ctx), hours, kinds)
    if not items:
        return ToolResult(True, f"Za posledních {hours:g} h jsem nic nenašel.", data=[])
    return ToolResult(True, "; ".join(f"{Path(i['path']).name} ({dt.datetime.fromtimestamp(i['mtime']):%d. %m. %H:%M}, {Path(i['path']).parent})" for i in items[:8]),
                      data=items)


@tool("find_in_files", "Najde soubory podle toho, co v nich je (text v PDF, Wordu, txt…), když si nepamatuješ název.",
      category="soubory", perm="files_read")
async def find_in_files(ctx, query: Annotated[str, "slova, která v souboru jsou"], folder: str = "") -> ToolResult:
    from .. import fileuniverse as fu

    hits = await asyncio.to_thread(fu.search_content, _folders(ctx, folder), query)
    if not hits:
        return ToolResult(True, "Nenašel jsem žádný soubor s tímhle textem.", data=[])
    return ToolResult(True, "; ".join(f"{Path(h['path']).name} („…{h['snippet'][:80]}…“)" for h in hits[:6]), data=hits)


# ---------------------------------------------------------------------------------------------- backup
@tool("backup_plan", "Co zálohovat a v jakém pořadí: tvoje dokumenty a fotky první, stažené instalačky poslední; s velikostmi.",
      category="soubory", perm="files_read")
async def backup_plan(ctx) -> ToolResult:
    from .. import fileuniverse as fu

    plan = await asyncio.to_thread(fu.backup_plan)
    if not plan:
        return ToolResult(False, "Nenašel jsem uživatelské složky.")
    total = sum(p["bytes"] for p in plan if p["value"] >= 5)
    return ToolResult(True, "Pořadí: " + "; ".join(f"{Path(p['folder']).name} {_size(p['bytes'])}{' (' + p['note'] + ')' if p['note'] else ''}" for p in plan)
                      + f". Nejdůležitější dohromady {_size(total)} – tolik místa potřebuje záloha.", data=plan)


@tool("backup_folder", "Zálohuje složku na jiný disk / do jiné složky: kopíruje jen nové a změněné soubory a zkopírované "
      "ověří otiskem SHA-256.", danger=True, category="soubory", perm="files_write",
      details=lambda a: [f"{resolve(a.get('source', ''))} → {resolve(a.get('destination', ''))}", "jen nové a změněné soubory; nic se nemaže"])
async def backup_folder(ctx, source: Annotated[str, "co zálohovat"], destination: Annotated[str, "kam (např. E:\\Záloha)"]) -> ToolResult:
    from .. import fileuniverse as fu

    src, dst = resolve(source), resolve(destination)
    if not src.is_dir():
        return ToolResult(False, f"Složka neexistuje: {src}")
    if dst.resolve().is_relative_to(src.resolve()):
        return ToolResult(False, "Záloha nemůže být uvnitř zálohované složky.")
    if not dst.exists():
        try:
            dst.mkdir(parents=True)
        except OSError as e:
            return ToolResult(False, f"Cíl nejde vytvořit: {e}")
    r = await asyncio.to_thread(fu.backup, src, dst)
    ok = not r["failed"] and not r["verify_failed"]
    ctx.tasks.add_evidence("SHA-256", "zkopírované soubory odpovídají originálu", f"{r['copied']} souborů", not r["verify_failed"])
    msg = f"Záloha do {r['folder']}: zkopírováno {r['copied']} nových/změněných ({_size(r['bytes'])}), {r['unchanged']} beze změny"
    if r["failed"]:
        msg += f", {len(r['failed'])} nešlo zkopírovat ({r['failed'][0]})"
    if r["verify_failed"]:
        msg += f", {len(r['verify_failed'])} NESEDÍ otisk"
    return ToolResult(ok, msg + (". Vše ověřeno." if ok else "."), data=r)
