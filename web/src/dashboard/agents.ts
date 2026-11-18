// 3.12 Firemní agenti: your own AI agents over Propojení (e-mails, Supabase, domains, calendar, GitHub, Slack…).
// They read and prepare on their own; every send / write / change waits in "Ke schválení" for your click.
import "./agents.css";
import { h, icon, toast } from "../shared/dom";
import { hero, HEROES } from "../shared/hero";
import type { JarvisClient } from "../shared/ws";
import { openHQ } from "./hq";

interface Agent { id: number; name: string; icon: string; role: string; task: string; tools: string[]; every_min: number; daily_at: string;
  work_hours: boolean; enabled: boolean; last_run: number | null; last_ok: number | null; last_result: string | null }
interface Proposal { id: number; agent: string; tool: string; description: string; details: string[]; created: number; status: string; result?: string }
interface Tool { name: string; danger: boolean; description: string }

const when = (a: Agent) => a.every_min ? `každých ${a.every_min >= 60 ? `${a.every_min / 60} h` : `${a.every_min} min`}` : a.daily_at ? `denně v ${a.daily_at}` : "jen ručně";
const ago = (t: number | null) => {
  if (!t) return "ještě nepracoval";
  const s = Math.round(Date.now() / 1000 - t);
  return s < 60 ? "před chvílí" : s < 3600 ? `před ${Math.round(s / 60)} min` : s < 86400 ? `před ${Math.round(s / 3600)} h` : `před ${Math.round(s / 86400)} dny`;
};

export function buildAgents(client: JarvisClient) {
  let agents: Agent[] = [], props: Proposal[] = [], done: Proposal[] = [], toolList: Tool[] = [], running: number[] = [];
  let templates: Record<string, { name: string; icon: string; role: string; tools: string[] }> = {};
  let editing: number | "new" | null = null, busy = "";
  const approvals = h("div", { class: "ag-approvals" });
  const list = h("div", { class: "ag-list" });
  const create = h("div", { class: "ag-create" });
  const log = h("div", { class: "ag-done" });

  const paintApprovals = () => {
    approvals.hidden = !props.length;
    approvals.replaceChildren(
      h("div", { class: "ag-sec" }, icon("seal-check", "ph-fill"), h("strong", {}, `Ke schválení (${props.length})`),
        h("span", {}, "Tohle agenti připravili – nic z toho se nestalo, dokud to neschválíš.")),
      ...props.map((p) => h("div", { class: "ag-prop" },
        h("div", { class: "ag-prop-h" }, h("b", {}, p.agent), h("span", {}, p.description)),
        p.details?.length ? h("pre", { class: "ag-prop-d" }, p.details.join("\n")) : "",
        h("div", { class: "ag-acts" },
          h("button", { type: "button", class: "btn primary", disabled: !!busy, onclick: () => { busy = `p${p.id}`; client.send("bizproposal_decide", { id: p.id, approve: true }); paint(); } },
            icon("check", "ph-bold"), "Schválit a provést"),
          h("button", { type: "button", class: "btn", disabled: !!busy, onclick: () => client.send("bizproposal_decide", { id: p.id, approve: false }) },
            icon("x"), "Zamítnout")))));
  };

  const editor = (a: Partial<Agent>) => {
    const name = h("input", { class: "cn-in", value: a.name || "", placeholder: "Název", "aria-label": "Název" }) as HTMLInputElement;
    const role = h("textarea", { class: "cn-in ag-ta", rows: 2, placeholder: "Kdo je a co hlídá", "aria-label": "Role" }, a.role || "") as HTMLTextAreaElement;
    const task = h("textarea", { class: "cn-in ag-ta", rows: 3, placeholder: "Co má pokaždé udělat", "aria-label": "Úkol" }, a.task || "") as HTMLTextAreaElement;
    const every = h("select", { class: "cn-in", "aria-label": "Jak často" },
      ...[["0", "Jen ručně / denně v čase"], ["15", "Každých 15 min"], ["30", "Každých 30 min"], ["60", "Každou hodinu"], ["120", "Každé 2 hodiny"], ["240", "Každé 4 hodiny"]]
        .map(([v, l]) => h("option", { value: v }, l))) as HTMLSelectElement;
    every.value = String(a.every_min || 0);
    const daily = h("input", { class: "cn-in", type: "time", value: a.daily_at || "", "aria-label": "Denně v" }) as HTMLInputElement;
    const hours = h("input", { type: "checkbox", checked: a.work_hours !== false }) as HTMLInputElement;
    const chosen = new Set(a.tools || []);
    const tl = h("div", { class: "ag-tools" }, ...toolList.map((t) => {
      const cb = h("input", { type: "checkbox", checked: chosen.has(t.name) }) as HTMLInputElement;
      cb.onchange = () => (cb.checked ? chosen.add(t.name) : chosen.delete(t.name));
      return h("label", { class: `ag-tool ${t.danger ? "danger" : ""}`, title: t.description }, cb, h("span", {}, t.name), t.danger ? h("em", {}, "schválení") : "");
    }));
    return h("div", { class: "ag-edit" },
      h("div", { class: "ag-row2" }, name, every, daily),
      role, task,
      h("label", { class: "ag-check" }, hours, "Pracovat jen 8–20 h"),
      h("details", {}, h("summary", {}, `Nástroje (${chosen.size})`), tl),
      h("div", { class: "ag-acts" },
        h("button", { type: "button", class: "btn primary", onclick: () => {
          client.send("bizagent_save", { agent: { id: a.id, name: name.value, icon: a.icon || "robot", role: role.value, task: task.value,
            tools: [...chosen], every_min: Number(every.value), daily_at: daily.value, work_hours: hours.checked, enabled: a.enabled !== false } });
          editing = null;
        } }, icon("floppy-disk"), "Uložit"),
        h("button", { type: "button", class: "btn", onclick: () => { editing = null; paint(); } }, "Zrušit")));
  };

  const card = (a: Agent) => {
    const run = running.includes(a.id) || busy === `a${a.id}`;
    const sw = h("input", { type: "checkbox", checked: a.enabled, "aria-label": "Zapnutý" }) as HTMLInputElement;
    sw.onchange = () => client.send("bizagent_save", { agent: { ...a, enabled: sw.checked } });
    return h("div", { class: `ag-card ${a.enabled ? "" : "off"} ${run ? "run" : ""}` },
      h("div", { class: "ag-card-h" },
        h("span", { class: "ag-ico" }, icon(run ? "circle-notch" : a.icon || "robot", "ph-fill")),
        h("div", { class: "ag-tt" }, h("strong", {}, a.name), h("span", {}, `${when(a)}${a.work_hours ? " · 8–20 h" : ""} · ${run ? "pracuje…" : ago(a.last_run)}`)),
        h("label", { class: "ag-sw", title: "Zapnout / vypnout" }, sw, h("i"))),
      h("p", { class: "ag-role" }, a.role),
      a.last_result ? h("details", { class: `ag-res ${a.last_ok ? "" : "bad"}` }, h("summary", {}, "Poslední výsledek"), h("pre", {}, a.last_result)) : "",
      editing === a.id ? editor(a) : h("div", { class: "ag-acts" },
        h("button", { type: "button", class: "btn primary", disabled: run, onclick: () => { busy = `a${a.id}`; client.send("bizagent_run", { id: a.id }); paint(); } },
          icon("play", "ph-fill"), "Spustit teď"),
        h("button", { type: "button", class: "btn", onclick: () => { editing = a.id; paint(); } }, icon("pencil-simple"), "Upravit"),
        h("button", { type: "button", class: "btn danger", onclick: () => { if (confirm(`Smazat agenta „${a.name}“?`)) client.send("bizagent_delete", { id: a.id }); } },
          icon("trash"))));
  };

  const paintCreate = () => {
    const txt = h("textarea", { class: "cn-in ag-ta", rows: 2, placeholder: "Popiš agenta jednou větou – např. „Každé ráno projdi nepřečtené e-maily, "
      + "na poptávky připrav odpověď a dej mi přehled“", "aria-label": "Popis agenta" }) as HTMLTextAreaElement;
    create.replaceChildren(
      h("div", { class: "ag-sec" }, icon("magic-wand", "ph-fill"), h("strong", {}, "Nový agent")),
      h("div", { class: "ag-new" }, txt, h("button", { type: "button", class: "btn primary", disabled: busy === "text", onclick: () => {
        if (txt.value.trim().length < 8) { toast("Napiš, co má agent dělat.", "error"); return; }
        busy = "text"; client.send("bizagent_text", { text: txt.value.trim() }); paint();
      } }, icon(busy === "text" ? "circle-notch" : "sparkle", "ph-fill"), busy === "text" ? "Vymýšlím…" : "Vytvořit")),
      h("div", { class: "ag-tpls" }, ...Object.entries(templates).map(([k, t]) => h("button", { type: "button", class: "ag-tpl", title: t.role,
        onclick: () => client.send("bizagent_template", { key: k }) }, icon(t.icon, "ph-fill"), h("span", {}, t.name)))),
      editing === "new" ? editor({ enabled: true, work_hours: true }) :
        h("button", { type: "button", class: "btn sm ag-manual", onclick: () => { editing = "new"; paint(); } }, icon("plus"), "Vytvořit ručně"));
  };

  const paint = () => {
    paintApprovals();
    paintCreate();
    list.replaceChildren(...(agents.length ? agents.map(card) : [h("p", { class: "help" }, "Zatím žádný agent – vyber šablonu nebo ho popiš větou. "
      + "Nejdřív propoj služby, se kterými má pracovat (stránka Propojení).")]));
    log.hidden = !done.length;
    log.replaceChildren(h("div", { class: "ag-sec" }, icon("clock-counter-clockwise"), h("strong", {}, "Naposledy schválené")),
      ...done.slice(0, 8).map((p) => h("div", { class: `ag-log ${p.status}` }, icon(p.status === "done" ? "check-circle" : "x-circle", "ph-fill"),
        h("span", {}, `${p.agent}: ${p.description}`), h("em", {}, p.result || ""))));
  };

  client.on("bizagents", (m: any) => {
    agents = m.agents || []; props = m.proposals || []; done = m.done || [];
    if (m.tools) toolList = m.tools;                 // a live update carries only what changed
    if (m.templates) templates = m.templates;
    running = m.running || [];
    if (m.req && m.req !== "bizagents_get") busy = "";
    if (m.message && !document.body.classList.contains("hq-open"))      // the open Velín says it itself (once)
      toast(m.message.length > 160 ? `${m.message.slice(0, 160)}…` : m.message, m.ok === false ? "error" : "ok", 6000);
    paint();
  });
  client.on("agent_activity", (m: any) => { if (String(m.key || "").startsWith("biz") && m.state !== "tool") client.send("bizagents_get"); });

  const el = h("section", { class: "ag-view" },
    hero(HEROES.agents, "Firemní agenti", "AI agenti, kteří se starají o tvoje služby – e-maily, databázi, domény, kalendář… "
      + "Čtou a připravují sami, odeslat nebo změnit cokoli smí až po tvém schválení.",
      [h("button", { type: "button", class: "btn primary ag-hq", title: "Celá firma na celé obrazovce: oddělení, 100 agentů, mozek firmy",
        onclick: () => openHQ(client) }, icon("arrows-out", "ph-bold"), "Velín firmy")]),
    approvals, create, list, log);
  paint();
  return { el, show() { client.send("bizagents_get"); } };
}
