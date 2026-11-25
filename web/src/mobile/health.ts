// 3.12 spánek a kroky z telefonu: with your yes in Android's Health Connect, the phone reads today's steps and last
// night's sleep and sends them to your PC, where they tick the Spánek and Kroky habits. 3.14 (návrh 42): with your
// watch too – Wear OS, Samsung, Pixel, Garmin Connect or Fitbit write into Health Connect – the resting heart rate,
// heart-rate variability, today's average heart rate and blood oxygen, for the morning "Stav systémů". Nothing is
// written, and it goes only to your own PC. Off until you press "Propojit"; each kind can be refused on its own.
import { registerPlugin } from "@capacitor/core";
import type { JarvisClient } from "../shared/ws";
import { native } from "./native";

const Health: any = native.isNative ? registerPlugin("Health") : null;
const KEY = "jarvis.health";
const READ = ["steps", "sleep", "restingHeartRate", "heartRateVariability", "heartRate", "oxygenSaturation"];
const load = (): { on?: boolean; last?: number; steps?: number; sleep?: number; rest_hr?: number; hrv?: number } => {
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
  const st = await Health.requestAuthorization({ read: READ });
  const ok = (st.readAuthorized || []) as string[];
  if (!ok.length) return "Bez povolení to nejde – v okně Health Connect zaškrtni Kroky, Spánek a Tep.";
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
  const since = new Date(now.getTime() - 24 * 3600 * 1000);
  const latest = async (type: string, from: Date): Promise<number | null> => {   // the newest reading (resting heart rate, oxygen)
    try {
      const r = await Health.readSamples({ dataType: type, startDate: iso(from), endDate: iso(now), limit: 50 });
      const s = (r.samples || []).filter((x: any) => Number.isFinite(Number(x.value)))
        .sort((a: any, b: any) => Date.parse(b.endDate) - Date.parse(a.endDate));
      return s.length ? Number(s[0].value) : null;
    } catch { return null; }                                                       // not allowed / no watch: skip it
  };
  const average = async (type: string, from: Date): Promise<number | null> => {
    try {
      const r = await Health.readSamples({ dataType: type, startDate: iso(from), endDate: iso(now), limit: 500 });
      const v = (r.samples || []).map((x: any) => Number(x.value)).filter((x: number) => Number.isFinite(x) && x > 0);
      return v.length ? Math.round((v.reduce((a: number, b: number) => a + b, 0) / v.length) * 10) / 10 : null;
    } catch { return null; }
  };
  const restHr = await latest("restingHeartRate", since);
  const hrv = await average("heartRateVariability", new Date(midnight.getTime() - 6 * 3600 * 1000));   // over the night
  let hr: number | null = null;
  try {
    const r = await Health.queryAggregated({ dataType: "heartRate", startDate: iso(midnight), endDate: iso(now), bucket: "day", aggregation: "average" });
    const s = (r.samples || [])[0];
    const v = Number(s?.value ?? s?.values?.average);
    hr = Number.isFinite(v) && v > 0 ? Math.round(v) : null;
  } catch { /* no heart rate */ }
  let spo2 = await latest("oxygenSaturation", since);
  if (spo2 != null && spo2 <= 1) spo2 = Math.round(spo2 * 1000) / 10;         // some watches report 0.97, others 97
  if (steps == null && sleepH == null && restHr == null && hrv == null) return;
  c.send("habit_health" as any, { day: ymd(now), steps, sleep_h: sleepH, rest_hr: restHr, hrv, hr, spo2 });
  save({ last: Date.now(), steps: steps ?? undefined, sleep: sleepH ?? undefined, rest_hr: restHr ?? undefined, hrv: hrv ?? undefined });
}
