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
  // 3.14 návrh 8: the model for search by meaning inside JARVIS (no Ollama needed)
  const embedBox = h("span", { class: "muted" });
  client.on("embedder", (m: any) => {
    if (m.progress != null && m.progress < 1) { embedBox.textContent = `Stahuju model… ${Math.round(m.progress * 100)} %`; return; }
    embedBox.replaceChildren(m.ready ? "Hledání podle významu funguje i bez Ollamy." : m.libs === false ? "" :
      h("button", { class: "btn sm", type: "button", onclick: () => {
        if (confirm(`Stáhnout model pro hledání podle významu (${m.size_mb} MB)? Pak funguje bez internetu i bez Ollamy.`)) client.send("embedder_download");
      } }, icon("download-simple"), `Hledat podle významu i bez Ollamy (${m.size_mb} MB)`));
  });
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

  // ---- 3.14 Mozek+: learned rules, 👍/👎 by AI, character and behaviour switches
  const rulesBox = h("div", { class: "card sec-card" });
  const newRule = h("input", { class: "input", placeholder: "Např. Hudbu pouštěj na Spotify, ne na YouTube.", "aria-label": "Nové pravidlo" }) as HTMLInputElement;
  client.on("rules", (m) => {
    if (m.learned) toast(`Naučil jsem se: ${m.learned.text}`, "ok", 6000);
    rulesBox.replaceChildren(
      h("p", { class: "help" }, "Když JARVISe opravíš („ne, myslel jsem…“), napíše si z toho pravidlo a příště ho dodrží. Tady je vidíš a můžeš smazat."),
      m.items?.length ? h("ul", { class: "sec-list" }, ...m.items.map((r: any) => h("li", {},
        h("span", {}, r.text, r.source && r.source !== "ručně" ? h("span", { class: "muted" }, ` – z opravy „${r.source}“`) : ""),
        h("button", { class: "btn ghost sm", type: "button", "aria-label": `Smazat pravidlo ${r.text}`, onclick: () => client.send("rule_delete", { id: r.id }) }, icon("trash"))))) :
        h("p", { class: "muted" }, "Zatím žádné pravidlo."),
      h("div", { class: "list-add" }, newRule, h("button", { class: "btn", type: "button", onclick: () => {
        if (newRule.value.trim()) { client.send("rule_add", { text: newRule.value.trim() }); newRule.value = ""; }
      } }, icon("plus"), "Přidat pravidlo")));
  });
  const rateBox = h("div", { class: "card sec-card" });
  const TIER: Record<string, string> = { fast: "rychlé otázky", normal: "běžné požadavky", strong: "těžké úkoly", "–": "starší odpovědi" };
  client.on("ratings", (m) => {
    rateBox.replaceChildren(
      h("p", { class: "help" }, m.total ? `Ohodnotil jsi ${m.total} odpovědí, ${m.good} 👍.` : "Pod každou odpovědí v chatu je 👍 a 👎 – z toho JARVIS pozná, která AI je na co nejlepší."),
      ...Object.entries(m.best || {}).map(([t, p]) => h("p", {}, h("strong", {}, `Na ${TIER[t] || t}: `), String(p))),
      m.rows?.length ? h("ul", { class: "sec-list" }, ...m.rows.slice(0, 12).map((r: any) => h("li", {},
        h("span", {}, `${r.provider}${r.model ? " · " + r.model : ""} – ${TIER[r.tier] || r.tier}`),
        h("span", { class: "muted" }, `${Math.round(r.rate * 100)} % 👍 z ${r.n}`)))) : "");
  });
  // 3.14 návrhy 52–57: clean-up, imports, the data folder encrypted
  const cleanBox = h("div", { class: "card sec-card" });
  client.on("memory_cleanup", (m: any) => {
    const ids: number[] = [...(m.duplicates || []).map((d: any) => d.drop.id), ...(m.expired || []).map((e: any) => e.id)];
    cleanBox.replaceChildren(
      ids.length ? h("p", { class: "help" }, "Skoro stejné fakty (novější zůstane) a fakty, jejichž termín prošel:") : h("p", { class: "muted" }, "V paměti není co uklízet."),
      ...(m.duplicates || []).map((d: any) => h("div", { class: "row" }, h("span", {}, `„${d.drop.text}“ ≈ „${d.keep.text}“`),
        h("button", { class: "btn ghost sm", type: "button", onclick: () => client.send("memory_cleanup_apply", { ids: [d.drop.id] }) }, "Sloučit"))),
      ...(m.expired || []).map((e: any) => h("div", { class: "row" }, h("span", {}, `„${e.text}“ (prošlé)`),
        h("button", { class: "btn ghost sm", type: "button", onclick: () => client.send("memory_cleanup_apply", { ids: [e.id] }) }, "Smazat"))),
      ids.length > 1 ? h("button", { class: "btn", type: "button", onclick: () => { client.send("memory_cleanup_apply", { ids }); client.send("knowledge_get"); } }, icon("broom"), "Uklidit vše") : "",
      h("div", { class: "row" }, h("span", {}, m.encrypted === "on" ? "🔒 Data JARVISe jsou zašifrovaná (EFS)." : "Data JARVISe zašifrovat klíčem tvého přihlášení do Windows (EFS)"),
        m.encrypted === "on" || m.encrypted === "unsupported" ? "" : h("button", { class: "btn sm", type: "button", onclick: () => {
          if (confirm("Zašifrovat složku s daty JARVISe (EFS)? Zálohuj si pak certifikát EFS, jinak po přeinstalaci Windows data neotevřeš.")) client.send("data_encrypt");
        } }, icon("lock-simple"), "Zašifrovat")));
  });
  client.on("data_encrypt_result", (m: any) => { toast(m.message, m.ok ? "ok" : "error", 8000); client.send("memory_cleanup_get"); });
  const importBox = h("div", { class: "card sec-card" });
  const importFile = h("input", { type: "file", accept: ".json,.zip", "aria-label": "Soubor k importu" }) as HTMLInputElement;
  let importAtt = "";
  importFile.onchange = async () => {
    const f = importFile.files?.[0]; if (!f) return;
    try { const a = await client.upload(f, f.name); importAtt = a.id; client.send("memory_import_preview", { attachment_id: a.id }); }
    catch (e) { toast(`Nahrání selhalo: ${e}`, "error"); }
  };
  const importOut = h("div", {});
  client.on("memory_import", (m: any) => {
    if (m.done) { importOut.replaceChildren(h("p", {}, `Načteno ${m.done.imported} zpráv/poznámek do ${m.done.conversations} konverzací (složka Import).`)); return; }
    const p = m.preview;
    importOut.replaceChildren(h("p", {}, p.kind === "chat" ? `${p.conversations} konverzací, ${p.messages} zpráv` : `${p.notes} poznámek`, ": ", p.titles.slice(0, 5).join(", ")),
      h("button", { class: "btn primary", type: "button", onclick: () => client.send("memory_import_run", { attachment_id: importAtt, source: p.kind === "chat" ? "Import" : "Keep" }) }, icon("download-simple"), "Načíst"));
  });
  importBox.append(h("p", { class: "help" }, "Export z ChatGPT nebo Claude (conversations.json nebo ZIP) a poznámky Google Keep (ZIP z Google Takeout). Nejdřív uvidíš, co se načte."), importFile, importOut);
  const behaveBox = h("div", { class: "card sec-card" });
  const TRAIT_LABEL: [string, string, [string, string, string]][] = [
    ["humor", "Humor", ["žádný", "občas", "hodně"]], ["formal", "Oslovení", ["tykání", "normálně", "formálně"]],
    ["brevity", "Délka odpovědí", ["co nejkratší", "normální", "podrobné"]]];
  const FLAGS: [string, string][] = [
    ["quick_preface", "U těžké otázky nahlas hned jedna věta, co dělám (rychlý model), než doběhne odpověď"],
    ["learn_corrections", "Učit se z oprav („ne, myslel jsem…“)"],
    ["verify_answers", "Odpověď z webu porovnat se zdroji a označit, co v nich není"],
    ["second_opinion", "U peněz, zdraví, práva a mazání odpovídat opatrně a ověřit u dalších AI"],
    ["private_local", "Hesla, zdraví a bankovní údaje posílat jen AI v tomhle PC (když běží)"]];
  client.on("settings", (m) => {
    const s = m.settings; if (!s?.general || !s?.brain) return;
    const tr = s.general.traits || {};
    behaveBox.replaceChildren(
      ...TRAIT_LABEL.map(([key, label, opts]) => h("div", { class: "row" }, h("span", {}, label),
        h("select", { "aria-label": label, onchange: (e: Event) => client.send("settings_set", { patch: { general: { traits: { ...tr, [key]: Number((e.target as HTMLSelectElement).value) } } } }) },
          ...opts.map((o, i) => h("option", { value: String(i), selected: Number(tr[key] ?? 1) === i }, o))))),
      ...FLAGS.map(([key, label]) => h("label", { class: "row" }, h("span", {}, label),
        h("input", { type: "checkbox", checked: s.brain[key] !== false, onchange: (e: Event) => client.send("settings_set", { patch: { brain: { [key]: (e.target as HTMLInputElement).checked } } }) }))),
      h("div", { class: "row" }, h("span", {}, `Rozpočet jedné mise na placené AI (${s.limits?.currency || "Kč"}, 0 = bez limitu)`),
        h("input", { class: "input sm", type: "number", min: "0", step: "1", value: String(s.limits?.mission_max_cost ?? 0), "aria-label": "Rozpočet mise",
          onchange: (e: Event) => client.send("settings_set", { patch: { limits: { mission_max_cost: Number((e.target as HTMLInputElement).value) || 0 } } }) })));
  });
  client.on("error", (m) => { if (/projekt/i.test(m.message || "")) toast(m.message, "error"); });

  const el = h("section", { class: "tasks-view brain-view" },
    hero(HEROES.knowledge, "Paměť a projekty", "Co JARVIS ví, odkud to ví a kde jste skončili. Všechno jde najít, opravit i smazat – a v soukromém režimu se nic neukládá.", []),
    h("h2", { class: "group-label" }, "Hledat ve všem"), h("div", { class: "card sec-card" }, h("div", { class: "list-add" }, q, h("button", { class: "btn primary", type: "button", onclick: search }, icon("magnifying-glass"), "Hledat")), meaningLabel, embedBox, hits),
    h("h2", { class: "group-label" }, "Projekty"), projBox,
    h("h2", { class: "group-label" }, "Časová osa"), h("div", { class: "card sec-card" }, day, tl),
    h("h2", { class: "group-label" }, "Rozpory v paměti"), conflictBox,
    h("h2", { class: "group-label" }, "Co o tobě vím"), factsBox,
    h("h2", { class: "group-label" }, "Naučená pravidla"), rulesBox,
    h("h2", { class: "group-label" }, "Povaha a chování"), behaveBox,
    h("h2", { class: "group-label" }, "Hodnocení odpovědí"), rateBox,
    h("h2", { class: "group-label" }, "Úklid paměti a šifrování"), cleanBox,
    h("h2", { class: "group-label" }, "Import z jiných AI a poznámek"), importBox);
  return { el, show: () => {
    client.send("knowledge_get"); client.send("timeline_get", { day: day.value });
    client.send("rules_get"); client.send("ratings_get"); client.send("settings_get");
    client.send("embedder_get"); client.send("memory_cleanup_get");
    meaningLabel.title = k.embed ? `Model: ${k.embed}` : "Potřebuje místní model na embeddingy v Ollamě (např. nomic-embed-text).";
  } };
}
