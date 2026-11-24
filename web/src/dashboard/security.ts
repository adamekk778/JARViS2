// Dashboard → Bezpečí a soukromí (OMEGA §5, §17, §51): read-only mode, limits of missions and AI spending,
// temporary permissions, the private mode, retention, what JARVIS stores, the microphone log, exports, the encrypted
// backup and the complete reset. Everything that loosens safety is only here, never by voice.
import { hero, HEROES } from "../shared/hero";
import { fmtSize, h, icon, loading, toast } from "../shared/dom";
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

  const statsBox = h("pre", { class: "sec-pre", "data-no-tr": "", hidden: true });
  // 3.14 nouzové kontakty: who gets a text when you do not answer "Jsi v pořádku?"
  const contactsRow = (list: { name: string; phone: string }[]) => {
    const name = h("input", { class: "input", placeholder: "Jméno", "aria-label": "Jméno kontaktu" }) as HTMLInputElement;
    const phone = h("input", { class: "input", placeholder: "+420 …", "aria-label": "Telefon kontaktu", inputmode: "tel" }) as HTMLInputElement;
    return h("div", { class: "row-text sec-contacts" }, h("strong", {}, "Nouzové kontakty"),
      h("span", { class: "help" }, "Komu JARVIS napíše SMS (z tvého telefonu) i s polohou, když na nouzovou otázku neodpovíš."),
      ...list.map((x, i) => h("div", { class: "row" }, h("span", {}, `${x.name} · ${x.phone}`),
        h("button", { class: "icon-btn sm", type: "button", "aria-label": `Odebrat ${x.name}`,
          onclick: () => set({ privacy: { emergency_contacts: list.filter((_, k) => k !== i) } }) }, icon("trash")))),
      h("div", { class: "house-add" }, name, phone, h("button", { class: "btn sm", type: "button", onclick: () => {
        if (!name.value.trim() || !/[\d+]{6,}/.test(phone.value.replace(/\s/g, ""))) { toast("Vyplň jméno a telefon"); return; }
        set({ privacy: { emergency_contacts: [...list, { name: name.value.trim(), phone: phone.value.replace(/\s/g, "") }] } });
      } }, icon("plus"), "Přidat")));
  };
  const statsUrl = (val: string) => {
    const inp = h("input", { class: "input", value: val, placeholder: "https://… (prázdné = nic se neposílá)", "aria-label": "Adresa pro statistiky" }) as HTMLInputElement;
    inp.onchange = () => {
      const v = inp.value.trim();
      if (v && !v.startsWith("https://")) { toast("Adresa musí začínat https://"); return; }
      set({ privacy: { stats_url: v } });
    };
    return h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Kam se statistiky posílají"),
      h("span", { class: "help" }, "Adresa serveru autora JARVISe. Dokud je prázdná, neodejde nic ani se zapnutým přepínačem.")), inp);
  };
  client.on("stats_preview", (m: any) => { statsBox.hidden = false; statsBox.textContent = JSON.stringify(m.data, null, 2); });
  const safety = h("div", { class: "group" });
  const usageBox = h("div", { class: "card sec-card" });
  const grantsBox = h("div", { class: "card sec-card" });
  const privacyBox = h("div", { class: "group" });
  const invBox = h("div", { class: "card sec-card" });
  const micBox = h("div", { class: "card sec-card" });
  const dataBox = h("div", { class: "card sec-card" });

  function renderSettings() {
    const L = s.limits || {}, P = s.privacy || {}, T = s.tools || {};
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
        h("span", { class: "help" }, "Když tu něco napíšeš, JARVIS bude klikat a psát jen v těchto aplikacích.")), allow),
      // 3.14 návrh 10: the fenced Python
      sw("Omezené prostředí pro kód", "Python, který JARVIS spouští (výpočty, grafy), nesmí spouštět programy, zapisovat mimo svou složku ani použít víc než 2 GB paměti.",
        () => T.sandbox_code !== false, (v) => set({ tools: { sandbox_code: v } })),
      sw("Kód smí na internet", "Jen když kód potřebuje stahovat data sám. Jinak stahují nástroje JARVISe (bezpečnější).",
        () => !!T.sandbox_network, (v) => set({ tools: { sandbox_network: v } })));
    privacyBox.replaceChildren(
      sw("Soukromý režim", "Nová konverzace se drží jen v paměti a nic se nezapíše na disk (ani fakta). Po vypnutí zmizí.",
        () => !!P.private_mode, (v) => set({ privacy: { private_mode: v } })),
      num("Mazat data starší než (dní)", "Konverzace, mise, záznamy akcí, diktování a spotřebu AI. 0 = nemazat. Fakta a nastavení zůstávají.",
        P.keep_days ?? 0, 0, 3650, (v) => set({ privacy: { keep_days: v } })),
      // 3.14 návrh 117: anonymous statistics – off unless you switch them on, and you see exactly what would go out
      sw("Anonymní statistiky", "Jednou týdně: verze, které vestavěné nástroje se používají a jak často selhávají, rychlost AI a hlasu. Nikdy nic z toho, co říkáš, píšeš nebo máš v souborech.",
        () => !!P.share_stats, (v) => set({ privacy: { share_stats: v } })),
      statsUrl(P.stats_url || ""),
      // 3.14 ochrana a nouze
      sw("Dětský režim", "U PC je dítě: laskavá řeč, nic nevhodného, žádné nákupy, mazání, instalace, zámky ani alarm.",
        () => !!P.kids_mode, (v) => set({ privacy: { kids_mode: v } })),
      sw("Fotka při hlídání PC", "Když někdo použije PC, zatímco ho JARVIS hlídá, vyfotí ho webkamera a fotka přijde do chatu v telefonu.",
        () => !!P.guard_photo, (v) => set({ privacy: { guard_photo: v } })),
      sw("Týdenní bezpečnostní brífink", "V neděli večer: neznámá zařízení v síti, neúspěšná přihlášení, úniky e-mailů.",
        () => P.security_weekly !== false, (v) => set({ privacy: { security_weekly: v } })),
      hibpRow(client),
      sw("Paměť života", "Šifrovaný deník tvých dní u PC (aplikace a okna s časem, tvoje poznámky) – jen v tomhle PC, klíč v trezoru Windows. Hesla, bankovnictví a anonymní okna se nezapisují. Pak se můžeš zeptat „co jsem dělal minulé úterý“.",
        () => !!P.life_log, (v) => set({ privacy: { life_log: v } })),
      contactsRow(P.emergency_contacts || []),
      h("div", { class: "row" }, h("span", { class: "help" }, "Přesně tohle by se poslalo:"),
        h("button", { class: "btn sm", type: "button", onclick: () => client.send("stats_preview_get") }, icon("eye"), "Ukázat")),
      statsBox);
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

  // 3.14 návrhy 107, 109: what JARVIS looked at / touched today, and the guest mode
  const accessBox = h("div", { class: "card sec-card" }, loading());
  const KIND_ICON: Record<string, string> = { screen: "monitor", input: "cursor-click", camera: "camera", clipboard: "clipboard-text", injection: "warning" };
  client.on("access_log", (m: any) => {
    const rows: any[] = m.rows || [];
    accessBox.replaceChildren(
      h("div", { class: "row" }, h("span", {}, m.guest ? "Režim host je zapnutý – nic osobního se neukazuje." : "Režim host (u PC sedí někdo jiný)"),
        h("button", { class: `btn ${m.guest ? "primary" : ""} sm`, type: "button", onclick: () => {
          client.send("settings_set", { patch: { privacy: { guest_mode: !m.guest } } }); window.setTimeout(() => client.send("access_log_get"), 300);
        } }, icon(m.guest ? "user-minus" : "user-plus"), m.guest ? "Vypnout" : "Zapnout")),
      h("p", { class: "help" }, rows.length ? `Dnes: ${Object.entries(m.counts || {}).map(([k, n]) => `${({ screen: "obrazovka", input: "ovládání", camera: "kamera", clipboard: "schránka", injection: "podezřelé texty" } as any)[k] || k} ${n}×`).join(", ")}.`
        : "Dnes JARVIS na obrazovku, schránku ani ovládání nesáhl."),
      ...rows.slice(0, 30).map((r) => h("div", { class: "row" }, h("span", {}, icon(KIND_ICON[r.kind] || "eye"), " ",
        new Date(r.ts * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" }), " · ", r.tool), h("span", { class: "muted" }, r.what || ""))));
  });

  // 3.18 Co zkoušel cizí text: steps an e-mail, a web page, a file, a picture or the clipboard led to – and your answer
  const foreignBox = h("div", { class: "card sec-card" });
  const SRC: Record<string, string> = { clipboard: "schránka", attachment: "příloha", email_read: "e-mail", email_inbox: "e-maily",
    email_search: "e-maily", web_read: "web", web_search: "web", google_search: "web", browser_read: "web", phone_messages: "zprávy",
    read_text_file: "soubor", read_attachment: "příloha", clipboard_get: "schránka", ui_read: "obrazovka", selected_text: "označený text" };
  client.on("foreign_log", (m: any) => {
    const items: any[] = m.items || [];
    foreignBox.replaceChildren(
      h("p", { class: "help" }, "Když JARVIS přečte cizí text a ten by ho chtěl dostat ke kroku, který něco mění (psaní, klávesy, odkaz s daty, paměť…), JARVIS se nejdřív zeptal. Tady je, co to bylo a jak jsi odpověděl."),
      items.length ? h("ul", { class: "sec-list" }, ...items.map((x) => h("li", {},
        h("span", {}, `${new Date(x.ts * 1000).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })} · ${SRC[x.source] || x.source || "cizí text"} → ${x.what}`),
        h("span", { class: x.approved ? "muted" : "sec-ok" }, x.approved ? `povoleno (${x.why})` : `zamítnuto (${x.why})`))))
        : h("p", { class: "muted" }, "Zatím nic – žádný cizí text se nepokusil o krok, který by něco měnil."));
  });
  const el = h("section", { class: "tasks-view security-view" },
    hero(HEROES.security, "Bezpečí a soukromí", "Co JARVIS smí, kolik smí utratit, co si pamatuje – a jak to všechno vypnout, vyexportovat nebo smazat.", [
      h("button", { class: "btn", type: "button", onclick: refresh }, icon("arrow-clockwise"), "Obnovit")]),
    h("h2", { class: "group-label" }, "Bezpečí"), safety,
    h("h2", { class: "group-label" }, "Dočasná oprávnění"), grantsBox,
    h("h2", { class: "group-label" }, "Spotřeba AI"), usageBox,
    h("h2", { class: "group-label" }, "Soukromí"), privacyBox,
    h("h2", { class: "group-label" }, "Co JARVIS ukládá"), invBox,
    h("h2", { class: "group-label" }, "Mikrofon a kamera"), micBox,
    h("h2", { class: "group-label" }, "Co JARVIS dnes viděl a čeho se dotkl"), accessBox,
    h("h2", { class: "group-label" }, "Co zkoušel cizí text"), foreignBox,
    h("h2", { class: "group-label" }, "Export, záloha, smazání"), dataBox);
  return { el, show: () => { refresh(); client.send("access_log_get"); client.send("foreign_log_get"); } };
}

// 3.14 the security briefing's leak check: the user's own Have I Been Pwned key (kept in the Windows vault)
function hibpRow(client: JarvisClient): HTMLElement {
  const inp = h("input", { class: "input", type: "password", placeholder: "Klíč Have I Been Pwned (nepovinné)", "aria-label": "Klíč Have I Been Pwned", autocomplete: "off" }) as HTMLInputElement;
  return h("div", { class: "row" },
    h("div", { class: "row-text" }, h("strong", {}, "Úniky e-mailů v brífinku"),
      h("span", { class: "help" }, "S vlastním klíčem z haveibeenpwned.com/API/Key brífink zkontroluje, jestli tvoje e-mailové adresy nejsou v nových únicích dat. Klíč zůstane v trezoru Windows.")),
    inp, h("button", { class: "btn sm", type: "button", onclick: () => {
      const v = inp.value.trim();
      if (!v) return;
      client.send("secret_set", { name: "hibp", value: v });
      inp.value = "";
      toast("Klíč uložen", "ok");
    } }, icon("floppy-disk"), "Uložit"));
}
