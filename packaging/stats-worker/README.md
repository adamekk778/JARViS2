# Anonymní statistiky JARVISe – sběrný server

JARVIS posílá statistiky **jen když je uživatel zapne** (Bezpečí a soukromí → Anonymní statistiky) **a** zadá adresu
serveru. Bez adresy neodejde nic. Co přesně se posílá, ukáže tlačítko „Ukázat“ v aplikaci (viz `core/jarvis/stats.py`).

Tenhle Worker ukládá jen součty za týden (instalace, verze, systém, jazyk, použití a chyby vestavěných nástrojů).
IP adresa ani nic jiného o odesílateli se neukládá.

## Spuštění (Cloudflare Workers, zdarma)

```bash
npm create cloudflare@latest jarvis-stats -- --type hello-world
```

1. Obsah `worker.js` vlož do `src/index.js`.
2. Vytvoř KV namespace a navaž ho jako `STATS` (v `wrangler.toml`: `[[kv_namespaces]] binding = "STATS" id = "…"`).
3. `npx wrangler deploy` – dostaneš adresu `https://jarvis-stats.<účet>.workers.dev`.
4. Tu adresu dej do výchozího nastavení (`privacy.stats_url` v `core/jarvis/config.py`) nebo ji uživatelé zadají sami.

Souhrn týdne: `GET https://…/week`.
