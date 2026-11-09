/* 3.12 the background picked in "Přizpůsobit" (notch) or Nastavení → Vzhled (window): black, the colours of the music
   that plays, or your own photo, with how dark and how blurred. Kept on this PC (both pages share it), the photo shrunk
   to at most 1600 px first. */
export type LookBg = "none" | "album" | "photo";
export type Look = { bg: LookBg; dim: number; blur: number };

export const LOOK_KEY = "jarvis.look", PHOTO_KEY = "jarvis.look.photo";
const DEF: Look = { bg: "none", dim: 45, blur: 0 };

export function loadLook(): Look {
  try { return { ...DEF, ...JSON.parse(localStorage.getItem(LOOK_KEY) || "{}") }; } catch { return { ...DEF }; }
}
export function saveLook(l: Look) {
  try { localStorage.setItem(LOOK_KEY, JSON.stringify(l)); } catch { /* private */ }
  window.dispatchEvent(new CustomEvent("jarvis-look"));
}
export function loadPhoto(): string {
  try { return localStorage.getItem(PHOTO_KEY) || ""; } catch { return ""; }
}
/** false when it is too big to keep */
export function savePhoto(dataUrl: string): boolean {
  try { localStorage.setItem(PHOTO_KEY, dataUrl); window.dispatchEvent(new CustomEvent("jarvis-look")); return true; } catch { return false; }
}

/** a picked photo → a JPEG data URL of at most 1600 px (small enough to keep) */
export function shrinkPhoto(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, 1600 / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", 0.86));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("Tohle není obrázek")); };
    img.src = url;
  });
}

/** changes made in another window of JARVIS (the notch ↔ the main window) */
export function onLookChange(fn: () => void) {
  window.addEventListener("jarvis-look", fn);
  window.addEventListener("storage", (e) => { if (e.key === LOOK_KEY || e.key === PHOTO_KEY) fn(); });
}
