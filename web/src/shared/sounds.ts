// Subtle interface sounds (spec §8), synthesised with WebAudio — no audio files, nothing to license.
type Sound = "wake" | "listen" | "done" | "error" | "notify";

const TONES: Record<Sound, [number, number, number][]> = { // [frequency Hz, start s, duration s]
  wake: [[660, 0, 0.09], [990, 0.07, 0.12]],
  listen: [[880, 0, 0.08]],
  done: [[784, 0, 0.09], [1175, 0.08, 0.14]],
  error: [[330, 0, 0.12], [247, 0.1, 0.16]],
  notify: [[1047, 0, 0.08], [1319, 0.09, 0.1]],
};

let ctx: AudioContext | null = null;
let enabled = true;
let volume = 0.3;

export function configureSounds(appearance: { sounds?: boolean; sound_volume?: number } | undefined) {
  enabled = appearance?.sounds !== false;
  volume = Math.max(0, Math.min(100, appearance?.sound_volume ?? 30)) / 100;
}

export function play(name: Sound) {
  if (!enabled || volume <= 0) return;
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
