# Integrace

| Integrace | Stav | Jak se připojuje | Kde jsou tajemství | Omezení |
|---|---|---|---|---|
| AI poskytovatelé (Claude, OpenAI, Gemini, Groq, OmniRoute, kompatibilní API) | funkční | Nastavení → Mozek | trezor OS | limity a cena podle poskytovatele; řetěz s náhradou |
| Claude přes oficiální SDK (3.14) | funkční | Nastavení → Mozek → Kdo odpovídá → Claude (klíč sk-ant- z console.anthropic.com) | trezor OS | modely Opus 5.5 / Sonnet 5.5 / Haiku 5.5 / Fable 5.2 přepínatelné v JARVISovi; placené podle tokenů; předplatné Claude Pro/Max klíč nedává |
| Místní modely (Ollama, LM Studio) | funkční, volitelné | Nastavení → Mozek | — | stažení jen ručně; výkon podle GPU |
| Claude Code CLI | funkční | háčky Claude Code → notch/telefon (claude_bridge.py) | — | jen podporovaným rozhraním, bez obcházení limitů |
| MCP servery | funkční | Nastavení → Integrace | trezor OS | nástroje MCP spadají pod oprávnění Internet |
| E-mail (IMAP/SMTP: Seznam, Gmail, Centrum, Atlas, iCloud, vlastní) | funkční | E-mail a telefon | trezor OS (heslo pro aplikace) | odeslání vždy po schválení |
| Kalendář | funkční | vlastní + odběr ICS (jen čtení) | — | zápis do Google kalendáře chybí |
| Telefon (Android) | funkční | QR párování, služba na pozadí | token v nastavení | iOS: viz ROADMAP (omezení platformy) |
| Twilio (skutečný hovor) | volitelné | E-mail a telefon → Twilio | trezor OS | placená služba |
| Home Assistant | funkční | Domov → adresa + dlouhodobý token | trezor OS | zámky/alarm/brány vždy s potvrzením |
| Kurzy ČNB, CoinGecko, Stooq | funkční | bez účtu | — | veřejná data, zpoždění podle zdroje |
| Google Zprávy RSS, Open-Meteo počasí | funkční | bez účtu | — | — |
| GitHub, Google Drive | přes MCP | MCP server | podle serveru | — |
| Blender, Unity, Roblox Studio | jen přes ovládání počítače | — | — | nativní integrace v ROADMAP |
| MHD Praha (PID, Golemio) | funkční s klíčem | Nastavení → Propojení → Golemio | trezor OS | bezplatný klíč z api.golemio.cz; jen Praha |
| Jízdní řády mimo Prahu | chybí | — | — | chybí veřejné API |
| OBS Studio (3.14) | funkční | obs-websocket 5 (OBS 28+), Nastavení → Propojení → OBS | trezor OS (heslo) | scény, nahrávání, stream, uložení posledních chvil |
| PresentMon (FPS ve hrách, 3.14) | volitelné | nainstalovaný PresentMon | — | bez něj se FPS neměří |
| winget (3.14) | připraveno | manifesty v příloze každého vydání | — | zařazení do katalogu = ruční PR do microsoft/winget-pkgs (docs/WINGET.md) |
| Webová stránka (GitHub Pages, 3.14) | připraveno | `site/` + workflow `pages.yml` | — | správce zapne Pages: Settings → Pages → GitHub Actions |
| Anonymní statistiky (3.14) | vypnuté | Bezpečí a soukromí → Anonymní statistiky + adresa serveru | — | jen se souhlasem; sběrný server `packaging/stats-worker` (Cloudflare Worker) |

Kontrola funkčnosti: Nastavení → Mozek (test poskytovatele), E-mail a telefon (stav účtů a spojení s telefonem),
Domov (test Home Assistantu při uložení), Diagnostika.
