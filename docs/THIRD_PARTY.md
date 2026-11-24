# Cizí součásti a jejich licence

JARVIS používá několik knihoven třetích stran. Tady jsou ty, u kterých licence něco vyžaduje nebo které se stahují
až na tvůj pokyn.

## occt-import-js + Open CASCADE Technology (LGPL-2.1) – STEP v prohlížeči (3.17)

- Co dělá: v HUD převádí STEP soubory na 3D model, když na PC není FreeCAD.
- Verze: `occt-import-js` **0.0.23** (pevně v `web/package.json`), uvnitř Open CASCADE Technology zkompilované do
  WebAssembly.
- Licence: GNU LGPL 2.1 (Open CASCADE s výjimkou Open CASCADE). Plné texty jsou přibalené v aplikaci:
  `/licenses/occt-import-js-LGPL-2.1.txt` a `/licenses/opencascade-LGPL-2.1.txt` (ve zdrojích `web/public/licenses/`).
- Zdrojový kód: <https://github.com/kovacsv/occt-import-js> a <https://dev.opencascade.org/>.
- Jak je knihovna oddělená: JARVIS ji nikdy nemíchá do svého kódu. Po sestavení leží jako dva samostatné soubory
  (`assets/occt-import-js-*.js` a `assets/occt-import-js-*.wasm`), které HUD načte až ve chvíli, kdy otevřeš STEP.
- Jak ji vyměnit za jinou (např. vlastní) verzi: ve složce `web` spusť `npm install --save-exact occt-import-js@<verze>`
  (nebo `npm link` na vlastní build) a `npm run build`; JARVIS používá jen veřejnou funkci `ReadStepFile`
  (`web/src/hud/stepload.ts`).

## AndroidX Wear Tiles, ProtoLayout a Guava (Apache-2.0) – aplikace pro hodinky (3.18)

- `androidx.wear.tiles:tiles` **1.4.1**, `androidx.wear.protolayout` **1.2.1** a Guava (pevně v `mobile/wear/app/build.gradle`).
- Licence: Apache License 2.0 – <https://developer.android.com/jetpack/androidx> a <https://github.com/google/guava>.

## OrcaSlicer (AGPL-3.0) – krájení pro Bambu (3.18)

- JARVIS OrcaSlicer nepřibaluje: jen spustí program, který si sám nainstaluješ, jako samostatný proces z příkazové
  řádky (`core/jarvis/printer3d.py`, `slice_for_bambu`). Zdroj: <https://github.com/SoftFever/OrcaSlicer>.

## MediaPipe Tasks Vision + Hand Landmarker (Apache-2.0) – gesta prsty (3.17)

- `@mediapipe/tasks-vision` **1.2.3** (npm) a model `hand_landmarker.task` (float16, verze 1).
- Model a jeho WebAssembly se stáhnou až po tvém kliknutí v Nastavení; každý soubor se ověří velikostí a SHA-256
  (`core/jarvis/handmodel.py`). Obraz z kamery neopouští PC.
- Licence: Apache License 2.0 – <https://github.com/google-ai-edge/mediapipe>.

## three.js (MIT) – 3D v HUD

- `three` **0.187.0** – <https://github.com/mrdoob/three.js>.
