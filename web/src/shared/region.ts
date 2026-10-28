// Window-region outlines (Windows only): the desktop shell clips the notch / pet window to these polygons, so
// nothing but the shape itself is drawn — no grey/white window background around it. Coordinates are window
// client coordinates in PHYSICAL pixels (CSS px × devicePixelRatio).
export type Pt = [number, number];
export type Poly = Pt[];

const arc = (cx: number, cy: number, r: number, from: number, to: number, steps: number): Pt[] => {
  const out: Pt[] = [];
  for (let i = 0; i <= steps; i++) {
    const a = from + ((to - from) * i) / steps;
    out.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  return out;
};
const scale = (poly: Pt[], k: number): Poly => poly.map(([x, y]) => [Math.round(x * k), Math.round(y * k)]);
const D = Math.PI / 180;

/** Notch: flat top with concave "ears" on both sides, rounded bottom corners. */
export function notchOutline(r: DOMRect, radius: number, ear: number, dpr: number, pad = 0): Poly {
  // pad > 0: the window is per-pixel transparent, the region only catches the mouse, so it may hug the shape loosely
  const L = r.left - pad, R = r.right + pad, T = r.top, B = r.bottom + pad;
  const rad = Math.max(0, Math.min(radius + pad, (B - T) / 2, (R - L) / 2));
  const pts: Pt[] = [
    [L - ear, T], [R + ear, T],
    ...arc(R + ear, T + ear, ear, -90 * D, -180 * D, 12),  // right ear (concave)
    ...arc(R - rad, B - rad, rad, 0, 90 * D, 18),           // bottom-right corner
    ...arc(L + rad, B - rad, rad, 90 * D, 180 * D, 18),     // bottom-left corner
    ...arc(L - ear, T + ear, ear, 0, -90 * D, 12),          // left ear (concave)
  ];
  return scale(pts, dpr);
}

export function roundRect(r: DOMRect, radius: number, dpr: number, pad = 0): Poly {
  const L = r.left - pad, T = r.top - pad, R = r.right + pad, B = r.bottom + pad;
  const rad = Math.max(0, Math.min(radius, (B - T) / 2, (R - L) / 2));
  return scale([
    ...arc(R - rad, T + rad, rad, -90 * D, 0, 4), ...arc(R - rad, B - rad, rad, 0, 90 * D, 4),
    ...arc(L + rad, B - rad, rad, 90 * D, 180 * D, 4), ...arc(L + rad, T + rad, rad, 180 * D, 270 * D, 4),
  ], dpr);
}

/** The character's gumdrop body (an ellipse rx 90 / ry 86 cut flat at the base — see character/blob.ts). */
export function domeOutline(r: DOMRect, dpr: number, pad = 3): Poly {
  const w = r.width + pad * 2, h = r.height + pad * 2, top = r.top - pad, left = r.left - pad;
  const rx = w / 2, ry = (h * 86) / 130, cx = left + rx, cy = top + ry;
  const bottom = top + h;
  const alpha = Math.asin(Math.min(1, (bottom - cy) / ry));
  return scale(arc(cx, cy, 1, Math.PI - alpha, 2 * Math.PI + alpha, 28).map(([x, y]) =>
    [cx + (x - cx) * rx, cy + (y - cy) * ry] as Pt), dpr);
}

/** Sends the polygons to the desktop shell when they change (cheap no-op in a normal browser). `force` sends them
 *  even unchanged; a call that fails or that the shell reports as not applied (false) is sent again next time.
 *  pywebview runs every call in its own thread, so frames can arrive out of order: each carries a rising number
 *  and the shell drops the older ones (an older outline arriving late made the edge jump back and forth). */
let seqBase = Date.now() * 1000, seqN = 0;
export function regionSender(apiName = "region") {
  let last = "";
  return (polys: Poly[], force = false) => {
    const api = (window as any).pywebview?.api;
    if (!api?.[apiName]) return;
    const key = JSON.stringify(polys);
    if (key === last && !force) return;
    last = key;
    const forget = () => { if (last === key) last = ""; };
    const seq = seqBase + ++seqN;
    Promise.resolve(api[apiName](polys, seq)).then((ok) => { if (ok === false) forget(); }, forget);
  };
}
