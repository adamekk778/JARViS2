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
  let editId = 0;                 // 3.13 the agent whose small editor is open
  let brief = "";
  let lastWidget = "";
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
      h("div", { class: "btn-row m-co-actions" },
        h("button", { type: "button", class: `btn ${n.paused ? "primary" : ""}`, onclick: () => { native.haptic(); c.send("bizpause_set", { paused: !n.paused }); } },
          icon(n.paused ? "play" : "pause", "ph-fill"), n.paused ? "Spustit firmu" : "Pozastavit vše"),
        h("button", { type: "button", class: "btn", onclick: () => { native.haptic(); brief = "…"; paint(); c.send("bizbrief_get"); } }, icon("megaphone-simple", "ph-fill"), "Co je nového?")),
      brief ? h("div", { class: "m-co-brief" }, h("p", {}, brief),
        brief !== "…" ? h("button", { type: "button", class: "btn", onclick: () => { try { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(brief); u.lang = "cs-CZ"; speechSynthesis.speak(u); } catch { /* no voice */ } } },
          icon("speaker-high"), "Přečíst nahlas") : "") : "",
      (st.goals || []).length ? h("h3", {}, "Cíle firmy") : "",
      ...(st.goals || []).slice(0, 6).map((g: Any) => h("div", { class: `m-co-goal ${g.pct == null ? "" : g.on_track ? "ok" : "warn"}` },
        h("div", {}, h("b", {}, g.name), h("small", {}, g.pct == null ? "zatím bez čísla" : `${g.pct} % · ${g.on_track ? "v plánu" : "pozadu"} · zbývá ${g.days_left} dní`)),
        h("i", { style: { "--p": `${Math.min(100, g.pct || 0)}%` } }))),
      props.length ? h("h3", {}, `Ke schválení (${props.length})`) : "",
      props.length > 1 ? h("div", { class: "btn-row" },
        h("button", { type: "button", class: "btn primary", onclick: () => {
          if (confirm(`Schválit a provést všech ${props.length} návrhů?`)) { native.haptic(); c.send("bizproposals_decide", { ids: props.map((p) => p.id), approve: true }); }
        } }, icon("checks", "ph-bold"), `Schválit vše (${props.length})`),
        h("button", { type: "button", class: "btn", onclick: () => { if (confirm(`Zamítnout všech ${props.length} návrhů?`)) c.send("bizproposals_decide", { ids: props.map((p) => p.id), approve: false }); } },
          "Zamítnout vše")) : "",
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
          isOpen ? h("div", { class: "m-co-agents" }, ...mine.flatMap((a) => [h("div", { class: "m-co-agent" },
            h("i", { class: `m-co-dot ${state(a)}` }),
            h("button", { type: "button", class: "m-co-aname", "aria-expanded": editId === a.id ? "true" : "false", onclick: () => { editId = editId === a.id ? 0 : a.id; paint(); } },
              h("b", {}, a.name), h("small", {}, `${a.when || ""} · naposledy ${ago(a.last_run)}`)),
            h("button", { type: "button", class: "icon-btn", "aria-label": `Spustit ${a.name}`, disabled: st.running?.includes(a.id),
              onclick: () => { native.haptic(); c.send("bizagent_run", { id: a.id }); toast(`${a.name} pracuje…`, "info"); } }, icon("play", "ph-fill"))),
            editId === a.id ? editor(a) : ""])) : "");
      }),
      (st.company?.runs || []).length ? h("h3", {}, "Poslední práce") : "",
      ...(st.company?.runs || []).slice(0, 8).map((r: Any) => h("div", { class: `m-co-run ${r.ok ? "" : "bad"}` },
        h("b", {}, r.agent), h("small", {}, ago(r.started)), h("p", {}, String(r.summary || "").split("\n")[0].slice(0, 160))))));
  };
  const kpi = (v: string, l: string) => h("div", { class: "m-co-kpi" }, h("b", {}, v), h("small", {}, l));
  // 3.13 the agent's small editor: on/off, when, the model, what starts it, 👍/👎 for its last work
  const editor = (a: Any) => {
    const quick = (changes: Any) => { native.haptic(); c.send("bizagent_quick", { id: a.id, changes }); };
    const when = h("select", { class: "input", "aria-label": "Kdy pracuje" },
      ...[["m", "Jen na pokyn"], ["e60", "Každou hodinu"], ["e120", "Každé 2 h"], ["e240", "Každé 4 h"], ["d07:30", "Denně v 7:30"], ["d09:00", "Denně v 9:00"],
        ["d18:00", "Denně v 18:00"], ["w0 08:00", "Každé pondělí v 8:00"]].map(([v, t]) => h("option", { value: v }, t))) as HTMLSelectElement;
    const cur = a.every_min ? `e${a.every_min}` : a.daily_at ? (a.daily_at.includes(" ") ? `w${a.daily_at}` : `d${a.daily_at}`) : "m";
    if (![...when.options].some((o) => o.value === cur)) when.prepend(h("option", { value: cur }, a.when || "Vlastní čas"));
    when.value = cur;
    when.onchange = () => {
      const v = when.value;
      quick(v === "m" ? { every_min: 0, daily_at: "" } : v[0] === "e" ? { every_min: Number(v.slice(1)), daily_at: "" } : { every_min: 0, daily_at: v.slice(1) });
    };
    const events = Object.entries(st.company?.events || {}) as [string, Any][];
    return h("div", { class: "m-co-edit" },
      h("label", { class: "m-co-switch" }, h("span", {}, "Zapnutý"),
        h("input", { type: "checkbox", role: "switch", checked: !!a.enabled, onchange: (e: Event) => quick({ enabled: (e.target as HTMLInputElement).checked }) })),
      h("label", { class: "m-co-field" }, h("span", {}, "Kdy pracuje"), when),
      h("div", { class: "m-co-chips" }, h("span", {}, "Model AI"),
        ...[["smart", "Chytrý"], ["fast", "Rychlý a levný"]].map(([k, t]) => h("button", { type: "button", class: `chip ${(a.tier || "smart") === k ? "on" : ""}`,
          onclick: () => quick({ tier: k }) }, t))),
      events.length ? h("div", { class: "m-co-chips" }, h("span", {}, "Spouštět hned při"),
        ...events.map(([k, ev]) => {
          const on = (a.triggers || []).includes(k);
          return h("button", { type: "button", class: `chip ${on ? "on" : ""}`, "aria-pressed": on ? "true" : "false",
            onclick: () => quick({ triggers: on ? a.triggers.filter((x: string) => x !== k) : [...(a.triggers || []), k] }) }, ev.label);
        })) : "",
      a.last_run_id ? h("div", { class: "m-co-chips" }, h("span", {}, "Poslední práce"),
        h("button", { type: "button", class: `chip ${a.last_rating === 1 ? "on" : ""}`, onclick: () => { native.haptic(); c.send("bizrun_rate", { agent: a.id, rating: a.last_rating === 1 ? 0 : 1 }); } }, "👍"),
        h("button", { type: "button", class: `chip ${a.last_rating === -1 ? "on" : ""}`, onclick: () => {
          const why = a.last_rating === -1 ? "" : prompt("Co bylo špatně? (nepovinné)");
          if (why !== null) c.send("bizrun_rate", { agent: a.id, rating: a.last_rating === -1 ? 0 : -1, note: why || "" });
        } }, "👎")) : "",
      a.last_result ? h("pre", { class: "m-co-res" }, String(a.last_result).slice(0, 600)) : "");
  };
  // 3.13 the home-screen widget: the first proposal with ✓ / ✕ (or how many wait)
  const pushWidget = () => {
    const props: Any[] = st.proposals || [];
    const p = props[0];
    const text = p ? `${props.length > 1 ? `${props.length}× ke schválení · ` : ""}${p.agent}: ${p.description}`.slice(0, 120) : "";
    const key = `${text}|${p?.id || ""}`;
    if (key !== lastWidget) { lastWidget = key; native.widgetBiz({ text, id: p ? String(p.id) : "" }); }
  };
  c.on("bizagents", (m: any) => {
    st = { ...st, ...m, company: { ...(st.company || {}), ...(m.company || {}) } };
    if (open && m.message && m.req) toast(String(m.message).slice(0, 140), m.ok === false ? "error" : "ok", 4000);
    pushWidget();
    paint();
  });
  c.on("bizbrief", (m: any) => { brief = String(m.text || ""); paint(); });
  window.addEventListener("jarvis-open-company", () => { open = true; c.send("bizagents_get"); paint(); });
  c.on("agent_activity", (m: any) => { if (String(m.key || "").startsWith("biz") && m.state !== "tool") c.send("bizagents_get"); });
  c.onStatus((s) => { if (s === "open") c.send("bizagents_get"); });
  window.addEventListener("popstate", () => { if (open) { open = false; paint(); } });
  paint();
  return card;
}
