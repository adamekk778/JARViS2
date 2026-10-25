// Dashboard → Úkoly (spec §4.5): the current task card + searchable history with details.
import { hero, HEROES } from "../shared/hero";
import { fmtSize, fmtTime, h, icon, toast } from "../shared/dom";
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
    const checks = (t.evidence || []).filter((e) => e.source === "ověření souboru");
    const measured = (t.evidence || []).filter((e) => e.source !== "ověření souboru");
    const crit = (t.criteria || []).map((c) => ({ c, e: checks.find((x) => x.claim === c) }));
    detail.replaceChildren(
      h("h3", {}, t.goal),
      h("p", { class: "muted" }, `${TASK_STATUS[t.status] || t.status} · ${fmtTime(t.created)} · ID ${t.id}`),
      t.summary ? h("div", { class: "md", html: renderMarkdown(t.summary) }) : "",
      crit.length ? h("div", { class: "mission-block" }, h("h4", {}, "Akceptační kritéria"),
        h("ul", { class: "mission-crit" }, ...crit.map(({ c, e }) => h("li", { class: e ? (e.ok ? "ok" : "bad") : "wait", title: e?.value || "" },
          icon(e ? (e.ok ? "check-circle" : "x-circle") : "circle", e ? "ph-fill" : ""), h("span", {}, c))))) : "",
      (t.artifacts || []).length ? h("div", { class: "mission-block" }, h("h4", {}, "Výsledky (soubory)"),
        ...(t.artifacts || []).map((a) => h("div", { class: "mission-art" }, icon("file-text"),
          h("div", {}, h("strong", {}, a.title), h("span", { class: "muted mono", title: a.path }, `${fmtSize(a.bytes)} · SHA-256 ${a.sha256.slice(0, 12)}…`)),
          client.local ? h("button", { class: "btn", type: "button", onclick: () => client.send("artifact_open", { task_id: t.id, path: a.path }) }, icon("arrow-square-out"), "Otevřít") : ""))) : "",
      measured.length ? h("details", { class: "mission-block" }, h("summary", {}, `Důkazy – co se měřilo (${measured.length})`),
        h("table", { class: "task-actions" }, h("tbody", {}, ...measured.map((e) => h("tr", { class: e.ok ? "" : "fail" },
          h("td", {}, e.claim), h("td", {}, e.value), h("td", { class: "muted" }, e.source)))))) : "",
      t.steps.length ? h("ol", { class: "task-steps" }, ...t.steps.map((s) => h("li", { class: `s-${s.status}` }, s.title))) : "",
      h("h4", {}, "Provedené akce (audit)"),
      (t.actions || []).length ? h("table", { class: "task-actions" },
        h("thead", {}, h("tr", {}, h("th", {}, "Čas"), h("th", {}, "Nástroj"), h("th", {}, "Výsledek"), h("th", {}, "ms"))),
        h("tbody", {}, ...(t.actions || []).map((a) => h("tr", { class: a.ok ? "" : "fail" },
          h("td", {}, fmtTime(a.ts)), h("td", { title: a.args }, a.tool), h("td", {}, a.summary), h("td", {}, String(a.ms))))))
        : h("p", { class: "muted" }, "Žádné akce."),
      (t.actions || []).length > 1 ? h("button", { class: "btn ghost", type: "button", onclick: () => replay(t) }, icon("film-strip"), "Přehrát průběh") : "",
      h("div", { class: "btn-row" },
        ["interrupted", "failed"].includes(t.status) && t.steps.some((x) => x.status === "done")
          ? h("button", { class: "btn primary", type: "button", title: "Naváže od posledního hotového kroku (stejná mise)",
            onclick: () => client.send("mission_resume", { id: t.id }) }, icon("play"), "Pokračovat") : "",
        h("button", { class: "btn", type: "button", onclick: () => client.send("task_retry", { id: t.id }) }, icon("arrow-clockwise"), "Zopakovat"),
        t.status === "done" && (t.actions || []).some((a) => a.ok) ? h("button", { class: "btn", type: "button", title: "Skill Forge: z kroků této mise udělá dovednost, kterou spustíš jedním příkazem",
          onclick: () => client.send("skill_from_task", { id: t.id }) }, icon("magic-wand"), "Uložit jako dovednost") : ""));
  };
  // OMEGA 010 Mission Replay: the recorded actions again, one after another, at their real relative pace (max 1 s)
  const replay = (t: Task) => {
    const acts = t.actions || [];
    const box = h("ol", { class: "replay" });
    const dlg = h("div", { class: "replay-dlg card", role: "dialog", "aria-label": "Přehrání mise" },
      h("h3", {}, `Přehrání: ${t.goal}`), box,
      h("button", { class: "btn", type: "button", onclick: () => { stop = true; dlg.remove(); } }, "Zavřít"));
    document.body.append(dlg);
    let stop = false;
    (async () => {
      for (let i = 0; i < acts.length && !stop; i++) {
        const a = acts[i];
        box.append(h("li", { class: a.ok ? "ok" : "fail" }, h("span", { class: "muted" }, fmtTime(a.ts)), h("strong", {}, a.tool), h("span", {}, a.summary)));
        box.lastElementChild?.scrollIntoView({ block: "nearest" });
        const gap = i + 1 < acts.length ? Math.min(1000, Math.max(250, (acts[i + 1].ts - a.ts) * 1000)) : 0;
        await new Promise((r) => setTimeout(r, gap));
      }
    })();
  };

  // OMEGA 211 / 220: the mission queue
  const qList = h("ul", { class: "sec-list" });
  const qGoal = h("input", { class: "input", placeholder: "Nová mise do fronty, např. „ukliď Stažené soubory“", "aria-label": "Mise do fronty" }) as HTMLInputElement;
  const qAt = h("input", { class: "input sm", placeholder: "kdy (18:30, za 20 minut)", "aria-label": "Kdy" }) as HTMLInputElement;
  const qDl = h("input", { class: "input sm", placeholder: "termín (volitelně)", "aria-label": "Termín" }) as HTMLInputElement;
  const queueBox = h("div", { class: "card sec-card" },
    h("div", { class: "list-add" }, qGoal, qAt, qDl,
      h("button", { class: "btn primary", type: "button", onclick: () => {
        if (!qGoal.value.trim()) return;
        client.send("queue_add", { goal: qGoal.value.trim(), at: qAt.value.trim(), deadline: qDl.value.trim() });
        qGoal.value = qAt.value = qDl.value = "";
      } }, icon("plus"), "Zařadit")),
    h("button", { class: "btn ghost sm", type: "button", onclick: () => client.send("queue_add", { template: "pc_report", at: qAt.value.trim() }) },
      icon("stethoscope"), "Kontrola PC do fronty"),
    qList);
  client.on("queue", (m) => qList.replaceChildren(...((m.items || []).length ? m.items.map((q: any) => h("li", {},
    h("span", {}, q.goal), h("span", { class: "row-actions" },
      h("span", { class: "muted" }, [q.not_before ? `od ${new Date(q.not_before * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}` : "až bude volno",
        q.deadline ? `termín ${new Date(q.deadline * 1000).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })}` : ""].filter(Boolean).join(" · ")),
      h("button", { class: "icon-btn sm", type: "button", "aria-label": "Zrušit misi ve frontě", onclick: () => client.send("queue_cancel", { id: q.id }) }, icon("x")))))
    : [h("li", { class: "muted" }, "Fronta je prázdná.")])));

  client.on("skill_draft", (m) => {
    const p = m.protocol, man = m.manifest;
    if (man.problems?.length) { toast(man.problems.join(" "), "error", 6000); return; }
    const steps = (p.steps || []).map((s: any, i: number) => `${i + 1}. ${s.tool}${s.args && Object.keys(s.args).length ? " " + JSON.stringify(s.args) : ""}`).join("\n");
    const name = prompt(`Skill Forge – nová dovednost\n\nKroky:\n${steps}\n\nOprávnění: ${man.permissions.join(", ") || "–"}\nNebezpečné kroky se i tak vždy zeptají.\n\nNázev dovednosti (OK = uložit, Zrušit = neukládat):`, p.name);
    if (!name?.trim()) return;
    const id = name.trim().toLowerCase().normalize("NFKD").replace(/[^\w]+/g, "-").replace(/^-|-$/g, "") || p.id;
    const list = (settings?.stark?.protocols || []).filter((x: any) => x.id !== id);
    client.send("settings_set", { patch: { stark: { protocols: [...list, { ...p, id, name: name.trim() }] } } });
    toast(`Dovednost ${name.trim()} uložena – najdeš ji ve Stark → Protokoly. Spustíš ji „spusť protokol ${name.trim().toLowerCase()}“.`, "ok", 5000);
  });
  let settings: any = {};

  client.on("tasks", (m) => {
    const items: Task[] = m.items || [];
    list.replaceChildren(...(items.length ? items.map((t) => h("button", {
      class: `task-row ${t.id === selected ? "on" : ""}`, type: "button", role: "listitem",
      onclick: () => { selected = t.id; client.send("task_get", { id: t.id }); list.querySelectorAll(".task-row").forEach((r) => r.classList.toggle("on", r === document.activeElement)); },
    }, h("span", { class: `tc-status st-${t.status}` }, TASK_STATUS[t.status] || t.status), h("span", { class: "task-goal" }, t.goal),
      h("span", { class: "muted" }, fmtTime(t.created)))) : [h("p", { class: "muted" }, "Zatím žádné úkoly.")]));
  });
  client.on("task", (m) => { if (m.task?.id === selected || !selected) renderDetail(m.task); });
  client.on("task_update", (m) => {
    if (!["running", "paused", "waiting", "verifying"].includes(m.task?.status)) { refresh(); client.send("queue_get"); }
    if (m.task?.id === selected) renderDetail(m.task);
  });
  const sync = (s: any) => { settings = s; agentSwitch.checked = !!s?.agent?.mode; };
  client.on("welcome", (m) => sync(m.settings));
  client.on("settings_changed", (m) => sync(m.settings));

  const el = h("section", { class: "tasks-view" },
    hero(HEROES.tasks, "Úkoly a mise", "Mission Control: plán, kroky, každá akce, důkazy a výsledky – co JARVIS dělá a co opravdu udělal.", [
      h("button", { class: "btn primary", type: "button", title: "Mise: jen čtení – zjistí stav PC, uloží report a ověří ho",
        onclick: () => { client.send("mission_start", { template: "pc_report" }); toast("Mise spuštěna: stav počítače", "ok"); } }, icon("stethoscope"), "Zkontrolovat PC"),
      h("label", { class: "agent-toggle", title: "Režim Agent: JARVIS si u složitých úkolů nejdřív udělá plán a postupuje krok po kroku (až 25 kroků)." },
        h("span", {}, "Režim Agent"), h("span", { class: "switch" }, agentSwitch, h("span")))]),
    card.el,
    h("h2", { class: "group-label" }, "Fronta misí"), queueBox,
    h("div", { class: "tasks-cols" },
      h("div", { class: "tasks-history" },
        h("div", { class: "tasks-filter" }, q, status,
          h("button", { class: "btn ghost", type: "button", onclick: () => { if (confirm("Smazat celou historii úkolů?")) client.send("tasks_clear"); } }, icon("trash"), "Smazat historii")),
        list),
      detail));
  return { el, show: () => { refresh(); client.send("queue_get"); } };
}
