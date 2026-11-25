// 3.20 (487): the Czech texts of the UI and their English translations for the translators' page (/translate).
// Reads the EN dictionary from src/shared/i18n.ts and writes public/i18n-keys.json and public/i18n-en.json.
import { readFileSync, writeFileSync } from "node:fs";

const src = readFileSync(new URL("../src/shared/i18n.ts", import.meta.url), "utf8");
const start = src.indexOf("const EN: Record<string, string> = {");
const end = src.indexOf("\n};", start);
const body = src.slice(start, end);
const pairs = {};
const rx = /"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"/g;
let m;
while ((m = rx.exec(body))) pairs[JSON.parse(`"${m[1]}"`)] = JSON.parse(`"${m[2]}"`);
writeFileSync(new URL("../public/i18n-keys.json", import.meta.url), JSON.stringify(Object.keys(pairs)));
writeFileSync(new URL("../public/i18n-en.json", import.meta.url), JSON.stringify(pairs));
console.log(`i18n: ${Object.keys(pairs).length} texts`);
