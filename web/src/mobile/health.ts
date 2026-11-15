// 3.12 spánek a kroky z telefonu: with your yes in Android's Health Connect, the phone reads today's steps and last
// night's sleep and sends them to your PC, where they tick the Spánek and Kroky habits. Nothing else is read, nothing
// is written, and it goes only to your own PC. Off until you press "Propojit".
import { registerPlugin } from "@capacitor/core";
import type { JarvisClient } from "../shared/ws";
import { native } from "./native";

const Health: any = native.isNative ? registerPlugin("Health") : null;
const KEY = "jarvis.health";
const load = (): { on?: boolean; last?: number; steps?: number; sleep?: number } => {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch { return {}; }
};
const save = (v: object) => { try { localStorage.setItem(KEY, JSON.stringify({ ...load(), ...v })); } catch { /* full */ } };

export const healthSupported = () => !!Health;
export const healthState = () => load();

export async function healthConnect(): Promise<string> {
  if (!Health) return "Tohle jde jen v aplikaci JARVIS v telefonu s Androidem.";
  const a = await Health.isAvailable().catch(() => ({ available: false }));
  if (!a.available) {
    await Health.openHealthConnectSettings?.().catch(() => {});
    return "V telefonu chybí Health Connect – nainstaluj „Health Connect“ z Obchodu Play (na Androidu 14+ už je) a zkus to znovu.";
  }
  const st = await Health.requestAuthorization({ read: ["steps", "sleep"] });
  const ok = (st.readAuthorized || []) as string[];
  if (!ok.length) return "Bez povolení to nejde – v okně Health Connect zaškrtni Kroky a Spánek.";
  save({ on: true });
  return "";
}

export function healthOff() { save({ on: false }); }

const iso = (d: Date) => d.toISOString();
const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Read today's steps and last night's sleep and send them to the PC (when on and connected). */
export async function healthSync(c: JarvisClient, force = false): Promise<void> {
  const st = load();
  if (!Health || !st.on || c.status !== "open") return;
  if (!force && st.last && Date.now() - st.last < 10 * 60 * 1000) return;
  const now = new Date();
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  let steps: number | null = null, sleepH: number | null = null;
  try {
    const r = await Health.queryAggregated({ dataType: "steps", startDate: iso(midnight), endDate: iso(now), bucket: "day", aggregation: "sum" });
    steps = (r.samples || []).reduce((a: number, s: any) => a + (Number(s.value) || 0), 0);
  } catch { /* no steps permission */ }
  try {
    const from = new Date(midnight.getTime() - 6 * 3600 * 1000);          // last night: from 18:00 yesterday
    const r = await Health.readSamples({ dataType: "sleep", startDate: iso(from), endDate: iso(now), limit: 60 });
    let min = 0;
    for (const s of r.samples || []) {
      if (Array.isArray(s.stages) && s.stages.length) {
        for (const g of s.stages) if (g.stage !== "awake" && g.stage !== "inBed") min += Number(g.durationMinutes) || 0;
      } else if (s.sleepState !== "awake" && s.sleepState !== "inBed") {
        min += Math.max(0, (Date.parse(s.endDate) - Date.parse(s.startDate)) / 60000);
      }
    }
    sleepH = min > 0 ? Math.round((min / 60) * 10) / 10 : null;
  } catch { /* no sleep permission */ }
  if (steps == null && sleepH == null) return;
  c.send("habit_health" as any, { day: ymd(now), steps, sleep_h: sleepH });
  save({ last: Date.now(), steps: steps ?? undefined, sleep: sleepH ?? undefined });
}
