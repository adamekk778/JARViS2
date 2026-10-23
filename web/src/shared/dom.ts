export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, any> = {},
  ...children: (Node | string | null | undefined | false)[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children) if (c !== null && c !== undefined && c !== false) el.append(c);
  return el;
}

export const icon = (name: string, extra = "") => h("i", { class: `ph ph-${name} ${extra}`.trim(), "aria-hidden": "true" });

export function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} kB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

export function fmtTime(ts?: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" }) +
        " " + d.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
}

export function toast(text: string, kind: "info" | "error" | "ok" = "info", ms = 3500) {
  let host = document.getElementById("toasts");
  if (!host) {
    host = h("div", { id: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(host);
  }
  const t = h("div", { class: `toast toast-${kind}` }, icon(kind === "error" ? "warning-circle" : kind === "ok" ? "check-circle" : "info"), text);
  host.append(t);
  setTimeout(() => t.classList.add("out"), ms);
  setTimeout(() => t.remove(), ms + 400);
}

export const KIND_ICON: Record<string, string> = {
  image: "image", pdf: "file-pdf", office: "file-doc", text: "file-text", audio: "file-audio",
  video: "file-video", other: "file",
};

export const TOOL_ICON: Record<string, string> = {
  youtube_play: "youtube-logo", youtube_search: "youtube-logo", open_app: "rocket-launch", close_app: "x-square",
  web_search: "magnifying-glass", web_read: "article", google_search: "google-logo", open_url: "globe",
  weather: "cloud-sun", volume: "speaker-high", media_control: "play-pause", screenshot: "camera",
  system_power: "power", run_shell: "terminal-window", computer_use: "cursor-click", run_python: "code",
  generate_image: "paint-brush", set_timer: "timer", set_reminder: "alarm", find_file: "folder-open",
  open_file: "folder-open", remember: "brain", forget: "eraser", send_file: "paper-plane-tilt",
  send_to_phone: "device-mobile", create_skill: "wrench", schedule_task: "calendar-plus",
  system_info: "cpu", window_control: "app-window", clipboard_get: "clipboard", clipboard_set: "clipboard",
  update_setting: "sliders", browser_open: "browser", browser_act: "browser", get_time: "clock",
};
