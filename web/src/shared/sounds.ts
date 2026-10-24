// Subtle interface sounds (spec §8), synthesised with WebAudio — no audio files, nothing to license.
type Sound = "wake" | "listen" | "done" | "error" | "notify" | "boot";

const TONES: Record<Sound, [number, number, number][]> = { // [frequency Hz, start s, duration s]
  wake: [[660, 0, 0.09], [990, 0.07, 0.12]],
  listen: [[880, 0, 0.08]],
  done: [[784, 0, 0.09], [1175, 0.08, 0.14]],
  error: [[330, 0, 0.12], [247, 0.1, 0.16]],
  notify: [[1047, 0, 0.08], [1319, 0.09, 0.1]],
  boot: [[220, 0, 0.22], [330, 0.1, 0.22], [440, 0.2, 0.26], [660, 0.32, 0.3], [880, 0.46, 0.42]],   // HUD power-up
};

let ctx: AudioContext | null = null;
// your own sounds from the PC's sounds folder (3.0): name -> URL
let custom: Partial<Record<Sound, string>> = {};

export function setCustomSounds(files: Record<string, string> | undefined, base = "") {
  custom = {};
  for (const name of Object.keys(files || {})) custom[name as Sound] = `${base}/api/sounds/${name}?v=${encodeURIComponent(files![name])}`;
}
let enabled = true;
let volume = 0.3;

export function configureSounds(appearance: { sounds?: boolean; sound_volume?: number } | undefined) {
  enabled = appearance?.sounds !== false;
  volume = Math.max(0, Math.min(100, appearance?.sound_volume ?? 30)) / 100;
}

export function play(name: Sound) {
  if (!enabled || volume <= 0) return;
  if (custom[name]) {
    const a = new Audio(custom[name]);
    a.volume = Math.min(1, volume * 1.5);
    a.play().catch(() => {});
    return;
  }
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    const t0 = ctx.currentTime + 0.01;
    for (const [freq, start, dur] of TONES[name]) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      const peak = volume * 0.3;
      gain.gain.setValueAtTime(0.0001, t0 + start);
      gain.gain.exponentialRampToValueAtTime(peak, t0 + start + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + start + dur);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t0 + start);
      osc.stop(t0 + start + dur + 0.02);
    }
  } catch { /* audio unavailable */ }
}
