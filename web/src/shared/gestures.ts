// OMEGA 188 / 493: hand gestures through the PC camera – only when the user turns it on, always with a visible
// indicator, nothing stored or sent anywhere. No model to download: tiny grey frames, the difference between
// them is the moving hand, and the path of its centre is the gesture (swipe left / right / up / down, wave).
export type Gesture = "left" | "right" | "up" | "down" | "wave";

const W = 64, H = 48;

export interface GestureOptions {
  onGesture: (g: Gesture) => void;
  onState?: (on: boolean, error?: string) => void;
  mirrored?: boolean;            // the camera shows you as in a mirror: your right is the image's left
}

/** Pure detector (also used by the tests): feed it motion centroids, it answers a gesture or null. */
export class SwipeDetector {
  private track: { x: number; y: number; t: number }[] = [];
  private last = 0;
  constructor(private cooldown = 1100) {}

  push(x: number | null, y: number | null, t: number): Gesture | null {
    if (x == null || y == null) {                     // no movement: the stroke ended – decide now
      const g = this.decide(t);
      this.track = [];
      return g;
    }
    this.track.push({ x, y, t });
    this.track = this.track.filter((p) => t - p.t <= 900);
    return null;
  }

  private decide(t: number): Gesture | null {
    const tr = this.track;
    if (tr.length < 4 || t - this.last < this.cooldown) return null;
    const dx = tr[tr.length - 1].x - tr[0].x, dy = tr[tr.length - 1].y - tr[0].y;
    let turns = 0;
    for (let i = 2; i < tr.length; i++) {
      const a = tr[i - 1].x - tr[i - 2].x, b = tr[i].x - tr[i - 1].x;
      if (Math.abs(a) > 0.03 && Math.abs(b) > 0.03 && Math.sign(a) !== Math.sign(b)) turns++;
    }
    let g: Gesture | null = null;
    if (turns >= 3) g = "wave";
    else if (Math.abs(dx) > 0.35 && Math.abs(dx) > Math.abs(dy) * 1.5) g = dx > 0 ? "right" : "left";
    else if (Math.abs(dy) > 0.35 && Math.abs(dy) > Math.abs(dx) * 1.5) g = dy > 0 ? "down" : "up";
    if (g) this.last = t;
    return g;
  }
}

/** Where the picture moved between two grey frames: centre (0–1) and how much moved (share of pixels). */
export function motionCentroid(prev: Uint8ClampedArray, cur: Uint8ClampedArray, w = W, h = H, thr = 28): { x: number; y: number; mass: number } {
  let sx = 0, sy = 0, n = 0;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    if (Math.abs(cur[i] - prev[i]) > thr) { sx += x; sy += y; n++; }
  }
  return n ? { x: sx / n / w, y: sy / n / h, mass: n / (w * h) } : { x: 0, y: 0, mass: 0 };
}

export class GestureCam {
  private stream: MediaStream | null = null;
  private timer = 0;
  private prev: Uint8ClampedArray | null = null;
  private det = new SwipeDetector();
  constructor(private opt: GestureOptions) {}

  get on() { return !!this.stream; }

  async start() {
    if (this.stream) return;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video: { width: 160, height: 120, frameRate: 15 }, audio: false });
    } catch (e: any) {
      this.opt.onState?.(false, e?.name === "NotAllowedError" ? "Kamera není povolená" : "Kameru se nepodařilo zapnout");
      return;
    }
    const video = document.createElement("video");
    video.muted = true; video.playsInline = true; video.srcObject = this.stream;
    await video.play().catch(() => {});
    const canvas = document.createElement("canvas");
    canvas.width = W; canvas.height = H;
    const g = canvas.getContext("2d", { willReadFrequently: true })!;
    this.opt.onState?.(true);
    this.timer = window.setInterval(() => {
      g.drawImage(video, 0, 0, W, H);
      const rgba = g.getImageData(0, 0, W, H).data;
      const grey = new Uint8ClampedArray(W * H);
      for (let i = 0; i < W * H; i++) grey[i] = (rgba[i * 4] * 77 + rgba[i * 4 + 1] * 150 + rgba[i * 4 + 2] * 29) >> 8;
      if (this.prev) {
        const m = motionCentroid(this.prev, grey);
        const moving = m.mass > 0.02 && m.mass < 0.6;      // a hand, not the whole picture (light change, camera moved)
        const x = this.opt.mirrored === false ? m.x : 1 - m.x;
        const ges = this.det.push(moving ? x : null, moving ? m.y : null, performance.now());
        if (ges) this.opt.onGesture(ges);
      }
      this.prev = grey;
    }, 66);
  }

  stop() {
    window.clearInterval(this.timer);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.prev = null;
    this.opt.onState?.(false);
  }
}

export const GESTURE_LABEL: Record<Gesture, string> = { left: "Předchozí", right: "Další", up: "Hlasitěji", down: "Tišeji", wave: "Play / pauza" };
