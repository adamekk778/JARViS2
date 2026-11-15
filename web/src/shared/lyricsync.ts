// 3.12 the lyrics' own shift: players report where the song is a little late (Spotify), and some synced lyrics are
// made for a slightly different version of the song – so the text can be moved earlier or later by hand. It is kept
// for each song, and the last one you set becomes the start for new songs (the player's lag is usually the same).
const KEY = "jarvis.lyrics.shift";
const DEFAULT = 0.3;                       // the light a hair before the voice reads better than a hair after it

type Store = { last: number; songs: Record<string, number> };
let mem: Store | null = null;

function load(): Store {
  if (mem) return mem;
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "null");
    if (raw && typeof raw.last === "number" && raw.songs && typeof raw.songs === "object") mem = raw as Store;
  } catch { /* no storage: the default */ }
  return (mem ??= { last: DEFAULT, songs: {} });
}
const songKey = (title?: string, artist?: string) => `${(artist || "").trim().toLowerCase()}|${(title || "").trim().toLowerCase()}`;
const clamp = (v: number) => Math.max(-5, Math.min(5, Math.round(v * 100) / 100));

/** Seconds to add to the song's position for the lyrics (positive = the text comes sooner). */
export function lyricShift(title?: string, artist?: string): number {
  const s = load();
  const v = s.songs[songKey(title, artist)];
  return typeof v === "number" && isFinite(v) ? v : s.last;
}

export function setLyricShift(title: string | undefined, artist: string | undefined, v: number): number {
  const s = load();
  const val = clamp(v);
  s.songs[songKey(title, artist)] = val;
  s.last = val;
  const keys = Object.keys(s.songs);
  if (keys.length > 400) for (const k of keys.slice(0, keys.length - 400)) delete s.songs[k];
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* kept for this run */ }
  return val;
}

export const fmtShift = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2).replace(/0$/, "").replace(".", ",")} s`;
