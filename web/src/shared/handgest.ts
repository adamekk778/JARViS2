// 3.17 Gesta prsty (návrh 11): the hand model (MediaPipe Hand Landmarker – 21 points of the hand, on this PC) reads
// what your fingers do instead of just where the hand moves:
//   • pinch (thumb + index together) and move up / down  → zoom in / out
//   • open hand moved left / right                       → turn (the 3D model, the globe) by as much as you move
//   • a fist held for a moment                           → take the model apart / put it together (else play/pause)
// The model and its engine come from JARVIS (/api/hands/…, downloaded once after your click); the picture stays here.

export type Pt = { x: number; y: number; z?: number };
export type FingerEvent = { type: "rotate"; deg: number } | { type: "zoom"; factor: number } | { type: "fist" };

const d = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y);

/** Which fingers are stretched out (index, middle, ring, little): the tip is farther from the wrist than its middle joint. */
export function extended(lm: Pt[]): boolean[] {
  return [[8, 6], [12, 10], [16, 14], [20, 18]].map(([tip, pip]) => d(lm[tip], lm[0]) > d(lm[pip], lm[0]) * 1.08);
}

export function pinching(lm: Pt[]): boolean {
  const size = d(lm[0], lm[9]) || 1;
  return d(lm[4], lm[8]) / size < 0.35;
}

/** Pure: feed it the hand's points each frame (null = no hand), it answers what the fingers did. */
export class HandReader {
  private pinchY: number | null = null;
  private palmX: number | null = null;
  private fistSince: number | null = null;
  private lastFist = -Infinity;
  private acc = 0;

  push(lm: Pt[] | null, t: number): FingerEvent | null {
    if (!lm || lm.length < 21) { this.pinchY = this.palmX = null; this.fistSince = null; return null; }
    const ext = extended(lm);
    const n = ext.filter(Boolean).length;
    const palm = { x: (lm[0].x + lm[9].x) / 2, y: (lm[0].y + lm[9].y) / 2 };
    // a fist: no finger out, held 0.4 s, at most every 1.5 s
    if (n === 0 && !pinching(lm)) {
      this.pinchY = this.palmX = null;
      if (this.fistSince === null) this.fistSince = t;
      if (t - this.fistSince > 400 && t - this.lastFist > 1500) { this.lastFist = t; this.fistSince = null; return { type: "fist" }; }
      return null;
    }
    this.fistSince = null;
    // pinch + up / down: zoom (up = closer)
    if (pinching(lm)) {
      this.palmX = null;
      const y = (lm[4].y + lm[8].y) / 2;
      if (this.pinchY === null) { this.pinchY = y; return null; }
      const dy = this.pinchY - y;
      if (Math.abs(dy) > 0.03) { this.pinchY = y; return { type: "zoom", factor: Math.round(Math.exp(dy * 3) * 1000) / 1000 }; }
      return null;
    }
    this.pinchY = null;
    // an open hand moving sideways: turn
    if (n >= 3) {
      if (this.palmX === null) { this.palmX = palm.x; this.acc = 0; return null; }
      this.acc += (palm.x - this.palmX) * 360;
      this.palmX = palm.x;
      if (Math.abs(this.acc) >= 6) { const deg = Math.round(this.acc); this.acc = 0; return { type: "rotate", deg }; }
      return null;
    }
    this.palmX = null;
    return null;
  }
}

export type FingerOptions = { base: string; onEvent: (e: FingerEvent) => void; onState?: (on: boolean, error?: string) => void };

export class FingerCam {
  private stream: MediaStream | null = null;
  private timer = 0;
  private reader = new HandReader();
  private landmarker: any = null;
  private opt: FingerOptions;
  constructor(opt: FingerOptions) { this.opt = opt; }

  get on() { return !!this.stream; }

  async start() {
    if (this.stream) return;
    try {
      const { FilesetResolver, HandLandmarker } = await import("@mediapipe/tasks-vision");
      const files = await FilesetResolver.forVisionTasks(this.opt.base);
      this.landmarker = await HandLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: `${this.opt.base}/hand_landmarker.task`, delegate: "GPU" },
        runningMode: "VIDEO", numHands: 1,
      });
    } catch (e: any) {
      this.opt.onState?.(false, `Model ruky nejde spustit: ${e?.message || e}`);
      return;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240, frameRate: 15 }, audio: false });
    } catch (e: any) {
      this.opt.onState?.(false, e?.name === "NotAllowedError" ? "Kamera není povolená" : "Kameru se nepodařilo zapnout");
      return;
    }
    const video = document.createElement("video");
    video.muted = true; video.playsInline = true; video.srcObject = this.stream;
    await video.play().catch(() => {});
    this.opt.onState?.(true);
    this.timer = window.setInterval(() => {
      if (video.readyState < 2) return;
      let lm: Pt[] | null = null;
      try {
        const res = this.landmarker.detectForVideo(video, performance.now());
        const hand = res?.landmarks?.[0];
        if (hand) lm = hand.map((p: Pt) => ({ x: 1 - p.x, y: p.y, z: p.z }));     // mirrored, like a mirror
      } catch { lm = null; }
      const ev = this.reader.push(lm, performance.now());
      if (ev) this.opt.onEvent(ev);
    }, 66);
  }

  stop() {
    window.clearInterval(this.timer);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    try { this.landmarker?.close?.(); } catch { /* fine */ }
    this.landmarker = null;
    this.opt.onState?.(false);
  }
}
