# Rozhodnutí (ADR)

### D1 – Rozšiřovat stávající stack, nepřepisovat
Python jádro (FastAPI, SQLite) + pywebview/WebView2 + Vite/TypeScript + Capacitor už funguje a je otestované na
skutečném Windows v CI. Přechod na Electron/Tauri by nic nepřinesl a rozbil by funkční části. **Zůstává.**

### D2 – Mise = rozšířené Úkoly, ne nový systém
Úkoly (`tasks.py`) už měly ID, plán, kroky, audit, pauzu a zrušení. OMEGA mise je doplněna o kritéria, artefakty,
důkazy, stav ověřování a obnovu po restartu – ve stejných tabulkách a stejném UI. Druhý „mission engine“ by
zdvojil stav a UI.

### D3 – Složené dovednosti = protokoly s verzemi
Skill Forge v prvním řezu nevytváří kód, ale skládá existující nástroje (protokol). Odpadá sandbox i bezpečnostní
audit kódu a uživatel vidí každý krok. Generování nového kódu zůstává ve stávajícím toku skillů se schválením.

### D4 – Diagnostika jen pevným read-only skriptem
Report nespouští příkazy vymyšlené AI. PowerShell skript je konstanta v `pcreport.py`, obsahuje jen povolené
cmdlety (`ALLOWED_CMDLETS`) a test to hlídá. Neměřitelné hodnoty jsou „neznámé“ s důvodem, nikdy odhad.

### D5 – Postavička: vlastní „blob“, ne cizí maskot
Zadání zmiňuje Mochi a inspiraci cizími projekty. JARVIS má vlastní originální postavičku (`character/blob.ts`) se
stejnými reakcemi (spánek, tanec, přemýšlení, radost, chyba, limit, sledování kurzoru); cizí jméno ani vzhled se
nepřebírá. Reakce jsou vázané na skutečné události (`mood.py`), včetně ověřené/neúspěšné mise.

### D6 – Žádná cizí platforma ani značka
Kód, UI ani dokumentace neobsahují značky, domény ani závislosti platforem, které uživatel vyloučil. Kopie zadání
v `OMEGA_SPEC.md` má jméno vyloučené platformy vynechané.

### D7 – Telefon v LAN přes token, zatím bez TLS
Párování QR kódem s náhodným tokenem (32 B), kontrola původu WebSocketu, nový token odpojí všechna zařízení.
Mimo domácí síť doporučujeme Tailscale (šifrovaný tunel). Vlastní TLS/relay je v ROADMAP (M6).

### D8 – Velké modely se nestahují potichu
Místní modely jsou volitelné; stažení vždy výslovně spouští uživatel a vidí velikost.

### D9 – Mikrofon jen viditelně
Naslouchání je vždy vidět v notchi; nahrávání hovorů a diktování spouští uživatel. Kamera se nepoužívá.
