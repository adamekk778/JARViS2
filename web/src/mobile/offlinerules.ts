// 3.20 (129) offline povely: the few things the phone does by itself when neither the PC nor the internet answers.
// Plain rules – no AI model; anything else gets an honest "this needs the PC or the internet".
export type Schedule = (title: string, body: string, at: Date) => void;
export interface OfflineAnswer { reply: string; run?: () => void | Promise<void> }

const NUM: Record<string, number> = { jednu: 1, jedna: 1, dve: 2, dva: 2, tri: 3, ctyri: 4, pet: 5, deset: 10, patnact: 15, dvacet: 20, tricet: 30, ctyricet: 40, padesat: 50, pul: 0.5 };

function fold(s: string): string {
  return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim();
}

function amount(t: string): number | null {
  const m = t.match(/(\d+(?:[.,]\d+)?)/);
  if (m) return Number(m[1].replace(",", "."));
  for (const [w, n] of Object.entries(NUM)) if (new RegExp(`\\b${w}\\b`).test(t)) return n;
  return null;
}

/** The few things the phone can do on its own. Anything else: an honest "this needs the PC or the internet". */
export function offlineRule(text: string, schedule: Schedule, now = new Date()): OfflineAnswer | null {
  const t = fold(text);
  if (/\b(casovac|minutk|odpocitej)/.test(t)) {
    const n = amount(t);
    if (!n) return { reply: "Na kolik minut? Třeba „časovač 10 minut“." };
    const secs = /\bsekund/.test(t) ? n : /\bhodin/.test(t) ? n * 3600 : n * 60;
    const at = new Date(now.getTime() + secs * 1000);
    return { reply: `Časovač na ${secs >= 60 ? `${Math.round(secs / 60)} min` : `${secs} s`} – ozvu se v ${at.toTimeString().slice(0, 5)}.`,
      run: () => schedule("⏲ Časovač", "Čas vypršel!", at) };
  }
  const alarm = t.match(/\b(?:budik|vzbud)\D*(\d{1,2})(?:[:.](\d{2}))?/);
  if (alarm) {
    const at = new Date(now);
    at.setHours(Number(alarm[1]), Number(alarm[2] || 0), 0, 0);
    if (at <= now) at.setDate(at.getDate() + 1);
    return { reply: `Budík na ${at.toTimeString().slice(0, 5)}${at.getDate() !== now.getDate() ? " zítra" : ""}.`,
      run: () => schedule("⏰ Budík", "Dobré ráno!", at) };
  }
  const remind = t.match(/^(?:pripomen|pripomenout)\w*\s+(?:mi\s+)?(?:za\s+)?(\S+)\s+(minut|hodin)\w*\s+(.+)$/);
  if (remind) {
    const n = amount(remind[1]) || 1;
    const at = new Date(now.getTime() + n * (remind[2] === "hodin" ? 3600 : 60) * 1000);
    // the words as you wrote them (with accents): fold() keeps one character per character, so the tail lines up
    const orig = text.replace(/\s+/g, " ").trim();
    const what = orig.length === t.length ? orig.slice(orig.length - remind[3].length) : remind[3];
    return { reply: `Připomenu: „${what}“ v ${at.toTimeString().slice(0, 5)}.`,
      run: () => schedule("Připomínka", what, at) };
  }
  if (/^(?:poznamk|zapis|poznamenej)/.test(t)) {
    const body = text.replace(/^\S+\s*(si\s+)?/i, "").trim();
    return { reply: body ? "Zapsáno – pošlu to JARVISovi na PC, až bude dostupné." : "Co si mám zapsat?" };
  }
  const call = t.match(/^(?:zavolej|vytoc)\s+(?:na\s+)?([+\d][\d ]{5,})$/);
  if (call) {
    const num = call[1].replace(/\s+/g, "");
    return { reply: `Vytáčím ${num}.`, run: () => { location.href = `tel:${num}`; } };
  }
  if (/\b(kolik je hodin|jaky je cas|cas\b)/.test(t)) return { reply: `Je ${now.toTimeString().slice(0, 5)}.` };
  if (/\b(jaky je dnes|kolikateho|datum)/.test(t)) {
    return { reply: `Dnes je ${now.toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" })}.` };
  }
  const calc = t.replace(/krat/g, "*").replace(/deleno/g, "/").replace(/plus/g, "+").replace(/minus/g, "-").replace(/,/g, ".");
  const expr = calc.match(/^(?:kolik je\s+)?([\d.\s+\-*/()]+)\??$/);
  if (expr && /[+\-*/]/.test(expr[1]) && /^[\d.\s+\-*/()]+$/.test(expr[1])) {
    const val = evalArith(expr[1]);
    if (val !== null) return { reply: `${expr[1].trim()} = ${Number(val.toFixed(6))}` };
  }
  return null;
}

/** + − × ÷ and brackets only (no eval). */
export function evalArith(src: string): number | null {
  if (!/^[\d.\s+\-*/()]+$/.test(src)) return null;          // numbers and + − × ÷ ( ) only
  const toks = src.match(/\d+(?:\.\d+)?|[+\-*/()]/g);
  if (!toks) return null;
  let i = 0;
  const peek = () => toks[i];
  const num = (): number => {
    const tk = toks[i++];
    if (tk === "(") { const v = sum(); if (toks[i++] !== ")") throw new Error("("); return v; }
    if (tk === "-") return -num();
    const v = Number(tk);
    if (Number.isNaN(v)) throw new Error("num");
    return v;
  };
  const prod = (): number => {
    let v = num();
    while (peek() === "*" || peek() === "/") { const op = toks[i++]; const r = num(); v = op === "*" ? v * r : v / r; }
    return v;
  };
  const sum = (): number => {
    let v = prod();
    while (peek() === "+" || peek() === "-") { const op = toks[i++]; const r = prod(); v = op === "+" ? v + r : v - r; }
    return v;
  };
  try {
    const v = sum();
    return i === toks.length && Number.isFinite(v) ? v : null;
  } catch { return null; }
}

