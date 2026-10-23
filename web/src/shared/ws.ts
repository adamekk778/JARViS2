import type { Attachment, ClientType, ServerMsg, ServerType } from "./protocol";

export interface Endpoint {
  base: string; // http://host:port (no trailing slash)
  token: string;
}

type Handler = (m: ServerMsg) => void;
export type ConnStatus = "connecting" | "open" | "closed";

export class JarvisClient {
  private ws: WebSocket | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private statusHandlers = new Set<(s: ConnStatus) => void>();
  private retry = 0;
  private timer: number | undefined;
  private closedByUser = false;
  private queue: string[] = [];
  status: ConnStatus = "closed";
  local = false;

  constructor(public ep: Endpoint, private client: "dashboard" | "notch" | "mobile", private name = "") {}

  on(type: ServerType | "*", h: Handler): () => void {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set());
    this.handlers.get(type)!.add(h);
    return () => this.handlers.get(type)!.delete(h);
  }

  onStatus(h: (s: ConnStatus) => void): () => void {
    this.statusHandlers.add(h);
    h(this.status);
    return () => this.statusHandlers.delete(h);
  }

  private setStatus(s: ConnStatus) {
    this.status = s;
    this.statusHandlers.forEach((h) => h(s));
  }

  connect() {
    this.closedByUser = false;
    clearTimeout(this.timer);
    const wsBase = this.ep.base.replace(/^http/, "ws");
    const url = `${wsBase}/ws${this.ep.token ? `?token=${encodeURIComponent(this.ep.token)}` : ""}`;
    this.setStatus("connecting");
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      ws.send(JSON.stringify({ type: "hello", client: this.client, name: this.name }));
      this.setStatus("open");
      for (const q of this.queue.splice(0)) ws.send(q);
    };
    ws.onmessage = (ev) => {
      let m: ServerMsg;
      try {
        m = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (m.type === "welcome") this.local = !!m.local;
      this.handlers.get(m.type)?.forEach((h) => h(m));
      this.handlers.get("*")?.forEach((h) => h(m));
    };
    ws.onclose = (ev) => {
      if (this.ws !== ws) return;
      this.setStatus("closed");
      if (ev.code === 4401) {
        this.handlers.get("error")?.forEach((h) => h({ type: "error", message: "Neplatný token. Spáruj telefon znovu.", auth: true }));
        return;
      }
      if (!this.closedByUser) {
        const delay = Math.min(10000, 500 * 2 ** this.retry++);
        this.timer = window.setTimeout(() => this.connect(), delay);
      }
    };
    ws.onerror = () => ws.close();
  }

  close() {
    this.closedByUser = true;
    clearTimeout(this.timer);
    this.ws?.close();
  }

  send(type: ClientType, data: Record<string, unknown> = {}) {
    const payload = JSON.stringify({ type, ...data });
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(payload);
    else if (type !== "ping") this.queue.push(payload);
  }

  url(path: string, download = false): string {
    if (!path) return "";
    if (/^https?:/.test(path)) return path;
    const q: string[] = [];
    if (this.ep.token) q.push(`token=${encodeURIComponent(this.ep.token)}`);
    if (download) q.push("download=1");
    return `${this.ep.base}${path}${q.length ? (path.includes("?") ? "&" : "?") + q.join("&") : ""}`;
  }

  async upload(file: Blob, name?: string, onProgress?: (p: number) => void): Promise<Attachment> {
    const fd = new FormData();
    fd.append("file", file, name || (file as File).name || "soubor");
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${this.ep.base}/api/upload`);
      if (this.ep.token) xhr.setRequestHeader("Authorization", `Bearer ${this.ep.token}`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
        else {
          let msg = `Nahrání selhalo (${xhr.status})`;
          try {
            msg = JSON.parse(xhr.responseText).detail || msg;
          } catch {}
          reject(new Error(msg));
        }
      };
      xhr.onerror = () => reject(new Error("Nahrání selhalo, PC není dostupné"));
      xhr.send(fd);
    });
  }
}

export function localEndpoint(): Endpoint {
  return { base: location.origin.startsWith("http") ? location.origin : "http://127.0.0.1:8765", token: "" };
}
