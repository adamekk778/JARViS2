// 3.20 (129) offline povely – the rules the phone runs on its own (no AI).
import assert from "node:assert/strict";
import { test } from "node:test";
import { evalArith, offlineRule } from "../../src/mobile/offlinerules.ts";

const now = new Date(2026, 10, 25, 22, 0, 0);

test("timers, alarms and reminders are scheduled on the phone", () => {
  const got: [string, string, Date][] = [];
  const sched = (t: string, b: string, at: Date) => { got.push([t, b, at]); };
  const a = offlineRule("Časovač 10 minut", sched, now)!;
  assert.match(a.reply, /10 min/);
  a.run!();
  assert.equal(got[0][2].getTime() - now.getTime(), 600_000);
  const b = offlineRule("budík na 6:30", sched, now)!;
  assert.match(b.reply, /06:30 zítra/);
  b.run!();
  assert.equal(got[1][2].getHours(), 6);
  assert.equal(got[1][2].getDate(), 26);
  const r = offlineRule("připomeň mi za 2 hodiny zalít kytky", sched, now)!;
  r.run!();
  assert.equal(got[2][1], "zalít kytky");
  assert.equal(got[2][2].getTime() - now.getTime(), 2 * 3600_000);
  assert.match(offlineRule("minutka", sched, now)!.reply, /Na kolik/);
  assert.match(offlineRule("časovač pět minut", sched, now)!.reply, /5 min/);
});

test("time, date, calculations, calls and notes", () => {
  const none = () => {};
  assert.equal(offlineRule("kolik je hodin", none, now)!.reply, "Je 22:00.");
  assert.match(offlineRule("jaký je dnes den", none, now)!.reply, /listopadu/);
  assert.equal(offlineRule("kolik je 12 krát 3 plus 4", none, now)!.reply, "12 * 3 + 4 = 40");
  assert.equal(offlineRule("(2+3)*4", none, now)!.reply, "(2+3)*4 = 20");
  assert.equal(offlineRule("zavolej 777 123 456", none, now)!.reply, "Vytáčím 777123456.");
  assert.match(offlineRule("poznámka koupit mléko", none, now)!.reply, /Zapsáno/);
  assert.equal(offlineRule("napiš mi básničku o podzimu", none, now), null);   // needs a real AI
});

test("the calculator never evaluates code", () => {
  assert.equal(evalArith("2+2*2"), 6);
  assert.equal(evalArith("10/4"), 2.5);
  assert.equal(evalArith("-(3+1)"), -4);
  assert.equal(evalArith("2+"), null);
  assert.equal(evalArith("1/0"), null);
  assert.equal(evalArith("alert(1)"), null);
});
