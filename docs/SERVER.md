# JARVIS nonstop – domácí server

JARVIS může běžet na malém počítači, který je zapnutý pořád (mini PC, Raspberry Pi 5, NAS s Dockerem). Telefon,
hlasové satelity v místnostech a nástěnný displej se pak připojují k němu, i když je herní PC nebo notebook vypnutý.
Počítače s JARVISem (desktop, notebook) přidáš jako **uzly** a server je umí probudit i ovládat.

## Spuštění (Docker)

```bash
git clone https://github.com/adamekk778/JARViS2 && cd JARViS2
docker compose -f packaging/server/docker-compose.yml up -d
```

Server poslouchá na portu 8765 (`http://<adresa-serveru>:8765`). Data (nastavení, paměť, klíče) jsou ve svazku
`jarvis-data`. První nastavení: otevři v prohlížeči `http://<adresa-serveru>:8765` z počítače v síti, nebo spáruj
telefon (Nastavení → Telefon ukáže QR kód).

Na serveru neběží věci, které patří k PC (ovládání oken, myš, obrazovka, mikrofon PC) – ty dělají uzly.

## Uzly – víc počítačů jako jeden JARVIS

V Nastavení → Domov → Počítače přidej každý počítač: jméno („herní PC“), adresu (`http://192.168.1.20:8765`),
jeho párovací klíč (na tom PC: Nastavení → Telefon) a volitelně MAC adresu síťovky pro zapnutí po síti.
Pak stačí říct „zapni herní PC“, „zeptej se notebooku, kolik má baterie“, „vypni herní PC“ – potvrzení
nebezpečných akcí z druhého počítače přijde k tobě.

## Hlasové satelity v místnostech

1. V Home Assistantu nastav hlasové satelity (Home Assistant Voice PE, ESP32-S3-BOX, Atom Echo…).
2. Řekni JARVISovi „jak připojím satelit v kuchyni“ – dostaneš adresu `http://<server>:8765/ha/<klíč>/kuchyn`.
3. Home Assistant → Zařízení a služby → Přidat integraci → **Ollama** → tu adresu → model `jarvis`.
4. Nastavení → Hlasoví asistenti → konverzační agent = ta Ollama, přiřaď ho satelitu v kuchyni.

JARVIS pak ví, ve které místnosti jsi, a odpovídá tam. Adresa funguje jen z domácí sítě a jen s klíčem.

## Reproduktory a nástěnný displej

- Nastavení → Domov → Reproduktory: které `media_player` jsou „celý dům“ a který je v které místnosti.
  „Řekni do kuchyně, že večeře je hotová“ pak zazní hlasem JARVISe.
- Tablet nebo TV na zdi: `http://<server>:8765/hud?kiosk=1&token=<klíč>&motion=1` – Stark HUD, který nezhasne,
  v noci se ztlumí a bez pohybu před tabletem zhasne na pár procent.
