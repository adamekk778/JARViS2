// OMEGA 725 / 418: what you write or say while the phone cannot reach the PC is kept on the phone (also over an app
// restart) and sent in order once the PC answers again – JARVIS is told when it was said.
import type { ClientType } from "../shared/protocol";
import type { JarvisClient } from "../shared/ws";

const KEY = "jarvis.outbox";
const PERSIST = new Set<string>(["user_text", "list_update", "pin_add"]);
export const MAX_OUTBOX = 50;

export interface Queued { type: string; data: Record<string, unknown> }

export function loadOutbox(): Queued[] {
  try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; }
}
function saveOutbox(q: Queued[]) {
  try { localStorage.setItem(KEY, JSON.stringify(q.slice(-MAX_OUTBOX))); } catch { /* full or private */ }
}

// ---- voice notes recorded offline: kept in IndexedDB (blobs do not fit localStorage) ----
const DB = "jarvis-offline", STORE = "voice";
function idb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { autoIncrement: true });
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}
export async function keepVoice(blob: Blob, name: string): Promise<void> {
  const db = await idb();
  await new Promise<void>((res, rej) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).add({ blob, name, at: Date.now() / 1000 });
    tx.oncomplete = () => res();
    tx.onerror = () => rej(tx.error);
  });
}
async function takeVoices(): Promise<{ key: IDBValidKey; blob: Blob; name: string; at: number }[]> {
  const db = await idb();
  return new Promise((res, rej) => {
    const out: any[] = [];
    const tx = db.transaction(STORE, "readonly");
    const cur = tx.objectStore(STORE).openCursor();
    cur.onsuccess = () => {
      const c = cur.result;
      if (c) { out.push({ key: c.key, ...c.value }); c.continue(); } else res(out);
    };
    cur.onerror = () => rej(cur.error);
  });
}
async function dropVoice(key: IDBValidKey) {
  const db = await idb();
  db.transaction(STORE, "readwrite").objectStore(STORE).delete(key);
}

/** Make `c.send` keep chosen messages on the phone while offline; returns how many wait. */
export function persistentOutbox(c: JarvisClient, onChange: (waiting: number) => void) {
  const send = c.send.bind(c);
  let flushing = false;
  c.send = (type: ClientType, data: Record<string, unknown> = {}) => {
    if (c.status !== "open" && PERSIST.has(type)) {
      const q = loadOutbox();
      q.push({ type, data: { ...data, queued_at: Date.now() / 1000 } });
      saveOutbox(q);
      onChange(q.length);
      return;
    }
    send(type, data);
  };
  const flush = async () => {
    if (flushing || c.status !== "open") return;
    flushing = true;
    try {
      const q = loadOutbox();
      saveOutbox([]);
      for (const m of q) send(m.type as ClientType, m.data);
      for (const v of await takeVoices().catch(() => [])) {
        try {
          const att = await c.upload(v.blob, v.name);
          send("voice_upload", { attachment_id: att.id });
          await dropVoice(v.key);
        } catch { break; }      // PC gone again: try the rest next time
      }
    } finally {
      flushing = false;
      onChange(loadOutbox().length);
    }
  };
  c.onStatus((s) => { if (s === "open") window.setTimeout(flush, 600); });
  onChange(loadOutbox().length);
  return { flush };
}
