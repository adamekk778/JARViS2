// Interface sounds (spec §8; 3.15 sound design), synthesised with WebAudio – layered tones, filtered noise and a small
// room echo, all made here: no audio files, nothing to license. Your own files in the sounds folder still win.
type Sound = "wake" | "listen" | "done" | "error" | "notify" | "boot" | "holo" | "whoosh" | "close" | "scan" | "alert" | "lock";
export const SOUNDS: Sound[] = ["wake", "listen", "done", "error", "notify", "boot", "holo", "whoosh", "close", "scan", "alert", "lock"];

type Tone = { f: number; t: number; d: number; type?: OscillatorType; g?: number; to?: number; wet?: number };
type Noise = { t: number; d: number; from: number; to: number; q?: number; g?: number; kind?: BiquadFilterType; wet?: number };
const R: Record<Sound, { tones?: Tone[]; noise?: Noise[] }> = {
  wake: { tones: [{ f: 660, t: 0, d: 0.1 }, { f: 990, t: 0.07, d: 0.16, wet: 0.35 }, { f: 1980, t: 0.1, d: 0.3, g: 0.18, wet: 0.6 }] },
  listen: { tones: [{ f: 880, t: 0, d: 0.08 }], noise: [{ t: 0, d: 0.03, from: 6000, to: 6000, kind: "highpass", g: 0.25 }] },
  done: { tones: [{ f: 784, t: 0, d: 0.1 }, { f: 1175, t: 0.08, d: 0.22, wet: 0.45 }, { f: 2350, t: 0.1, d: 0.25, g: 0.12, wet: 0.6 }] },
  error: { tones: [{ f: 330, t: 0, d: 0.13, type: "triangle" }, { f: 247, t: 0.1, d: 0.2, type: "triangle" }] },
  notify: { tones: [{ f: 1047, t: 0, d: 0.25, wet: 0.4 }, { f: 2889, t: 0, d: 0.12, g: 0.15 }, { f: 1319, t: 0.09, d: 0.3, wet: 0.5 }] },
  boot: {
    tones: [{ f: 110, t: 0, d: 1.4, type: "sawtooth", g: 0.12, wet: 0.5 }, { f: 165, t: 0.05, d: 1.35, type: "sawtooth", g: 0.1, wet: 0.5 },
      { f: 220, t: 0, d: 1.1, to: 1760, g: 0.25, wet: 0.4 }, { f: 880, t: 1.0, d: 0.5, wet: 0.7 }, { f: 1320, t: 1.08, d: 0.6, g: 0.6, wet: 0.7 }],
    noise: [{ t: 0, d: 1.1, from: 200, to: 4000, q: 6, g: 0.35, wet: 0.5 }],
  },
  holo: { tones: [{ f: 2400, t: 0, d: 0.035, g: 0.45 }], noise: [{ t: 0, d: 0.02, from: 8000, to: 8000, kind: "highpass", g: 0.2 }] },
  whoosh: { noise: [{ t: 0, d: 0.38, from: 400, to: 3200, q: 1.4, g: 0.6, wet: 0.3 }], tones: [{ f: 520, t: 0.05, d: 0.25, to: 1040, g: 0.12 }] },
  close: { noise: [{ t: 0, d: 0.3, from: 3000, to: 350, q: 1.4, g: 0.5, wet: 0.2 }] },
  scan: { tones: [{ f: 600, t: 0, d: 0.9, to: 1500, g: 0.22, wet: 0.4 }, { f: 1200, t: 0, d: 0.9, to: 3000, g: 0.08 }],
    noise: [{ t: 0, d: 0.9, from: 1500, to: 6000, q: 8, g: 0.15 }] },
  alert: { tones: [0, 0.32, 0.64].flatMap((t) => [{ f: 880, t, d: 0.14, type: "square" as OscillatorType, g: 0.25 },
    { f: 660, t: t + 0.15, d: 0.14, type: "square" as OscillatorType, g: 0.25 }]) },
  lock: { tones: [{ f: 1800, t: 0, d: 0.03 }, { f: 1800, t: 0.07, d: 0.03 }, { f: 1800, t: 0.14, d: 0.03 }, { f: 1320, t: 0.22, d: 0.25, wet: 0.5 }] },
};
/** The recipes – the tests check every sound has one and stays short. */
export const RECIPES = R;

let ctx: AudioContext | null = null;
// your own sounds from the PC's sounds folder (3.0): name -> URL
let custom: Partial<Record<Sound, string>> = {};

export function setCustomSounds(files: Record<string, string> | undefined, base = "") {
  custom = {};
  for (const name of Object.keys(files || {})) custom[name as Sound] = `${base}/api/sounds/${name}?v=${encodeURIComponent(files![name])}`;
}
let enabled = true;
let volume = 0.3;
let spatial = true;
let anchorPan = 0;

export function configureSounds(appearance: { sounds?: boolean; sound_volume?: number; spatial_sounds?: boolean } | undefined) {
  enabled = appearance?.sounds !== false;
  volume = Math.max(0, Math.min(100, appearance?.sound_volume ?? 30)) / 100;
  spatial = appearance?.spatial_sounds !== false;
}

/** OMEGA 102 / 761: where a sound comes from, -1 (left) … 1 (right). The notch is at the top centre; the phone and
 *  toasts sit on the right; while JARVIS works in a window, its sounds come from that side of the screen. */
export function panFor(source: string): number {
  if (source === "phone" || source === "toast" || source === "mobile") return 0.7;
  if (source === "window") return anchorPan;
  if (source === "mail") return -0.5;
  return 0;
}
export function setAnchorPan(cx: number | null) { anchorPan = cx == null ? 0 : Math.max(-1, Math.min(1, (cx - 0.5) * 2)); }

export function play(name: Sound, pan = 0) {
  if (!enabled || volume <= 0) return;
  const p = spatial ? Math.max(-1, Math.min(1, pan)) : 0;
  if (custom[name]) {
    const a = new Audio(custom[name]);
    a.volume = Math.min(1, volume * 1.5);
    try {
      if (p) {
        ctx ??= new AudioContext();
        const src = ctx.createMediaElementSource(a);
        const pn = ctx.createStereoPanner();
        pn.pan.value = p;
        src.connect(pn).connect(ctx.destination);
      }
    } catch { /* plain playback */ }
    a.play().catch(() => {});
    return;
  }
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    const c = ctx;
    const t0 = c.currentTime + 0.01;
    const out: AudioNode = p ? (() => { const pn = c.createStereoPanner(); pn.pan.value = p; pn.connect(c.destination); return pn; })() : c.destination;
    const room = reverb(c, out);
    const send = (node: AudioNode, wet = 0) => {
      node.connect(out);
      if (wet > 0) { const w = c.createGain(); w.gain.value = wet; node.connect(w).connect(room); }
    };
    const env = (g: GainNode, start: number, dur: number, peak: number) => {
      g.gain.setValueAtTime(0.0001, t0 + start);
      g.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), t0 + start + Math.min(0.015, dur / 3));
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + start + dur);
    };
    const r = R[name];
    for (const tn of r.tones || []) {
      const osc = c.createOscillator();
      const gain = c.createGain();
      osc.type = tn.type || "sine";
      osc.frequency.setValueAtTime(tn.f, t0 + tn.t);
      if (tn.to) osc.frequency.exponentialRampToValueAtTime(tn.to, t0 + tn.t + tn.d);
      env(gain, tn.t, tn.d, volume * 0.3 * (tn.g ?? 1));
      osc.connect(gain);
      send(gain, tn.wet);
      osc.start(t0 + tn.t);
      osc.stop(t0 + tn.t + tn.d + 0.03);
    }
    for (const nz of r.noise || []) {
      const src = c.createBufferSource();
      src.buffer = noiseBuffer(c);
      const f = c.createBiquadFilter();
      f.type = nz.kind || "bandpass";
      f.Q.value = nz.q ?? 1;
      f.frequency.setValueAtTime(nz.from, t0 + nz.t);
      if (nz.to !== nz.from) f.frequency.exponentialRampToValueAtTime(nz.to, t0 + nz.t + nz.d);
      const gain = c.createGain();
      env(gain, nz.t, nz.d, volume * 0.3 * (nz.g ?? 1));
      src.connect(f).connect(gain);
      send(gain, nz.wet);
      src.start(t0 + nz.t);
      src.stop(t0 + nz.t + nz.d + 0.03);
    }
  } catch { /* audio unavailable */ }
}

let noiseBuf: AudioBuffer | null = null;
function noiseBuffer(c: AudioContext): AudioBuffer {
  if (noiseBuf && noiseBuf.sampleRate === c.sampleRate) return noiseBuf;
  const b = c.createBuffer(1, Math.round(c.sampleRate * 1.5), c.sampleRate);
  const d = b.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  return (noiseBuf = b);
}

// a small synthetic room (decaying noise as the impulse response): the "space" behind the holographic sounds
let roomBuf: AudioBuffer | null = null;
function reverb(c: AudioContext, out: AudioNode): AudioNode {
  if (!roomBuf || roomBuf.sampleRate !== c.sampleRate) {
    const len = Math.round(c.sampleRate * 0.9);
    roomBuf = c.createBuffer(2, len, c.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const d = roomBuf.getChannelData(ch);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3);
    }
  }
  const conv = c.createConvolver();
  conv.buffer = roomBuf;
  conv.connect(out);
  return conv;
}
