import type { Endpoint } from "../shared/ws";

export interface Pairing {
  hosts: string[];
  port: number;
  token: string;
  last?: string; // last host that worked
}

const KEY = "jarvis.pairing";

export function loadPairing(): Pairing | null {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) || "null");
    return p && p.token && p.hosts?.length ? p : null;
  } catch {
    return null;
  }
}

export function savePairing(p: Pairing | null) {
  try {
    if (p) localStorage.setItem(KEY, JSON.stringify(p));
    else localStorage.removeItem(KEY);
  } catch { /* private mode */ }
}

/** Accepts the QR url (http://ip:8765/mobile#token=..&hosts=..&port=..), a jarvis:// link or "ip:port token". */
export function parsePairing(text: string): Pairing | null {
  text = text.trim();
  try {
    const u = new URL(text.replace(/^jarvis:\/\/pair/, "http://x/pair"));
    const frag = new URLSearchParams(u.hash.slice(1) || u.search.slice(1));
    const token = frag.get("token");
    if (token) {
      const hosts = (frag.get("hosts") || "").split(",").filter(Boolean);
      const port = Number(frag.get("port")) || Number(u.port) || 8765;
      if (u.hostname && u.hostname !== "x" && !hosts.includes(u.hostname)) hosts.unshift(u.hostname);
      return { hosts, port, token };
    }
  } catch { /* not a url */ }
  const m = text.match(/^([\w.-]+)(?::(\d+))?\s+(\S{16,})$/);
  if (m) return { hosts: [m[1]], port: Number(m[2]) || 8765, token: m[3] };
  return null;
}

async function healthy(base: string, ms = 2500): Promise<boolean> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(`${base}/api/health`, { signal: ctl.signal, cache: "no-store" });
    return r.ok && (await r.json()).name === "JARVIS";
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
}

/** Try last working host first, then LAN, then Tailscale. */
export async function resolveEndpoint(p: Pairing): Promise<Endpoint | null> {
  const order = [...new Set([p.last, ...p.hosts].filter(Boolean) as string[])];
  const results = await Promise.all(order.map(async (host) => ((await healthy(`http://${host}:${p.port}`)) ? host : null)));
  const host = results.find(Boolean);
  if (!host) return null;
  if (host !== p.last) savePairing({ ...p, last: host });
  return { base: `http://${host}:${p.port}`, token: p.token };
}
