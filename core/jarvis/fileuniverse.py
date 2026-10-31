"""OMEGA §27 Intelligent File Universe: duplicates, similar photos, bulk rename with undo, archives, format conversion,
metadata cleaning, folder fingerprints (integrity), file versions, document sorting and naming, a verified backup.

Rules: nothing is deleted for good (duplicates go to the Recycle Bin), nothing is overwritten without a new name or a
version copy, every bulk change has a preview and an undo log. Third-party file content is data only.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import tarfile
import time
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from . import paths

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "$RECYCLE.BIN", "System Volume Information", "AppData"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic"}


def walk(folders: Iterable[Path], max_files: int = 200_000) -> Iterable[Path]:
    n = 0
    for root in folders:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                n += 1
                if n > max_files:
                    return
                yield Path(dirpath) / f


def sha256(p: Path, limit: int | None = None) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        if limit:
            h.update(f.read(limit))
        else:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------- 317 duplicates
def duplicates(folders: list[Path], min_size: int = 1024) -> list[dict]:
    """Same content = same SHA-256. Size first, then the first 64 kB, then the whole file (fast on big folders).
    In each group the suggestion keeps the oldest copy (usually the original) and marks the rest."""
    by_size: dict[int, list[Path]] = defaultdict(list)
    for p in walk(folders):
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size >= min_size:
            by_size[st.st_size].append(p)
    groups = []
    for size, files in by_size.items():
        if len(files) < 2:
            continue
        by_head: dict[str, list[Path]] = defaultdict(list)
        for p in files:
            try:
                by_head[sha256(p, 65536)].append(p)
            except OSError:
                pass
        for same in by_head.values():
            if len(same) < 2:
                continue
            by_full: dict[str, list[Path]] = defaultdict(list)
            for p in same:
                try:
                    by_full[sha256(p) if size > 65536 else sha256(p, 65536)].append(p)
                except OSError:
                    pass
            for digest, dup in by_full.items():
                if len(dup) < 2:
                    continue
                dup.sort(key=lambda q: (q.stat().st_mtime, len(str(q))))
                groups.append({"sha256": digest, "size": size, "keep": str(dup[0]), "extra": [str(q) for q in dup[1:]]})
    groups.sort(key=lambda g: -g["size"] * len(g["extra"]))
    return groups


def wasted(groups: list[dict]) -> int:
    return sum(g["size"] * len(g["extra"]) for g in groups)


def trash(paths_: list[str], verify_keep: dict[str, tuple[str, str]] | None = None) -> tuple[list[str], list[str]]:
    """Into the Recycle Bin (send2trash). verify_keep: path → (kept copy, its sha256) that must still exist and match."""
    try:
        from send2trash import send2trash
    except ImportError:
        return [], ["Koš není dostupný (send2trash) – nic jsem nemazal."]
    done, failed = [], []
    for p in paths_:
        keep = (verify_keep or {}).get(p)
        try:
            if keep and (not Path(keep[0]).is_file() or sha256(Path(keep[0])) != keep[1]):
                raise OSError("ponechaná kopie chybí nebo se změnila – tuhle nemažu")
            send2trash(p)
            done.append(p)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{p}: {e}")
    return done, failed


# ---------------------------------------------------------------------------------------------- 318 similar photos
def dhash(p: Path, size: int = 8) -> int | None:
    """Difference hash: robust to resizing, recompression and small edits."""
    try:
        from PIL import Image

        with Image.open(p) as im:
            px = im.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS).tobytes()
    except Exception:  # noqa: BLE001 – not an image we can read
        return None
    bits = 0
    for row in range(size):
        for col in range(size):
            bits = (bits << 1) | (px[row * (size + 1) + col] > px[row * (size + 1) + col + 1])
    return bits


def similar_images(folders: list[Path], threshold: int = 6, max_images: int = 5000) -> list[list[str]]:
    hashes = []
    for p in walk(folders):
        if p.suffix.lower() in IMAGE_EXT and len(hashes) < max_images:
            h = dhash(p)
            if h is not None:
                hashes.append((p, h))
    parent = list(range(len(hashes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(hashes)):
        for j in range(i + 1, len(hashes)):
            if bin(hashes[i][1] ^ hashes[j][1]).count("1") <= threshold:
                parent[find(i)] = find(j)
    groups: dict[int, list[str]] = defaultdict(list)
    for i, (p, _h) in enumerate(hashes):
        groups[find(i)].append(str(p))
    return sorted((sorted(g) for g in groups.values() if len(g) > 1), key=len, reverse=True)


# ---------------------------------------------------------------------------------------------- 325 bulk rename
def _taken_date(p: Path) -> dt.datetime:
    if p.suffix.lower() in (".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".png", ".webp"):
        try:
            from PIL import Image

            with Image.open(p) as im:
                exif = im.getexif()
                raw = exif.get(36867) or exif.get_ifd(0x8769).get(36867) or exif.get(306)
            if raw:
                return dt.datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S")
        except Exception:  # noqa: BLE001
            pass
    return dt.datetime.fromtimestamp(p.stat().st_mtime)


def plan_rename(files: list[Path], pattern: str = "{date}_{n}", find: str = "", replace: str = "",
                start: int = 1) -> list[dict]:
    """New names from a pattern: {name} original name, {n} number, {date} date taken (photo) or modified,
    {ext} extension, {folder} folder name. Optional find → replace in the result. Conflicts get a suffix."""
    files = sorted(files, key=lambda p: (_taken_date(p), p.name))
    width = max(2, len(str(len(files) + start - 1)))
    moving = {str(p).lower() for p in files}
    plan, used = [], set()
    for i, p in enumerate(files):
        d = _taken_date(p)
        stem = pattern.format(name=p.stem, n=str(i + start).zfill(width), date=d.strftime("%Y-%m-%d"),
                              time=d.strftime("%H-%M-%S"), ext=p.suffix.lstrip("."), folder=p.parent.name)
        if find:
            stem = stem.replace(find, replace)
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .") or p.stem
        new, k = p.with_name(stem + p.suffix.lower()), 2
        while str(new).lower() in used or (new.exists() and str(new).lower() not in moving):
            new, k = p.with_name(f"{stem} ({k}){p.suffix.lower()}"), k + 1
        used.add(str(new).lower())
        if new != p:
            plan.append({"src": str(p), "dst": str(new)})
    return plan


def undo_dir() -> Path:
    return paths.sub("undo")


def apply_rename(plan: list[dict], log: bool = True) -> dict:
    """Two-phase (temporary names first) so a → b, b → c chains never clash. Writes an undo log."""
    tmp = []
    for i, m in enumerate(plan):
        src = Path(m["src"])
        t = src.with_name(f".jarvis-rename-{os.getpid()}-{i}{src.suffix}")
        src.rename(t)
        tmp.append((t, Path(m["dst"]), src))
    done = []
    for t, dst, src in tmp:
        dst.parent.mkdir(parents=True, exist_ok=True)
        t.rename(dst)
        done.append({"src": str(src), "dst": str(dst)})
    if not log:
        return {"renamed": len(done)}
    f = undo_dir() / f"rename_{dt.datetime.now():%Y%m%d-%H%M%S-%f}.json"
    f.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"renamed": len(done), "undo": str(f)}


def last_undo() -> Path | None:
    logs = sorted(undo_dir().glob("rename_*.json"))
    return logs[-1] if logs else None


def undo_rename(log: Path) -> dict:
    items = json.loads(log.read_text(encoding="utf-8"))
    back = [{"src": m["dst"], "dst": m["src"]} for m in items if Path(m["dst"]).exists() and not Path(m["src"]).exists()]
    r = apply_rename(back, log=False) if back else {"renamed": 0}
    log.rename(log.with_suffix(".done"))
    return {"restored": r["renamed"], "skipped": len(items) - len(back)}


# ---------------------------------------------------------------------------------------------- 323 archives
def archive_list(p: Path, limit: int = 500) -> dict:
    name = p.name.lower()
    try:
        if zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as z:
                infos = z.infolist()
                return {"type": "ZIP", "files": len(infos), "bytes": sum(i.file_size for i in infos),
                        "packed": p.stat().st_size, "encrypted": any(i.flag_bits & 1 for i in infos),
                        "items": [{"name": i.filename, "bytes": i.file_size} for i in infos[:limit]]}
        if tarfile.is_tarfile(p):
            with tarfile.open(p) as t:
                mem = t.getmembers()
                return {"type": "TAR", "files": len(mem), "bytes": sum(m.size for m in mem), "packed": p.stat().st_size,
                        "encrypted": False, "items": [{"name": m.name, "bytes": m.size} for m in mem[:limit]]}
    except (OSError, zipfile.BadZipFile, tarfile.TarError) as e:
        return {"error": f"Archiv je poškozený nebo nečitelný: {e}"}
    if name.endswith((".7z", ".rar")):
        exe = seven_zip()
        if not exe:
            return {"error": "Na .7z a .rar je potřeba 7-Zip (zdarma, 7-zip.org). Po instalaci to půjde."}
        from .pcreport import run_quiet

        _c, out, _e = run_quiet([exe, "l", "-slt", str(p)], 60)
        items = [{"name": m.group(1), "bytes": int(m.group(2) or 0)}
                 for m in re.finditer(r"Path = (.+?)\r?\n(?:.*\r?\n)*?Size = (\d*)", out.split("----------", 1)[-1])]
        return {"type": name.rsplit(".", 1)[-1].upper(), "files": len(items), "bytes": sum(i["bytes"] for i in items),
                "packed": p.stat().st_size, "encrypted": "Encrypted = +" in out, "items": items[:limit]}
    return {"error": "Tohle není archiv, který umím otevřít (ZIP, TAR, 7Z, RAR)."}


def seven_zip() -> str | None:
    found = shutil.which("7z") or shutil.which("7z.exe")
    for c in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if not found and os.path.isfile(c):
            found = c
    return found


def safe_extract(p: Path, dest: Path) -> dict:
    """Into a NEW folder; entries that would escape it (../, absolute paths, links) are refused (zip slip)."""
    if dest.exists() and any(dest.iterdir()):
        raise ValueError(f"Cílová složka {dest} není prázdná – vyber novou.")
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    skipped, n = [], 0
    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            for i in z.infolist():
                target = (dest / i.filename).resolve()
                if not target.is_relative_to(root):
                    skipped.append(i.filename)
                    continue
                z.extract(i, dest)
                n += 1 if not i.is_dir() else 0
    elif tarfile.is_tarfile(p):
        with tarfile.open(p) as t:
            for m in t.getmembers():
                target = (dest / m.name).resolve()
                if not target.is_relative_to(root) or m.issym() or m.islnk() or m.isdev():
                    skipped.append(m.name)
                    continue
                t.extract(m, dest, filter="data") if hasattr(tarfile, "data_filter") else t.extract(m, dest)
                n += 1 if m.isfile() else 0
    else:
        exe = seven_zip()
        if not exe:
            raise ValueError("Na tenhle archiv je potřeba 7-Zip.")
        from .pcreport import run_quiet

        code, out, err = run_quiet([exe, "x", "-y", f"-o{dest}", str(p)], 600)
        if code != 0:
            raise ValueError(f"7-Zip: {(err or out)[-200:]}")
        n = sum(1 for q in dest.rglob("*") if q.is_file())
    return {"files": n, "skipped": skipped, "folder": str(dest)}


def make_zip(sources: list[Path], dest: Path) -> dict:
    if dest.exists():
        raise ValueError(f"{dest.name} už existuje – zvol jiný název.")
    n = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for s in sources:
            if s.is_dir():
                for q in walk([s]):
                    z.write(q, Path(s.name) / q.relative_to(s))
                    n += 1
            elif s.is_file():
                z.write(s, s.name)
                n += 1
    with zipfile.ZipFile(dest) as z:                      # verify: every entry readable, CRCs match
        bad = z.testzip()
    if bad:
        raise ValueError(f"Archiv se nepovedl ověřit ({bad}).")
    return {"files": n, "bytes": dest.stat().st_size, "path": str(dest)}


# ---------------------------------------------------------------------------------------------- 324 conversion
CONVERSIONS = {
    "image": ({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}, {"png", "jpg", "webp", "bmp", "gif", "tiff", "pdf"}),
    "pdf": ({".pdf"}, {"txt"}),
    "docx": ({".docx"}, {"txt", "md"}),
    "xlsx": ({".xlsx"}, {"csv"}),
    "csv": ({".csv"}, {"xlsx"}),
    "text": ({".txt", ".md"}, {"docx"}),
}


def free_name(p: Path) -> Path:
    k, q = 2, p
    while q.exists():
        q = p.with_name(f"{p.stem} ({k}){p.suffix}")
        k += 1
    return q


def convert(src: Path, to: str, max_side: int = 0) -> Path:
    """A new file next to the original (the original stays). Returns the new path."""
    to = to.lower().lstrip(".").replace("jpeg", "jpg")
    ext = src.suffix.lower()
    kind = next((k for k, (ins, outs) in CONVERSIONS.items() if ext in ins and to in outs), None)
    if not kind:
        raise ValueError(f"{ext} → .{to} neumím. Umím: obrázky mezi sebou a do PDF, PDF → txt, Word → txt/md, "
                         "Excel ↔ CSV, txt/md → Word.")
    dst = free_name(src.with_suffix("." + to))
    if kind == "image":
        from PIL import Image, ImageOps

        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            if max_side and max(im.size) > max_side:
                im.thumbnail((max_side, max_side))
            if to in ("jpg", "pdf", "bmp") and im.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", im.size, "white")
                bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
                im = bg
            im.save(dst, {"jpg": "JPEG", "tiff": "TIFF"}.get(to, to.upper()), **({"quality": 92} if to in ("jpg", "webp") else {}))
    elif kind == "pdf":
        from pypdf import PdfReader

        text = "\n\n".join((pg.extract_text() or "") for pg in PdfReader(str(src)).pages)
        if not text.strip():
            raise ValueError("PDF neobsahuje text (asi je naskenované – to umí až rozpoznání textu z obrázku).")
        dst.write_text(text, encoding="utf-8")
    elif kind == "docx":
        import docx

        d = docx.Document(str(src))
        lines = []
        for para in d.paragraphs:
            t = para.text
            style = (para.style.name or "").lower() if para.style is not None else ""
            if to == "md" and t.strip():
                if style.startswith("heading"):
                    lvl = int(re.sub(r"\D", "", style) or 1)
                    t = "#" * min(6, lvl) + " " + t
                elif "list" in style:
                    t = "- " + t
            lines.append(t)
        for table in d.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells]
                lines.append(("| " + " | ".join(cells) + " |") if to == "md" else "\t".join(cells))
        dst.write_text("\n".join(lines), encoding="utf-8")
    elif kind == "xlsx":
        import csv

        import openpyxl

        wb = openpyxl.load_workbook(str(src), read_only=True, data_only=True)
        ws = wb.active
        with open(dst, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            for row in ws.iter_rows(values_only=True):
                w.writerow(["" if v is None else v for v in row])
        wb.close()
    elif kind == "csv":
        import csv

        import openpyxl

        raw = src.read_text(encoding="utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=";,\t") if raw.strip() else csv.excel
        wb = openpyxl.Workbook()
        ws = wb.active
        for row in csv.reader(raw.splitlines(), dialect):
            ws.append([_num(v) for v in row])
        wb.save(str(dst))
    elif kind == "text":
        import docx

        d = docx.Document()
        for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^(#{1,6})\s+(.*)", line)
            if m and ext == ".md":
                d.add_heading(m.group(2), level=len(m.group(1)))
            elif re.match(r"^\s*[-*]\s+", line) and ext == ".md":
                d.add_paragraph(re.sub(r"^\s*[-*]\s+", "", line), style="List Bullet")
            else:
                d.add_paragraph(line)
        d.save(str(dst))
    if not dst.is_file() or dst.stat().st_size == 0:
        raise ValueError("Převod nevytvořil soubor.")
    return dst


def _num(v: str) -> Any:
    s = v.strip().replace("\u00a0", "").replace(" ", "")
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+[.,]\d+", s):
        return float(s.replace(",", "."))
    return v


# ---------------------------------------------------------------------------------------------- 326 metadata
def read_metadata(p: Path) -> dict:
    ext = p.suffix.lower()
    out: dict[str, Any] = {}
    if ext in IMAGE_EXT:
        from PIL import ExifTags, Image

        with Image.open(p) as im:
            exif = im.getexif()
            for k, v in exif.items():
                out[ExifTags.TAGS.get(k, str(k))] = str(v)[:80]
            gps = exif.get_ifd(0x8825)
            if gps:
                out["GPS"] = "poloha, kde byla fotka pořízena"
    elif ext == ".docx":
        import docx

        cp = docx.Document(str(p)).core_properties
        for k in ("author", "last_modified_by", "title", "comments", "company", "keywords", "subject"):
            v = getattr(cp, k, None)
            if v:
                out[k] = str(v)
    elif ext == ".pdf":
        from pypdf import PdfReader

        md = PdfReader(str(p)).metadata or {}
        out = {str(k).lstrip("/"): str(v)[:80] for k, v in md.items()}
    return out


def clean_metadata(p: Path, overwrite: bool = False) -> Path:
    """A copy without author, GPS, camera, software… (overwrite=True replaces the original after a version copy)."""
    ext = p.suffix.lower()
    dst = p if overwrite else free_name(p.with_name(p.stem + "_bez_metadat" + p.suffix))
    tmp = dst.with_name(dst.name + ".jarvis-tmp")
    if ext in IMAGE_EXT:
        from PIL import Image, ImageOps

        with Image.open(p) as im:
            im2 = ImageOps.exif_transpose(im)          # keep the visible orientation, drop the EXIF that held it
            clean = Image.frombytes(im2.mode, im2.size, im2.tobytes())
            if im2.mode == "P" and im2.getpalette():
                clean.putpalette(im2.getpalette())
            fmt = (im.format or ext.lstrip(".")).upper().replace("JPG", "JPEG")
            clean.save(tmp, fmt, **({"quality": 95} if fmt in ("JPEG", "WEBP") else {}))
    elif ext == ".docx":
        import docx

        d = docx.Document(str(p))
        cp = d.core_properties
        for k in ("author", "last_modified_by", "title", "comments", "keywords", "subject", "category", "identifier",
                  "content_status", "language", "version"):
            try:
                setattr(cp, k, "")
            except (ValueError, TypeError):
                pass
        d.save(str(tmp))
    elif ext == ".pdf":
        from pypdf import PdfReader, PdfWriter

        w = PdfWriter()
        for pg in PdfReader(str(p)).pages:
            w.add_page(pg)
        w.add_metadata({"/Producer": ""})
        with open(tmp, "wb") as f:
            w.write(f)
    else:
        raise ValueError("Metadata umím odstranit z fotek, Wordu (.docx) a PDF.")
    if overwrite:
        save_version(p)
    os.replace(tmp, dst)
    return dst


# ---------------------------------------------------------------------------------------------- 328 versions
def versions_dir() -> Path:
    return paths.sub("versions")


def _vkey(p: Path) -> str:
    return hashlib.sha1(str(p.resolve()).lower().encode()).hexdigest()[:16]


def save_version(p: Path, note: str = "") -> dict:
    d = versions_dir() / _vkey(p)
    d.mkdir(parents=True, exist_ok=True)
    digest = sha256(p)
    prev = list_versions(p)
    if prev and prev[0]["sha256"] == digest:
        return {**prev[0], "unchanged": True}
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    shutil.copy2(p, d / f"{stamp}{p.suffix}")
    meta = d / "versions.json"
    items = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else []
    v = {"file": f"{stamp}{p.suffix}", "ts": time.time(), "sha256": digest, "bytes": p.stat().st_size, "note": note[:120],
         "original": str(p)}
    items.append(v)
    meta.write_text(json.dumps(items[-50:], ensure_ascii=False, indent=1), encoding="utf-8")
    for old in items[:-50]:
        try:
            (d / old["file"]).unlink()
        except OSError:
            pass
    return v


def list_versions(p: Path) -> list[dict]:
    meta = versions_dir() / _vkey(p) / "versions.json"
    items = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else []
    return sorted(items, key=lambda v: -v["ts"])


def restore_version(p: Path, index: int = 0) -> dict:
    vs = list_versions(p)
    if not vs or index >= len(vs):
        raise ValueError("Tahle verze neexistuje.")
    v = vs[index]
    src = versions_dir() / _vkey(p) / v["file"]
    if sha256(src) != v["sha256"]:
        raise ValueError("Uložená verze je poškozená (nesedí otisk) – neobnovuji ji.")
    if p.exists():
        save_version(p, "před obnovením starší verze")
    shutil.copy2(src, p)
    return v


# ---------------------------------------------------------------------------------------------- 329 integrity
def manifest(folder: Path) -> dict:
    files = {}
    for q in walk([folder]):
        try:
            files[str(q.relative_to(folder))] = {"sha256": sha256(q), "bytes": q.stat().st_size}
        except OSError:
            pass
    return {"folder": str(folder), "created": time.time(), "files": files}


def manifest_path(folder: Path) -> Path:
    return paths.sub("integrity") / f"{_vkey(folder)}.json"


def integrity_save(folder: Path) -> dict:
    m = manifest(folder)
    manifest_path(folder).write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return {"files": len(m["files"]), "bytes": sum(f["bytes"] for f in m["files"].values())}


def integrity_check(folder: Path) -> dict:
    mp = manifest_path(folder)
    if not mp.exists():
        raise ValueError("Pro tuhle složku ještě nemám otisky – nejdřív je ulož.")
    old = json.loads(mp.read_text(encoding="utf-8"))
    now = manifest(folder)["files"]
    before = old["files"]
    changed = sorted(k for k in before if k in now and now[k]["sha256"] != before[k]["sha256"])
    missing = sorted(k for k in before if k not in now)
    added = sorted(k for k in now if k not in before)
    return {"since": old["created"], "files": len(now), "changed": changed, "missing": missing, "added": added,
            "same": len(before) - len(changed) - len(missing)}


# ---------------------------------------------------------------------------------------------- 319 / 320 documents
DOC_RULES = [
    ("Faktury", r"\bfaktur|invoice|daňový doklad|variabilní symbol|\bDPH\b"),
    ("Smlouvy", r"\bsmlouv|contract|smluvní stran|dodatek č"),
    ("Banka a výpisy", r"výpis z účtu|bank statement|zůstatek|IBAN"),
    ("Úřady a daně", r"finanční úřad|daňové přiznání|ČSSZ|zdravotní pojišťovna|úřad práce|katastr"),
    ("Zdraví", r"lékař|nemocnice|recept|vyšetření|očkování|diagnóz"),
    ("Práce", r"pracovní smlouv|výplatní páska|mzd|životopis|curriculum vitae|\bCV\b"),
    ("Pojištění", r"pojistn|pojišťovn|pojistka"),
    ("Účtenky", r"účtenka|paragon|celkem k úhradě|EET|děkujeme za nákup"),
    ("Škola", r"vysvědčení|škol|seminární práce|zápočet|zkouška|přihláška ke studiu"),
]
TYPE_RULES = [("Fotky", IMAGE_EXT), ("Videa", {".mp4", ".mov", ".mkv", ".avi", ".webm"}), ("Hudba", {".mp3", ".flac", ".wav", ".m4a", ".ogg"}),
              ("Instalačky", {".exe", ".msi"}), ("Archivy", {".zip", ".rar", ".7z", ".tar", ".gz"}),
              ("Tabulky", {".xlsx", ".xls", ".csv", ".ods"}), ("Prezentace", {".pptx", ".ppt", ".odp"})]


def doc_text(p: Path, limit: int = 4000) -> str:
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader

            r = PdfReader(str(p))
            return "\n".join((pg.extract_text() or "") for pg in r.pages[:3])[:limit]
        if ext == ".docx":
            import docx

            return "\n".join(par.text for par in docx.Document(str(p)).paragraphs)[:limit]
        if ext in (".txt", ".md", ".csv", ".eml", ".html", ".htm"):
            return p.read_text(encoding="utf-8", errors="ignore")[:limit]
    except Exception:  # noqa: BLE001 – unreadable document: classified by its name and type only
        return ""
    return ""


def classify(p: Path) -> tuple[str, str]:
    """(category, why). Content first (PDF, Word, text), then the name, then the file type."""
    text = doc_text(p)
    for cat, rx in DOC_RULES:
        if text and re.search(rx, text, re.I):
            return cat, "podle obsahu"
    for cat, rx in DOC_RULES:
        if re.search(rx, p.stem.replace("_", " "), re.I):
            return cat, "podle názvu"
    ext = p.suffix.lower()
    for cat, exts in TYPE_RULES:
        if ext in exts:
            return cat, "podle typu"
    if ext in (".pdf", ".docx", ".doc", ".txt", ".odt", ".rtf", ".md"):
        return "Dokumenty", "podle typu"
    return "Ostatní", "nepoznal jsem"


def sort_plan(folder: Path, files: list[Path] | None = None) -> list[dict]:
    files = files if files is not None else [q for q in folder.iterdir() if q.is_file() and not q.name.startswith(".")]
    plan = []
    for p in files:
        cat, why = classify(p)
        plan.append({"src": str(p), "dst": str(free_name(folder / cat / p.name)), "category": cat, "why": why})
    return plan


DATE_RX = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(20\d\d)\b|\b(20\d\d)-(\d\d)-(\d\d)\b")
ORG_RX = re.compile(r"([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][\w&.\- ]{1,40}?)\s*,?\s*(s\.\s?r\.\s?o\.|a\.\s?s\.|spol\. s r\.\s?o\.|GmbH|Ltd|Inc)", re.U)


SMART_DOCS = {".pdf", ".docx", ".txt", ".md"}
SMART_MEDIA = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".tif", ".tiff", ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp",
               ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac"}
_CLEAN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _camera(p: Path) -> str:
    try:
        from PIL import Image

        with Image.open(p) as im:
            ex = im.getexif()
            model = str(ex.get(272) or "").strip().strip("\x00")
            make = str(ex.get(271) or "").strip().strip("\x00")
    except Exception:  # noqa: BLE001
        return ""
    if model and make and not model.lower().startswith(make.lower().split()[0]):
        model = f"{make.split()[0]} {model}"
    return re.sub(r"\s+", "-", model)[:24]


def _audio_tags(p: Path) -> tuple[str, str]:
    try:
        import av

        with av.open(str(p)) as c:
            md = {k.lower(): v for k, v in (c.metadata or {}).items()}
        return str(md.get("artist") or "").strip()[:40], str(md.get("title") or "").strip()[:60]
    except Exception:  # noqa: BLE001
        return "", ""


def media_smart_name(p: Path) -> str:
    """OMEGA 320 for photos, videos and sound: Foto_2026-06-14_14-03_iPhone-13.jpg, Video_…, Interpret - Skladba.mp3."""
    ext = p.suffix.lower()
    if ext in (".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac"):
        artist, title = _audio_tags(p)
        if title:
            return _CLEAN.sub("", f"{artist} - {title}" if artist else title) + ext
    from .mediapro import media_date

    d = media_date(p)
    kind = "Video" if ext in (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp") else "Nahravka" if ext in (".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac") else "Foto"
    parts = [kind, d.strftime("%Y-%m-%d_%H-%M")]
    if kind == "Foto":
        cam = _camera(p)
        if cam:
            parts.append(cam)
    return _CLEAN.sub("", "_".join(parts)) + ext


def smart_name(p: Path) -> str:
    """A readable name from the content: <Type>_<date>_<company>.ext (what is not found is left out)."""
    if p.suffix.lower() in SMART_MEDIA:
        return media_smart_name(p)
    text = doc_text(p)
    cat, _why = classify(p)
    kind = {"Faktury": "Faktura", "Smlouvy": "Smlouva", "Banka a výpisy": "Vypis", "Účtenky": "Uctenka",
            "Pojištění": "Pojisteni", "Zdraví": "Zdravi", "Úřady a daně": "Urad", "Práce": "Prace", "Škola": "Skola"}.get(cat, "")
    parts = [kind] if kind else []
    m = DATE_RX.search(text)
    if m:
        d, mo, y = (m.group(1), m.group(2), m.group(3)) if m.group(3) else (m.group(6), m.group(5), m.group(4))
        try:
            parts.append(dt.date(int(y), int(mo), int(d)).isoformat())
        except ValueError:
            pass
    o = ORG_RX.search(text)
    if o:
        parts.append(re.sub(r"\s+", "-", o.group(1).strip())[:30])
    if not parts or parts == [kind]:
        parts.append(re.sub(r"\s+", "_", p.stem)[:40])
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", "_".join(parts))
    return stem + p.suffix.lower()


# ---------------------------------------------------------------------------------------------- 322 lost files
def recent_files(folders: list[Path], hours: float = 48, kinds: set[str] | None = None, limit: int = 30) -> list[dict]:
    since = time.time() - hours * 3600
    out = []
    for p in walk(folders):
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_mtime >= since and (not kinds or p.suffix.lower() in kinds):
            out.append({"path": str(p), "mtime": st.st_mtime, "bytes": st.st_size})
    return sorted(out, key=lambda x: -x["mtime"])[:limit]


def search_content(folders: list[Path], query: str, limit: int = 20) -> list[dict]:
    """Files whose TEXT contains all the words (txt, md, PDF, Word…) – for "I don't remember the name"."""
    words = [w.lower() for w in re.findall(r"\w{3,}", query)]
    if not words:
        return []
    out = []
    for p in walk(folders, 30_000):
        if p.suffix.lower() not in (".txt", ".md", ".pdf", ".docx", ".csv", ".html", ".htm", ".eml", ".json"):
            continue
        try:
            if p.stat().st_size > 30_000_000:
                continue
        except OSError:
            continue
        text = doc_text(p, 200_000).lower()
        if text and all(w in text for w in words):
            i = text.find(words[0])
            out.append({"path": str(p), "snippet": text[max(0, i - 60):i + 100].replace("\n", " ")})
            if len(out) >= limit:
                break
    return out


# ---------------------------------------------------------------------------------------------- 330 backups
VALUE = {"Documents": 10, "Desktop": 9, "Pictures": 9, "OneDrive": 6, "Videos": 5, "Music": 4, "Downloads": 2}


def backup_plan(home: Path | None = None) -> list[dict]:
    """What to back up first: your own work and photos; downloads and installers last (can be downloaded again)."""
    home = home or Path.home()
    out = []
    for name, value in VALUE.items():
        p = home / name
        if not p.is_dir():
            continue
        size = files = 0
        installers = 0
        for q in walk([p], 300_000):
            try:
                s = q.stat().st_size
            except OSError:
                continue
            size += s
            files += 1
            if q.suffix.lower() in (".exe", ".msi", ".iso", ".zip"):
                installers += s
        out.append({"folder": str(p), "bytes": size, "files": files, "value": value,
                    "note": "hlavně instalačky a stažené věci – jdou stáhnout znovu" if installers > size / 2 else ""})
    out.sort(key=lambda x: (-x["value"], x["bytes"]))
    return out


def backup(src: Path, dst_root: Path) -> dict:
    """Incremental copy src → dst_root/<src name> (only new or changed files), then a SHA-256 check of what was copied."""
    dst = dst_root / src.name
    copied, same, failed = [], 0, []
    for q in walk([src]):
        rel = q.relative_to(src)
        t = dst / rel
        try:
            st = q.stat()
            if t.exists() and t.stat().st_size == st.st_size and int(t.stat().st_mtime) >= int(st.st_mtime):
                same += 1
                continue
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(q, t)
            copied.append(rel)
        except OSError as e:
            failed.append(f"{rel}: {e}")
    bad = [str(r) for r in copied if sha256(src / r) != sha256(dst / r)]
    return {"copied": len(copied), "unchanged": same, "failed": failed[:50], "verify_failed": bad[:50], "folder": str(dst),
            "bytes": sum((dst / r).stat().st_size for r in copied)}
