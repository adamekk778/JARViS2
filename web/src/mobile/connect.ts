import type { Endpoint } from "../shared/ws";
import { native } from "./native";

export interface Pairing {
  hosts: string[];
  port: number;
  token: string;
  last?: string; // last host that worked
  link?: LinkInfo; // 3.12 JARVIS Link: how to reach the PC from outside (learnt at home over the paired connection)
}

export interface LinkInfo { enabled: boolean; fp?: string; direct?: { host: string; port: number; kind: string }[]; relay?: { host: string; port: number } | null; at?: number }

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

/** Try last working host first, then LAN (and Tailscale if you use it); away from home: our own JARVIS Link. */
export async function resolveEndpoint(p: Pairing): Promise<Endpoint | null> {
  const order = [...new Set([p.last, ...p.hosts].filter(Boolean) as string[])];
  const results = await Promise.all(order.map(async (host) => ((await healthy(`http://${host}:${p.port}`)) ? host : null)));
  const host = results.find(Boolean);
  if (host) {
    if (host !== p.last) savePairing({ ...p, last: host });
    return { base: `http://${host}:${p.port}`, token: p.token };
  }
  if (p.link?.enabled && native.phone.available) {
    try {
      const r = await native.phone.linkStart();
      if (r.ok && (await healthy(r.base, 16000))) return { base: r.base, token: p.token, via: "link" } as Endpoint;
    } catch { /* an older app without the tunnel */ }
  }
  return null;
}

/** 3.12 at home (or anywhere connected): learn / refresh how to reach this PC from outside. */
export async function refreshLink(ep: Endpoint, p: Pairing): Promise<Pairing> {
  try {
    const r = await fetch(`${ep.base}/api/link/info`, { headers: { Authorization: `Bearer ${ep.token}` }, cache: "no-store" });
    if (!r.ok) return p;
    const info: LinkInfo = await r.json();
    const next = { ...p, link: info.enabled ? info : undefined };
    savePairing(next);
    if (native.phone.available) await native.phone.configure({ link: info.enabled ? JSON.stringify(info) : "" }).catch(() => {});
    return next;
  } catch {
    return p;
  }
}
