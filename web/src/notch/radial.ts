// OMEGA 751: right-click on the character → a ring of actions around him: what fits the app in front (089),
// what fits the moment (094) and the everyday ones. One click runs it, Esc or moving away closes it.
import { h, icon } from "../shared/dom";

export interface UiAction { label: string; icon: string; text?: string; quick?: string; args?: any; pin?: number; open?: string }

export const BASE_ACTIONS: UiAction[] = [
  { label: "Mluvit", icon: "microphone", open: "talk" },
  { label: "Chat", icon: "chat-circle-dots", open: "chat" },
  { label: "Plochy", icon: "squares-four", open: "workspaces" },
  { label: "Hra", icon: "game-controller", open: "play" },
  { label: "Nastavení", icon: "gear-six", open: "settings" },
];

/** Up to 8 actions: the app's first, then the moment's, then the everyday ones. */
export function radialActions(app: UiAction[], moment: UiAction[]): UiAction[] {
  const out: UiAction[] = [];
  for (const a of [...app.slice(0, 3), ...moment.slice(0, 1), ...BASE_ACTIONS]) {
    if (out.length >= 8) break;
    if (!out.some((x) => x.label === a.label)) out.push(a);
  }
  return out;
}

/** Positions on a circle around (cx, cy), starting at the top and going clockwise. */
export function ringPositions(n: number, cx: number, cy: number, r: number): [number, number][] {
  return Array.from({ length: n }, (_, i) => {
    const a = -Math.PI / 2 + (i / Math.max(1, n)) * Math.PI * 2;
    return [Math.round(cx + Math.cos(a) * r), Math.round(cy + Math.sin(a) * r)];
  });
}

export function renderRadial(host: HTMLElement, actions: UiAction[], appName: string, run: (a: UiAction) => void) {
  const pos = ringPositions(actions.length, 170, 166, 110);
  host.replaceChildren(
    h("div", { class: "r-app" }, appName ? `${appName}` : ""),
    ...actions.map((a, i) => h("button", {
      class: `r-btn ${a.text || a.quick ? "ctx" : ""}`, type: "button", title: a.label, "aria-label": a.label,
      style: { left: `${pos[i][0]}px`, top: `${pos[i][1]}px`, "--d": `${i * 22}ms` },
      onclick: () => run(a),
    }, icon(a.icon), h("span", {}, a.label))));
  (host.querySelector(".r-btn") as HTMLElement | null)?.focus({ preventScroll: true });
}
