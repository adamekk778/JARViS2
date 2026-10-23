# JARVIS 2

Osobní AI asistent pro **Windows PC** a **Android telefon**. Mluví česky, má chat s přílohami, vlastní nastavení,
„notch“ nahoře na obrazovce jako MacBook a umí ovládat počítač. Funguje zdarma (OmniRoute / Ollama) a z telefonu
ho ovládáš odkudkoli.

## Instalace (2 soubory)

Stáhni z **[Releases](../../releases/latest)**:

| Soubor | Kam | Jak |
|---|---|---|
| `JARVIS-Setup.exe` | PC (Windows 10/11, 64 bit) | Spusť, klikni Další. Instalátor nabídne i OmniRoute, Ollamu a Tailscale. |
| `JARVIS.apk` | Telefon (Android 8+) | Otevři v telefonu a povol „Instalovat z tohoto zdroje“. |

Pak na PC: JARVIS → **Telefon** → v aplikaci na mobilu **Naskenovat QR kód**. Hotovo.

> Při prvním spuštění se Windows zeptá na povolení v bráně firewall: povol **Soukromé sítě**, jinak se telefon nepřipojí.
> Hlasové modely (Whisper ~460 MB) se stáhnou automaticky při prvním použití hlasu.

## Mozek (AI) zdarma

JARVIS zkouší poskytovatele v pořadí z **Nastavení → Mozek** a když jeden nejde, vezme další:

1. **OmniRoute** (výchozí, `http://localhost:20128/v1`): bezplatná brána k mnoha AI. Po instalaci otevři
   `http://localhost:20128` a přidej si poskytovatele zdarma. JARVIS OmniRoute sám spouští.
2. **Ollama** (offline): JARVIS si sám stáhne malý model `qwen2.5:3b`. Funguje bez internetu.
3. Cokoli s OpenAI API: OpenRouter, Groq, Gemini, LM Studio, vlastní URL. Klíč vložíš v Nastavení (uloží se do Správce pověření Windows).

## Co umí

- **Hlas:** „Hey Jarvis“ nebo Ctrl+Alt+Mezerník, česky, offline rozpoznávání (Whisper), hlas Microsoft Edge (zdarma) / Piper offline, dá se přerušit.
- **Chat** jako ChatGPT (Ctrl+Alt+J): Markdown, kód, historie, hledání, 🔊 přečíst nahlas.
- **Přílohy:** fotky (popíše), PDF, Word, Excel, PowerPoint, kód, hlasovky (přepíše), cokoli dalšího uloží/otevře.
- **Notch:** najeď myší nahoru doprostřed obrazovky → Zeptej se, Právě hraje, Police na soubory, Rychlé akce, Časovače, Systém, Počasí, Telefon.
- **Ovládání PC:** aplikace, YouTube, Spotify/média, hlasitost, okna, soubory, schránka, screenshot, vypnutí (s potvrzením), PowerShell.
- **Internet:** vyhledávání a čtení stránek, počasí.
- **Superschopnosti:** ovládání počítače jako člověk (vidí obrazovku a kliká), ovládání prohlížeče, spouštění Python kódu,
  generování obrázků, MCP servery (Gmail, kalendář, …), **učí se nové dovednosti** (napíše si nástroj, ty schválíš kód),
  rutiny („každý den v 7:00 mi řekni počasí“).
- **Telefon:** chat a hlas, ovládání PC, Sdílet → JARVIS (odkaz se otevře na PC, soubor přistane v polici notche), notifikace.
- **Nastavení:** úplně všechno (mozek, hlas, notch, vzhled, zkratky, oprávnění nástrojů, integrace, paměť, záloha). Základní věci i hlasem („mluv rychleji“).

Nebezpečné akce (vypnutí, mazání, nákupy, příkazy) vždy nejdřív potvrdíš ty.

## Ruční test po instalaci

- [ ] „Hey Jarvis, pusť na YouTube trailer na Avengers“ → rozevře se notch, JARVIS odpoví a pustí video.
- [ ] Ctrl+Alt+J → chat, pošli fotku → JARVIS ji popíše.
- [ ] „Ztlum zvuk“, „hlasitost na 30“, „jaké bude počasí“.
- [ ] Najeď myší na notch → dlaždice, odjeď → zavře se.
- [ ] Telefon na Wi-Fi: napiš „otevři Spotify“ → otevře se na PC. Pak přes mobilní data se zapnutým Tailscale.
- [ ] „Vypni počítač“ → JARVIS se zeptá na potvrzení, řekni „ne“.

## Vývoj

```bash
cd web && npm ci && npm run build          # UI
pip install -e "./core[desktop,voice,dev]"  # jádro
python -m jarvis                           # spustí vše (na Linuxu: --no-ui)
cd core && pytest                          # testy
```

Struktura: `core/` Python jádro (agent, nástroje, hlas, server), `web/` UI (notch, chat, mobil),
`mobile/` Android obal (Capacitor), `packaging/` instalátor, návrh v `docs/superpowers/specs/`.
