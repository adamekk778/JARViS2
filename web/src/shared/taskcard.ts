// Current-task card (spec §4.5): goal, steps, progress, current action, pending approval, controls.
// Shared by the dashboard Tasks page, the notch panel and the phone.
import "./taskcard.css";
import { guardApprove } from "./approve";
import { h, icon } from "./dom";
import { renderMarkdown } from "./markdown";
import type { JarvisClient } from "./ws";

export interface TaskStep { idx: number; title: string; status: string; note?: string }
export interface Task {
  id: string; goal: string; status: string; created: number; finished?: number | null; summary?: string;
  steps: TaskStep[]; done: number; total: number; current_action?: string;
  actions?: { ts: number; tool: string; args: string; ok: number; summary: string; ms: number }[];
  criteria?: string[];
  artifacts?: { ts: number; title: string; path: string; sha256: string; bytes: number }[];
  evidence?: { ts: number; source: string; claim: string; value: string; ok: number }[];
}

export const TASK_STATUS: Record<string, string> = {
  running: "Probíhá", paused: "Pozastaveno", waiting: "Čeká na potvrzení", verifying: "Ověřuji", done: "Hotovo",
  failed: "Chyba", cancelled: "Zrušeno", interrupted: "Přerušeno",
};
const STEP_ICON: Record<string, string> = {
  pending: "circle", running: "circle-notch", done: "check-circle", failed: "x-circle", skipped: "minus-circle",
};
export const isActive = (t?: Task | null) => !!t && ["running", "paused", "waiting", "verifying"].includes(t.status);

export class TaskCard {
  el: HTMLElement;
  private task: Task | null = null;
  private confirm: { id: string; description: string; details: string[] } | null = null;

  constructor(private client: JarvisClient, private opts: { compact?: boolean; hideWhenIdle?: boolean } = {}) {
    this.el = h("section", { class: `taskcard ${opts.compact ? "compact" : ""}`, "aria-live": "polite" });
    client.on("welcome", (m) => this.update(m.task || null));
    client.on("task_update", (m) => this.update(m.task));
    client.on("tasks", (m) => { if (m.current !== undefined) this.update(m.current); });
    client.on("confirm_request", (m) => { this.confirm = { id: m.id, description: m.description, details: m.details || [] }; this.render(); });
    const clear = (m: any) => { if (this.confirm?.id === m.id) { this.confirm = null; this.render(); } };
    client.on("confirm_resolved", clear);
    client.on("confirm_timeout", clear);
    client.on("stopped", () => { this.confirm = null; this.render(); });
    this.render();
  }

  update(task: Task | null) {
    if (task && this.task && task.id !== this.task.id && !isActive(task) && isActive(this.task)) return;
    this.task = task;
    this.render();
  }

  private btn(ic: string, label: string, fn: () => void, cls = "") {
    return h("button", { class: `tc-btn ${cls}`, type: "button", onclick: fn }, icon(ic), h("span", {}, label));
  }

  private render() {
    const t = this.task;
    this.el.hidden = !!this.opts.hideWhenIdle && !isActive(t);
    if (!t) {
      this.el.replaceChildren(h("div", { class: "tc-empty" }, icon("list-checks"),
        h("span", {}, "Teď neběží žádný úkol. Zadej JARVISovi něco složitějšího – plán a průběh uvidíš tady.")));
      return;
    }
    const pct = t.total ? Math.round((t.done / t.total) * 100) : isActive(t) ? 0 : 100;
    const active = isActive(t);
    const c = this.confirm;
    this.el.replaceChildren(
      h("header", { class: "tc-head" },
        h("span", { class: `tc-status st-${t.status}` }, TASK_STATUS[t.status] || t.status),
        h("strong", { class: "tc-goal", title: t.goal }, t.goal),
        t.total ? h("span", { class: "tc-count" }, `Krok ${Math.min(t.done + (active ? 1 : 0), t.total)}/${t.total}`) : ""),
      h("div", { class: "tc-bar", role: "progressbar", "aria-valuenow": String(pct), "aria-valuemin": "0", "aria-valuemax": "100" },
        h("b", { style: { width: `${pct}%` } })),
      t.steps.length ? h("ol", { class: "tc-steps" }, ...t.steps.map((s) =>
        h("li", { class: `s-${s.status}` }, icon(STEP_ICON[s.status] || "circle", s.status === "running" ? "spin" : ""),
          h("span", {}, s.title), s.note ? h("em", {}, s.note) : ""))) : "",
      active && t.current_action ? h("div", { class: "tc-action" }, icon("lightning"), h("span", {}, t.current_action)) : "",
      c ? h("div", { class: "tc-confirm" },
        h("div", { class: "tc-confirm-text" }, icon("shield-warning", "ph-fill"), h("span", {}, c.description)),
        c.details.length ? h("ul", { class: "tc-details" }, ...c.details.map((d) => h("li", {}, d))) : "",
        h("div", { class: "tc-row" },
          this.btn("x", "Zamítnout", () => this.client.send("confirm_response", { id: c.id, approved: false })),
          this.btn("check", "Povolit", async () => { if (await guardApprove(c.description)) this.client.send("confirm_response", { id: c.id, approved: true }); }, "primary"))) : "",
      !active && t.summary ? h("div", { class: "tc-summary md", html: renderMarkdown(t.summary) }) : "",
      h("div", { class: "tc-row" },
        ...(active ? [
          t.status === "paused" ? this.btn("play", "Pokračovat", () => this.client.send("task_resume"))
            : this.btn("pause", "Pozastavit", () => this.client.send("task_pause")),
          this.btn("x-circle", "Zrušit", () => this.client.send("task_cancel")),
          this.btn("hand-palm", "STOP", () => this.client.send("stop_all"), "stop"),
        ] : [this.btn("arrow-clockwise", "Zopakovat", () => this.client.send("task_retry", { id: t.id }))])));
  }
}

/** Big red STOP button (emergency stop for everything JARVIS does). */
export function stopButton(client: JarvisClient, cls = "") {
  return h("button", { class: `stop-btn ${cls}`, type: "button", title: "STOP – okamžitě zastavit vše (Ctrl+Alt+X)",
    "aria-label": "STOP – zastavit vše", onclick: () => client.send("stop_all") }, icon("hand-palm", "ph-fill"), h("span", {}, "STOP"));
}
