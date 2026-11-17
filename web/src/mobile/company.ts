// 3.12 Velín firmy v telefonu: the company in your pocket – the day's numbers, what waits for approval (approve with one
// tap), the departments with their agents (run one now), the latest work, and a pause for the whole company.
import "./company.css";
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import { native } from "./native";

type Any = Record<string, any>;
/** Minutes as hours the Czech way: 0, 1,5, 12. */
const hours = (min?: number) => { const v = Math.round((min || 0) / 6) / 10; return v.toLocaleString("cs-CZ", { maximumFractionDigits: v >= 10 ? 0 : 1 }); };
const ago = (t: number | null) => {
  if (!t) return "ještě ne";
  const s = Math.round(Date.now() / 1000 - t);
  return s < 60 ? "teď" : s < 3600 ? `${Math.round(s / 60)} min` : s < 86400 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} d`;
};

export function companyCard(c: JarvisClient): HTMLElement {
  let st: Any = { agents: [], proposals: [], running: [], company: {} };
  let open = false;
  let openDept = "";
  const card = h("button", { type: "button", class: "card m-co-entry", onclick: () => { open = true; c.send("bizagents_get"); paint(); } });
  const sheet = h("div", { class: "m-co", hidden: true, role: "dialog", "aria-label": "Velín firmy" });
  document.body.append(sheet);
  const state = (a: Any) => st.running?.includes(a.id) ? "run" : !a.enabled ? "off" : a.last_run && !a.last_ok ? "bad" : "on";
  const paint = () => {
    const n = st.company?.numbers || {};
    const ags: Any[] = st.agents || [];
    const props: Any[] = st.proposals || [];
    const busy = ags.filter((a) => st.running?.includes(a.id));
    card.hidden = !ags.length;
    card.replaceChildren(
      h("span", { class: "m-co-ico" }, icon("buildings", "ph-fill")),
      h("div", {}, h("strong", {}, "Velín firmy"),
        h("span", {}, busy.length ? `Pracuje: ${busy[0].name}` : `${ags.filter((a) => a.enabled).length} agentů · ${n.runs_today ?? 0} běhů dnes`)),
      props.length ? h("em", {}, String(props.length)) : icon("caret-right"));
    sheet.hidden = !open;
    if (!open) return;
    const depts: Any[] = st.company?.depts || [];
    sheet.replaceChildren(h("div", { class: "m-co-in" },
      h("div", { class: "m-co-head" },
        h("div", {}, h("small", {}, "VELÍN FIRMY"), h("strong", {}, st.company?.profile?.name || "Moje firma")),
        h("button", { type: "button", class: "icon-btn", "aria-label": "Zavřít", onclick: () => { open = false; paint(); } }, icon("x"))),
      h("div", { class: "m-co-kpis" },
        kpi(String(n.runs_today ?? 0), "běhů dnes"), kpi(String(props.length), "ke schválení"),
        kpi(`${hours(n.saved_week_min)} h`, "ušetřeno/týden"),
        kpi(n.runs_week ? `${Math.round(((n.ok_week || 0) / n.runs_week) * 100)} %` : "–", "úspěšnost")),
      h("button", { type: "button", class: `btn ${n.paused ? "primary" : ""} m-co-pause`, onclick: () => { native.haptic(); c.send("bizpause_set", { paused: !n.paused }); } },
        icon(n.paused ? "play" : "pause", "ph-fill"), n.paused ? "Spustit firmu" : "Pozastavit všechny agenty"),
      props.length ? h("h3", {}, `Ke schválení (${props.length})`) : "",
      ...props.slice(0, 20).map((p) => h("div", { class: "m-co-prop" },
        h("b", {}, p.agent), h("span", {}, p.description),
        p.details?.length ? h("pre", {}, p.details.slice(0, 10).join("\n")) : "",
        h("div", { class: "btn-row" },
          h("button", { type: "button", class: "btn", onclick: () => c.send("bizproposal_decide", { id: p.id, approve: false }) }, "Zamítnout"),
          h("button", { type: "button", class: "btn primary", onclick: () => { native.haptic(); c.send("bizproposal_decide", { id: p.id, approve: true }); } },
            icon("check", "ph-bold"), "Schválit")))),
      h("h3", {}, "Oddělení"),
      ...depts.filter((d) => d.agents).map((d) => {
        const mine = ags.filter((a) => (a.dept || "") === d.id);
        const isOpen = openDept === d.id;
        return h("div", { class: `m-co-dept ${isOpen ? "open" : ""}`, style: { "--c": d.color } },
          h("button", { type: "button", class: "m-co-dhead", onclick: () => { openDept = isOpen ? "" : d.id; paint(); } },
            h("span", { class: "m-co-dico" }, icon(d.icon, "ph-fill")), h("b", {}, d.name),
            h("small", {}, `${mine.length} agentů${mine.some((a) => st.running?.includes(a.id)) ? " · pracuje" : ""}`), icon(isOpen ? "caret-up" : "caret-down")),
          isOpen ? h("div", { class: "m-co-agents" }, ...mine.map((a) => h("div", { class: "m-co-agent" },
            h("i", { class: `m-co-dot ${state(a)}` }), h("div", {}, h("b", {}, a.name), h("small", {}, `${a.when || ""} · naposledy ${ago(a.last_run)}`)),
            h("button", { type: "button", class: "icon-btn", "aria-label": `Spustit ${a.name}`, disabled: st.running?.includes(a.id),
              onclick: () => { native.haptic(); c.send("bizagent_run", { id: a.id }); toast(`${a.name} pracuje…`, "info"); } }, icon("play", "ph-fill"))))) : "");
      }),
      (st.company?.runs || []).length ? h("h3", {}, "Poslední práce") : "",
      ...(st.company?.runs || []).slice(0, 8).map((r: Any) => h("div", { class: `m-co-run ${r.ok ? "" : "bad"}` },
        h("b", {}, r.agent), h("small", {}, ago(r.started)), h("p", {}, String(r.summary || "").split("\n")[0].slice(0, 160))))));
  };
  const kpi = (v: string, l: string) => h("div", { class: "m-co-kpi" }, h("b", {}, v), h("small", {}, l));
  c.on("bizagents", (m: any) => {
    st = { ...st, ...m, company: { ...(st.company || {}), ...(m.company || {}) } };
    if (open && m.message && m.req) toast(String(m.message).slice(0, 140), m.ok === false ? "error" : "ok", 4000);
    paint();
  });
  c.on("agent_activity", (m: any) => { if (String(m.key || "").startsWith("biz") && m.state !== "tool") c.send("bizagents_get"); });
  c.onStatus((s) => { if (s === "open") c.send("bizagents_get"); });
  window.addEventListener("popstate", () => { if (open) { open = false; paint(); } });
  paint();
  return card;
}
