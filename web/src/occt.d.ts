// 3.17 occt-import-js (LGPL-2.1) ships no types: the one call JARVIS uses (stepload.ts).
declare module "occt-import-js" {
  const init: (opts?: { locateFile?: (path: string) => string }) => Promise<unknown>;
  export default init;
}
