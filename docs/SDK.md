# Dovednosti pro JARVISe – návod pro tvůrce

Dovednost (skill) je **jeden soubor Pythonu**, který JARVISovi přidá nové nástroje. JARVIS je pak sám používá, když
na ně narazí v požadavku („řekni vtip podle počasí v Brně“). Šablona: [`docs/sdk/pocasi_vtip.py`](sdk/pocasi_vtip.py).

## Jak vypadá
```python
from jarvis.tools.base import ToolResult, tool

SKILL = {"name": "pocasi_vtip", "description": "Řekne vtip podle počasí.", "version": "1.0",
         "permissions": ["network"], "timeout": 20}

@tool("weather_joke", "Řekne krátký vtip podle aktuálního počasí ve městě.")
async def weather_joke(ctx, city: str = "Praha") -> ToolResult:
    ...
    return ToolResult(True, "co JARVIS řekne", data={...})
```
- **`SKILL`** – název (malá písmena, číslice, `_`), popis, verze, **oprávnění** a časový limit.
- **`@tool(název, popis)`** – popis česky a konkrétně: podle něj AI pozná, kdy nástroj použít. Parametry s typy
  (`str`, `int`, `float`, `bool`, `list[str]`, `Literal[...]`) se samy převedou na schéma pro AI.
- **`ctx`** – `ctx.http()` (httpx klient), `ctx.platform` (ovládání PC), `ctx.store` (soubory a přílohy),
  `ctx.notify(titulek, text)`, `ctx.cfg` (nastavení, jen číst).
- **`ToolResult(ok, shrnutí, data=…, attachments=[…])`** – shrnutí je věta pro uživatele, `data` pro AI.

### Oprávnění
`apps`, `input` (myš a klávesnice), `screen`, `files_read`, `files_write`, `shell`, `network`, `system`.
Dovednost dostane jen ta, která uvede, a uživatel je vidí při schválení. Nástroje, které něco mění (mazání, platby,
zprávy), označ `danger=True` – JARVIS se pak pokaždé zeptá.

### Bezpečnost
- Dovednost běží v **odděleném procesu** s časovým limitem (`skill_runner.py`), ne uvnitř JARVISe.
- Uživatel vždy vidí a schvaluje **celý kód** (při `create_skill` i při instalaci balíčku).
- Obsah webů, e-mailů a souborů jsou pro AI **data, ne pokyny** – nepiš dovednost, která by text z webu vykonávala.

## Vyzkoušení
1. Ulož soubor do `%APPDATA%\JARVIS\skills\` (nebo řekni „nauč se dovednost…“ a vlož kód).
2. JARVIS ukáže kód ke schválení, po schválení se nástroj hned načte.
3. Napiš „řekni vtip podle počasí v Brně“.

## Sdílení: podepsané balíčky `.jarvisskill`
- „Zabal dovednost pocasi_vtip“ → soubor `.jarvisskill` (ZIP: kód, manifest, podpis **Ed25519** klíčem tvého PC).
- Kdo ho nainstaluje („nainstaluj dovednost ze souboru …“), uvidí autora, otisk jeho klíče, oprávnění a kód.
  Změněný soubor nebo nesedící podpis JARVIS odmítne. Autora lze označit jako důvěryhodného.
- **Katalog** je obyčejný JSON na webu (třeba v repozitáři na GitHubu), adresu přidáš v nastavení:
  ```json
  {"skills": [{"name": "Vtip podle počasí", "url": "https://…/pocasi_vtip.jarvisskill",
               "description": "Řekne vtip podle počasí.", "author": "Adam", "version": "1.0"}]}
  ```

## Alternativa: MCP server
Pro velké integrace (vlastní služba, jiný jazyk) napiš MCP server a přidej ho v Nastavení → Integrace.
Jeho nástroje spadají pod oprávnění Internet a nedůvěryhodné servery se ptají před každou akcí.
