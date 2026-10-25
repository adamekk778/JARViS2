// Dashboard → E-mail a kalendář (3.4): connect a mailbox with an app password (it goes to the Windows keyring),
// who counts as important, how JARVIS announces new mail; calendars from an iCal address; what is coming up.
import { hero, HEROES } from "../shared/hero";
import { fmtTime, h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";

export function buildComms(client: JarvisClient) {
  let settings: any = {};
  let presets: Record<string, any> = {};
  const accountsBox = h("div", { class: "group" });
  const status = h("p", { class: "help" });

  // ---------- add an account ----------
  const provider = h("select", { class: "input", "aria-label": "Poskytovatel" }) as HTMLSelectElement;
  const address = h("input", { class: "input", type: "email", placeholder: "jmeno@seznam.cz", autocomplete: "username", "aria-label": "E-mail" }) as HTMLInputElement;
  const password = h("input", { class: "input", type: "password", placeholder: "Heslo pro aplikace", autocomplete: "new-password", "aria-label": "Heslo pro aplikace" }) as HTMLInputElement;
  const name = h("input", { class: "input", placeholder: "Tvoje jméno (podpis e-mailů)", "aria-label": "Jméno" }) as HTMLInputElement;
  const imap = h("input", { class: "input", placeholder: "IMAP server, např. imap.firma.cz", "aria-label": "IMAP server" }) as HTMLInputElement;
  const smtp = h("input", { class: "input", placeholder: "SMTP server, např. smtp.firma.cz", "aria-label": "SMTP server" }) as HTMLInputElement;
  const custom = h("div", { class: "comms-custom", hidden: true }, imap, smtp);
  const help = h("p", { class: "help" });
  const addBtn = h("button", { class: "btn primary", type: "button" }, icon("plug"), "Připojit") as HTMLButtonElement;
  const guess = (a: string) => {
    const d = a.split("@")[1]?.toLowerCase() || "";
    return ["seznam.cz", "email.cz", "post.cz"].includes(d) ? "seznam" : ["gmail.com", "googlemail.com"].includes(d) ? "gmail"
      : d === "centrum.cz" ? "centrum" : d === "atlas.cz" ? "atlas" : ["icloud.com", "me.com"].includes(d) ? "icloud" : "";
  };
  const syncProvider = () => { custom.hidden = provider.value !== "custom"; help.textContent = presets[provider.value]?.help || ""; };
  address.oninput = () => { const g = guess(address.value); if (g) { provider.value = g; syncProvider(); } };
  provider.onchange = syncProvider;
  addBtn.onclick = () => {
    if (!address.value.includes("@") || !password.value) { toast("Vyplň e-mail a heslo pro aplikace", "error"); return; }
    addBtn.disabled = true;
    addBtn.lastChild!.textContent = "Zkouším přihlášení…";
    client.send("mail_account_add", { address: address.value.trim(), password: password.value, name: name.value.trim(), provider: provider.value,
      imap_host: imap.value.trim(), smtp_host: smtp.value.trim() });
  };
  const addForm = h("div", { class: "card comms-add" },
    h("h3", {}, "Připojit e-mail"),
    h("div", { class: "comms-grid" }, address, provider, password, name), custom, help,
    h("p", { class: "help" }, icon("lock-simple"), " Heslo se uloží do trezoru Windows (Správce přihlašovacích údajů), ne do souboru. JARVIS e-mail nikdy neodešle bez tvého potvrzení."),
    h("div", { class: "btn-row" }, addBtn));

  // ---------- behaviour ----------
  const behaviour = h("div", { class: "group" });
  function renderBehaviour() {
    const m = settings?.mail || {};
    const sw = (key: string, title: string, desc: string) => {
      const inp = h("input", { type: "checkbox", role: "switch", "aria-label": title }) as HTMLInputElement;
      inp.checked = !!m[key];
      inp.onchange = () => client.send("settings_set", { patch: { mail: { [key]: inp.checked } } });
      return h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, title), h("span", { class: "help" }, desc)), h("span", { class: "switch" }, inp, h("span")));
    };
    const vip = h("input", { class: "input", value: (m.vip || []).join(", "), placeholder: "máma, petr@firma.cz, šéf", "aria-label": "Důležití lidé" }) as HTMLInputElement;
    vip.onchange = () => client.send("settings_set", { patch: { mail: { vip: vip.value.split(",").map((x) => x.trim()).filter(Boolean) } } });
    behaviour.replaceChildren(
      sw("notify", "Hlásit nové e-maily", "V notchi a na telefonu, do ~20 sekund od doručení."),
      sw("speak", "Říct to nahlas", "„Píše vám Petr: Schůzka zítra.“"),
      sw("ignore_newsletters", "Ignorovat reklamy a newslettery", "Hromadné e-maily jen tiše přibydou do schránky."),
      h("label", { class: "row wide" }, h("div", { class: "row-text" }, h("strong", {}, "Důležití lidé"),
        h("span", { class: "help" }, "Jména nebo adresy oddělené čárkou. Jejich e-maily projdou vždycky.")), vip),
      sw("call_vip", "Od důležitých lidí zazvonit na telefon", "JARVIS ti na telefonu „zavolá“ a e-mail přečte (aplikace JARVIS v telefonu)."));
  }

  // ---------- calendar ----------
  const icsList = h("div", { class: "group" });
  const icsInput = h("input", { class: "input", placeholder: "https://calendar.google.com/calendar/ical/…/basic.ics", "aria-label": "Adresa kalendáře" }) as HTMLInputElement;
  const upcoming = h("div", { class: "comms-events" }, h("p", { class: "help" }, "Načítám…"));
  function renderIcs() {
    const urls: string[] = settings?.calendar?.ics_urls || [];
    icsList.replaceChildren(...urls.map((u, i) => h("div", { class: "row" },
      h("div", { class: "row-text" }, h("strong", {}, `Kalendář ${i + 1}`), h("span", { class: "help mono" }, u.replace(/(\/ical\/[^/]{4})[^/]+/, "$1…"))),
      h("button", { class: "btn ghost", type: "button", "aria-label": `Odebrat kalendář ${i + 1}`, onclick: () =>
        client.send("settings_set", { patch: { calendar: { ics_urls: urls.filter((_, j) => j !== i) } } }) }, icon("trash")))));
  }
  const addIcs = () => {
    const u = icsInput.value.trim();
    if (!/^(https?|webcal):\/\//.test(u)) { toast("Vlož adresu začínající https:// nebo webcal://", "error"); return; }
    client.send("settings_set", { patch: { calendar: { ics_urls: [...(settings?.calendar?.ics_urls || []), u] } } });
    icsInput.value = "";
    setTimeout(() => client.send("calendar_get", { days: 7 }), 800);
  };

  client.on("mail_status", (m) => {
    presets = m.presets || presets;
    if (!provider.options.length) {
      for (const [k, p] of Object.entries(presets)) provider.append(h("option", { value: k }, (p as any).label));
      provider.value = "seznam";
      syncProvider();
    }
    addBtn.disabled = false;
    addBtn.lastChild!.textContent = "Připojit";
    if (m.error) toast(m.error, "error", 7000);
    if (m.added) { toast(`E-mail ${m.added} je připojený. Zkus: „co mi přišlo?“`, "ok", 5000); address.value = password.value = ""; }
    accountsBox.replaceChildren(...(m.accounts || []).map((a: any) => h("div", { class: "row" },
      h("div", { class: "row-text" }, h("strong", {}, icon(a.error ? "warning-circle" : "envelope-simple"), " ", a.address),
        h("span", { class: "help" }, a.error ? `Chyba: ${a.error}` : `${presets[a.provider]?.label || a.provider} · hlídám nové e-maily`)),
      h("button", { class: "btn ghost", type: "button", onclick: () => { if (confirm(`Odpojit ${a.address}? Heslo se smaže z trezoru.`)) client.send("mail_account_remove", { id: a.id }); } },
        icon("plugs"), "Odpojit"))));
    status.textContent = (m.accounts || []).length ? "" : "Zatím žádný e-mail. Připoj ho níž – stačí heslo pro aplikace.";
  });
  client.on("calendar", (m) => {
    const items = m.items || [];
    let day = "";
    upcoming.replaceChildren(...(items.length ? items.flatMap((e: any) => {
      const d = new Date(e.start * 1000);
      const label = d.toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "numeric" });
      const out: HTMLElement[] = [];
      if (label !== day) { day = label; out.push(h("h4", {}, label)); }
      out.push(h("div", { class: "comms-ev" }, h("b", {}, e.all_day ? "celý den" : fmtTime(e.start).split(" ").pop() || ""),
        h("span", {}, e.title), e.location ? h("span", { class: "muted" }, e.location) : null, h("span", { class: "chip" }, e.source)));
      return out;
    }) : [h("p", { class: "help" }, "Na příštích 7 dní nic. Zkus říct: „připomeň mi zítra v 10 zubaře“.")]));
  });
  const sync = (s: any) => { settings = s; renderBehaviour(); renderIcs(); };
  client.on("welcome", (m) => sync(m.settings));
  client.on("settings_changed", (m) => sync(m.settings));

  const el = h("section", { class: "tasks-view comms-view" },
    hero(HEROES.comms, "E-mail a kalendář", "JARVIS čte, hlídá a píše tvoje e-maily, ví, co tě čeká, a připomene to.", []),
    h("h2", { class: "group-label" }, "E-mailové účty"), status, accountsBox, addForm,
    h("h2", { class: "group-label" }, "Nové e-maily"), behaviour,
    h("h2", { class: "group-label" }, "Kalendář"),
    h("p", { class: "help" }, "Vlastní události JARVIS uloží sám („naplánuj schůzku ve 3“). Google, Seznam nebo Outlook kalendář připojíš přes „tajnou adresu ve formátu iCal“ z jeho nastavení."),
    icsList, h("div", { class: "comms-ics" }, icsInput, h("button", { class: "btn", type: "button", onclick: addIcs }, icon("plus"), "Přidat kalendář")),
    h("h2", { class: "group-label" }, "Příštích 7 dní"), upcoming);
  return { el, show: () => { client.send("mail_status_get"); client.send("calendar_get", { days: 7 }); } };
}
