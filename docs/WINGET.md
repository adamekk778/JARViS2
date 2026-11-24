# JARVIS ve winget (Správce balíčků Windows)

Každé stabilní vydání má v příloze `winget-manifests.zip` – tři soubory, které winget potřebuje (verze, instalátor
s SHA-256, popis). Generuje je `packaging/winget/make_manifest.py` v jobu `release`.

## Jednorázově: dostat JARVIS do veřejného katalogu

Do katalogu se balíček dostane pull requestem do [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs).
To musí udělat člověk s GitHub účtem (správce repozitáře):

1. Stáhni `winget-manifests.zip` z posledního vydání a rozbal ho.
2. Ve svém forku `winget-pkgs` vytvoř složku `manifests/a/adamekk778/JARVIS/<verze>/` a vlož do ní ty tři soubory.
3. Ověř je lokálně: `winget validate --manifest <složka>` a `winget install --manifest <složka>`.
4. Otevři pull request. Po schválení stačí uživatelům `winget install adamekk778.JARVIS`.

Další verze jdou stejně (nebo nástrojem `wingetcreate update adamekk778.JARVIS --version <verze> --urls <odkaz na Setup>`).

Pozn.: Instalátor bez podpisu kódu (viz `docs/SIGNING.md`) projde, ale SmartScreen při instalaci varuje.
