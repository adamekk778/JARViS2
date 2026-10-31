"""Desktop helpers: Windows error codes explained (033), form values checked (530 – e-mail, phone, PSČ, IČO, rodné číslo,
IBAN, card, date), a Windows Search query (512) and what documents are open (029)."""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import sys

ERRORS = {
    0x80070005: ("Přístup odepřen", "Program nemá oprávnění – spusť ho jako správce nebo zkontroluj oprávnění složky / antivir."),
    0x80070002: ("Soubor nenalezen", "Chybí soubor, který program čeká – přeinstaluj ho nebo oprav cestu."),
    0x80070003: ("Cesta nenalezena", "Složka neexistuje nebo disk není připojený."),
    0x80070020: ("Soubor používá jiný proces", "Zavři program, který má soubor otevřený, a zkus to znovu."),
    0x80070057: ("Neplatný parametr", "Často poškozený instalátor nebo špatné nastavení – stáhni ho znovu."),
    0x80070070: ("Málo místa na disku", "Uvolni místo na disku (JARVIS: co zabírá místo)."),
    0x8007000E: ("Nedostatek paměti", "Zavři programy, restartuj PC."),
    0x800F081F: ("Chybí zdrojové soubory Windows", "Spusť kontrolu systémových souborů (DISM) a Windows Update."),
    0x800F0922: ("Aktualizace se nenainstalovala", "Zkontroluj místo na oddílu systému, připojení k internetu a vypni VPN."),
    0x80240034: ("Stažení aktualizace selhalo", "Restartuj PC a zkus Windows Update znovu; pomůže Poradce při potížích s Windows Update."),
    0x8024402C: ("Windows Update nemůže na server", "Zkontroluj internet, proxy a DNS."),
    0x80072EE7: ("Server nenalezen (DNS)", "Problém s internetem nebo DNS – JARVIS: zkontroluj síť."),
    0x80072EFD: ("Nelze se připojit k serveru", "Internet, firewall nebo proxy blokuje spojení."),
    0x800704CF: ("Síťové umístění není dostupné", "Síť nebo sdílená složka není dostupná."),
    0xC0000005: ("Přístup do neplatné paměti (pád programu)", "Aktualizuj program a ovladače; když padá jen jeden program, přeinstaluj ho."),
    0xC0000135: ("Chybí knihovna DLL / .NET", "Nainstaluj potřebný .NET / Visual C++ Redistributable."),
    0xC000007B: ("Špatná verze knihovny (32/64 bit)", "Přeinstaluj Visual C++ Redistributable (x86 i x64) a program."),
    0xC0000142: ("Program se nepodařilo spustit (DLL init)", "Restartuj PC, přeinstaluj program a Visual C++ Redistributable."),
    0x00000005: ("Přístup odepřen", "Spusť jako správce nebo zkontroluj oprávnění."),
    0x00000002: ("Soubor nenalezen", "Zkontroluj cestu / přeinstaluj."),
    0x0000007E: ("Modul nenalezen (DLL)", "Chybí DLL – přeinstaluj program nebo Visual C++ Redistributable."),
    0x000000C1: ("Není platná aplikace Win32", "Soubor je poškozený nebo pro jinou architekturu – stáhni ho znovu."),
    0x000005B4: ("Vypršel časový limit", "Služba neodpověděla včas – restartuj PC."),
    0x00000643: ("Instalace selhala (MSI 1603)", "Restartuj PC, odinstaluj starou verzi a instaluj jako správce."),
}


def find_codes(text: str) -> list[int]:
    out = []
    for m in re.finditer(r"0x[0-9a-fA-F]{6,8}|\b[0-9a-fA-F]{8}\b|(?:chyba|error|kód|code)\s*[:#]?\s*(\d{1,5})\b", text or "", re.I):
        tok = m.group(1) or m.group(0)
        try:
            v = int(tok, 16) if not m.group(1) else int(tok)
        except ValueError:
            continue
        if v not in out:
            out.append(v)
    return out


def explain_code(v: int) -> dict:
    name, fix = ERRORS.get(v, ("", ""))
    if not name and (v & 0xFFFF0000) == 0x80070000:            # HRESULT wrapping a Win32 error
        name, fix = ERRORS.get(v & 0xFFFF, ("", ""))
    return {"code": f"0x{v:08X}", "known": bool(name), "name": name or "neznámý kód", "fix": fix}


# ---------------------------------------------------------------- 530 form values
def _ico_ok(s: str) -> bool:
    if not re.fullmatch(r"\d{8}", s):
        return False
    w = sum(int(s[i]) * (8 - i) for i in range(7))
    c = (11 - w % 11) % 10
    return c == int(s[7])


def _rc_ok(s: str) -> bool:
    d = re.sub(r"\D", "", s)
    if len(d) not in (9, 10):
        return False
    yy, mm, dd = int(d[:2]), int(d[2:4]) % 50 % 20, int(d[4:6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return False
    if len(d) == 10:
        n = int(d)
        return n % 11 == 0 or (int(d[:9]) % 11 == 10 and d[9] == "0")
    return yy < 54


def _iban_ok(s: str) -> bool:
    x = re.sub(r"\s", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", x):
        return False
    r = x[4:] + x[:4]
    n = "".join(str(int(c, 36)) for c in r)
    return int(n) % 97 == 1


def _luhn(s: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", s)][::-1]
    if not 12 <= len(d) <= 19:
        return False
    return sum(x if i % 2 == 0 else (x * 2 - 9 if x * 2 > 9 else x * 2) for i, x in enumerate(d)) % 10 == 0


CHECKS = {
    "email": (lambda v: bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", v, re.I)), "e-mail nemá tvar jmeno@domena.cz"),
    "telefon": (lambda v: bool(re.fullmatch(r"(\+?420)?\s?\d{3}\s?\d{3}\s?\d{3}", v.strip())), "telefon: 9 číslic, případně s +420"),
    "psc": (lambda v: bool(re.fullmatch(r"\d{3}\s?\d{2}", v.strip())), "PSČ má 5 číslic (např. 602 00)"),
    "ico": (lambda v: _ico_ok(re.sub(r"\s", "", v)), "IČO nesedí (8 číslic s kontrolní číslicí)"),
    "dic": (lambda v: bool(re.fullmatch(r"CZ\d{8,10}", re.sub(r"\s", "", v).upper())), "DIČ má tvar CZ + 8 až 10 číslic"),
    "rodne_cislo": (_rc_ok, "rodné číslo nesedí (datum nebo kontrolní dělitelnost 11)"),
    "iban": (_iban_ok, "IBAN nesedí (kontrolní součet)"),
    "karta": (_luhn, "číslo karty nesedí (Luhnův součet)"),
    "datum": (lambda v: _date_ok(v), "datum neexistuje nebo má špatný tvar (d. m. rrrr)"),
}


def _date_ok(v: str) -> bool:
    m = re.fullmatch(r"\s*(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\s*", v) or re.fullmatch(r"\s*(\d{4})-(\d{2})-(\d{2})\s*", v)
    if not m:
        return False
    a, b, c = (int(x) for x in m.groups())
    y, mo, d = (a, b, c) if a > 31 else (c, b, a)
    try:
        dt.date(y, mo, d)
        return True
    except ValueError:
        return False


KIND_HINTS = [("email", r"mail"), ("telefon", r"tel|phone|mobil"), ("psc", r"ps[čc]|zip|post"), ("ico", r"\bi[čc]o?\b|ičo"),
              ("dic", r"di[čc]|vat"), ("rodne_cislo", r"rodn|birth"), ("iban", r"iban|účet|ucet|account"), ("karta", r"karta|card"),
              ("datum", r"datum|date|narozen")]


def guess_kind(label: str, value: str) -> str | None:
    lab = (label or "").lower()
    for k, rx in KIND_HINTS:
        if re.search(rx, lab):
            return k
    if "@" in value:
        return "email"
    return None


def check_values(fields: dict[str, str]) -> list[dict]:
    out = []
    for label, value in fields.items():
        k = guess_kind(label, str(value))
        if not k:
            out.append({"field": label, "kind": None, "ok": None, "why": "nevím, co je to za údaj – nekontroluji"})
            continue
        if not str(value).strip():
            out.append({"field": label, "kind": k, "ok": False, "why": "prázdné"})
            continue
        fn, why = CHECKS[k]
        ok = bool(fn(str(value)))
        out.append({"field": label, "kind": k, "ok": ok, "why": "" if ok else why})
    return out


# ---------------------------------------------------------------- 512 Windows Search
SEARCH_PS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$q = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__Q__'))
$c = New-Object -ComObject ADODB.Connection
$r = New-Object -ComObject ADODB.Recordset
$c.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
$sql = "SELECT TOP 25 System.ItemPathDisplay, System.ItemName, System.Kind, System.DateModified, System.ItemType FROM SystemIndex WHERE FREETEXT('" + $q.Replace("'", "''") + "') ORDER BY System.Search.Rank DESC"
$r.Open($sql, $c)
$out = @()
while (-not $r.EOF) { $out += @{ path = "$($r.Fields.Item('System.ItemPathDisplay').Value)"; name = "$($r.Fields.Item('System.ItemName').Value)";
  kind = "$($r.Fields.Item('System.Kind').Value)"; modified = "$($r.Fields.Item('System.DateModified').Value)"; type = "$($r.Fields.Item('System.ItemType').Value)" }; $r.MoveNext() }
$r.Close(); $c.Close()
@{ items = $out } | ConvertTo-Json -Depth 4 -Compress
"""


def windows_search(query: str) -> dict:
    """The Windows search index – files, but also indexed Outlook e-mails, OneNote pages and contacts (what Start search finds)."""
    if sys.platform != "win32":
        return {"error": "jen ve Windows", "items": []}
    from .pcreport import run_quiet

    script = SEARCH_PS.replace("__Q__", base64.b64encode(query.encode("utf-8")).decode())
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    _c, out, err = run_quiet(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], 40)
    try:
        d = json.loads(out[out.find("{"):]) if "{" in out else {}
    except ValueError:
        d = {}
    items = d.get("items") or []
    if isinstance(items, dict):
        items = [items]
    return {"items": items, "error": None if d else (err.strip()[:200] or "Windows Search neodpověděl")}


# ---------------------------------------------------------------- 029 open documents
DOC_TITLE = re.compile(r"^(?P<name>.+?\.(?:docx?|xlsx?|pptx?|odt|ods|pdf|txt|md|csv|rtf))(?:\s*(?:\[[^\]]*\])?\s*[-–—]\s*.*)?$", re.I)


def open_document_names(titles: list[str]) -> list[str]:
    """Document names from window titles ("Smlouva_v2.docx - Word", "data.xlsx - Excel", "zapis.txt – Poznámkový blok")."""
    out = []
    for t in titles:
        m = DOC_TITLE.match((t or "").strip())
        if m and m.group("name") not in out:
            out.append(m.group("name").strip())
    return out
