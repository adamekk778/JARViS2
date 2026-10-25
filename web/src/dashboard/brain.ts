// Dashboard → Paměť a projekty (OMEGA §04 Ultra Memory, §4.4 Personal AI Brain): search over everything JARVIS
// stores, the timeline of a day, projects with their own memory and "navázat", contradictions to settle, and the
// facts by category with their source. Everything here can be corrected or deleted.
import { hero, HEROES } from "../shared/hero";
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";

const KIND: Record<string, [string, string]> = {
  chat: ["chat-circle-dots", "Chat"], fact: ["brain", "Paměť"], dictation: ["microphone", "Diktování"], call: ["record", "Hovor"],
  mission: ["list-checks", "Mise"], apps: ["app-window", "Aplikace"],
};
const when = (ts: number) => new Date(ts * 1000).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" });
const mark = (s: string) => {   // the FTS snippet marks hits with [ ]
  const out: (HTMLElement | string)[] = [];
  s.split(/(\[[^\]]*\])/).forEach((part) => out.push(part.startsWith("[") ? h("mark", {}, part.slice(1, -1)) : part));
  return out;
};

export function buildBrain(client: JarvisClient) {
  let k: any = { facts: [], conflicts: [], projects: [], current: "", embed: "" };

  // ---- search
  const q = h("input", { class: "input", type: "search", placeholder: "Co hledáš? (nevadí jiný tvar slova ani bez háčků)", "aria-label": "Hledat v paměti" }) as HTMLInputElement;
  const meaning = h("input", { type: "checkbox", "aria-label": "Podle významu" }) as HTMLInputElement;
  const hits = h("div", { class: "rs-out" });
  const search = () => { if (q.value.trim()) { hits.replaceChildren(h("p", { class: "muted" }, "Hledám…")); client.send("knowledge_search", { q: q.value.trim(), meaning: meaning.checked }); } };
  q.onkeydown = (e) => { if (e.key === "Enter") search(); };
  const meaningLabel = h("label", { class: "rs-check" }, meaning, "i podle významu");
  const row = (x: any, score?: number) => h("li", { class: "br-hit" },
    h("span", { class: "br-kind" }, icon(KIND[x.kind]?.[0] || "circle"), KIND[x.kind]?.[1] || x.kind),
    h("div", {}, h("strong", {}, x.title || ""), h("p", {}, ...mark(x.snippet || "")),
      h("span", { class: "muted" }, when(x.ts) + (score != null ? ` · shoda ${Math.round(score * 100)} %` : ""))));
  client.on("knowledge_hits", (m) => {
    hits.replaceChildren(
      m.hits.length ? h("ul", { class: "rs-list" }, ...m.hits.map((x: any) => row(x))) : h("p", { class: "muted" }, "Nic jsem nenašel."),
      m.meaning?.length ? h("h4", {}, "Podobné významem") : "", m.meaning?.length ? h("ul", { class: "rs-list" }, ...m.meaning.map((x: any) => row(x, x.score))) : "");
  });

  // ---- timeline
  const day = h("input", { class: "input sm", type: "date", "aria-label": "Den", value: new Date().toISOString().slice(0, 10) }) as HTMLInputElement;
  const tl = h("ol", { class: "br-timeline" });
  day.onchange = () => client.send("timeline_get", { day: day.value });
  client.on("timeline", (m) => {
    tl.replaceChildren(...(m.events.length ? m.events.map((e: any) => h("li", {}, h("time", {}, new Date(e.ts * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })),
      icon(KIND[e.kind]?.[0] || "circle"), h("span", {}, e.text))) : [h("li", { class: "muted" }, "Ten den jsem nic nezaznamenal.")]));
  });

  // ---- projects
  const projBox = h("div", { class: "card sec-card" });
  const resumeBox = h("div", { class: "rs-out" });
  const pName = h("input", { class: "input", placeholder: "název projektu", "aria-label": "Název projektu" }) as HTMLInputElement;
  const pFolder = h("input", { class: "input", placeholder: "složka na disku (volitelné)", "aria-label": "Složka projektu" }) as HTMLInputElement;
  const renderProjects = () => {
    projBox.replaceChildren(
      h("p", { class: "help" }, k.current ? `Aktuální projekt: ${k.current}. JARVIS při odpovědích použije jen jeho fakta (a obecná).` : "Žádný projekt není aktuální – JARVIS používá jen obecná fakta."),
      k.projects.length ? h("ul", { class: "sec-list" }, ...k.projects.map((p: any) => h("li", {},
        h("span", {}, h("strong", {}, p.name), p.note ? h("span", { class: "muted" }, ` – ${p.note}`) : ""),
        h("span", { class: "row-actions" },
          h("button", { class: "btn sm", type: "button", onclick: () => client.send("project_set", { action: "resume", name: p.name }) }, icon("play"), "Navázat"),
          p.name === k.current ? h("button", { class: "btn ghost sm", type: "button", onclick: () => client.send("project_set", { action: "switch", name: "" }) }, "Bez projektu")
            : h("button", { class: "btn ghost sm", type: "button", onclick: () => client.send("project_set", { action: "switch", name: p.name }) }, "Přepnout"),
          h("button", { class: "btn ghost sm", type: "button", title: "Archivovat", "aria-label": `Archivovat ${p.name}`, onclick: () => { if (confirm(`Archivovat projekt ${p.name}?`)) client.send("project_set", { action: "archive", name: p.name }); } }, icon("archive")))))) : "",
      h("div", { class: "list-add" }, pName, pFolder, h("button", { class: "btn primary", type: "button", onclick: () => {
        if (!pName.value.trim()) { pName.focus(); return; }
        client.send("project_set", { action: "create", name: pName.value.trim(), folder: pFolder.value.trim() }); pName.value = ""; pFolder.value = "";
      } }, icon("plus"), "Nový projekt")),
      resumeBox);
  };
  client.on("project_resume", (r) => {
    resumeBox.replaceChildren(h("div", { class: "card br-resume" },
      h("h4", {}, `Kde jsme skončili: ${r.project.name}`),
      r.conversations.length ? h("p", {}, `Poslední konverzace: „${r.conversations[0].title}“ (${when(r.conversations[0].updated)})`) : "",
      r.last_answer ? h("p", { class: "muted" }, r.last_answer) : "",
      r.tasks.length ? h("p", {}, "Mise: " + r.tasks.map((t: any) => `${t.goal} (${t.status})`).join(", ")) : "",
      r.files.length ? h("p", {}, "Nedávné soubory: " + r.files.map((f: any) => f.path.split(/[\\/]/).pop()).join(", ")) : "",
      r.facts.length ? h("p", {}, "Vím: " + r.facts.join("; ")) : "",
      h("p", {}, h("strong", {}, "Další krok: "), r.next)));
  });

  // ---- conflicts + facts by category
  const conflictBox = h("div", { class: "card sec-card" });
  const factsBox = h("div", { class: "card sec-card" });
  const newFact = h("input", { class: "input", placeholder: "Co si mám zapamatovat?", "aria-label": "Nový fakt" }) as HTMLInputElement;
  const render = () => {
    renderProjects();
    conflictBox.replaceChildren(k.conflicts.length ? h("ul", { class: "sec-list" }, ...k.conflicts.map((c: any) => h("li", { class: "br-conflict" },
      h("span", {}, `Dřív: „${c.old_text}“ · nově: „${c.new_text}“`),
      h("span", { class: "row-actions" },
        h("button", { class: "btn sm", type: "button", onclick: () => client.send("conflict_resolve", { id: c.id, keep: "new" }) }, "Platí nové"),
        h("button", { class: "btn ghost sm", type: "button", onclick: () => client.send("conflict_resolve", { id: c.id, keep: "old" }) }, "Platí staré"),
        h("button", { class: "btn ghost sm", type: "button", onclick: () => client.send("conflict_resolve", { id: c.id, keep: "both" }) }, "Obojí"))))) : h("p", { class: "muted" }, "Žádné rozpory."));
    const cats: Record<string, any[]> = {};
    for (const f of k.facts) (cats[f.category || "Ostatní"] ||= []).push(f);
    factsBox.replaceChildren(
      h("div", { class: "list-add" }, newFact, h("button", { class: "btn", type: "button", onclick: () => {
        if (newFact.value.trim()) { client.send("fact_update", { text: newFact.value.trim(), full: true }); newFact.value = ""; }
      } }, icon("plus"), "Zapamatovat")),
      ...Object.entries(cats).sort((a, b) => b[1].length - a[1].length).map(([cat, list]) => h("details", { class: "rs-area", open: true },
        h("summary", {}, h("span", {}, cat), h("span", { class: "muted" }, String(list.length))),
        h("ul", { class: "sec-list" }, ...list.map((f: any) => h("li", {},
          h("span", {}, f.text, f.project ? h("span", { class: "br-proj" }, f.project) : ""),
          h("span", { class: "row-actions" }, h("span", { class: "muted br-src" }, f.source || ""),
            h("button", { class: "btn ghost sm", type: "button", "aria-label": `Smazat ${f.text}`, onclick: () => client.send("fact_delete", { id: f.id, full: true }) }, icon("trash")))))))),
      k.facts.length ? "" : h("p", { class: "muted" }, "Zatím si nic nepamatuji. Řekni „zapamatuj si, že…“."));
  };
  client.on("knowledge", (m) => { k = { ...k, ...m }; render(); });
  client.on("error", (m) => { if (/projekt/i.test(m.message || "")) toast(m.message, "error"); });

  const el = h("section", { class: "tasks-view brain-view" },
    hero(HEROES.knowledge, "Paměť a projekty", "Co JARVIS ví, odkud to ví a kde jste skončili. Všechno jde najít, opravit i smazat – a v soukromém režimu se nic neukládá.", []),
    h("h2", { class: "group-label" }, "Hledat ve všem"), h("div", { class: "card sec-card" }, h("div", { class: "list-add" }, q, h("button", { class: "btn primary", type: "button", onclick: search }, icon("magnifying-glass"), "Hledat")), meaningLabel, hits),
    h("h2", { class: "group-label" }, "Projekty"), projBox,
    h("h2", { class: "group-label" }, "Časová osa"), h("div", { class: "card sec-card" }, day, tl),
    h("h2", { class: "group-label" }, "Rozpory v paměti"), conflictBox,
    h("h2", { class: "group-label" }, "Co o tobě vím"), factsBox);
  return { el, show: () => {
    client.send("knowledge_get"); client.send("timeline_get", { day: day.value });
    meaningLabel.title = k.embed ? `Model: ${k.embed}` : "Potřebuje místní model na embeddingy v Ollamě (např. nomic-embed-text).";
  } };
}
