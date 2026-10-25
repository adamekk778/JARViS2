# Integrace

| Integrace | Stav | Jak se připojuje | Kde jsou tajemství | Omezení |
|---|---|---|---|---|
| AI poskytovatelé (Claude, OpenAI, Gemini, Groq, OmniRoute, kompatibilní API) | funkční | Nastavení → Mozek | trezor OS | limity a cena podle poskytovatele; řetěz s náhradou |
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
| Jízdní řády ČR | chybí | — | — | chybí veřejné API |

Kontrola funkčnosti: Nastavení → Mozek (test poskytovatele), E-mail a telefon (stav účtů a spojení s telefonem),
Domov (test Home Assistantu při uložení), Diagnostika.
