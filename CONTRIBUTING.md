# Jak přispět do JARVISe

Díky, že chceš pomoct. Tady je, jak na to.

## Nápady a chyby

- **Nápad:** nové issue podle šablony „Nápad“. Hlasuje se 👍 reakcí na issue – podle počtu 👍 se řadí veřejná roadmapa
  (`packaging/roadmap_votes.py`).
- **Chyba:** issue podle šablony „Chyba“. Nejvíc pomůže výpis z Diagnostiky (Nastavení → Diagnostika → Zkopírovat).
- **Bezpečnost:** nikdy veřejně – viz [SECURITY.md](SECURITY.md).

## Kód

1. Jádro je v `core/` (Python 3.11+), rozhraní ve `web/` (TypeScript), telefon v `mobile/`.
2. Před pull requestem musí projít:

   ```
   cd core && ruff check jarvis tests && python -m pytest -q && python -m jarvis.evals
   cd web && npx tsc --noEmit && npx eslint src --quiet && npm test
   ```

3. Nový nástroj: `@tool(...)` v `core/jarvis/tools/`, test v `core/tests/`. Akce, která něco odesílá, maže nebo platí,
   musí mít `danger` / `danger_if` (zeptá se uživatele).
4. Texty pro uživatele jsou česky, komentáře v kódu anglicky.
5. Žádné cizí značky, postavy ani grafika z filmů – všechno je vlastní.

## Překlady

Rozhraní přeložíš na stránce `/translate` ve svém JARVISovi (Nastavení → Vzhled → Přístupnost → Překlad rozhraní).
Hotový soubor (`sk.json`, `de.json`, `pl.json`, `uk.json`) pošli jako pull request do `core/jarvis/i18npacks.py`
nebo přilož k issue.

## Licence

O licenci projektu rozhoduje autor; dokud není v repozitáři soubor LICENSE, platí, že kód je jeho (proprietární).
Posláním pull requestu souhlasíš, že tvůj příspěvek může být součástí JARVISe pod licencí, kterou autor zvolí.
