// Dashboard → Bezpečí a soukromí (OMEGA §5, §17, §51): read-only mode, limits of missions and AI spending,
// temporary permissions, the private mode, retention, what JARVIS stores, the microphone log, exports, the encrypted
// backup and the complete reset. Everything that loosens safety is only here, never by voice.
import { hero, HEROES } from "../shared/hero";
import { fmtSize, h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";

const PERM_LABEL: Record<string, string> = {
  apps: "Aplikace a okna", input: "Myš a klávesnice", screen: "Obrazovka", files_read: "Čtení souborů",
  files_write: "Změny souborů", shell: "PowerShell a kód", network: "Internet", system: "Systém a napájení", home: "Chytrá domácnost",
};

export function buildSecurity(client: JarvisClient) {
  let s: any = {};
  const set = (patch: any) => client.send("settings_set", { patch });
  const sw = (title: string, desc: string, get: () => boolean, put: (v: boolean) => void) => {
    const inp = h("input", { type: "checkbox", role: "switch", "aria-label": title }) as HTMLInputElement;
    inp.checked = get();
    inp.onchange = () => put(inp.checked);
    return h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, title), h("span", { class: "help" }, desc)),
      h("span", { class: "switch" }, inp, h("span")));
  };
  const num = (title: string, desc: string, val: number, min: number, max: number, put: (v: number) => void, step = 1) => {
    const inp = h("input", { class: "input sm", type: "number", min, max, step, value: val, "aria-label": title }) as HTMLInputElement;
    inp.onchange = () => put(Math.max(min, Math.min(max, +inp.value || 0)));
    return h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, title), h("span", { class: "help" }, desc)), inp);
  };

  const safety = h("div", { class: "group" });
  const usageBox = h("div", { class: "card sec-card" });
  const grantsBox = h("div", { class: "card sec-card" });
  const privacyBox = h("div", { class: "group" });
  const invBox = h("div", { class: "card sec-card" });
  const micBox = h("div", { class: "card sec-card" });
  const dataBox = h("div", { class: "card sec-card" });

  function renderSettings() {
    const L = s.limits || {}, P = s.privacy || {};
    const allow = h("input", { class: "input", value: (L.app_allowlist || []).join(", "), placeholder: "prázdné = kdekoli, např. Poznámkový blok, Chrome",
      "aria-label": "Povolené aplikace" }) as HTMLInputElement;
    allow.onchange = () => set({ limits: { app_allowlist: allow.value.split(",").map((x) => x.trim()).filter(Boolean) } });
    safety.replaceChildren(
      sw("Režim jen pro čtení", "JARVIS jen čte a radí: nemění soubory, nastavení, domácnost ani nic neodesílá. Hlasem ho vypnout nejde.",
        () => !!L.read_only, (v) => set({ limits: { read_only: v } })),
      sw("Dvojí potvrzení", "Mazání, vypnutí PC, odemčení dveří a další nevratné akce se zeptají dvakrát.",
        () => L.double_confirm !== false, (v) => set({ limits: { double_confirm: v } })),
      num("Mise: nejvýš akcí", "Kolik kroků smí jedna mise udělat, než ji JARVIS zastaví.", L.mission_max_actions ?? 60, 1, 1000, (v) => set({ limits: { mission_max_actions: v } })),
      num("Mise: nejdéle minut", "Jak dlouho smí jedna mise běžet.", L.mission_max_minutes ?? 30, 1, 1440, (v) => set({ limits: { mission_max_minutes: v } })),
      h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Myš a klávesnice jen v aplikacích"),
        h("span", { class: "help" }, "Když tu něco napíšeš, JARVIS bude klikat a psát jen v těchto aplikacích.")), allow));
    privacyBox.replaceChildren(
      sw("Soukromý režim", "Nová konverzace se drží jen v paměti a nic se nezapíše na disk (ani fakta). Po vypnutí zmizí.",
        () => !!P.private_mode, (v) => set({ privacy: { private_mode: v } })),
      num("Mazat data starší než (dní)", "Konverzace, mise, záznamy akcí, diktování a spotřebu AI. 0 = nemazat. Fakta a nastavení zůstávají.",
        P.keep_days ?? 0, 0, 3650, (v) => set({ privacy: { keep_days: v } })));
  }

  function renderUsage(m: any) {
    const t = m.today, L = s.limits || {};
    const hist: any[] = m.history || [];
    const max = Math.max(1, ...hist.map((d) => d.tok_in + d.tok_out));
    const prices = h("div", { class: "sec-prices" }, ...((s.brain?.providers || []) as any[]).map((p) => {
      const inp = h("input", { class: "input sm", type: "number", min: 0, step: 0.1, value: (L.prices || {})[p.id] ?? 0, "aria-label": `Cena ${p.id}` }) as HTMLInputElement;
      inp.onchange = () => set({ limits: { prices: { ...(L.prices || {}), [p.id]: Math.max(0, +inp.value || 0) } } });
      return h("label", {}, h("span", {}, p.name || p.id), inp, h("span", { class: "muted" }, `${L.currency || "Kč"} / 1M tokenů`));
    }));
    usageBox.replaceChildren(
      h("div", { class: "sec-big" }, h("strong", {}, `${t.tokens.toLocaleString("cs-CZ")}`), h("span", {}, "tokenů dnes (odhad)"),
        h("strong", {}, `${t.cost.toLocaleString("cs-CZ")} ${t.currency}`), h("span", {}, "cena dnes (odhad)")),
      h("div", { class: "sec-bars", "aria-label": "Spotřeba za 30 dní" }, ...hist.map((d) => h("i", { title: `${d.day}: ${d.tok_in + d.tok_out} tokenů`,
        style: { height: `${Math.max(3, ((d.tok_in + d.tok_out) / max) * 100)}%` } }))),
      (t.rows || []).length ? h("ul", { class: "sec-list" }, ...t.rows.map((r: any) => h("li", {}, h("span", {}, `${r.provider} · ${r.model}`),
        h("span", { class: "muted" }, `${r.calls}× · ${(r.tok_in + r.tok_out).toLocaleString("cs-CZ")} tokenů${r.images ? ` · ${r.images} obrázků` : ""}`)))) : h("p", { class: "muted" }, "Dnes zatím nic."),
      num("Denní limit tokenů", "0 = bez limitu. Po překročení odpovídají jen bezplatné a místní modely.", L.ai_daily_tokens ?? 0, 0, 1e9, (v) => set({ limits: { ai_daily_tokens: v } }), 1000),
      num(`Denní limit ceny (${L.currency || "Kč"})`, "0 = bez limitu. Placení poskytovatelé se po limitu přeskočí.", L.ai_daily_cost ?? 0, 0, 1e6, (v) => set({ limits: { ai_daily_cost: v } }), 1),
      h("details", {}, h("summary", {}, "Ceny poskytovatelů (pro odhad)"), prices),
      h("p", { class: "help" }, "Poskytovatelé nehlásí přesnou spotřebu při streamování, proto jde o odhad (znaky ÷ 4). Co se kam posílá, vidíš tady po poskytovatelích."));
  }

  function renderGrants(grants: Record<string, number>) {
    const P = s.permissions || {};
    const off = Object.keys(PERM_LABEL).filter((k) => P[k] === false);
    grantsBox.replaceChildren(
      h("p", { class: "help" }, "Vypnuté oprávnění můžeš na chvíli povolit – po čase se samo zase zavře. JARVIS si ho sám povolit nemůže."),
      off.length ? h("ul", { class: "sec-list" }, ...off.map((k) => {
        const until = grants[k];
        return h("li", {}, h("span", {}, PERM_LABEL[k]), until
          ? h("span", { class: "row-actions" }, h("span", { class: "muted" }, `povoleno do ${new Date(until * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}`),
            h("button", { class: "btn ghost sm", type: "button", onclick: () => client.send("perm_grant", { perm: k, minutes: 0 }) }, "Zavřít hned"))
          : h("span", { class: "row-actions" }, ...[15, 60].map((mins) => h("button", { class: "btn sm", type: "button",
            onclick: () => client.send("perm_grant", { perm: k, minutes: mins }) }, `Povolit na ${mins} min`))));
      })) : h("p", { class: "muted" }, "Všechna oprávnění jsou zapnutá (vypínají se v Nastavení → Oprávnění)."));
  }

  function renderInventory(inv: any) {
    invBox.replaceChildren(
      h("p", { class: "help" }, `Všechno je v ${inv.base}. Hesla a klíče: ${inv.secrets_where}.`),
      h("table", { class: "task-actions" }, h("tbody", {},
        ...inv.database.map((r: any) => h("tr", {}, h("td", {}, r.what), h("td", {}, String(r.count)))),
        ...inv.folders.map((f: any) => h("tr", {}, h("td", {}, `složka ${f.folder}`), h("td", {}, fmtSize(f.bytes)))))));
  }

  function renderMic(mic: any) {
    micBox.replaceChildren(
      h("p", {}, mic.now ? "🎙️ Mikrofon právě naslouchá." : `Za 7 dní naslouchal ${mic.sessions.length}× (celkem ${Math.round(mic.seconds / 60)} min).`),
      h("p", { class: "muted" }, mic.camera),
      mic.sessions.length ? h("ul", { class: "sec-list" }, ...mic.sessions.slice(0, 10).map((x: any) => h("li", {},
        h("span", {}, new Date(x.start * 1000).toLocaleString("cs-CZ")), h("span", { class: "muted" }, `${Math.round(x.end - x.start)} s`)))) : "");
  }

  const pw = h("input", { class: "input", type: "password", placeholder: "Heslo zálohy (aspoň 8 znaků)", autocomplete: "new-password", "aria-label": "Heslo zálohy" }) as HTMLInputElement;
  const rPath = h("input", { class: "input", placeholder: "Cesta k souboru .jarvisvault", "aria-label": "Cesta k záloze" }) as HTMLInputElement;
  const rPw = h("input", { class: "input", type: "password", placeholder: "Heslo", autocomplete: "off", "aria-label": "Heslo k obnově" }) as HTMLInputElement;
  dataBox.replaceChildren(
    h("div", { class: "btn-row" },
      h("button", { class: "btn", type: "button", onclick: () => client.send("audit_export") }, icon("file-csv"), "Exportovat audit (CSV + JSON)"),
      h("button", { class: "btn", type: "button", onclick: () => { if (confirm("Uložit všechna tvoje data JARVISe do ZIP v Dokumentech? (bez hesel a klíčů)")) client.send("data_export"); } }, icon("download-simple"), "Export všech dat")),
    h("h4", {}, "Šifrovaná záloha"),
    h("div", { class: "list-add" }, pw, h("button", { class: "btn primary", type: "button", onclick: () => {
      if (pw.value.length < 8) { toast("Heslo musí mít aspoň 8 znaků", "error"); return; }
      client.send("backup_create", { password: pw.value }); pw.value = "";
    } }, icon("lock-key"), "Vytvořit")),
    h("details", {}, h("summary", {}, "Obnovit ze zálohy"), h("div", { class: "list-add" }, rPath, rPw,
      h("button", { class: "btn", type: "button", onclick: () => { client.send("backup_restore", { path: rPath.value.trim(), password: rPw.value }); rPw.value = ""; } }, "Rozbalit")),
      h("p", { class: "help" }, "Záloha se rozbalí do nové složky vedle souboru – živá data se nepřepisují.")),
    h("h4", {}, "Úplné smazání"),
    h("p", { class: "help" }, "Smaže historii, paměť, mise, záznamy a soubory JARVISe a odpojí spárované telefony. Nastavení zůstane."),
    h("button", { class: "btn danger", type: "button", onclick: () => {
      const w = prompt("Úplně smazat všechna data JARVISe? Nejde to vrátit. Napiš SMAZAT:");
      if (w === "SMAZAT") client.send("reset_all", { confirm: "SMAZAT" });
    } }, icon("trash"), "Smazat všechna data"));

  client.on("usage", renderUsage);
  client.on("privacy", (m) => { if (m.inventory) renderInventory(m.inventory); if (m.mic) renderMic(m.mic); if (m.grants) renderGrants(m.grants); });
  client.on("export_done", (m) => toast(`${{ audit: "Audit", data: "Export", backup: "Záloha", restore: "Obnova", reset: "Smazáno" }[m.kind as string] || "Hotovo"}: ${m.path || ""} (${m.detail})`, "ok", 8000));
  const refresh = () => { client.send("usage_get"); client.send("privacy_get"); };
  const sync = (st: any) => { s = st || {}; renderSettings(); };
  client.on("welcome", (m) => sync(m.settings));
  client.on("settings_changed", (m) => sync(m.settings));
  renderGrants({});

  const el = h("section", { class: "tasks-view security-view" },
    hero(HEROES.security, "Bezpečí a soukromí", "Co JARVIS smí, kolik smí utratit, co si pamatuje – a jak to všechno vypnout, vyexportovat nebo smazat.", [
      h("button", { class: "btn", type: "button", onclick: refresh }, icon("arrow-clockwise"), "Obnovit")]),
    h("h2", { class: "group-label" }, "Bezpečí"), safety,
    h("h2", { class: "group-label" }, "Dočasná oprávnění"), grantsBox,
    h("h2", { class: "group-label" }, "Spotřeba AI"), usageBox,
    h("h2", { class: "group-label" }, "Soukromí"), privacyBox,
    h("h2", { class: "group-label" }, "Co JARVIS ukládá"), invBox,
    h("h2", { class: "group-label" }, "Mikrofon a kamera"), micBox,
    h("h2", { class: "group-label" }, "Export, záloha, smazání"), dataBox);
  return { el, show: refresh };
}
