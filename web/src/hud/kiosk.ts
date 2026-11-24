// 3.14 Nástěnný displej (návrh 22): the Stark HUD on a tablet or a TV in the room, always on –
//   http://<PC>:8765/hud?kiosk=1&token=<klíč telefonu>[&motion=1]
// The screen stays awake (Wake Lock), dims at night, and with motion=1 the tablet's own camera only checks whether
// something moves in front of it (a few tiny frames compared, nothing stored or sent): nobody around for 5 minutes →
// dimmed to a glow; someone walks by → full brightness again. The close button is hidden (it is not a PC window).

const DIM_AFTER_MS = 5 * 60 * 1000;

export function kioskMode(root: HTMLElement): boolean {
  const q = new URLSearchParams(location.search);
  if (q.get("kiosk") !== "1") return false;
  document.documentElement.classList.add("kiosk");
  let lastMotion = Date.now();
  const paint = () => {
    const h = new Date().getHours();
    const night = h >= 23 || h < 6;
    const idle = Date.now() - lastMotion > DIM_AFTER_MS;
    root.style.transition = "filter 1.2s ease";
    root.style.filter = idle ? "brightness(.12)" : night ? "brightness(.45)" : "";
  };
  // keep the screen on
  const nav: any = navigator;
  let lock: any = null;
  const wake = async () => { try { lock = await nav.wakeLock?.request("screen"); } catch { /* not allowed: fine */ } };
  void wake();
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && !lock) void wake(); });
  // a touch counts as someone being there
  for (const ev of ["pointerdown", "keydown"]) window.addEventListener(ev, () => { lastMotion = Date.now(); paint(); });
  if (q.get("motion") === "1") void watchMotion(() => { lastMotion = Date.now(); paint(); });
  setInterval(paint, 15000);
  paint();
  return true;
}

/** Compares tiny grey frames from the device camera twice a second; calls `seen` when enough pixels change. */
async function watchMotion(seen: () => void): Promise<void> {
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 160, height: 120, facingMode: "user" }, audio: false });
  } catch {
    return;                                             // no camera or not allowed: dimming by touch only
  }
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.srcObject = stream;
  await video.play().catch(() => undefined);
  const c = document.createElement("canvas");
  c.width = 64; c.height = 48;
  const g = c.getContext("2d", { willReadFrequently: true });
  if (!g) return;
  let prev: Uint8ClampedArray | null = null;
  setInterval(() => {
    g.drawImage(video, 0, 0, c.width, c.height);
    const px = g.getImageData(0, 0, c.width, c.height).data;
    if (prev) {
      let changed = 0;
      for (let i = 0; i < px.length; i += 4) {
        const a = (px[i] + px[i + 1] + px[i + 2]) / 3, b = (prev[i] + prev[i + 1] + prev[i + 2]) / 3;
        if (Math.abs(a - b) > 28) changed++;
      }
      if (changed > (c.width * c.height) * 0.04) seen();
    }
    prev = new Uint8ClampedArray(px);
  }, 500);
}
