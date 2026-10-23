// Dashboard → Úkoly (spec §4.5): the current task card + searchable history with details.
import { hero, HEROES } from "../shared/hero";
import { fmtTime, h, icon } from "../shared/dom";
import { renderMarkdown } from "../shared/markdown";
import { TASK_STATUS, TaskCard, type Task } from "../shared/taskcard";
import type { JarvisClient } from "../shared/ws";

export function buildTasks(client: JarvisClient) {
  const card = new TaskCard(client);
  const agentSwitch = h("input", { type: "checkbox", role: "switch", "aria-label": "Režim Agent" }) as HTMLInputElement;
  agentSwitch.onchange = () => client.send("settings_set", { patch: { agent: { mode: agentSwitch.checked } } });
  const q = h("input", { class: "input", type: "search", placeholder: "Hledat v úkolech…", "aria-label": "Hledat v úkolech" }) as HTMLInputElement;
  const status = h("select", { class: "input", "aria-label": "Filtr stavu" },
    h("option", { value: "" }, "Všechny"), ...Object.entries(TASK_STATUS).map(([k, v]) => h("option", { value: k }, v))) as HTMLSelectElement;
  const list = h("div", { class: "task-list", role: "list" });
  const detail = h("div", { class: "task-detail" }, h("p", { class: "muted" }, "Vyber úkol ze seznamu."));
  let selected = "";
  let timer = 0;
  const refresh = () => client.send("tasks_get", { q: q.value.trim(), status: status.value, limit: 100 });
  q.oninput = () => { window.clearTimeout(timer); timer = window.setTimeout(refresh, 250); };
  status.onchange = refresh;

  const renderDetail = (t: Task | null) => {
    if (!t) { detail.replaceChildren(h("p", { class: "muted" }, "Úkol už neexistuje.")); return; }
    detail.replaceChildren(
      h("h3", {}, t.goal),
      h("p", { class: "muted" }, `${TASK_STATUS[t.status] || t.status} · ${fmtTime(t.created)}`),
      t.summary ? h("div", { class: "md", html: renderMarkdown(t.summary) }) : "",
      t.steps.length ? h("ol", { class: "task-steps" }, ...t.steps.map((s) => h("li", { class: `s-${s.status}` }, s.title))) : "",
      h("h4", {}, "Provedené akce"),
      (t.actions || []).length ? h("table", { class: "task-actions" },
        h("thead", {}, h("tr", {}, h("th", {}, "Čas"), h("th", {}, "Nástroj"), h("th", {}, "Výsledek"), h("th", {}, "ms"))),
        h("tbody", {}, ...(t.actions || []).map((a) => h("tr", { class: a.ok ? "" : "fail" },
          h("td", {}, fmtTime(a.ts)), h("td", { title: a.args }, a.tool), h("td", {}, a.summary), h("td", {}, String(a.ms))))))
        : h("p", { class: "muted" }, "Žádné akce."),
      h("button", { class: "btn", type: "button", onclick: () => client.send("task_retry", { id: t.id }) }, icon("arrow-clockwise"), "Zopakovat"));
  };

  client.on("tasks", (m) => {
    const items: Task[] = m.items || [];
    list.replaceChildren(...(items.length ? items.map((t) => h("button", {
      class: `task-row ${t.id === selected ? "on" : ""}`, type: "button", role: "listitem",
      onclick: () => { selected = t.id; client.send("task_get", { id: t.id }); list.querySelectorAll(".task-row").forEach((r) => r.classList.toggle("on", r === document.activeElement)); },
    }, h("span", { class: `tc-status st-${t.status}` }, TASK_STATUS[t.status] || t.status), h("span", { class: "task-goal" }, t.goal),
      h("span", { class: "muted" }, fmtTime(t.created)))) : [h("p", { class: "muted" }, "Zatím žádné úkoly.")]));
  });
  client.on("task", (m) => { if (m.task?.id === selected || !selected) renderDetail(m.task); });
  client.on("task_update", (m) => { if (!["running", "paused", "waiting"].includes(m.task?.status)) refresh(); });
  const sync = (s: any) => { agentSwitch.checked = !!s?.agent?.mode; };
  client.on("welcome", (m) => sync(m.settings));
  client.on("settings_changed", (m) => sync(m.settings));

  const el = h("section", { class: "tasks-view" },
    hero(HEROES.tasks, "Úkoly", "Co JARVIS dělá a co udělal: plán, kroky a každá akce.", [
      h("label", { class: "agent-toggle", title: "Režim Agent: JARVIS si u složitých úkolů nejdřív udělá plán a postupuje krok po kroku (až 25 kroků)." },
        h("span", {}, "Režim Agent"), h("span", { class: "switch" }, agentSwitch, h("span")))]),
    card.el,
    h("div", { class: "tasks-cols" },
      h("div", { class: "tasks-history" },
        h("div", { class: "tasks-filter" }, q, status,
          h("button", { class: "btn ghost", type: "button", onclick: () => { if (confirm("Smazat celou historii úkolů?")) client.send("tasks_clear"); } }, icon("trash"), "Smazat historii")),
        list),
      detail));
  return { el, show: refresh };
}
