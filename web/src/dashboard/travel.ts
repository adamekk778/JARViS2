// 3.18 Cesty: hotels and flights by your description, booked and paid only after your confirmation (twice, with the
// exact amount; on the phone with the fingerprint). This page shows the bookings, the price watches and what trips
// cost, and holds the limits and the traveller's details (they stay on this PC). Searching and cancelling go through
// the chat, where JARVIS asks.
import { hero, HEROES } from "../shared/hero";
import { h, icon, loading, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import "./travel.css";

const nodes = (...xs: (Node | string | null | undefined | false)[]) => xs.filter((x): x is Node | string => !!x);
const money = (v: number, cur: string) => `${Math.round(v).toLocaleString("cs-CZ")} ${cur}`;
const day = (iso: string) => {
  const d = new Date(String(iso || "").slice(0, 19));
  return isNaN(+d) ? String(iso || "") : d.toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric", year: "numeric" });
};

export function buildTravel(client: JarvisClient, ask: (text: string) => void) {
  let s: any = {};
  const set = (patch: any) => client.send("settings_set", { patch: { booking: patch } });

  const sw = (title: string, desc: string, key: string) => {
    const inp = h("input", { type: "checkbox", role: "switch", "aria-label": title }) as HTMLInputElement;
    inp.checked = !!s.booking?.[key];
    inp.onchange = () => set({ [key]: inp.checked });
    return h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, title), h("span", { class: "help" }, desc)),
      h("span", { class: "switch" }, inp, h("span")));
  };
  const field = (title: string, key: string, opts: { type?: string; placeholder?: string; help?: string; min?: number } = {}) => {
    const inp = h("input", { class: "input", type: opts.type || "text", placeholder: opts.placeholder || "", value: s.booking?.[key] ?? "",
      "aria-label": title, autocomplete: "off", min: opts.min }) as HTMLInputElement;
    inp.onchange = () => set({ [key]: opts.type === "number" ? Math.max(0, +inp.value || 0) : inp.value.trim() });
    return h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, title), opts.help ? h("span", { class: "help" }, opts.help) : null), inp);
  };
  const pick = (title: string, key: string, options: [string, string][], help = "") => {
    const sel = h("select", { class: "input", "aria-label": title },
      ...options.map(([v, label]) => h("option", { value: v, selected: s.booking?.[key] === v }, label))) as HTMLSelectElement;
    sel.onchange = () => set({ [key]: sel.value });
    return h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, title), help ? h("span", { class: "help" }, help) : null), sel);
  };

  const search = h("input", { class: "input", placeholder: "Např. Řím, 3 noci od pátku, do 150 € za noc, blízko centra, snídaně", "aria-label": "Popiš cestu" }) as HTMLInputElement;
  const go = () => {
    const t = search.value.trim();
    if (!t) { toast("Napiš, kam a kdy"); return; }
    ask(/\b(let|letenk|odlet|přílet|prilet)\w*/i.test(t) ? `Najdi letenky: ${t}` : `Najdi hotel: ${t}`);
    search.value = "";
  };
  search.onkeydown = (e) => { if (e.key === "Enter") go(); };
  const searchBox = h("div", { class: "card sec-card" },
    h("p", { class: "help" }, "Napiš to jako člověku. JARVIS najde 3–5 nejlepších nabídek s důvodem a celkovou cenou; „beru dvojku“ ji zarezervuje – po dvou potvrzeních (podruhé s přesnou částkou)."),
    h("div", { class: "house-add" }, search, h("button", { class: "btn primary", type: "button", onclick: go }, icon("magnifying-glass"), "Najít")));

  const statusBox = h("div", { class: "card sec-card" }, loading());
  const bookingsBox = h("div", { class: "card sec-card" }, loading());
  const watchesBox = h("div", { class: "card sec-card" });
  const spendBox = h("div", { class: "card sec-card" });
  const settingsBox = h("div", { class: "group" });

  client.on("travel", (m: any) => {
    const p = m.providers || {};
    statusBox.replaceChildren(...nodes(
      h("div", { class: "row" }, h("span", {}, icon("buildings"), " Hotely (LiteAPI)"), h("span", { class: p.liteapi ? "sec-ok" : "muted" }, p.liteapi ? (p.sandbox ? "zkušební klíč – nic se nezaplatí" : "připojeno") : "bez klíče")),
      h("div", { class: "row" }, h("span", {}, icon("airplane-tilt"), " Lety a hotely (Duffel)"), h("span", { class: p.duffel ? "sec-ok" : "muted" }, p.duffel ? "připojeno" : "bez klíče")),
      !p.liteapi && !p.duffel ? h("p", { class: "help" }, "Bez klíče JARVIS otevře Booking.com, Airbnb nebo Google Flights s vyplněným hledáním, vyplní údaje a před tlačítkem Zaplatit se vždycky zastaví. Klíče přidáš v Propojení.") : null,
      m.traveller_missing ? h("p", { class: "help warn" }, icon("warning"), ` Pro rezervace ${m.traveller_missing.replace(" (Cesty → Údaje a limity)", "")} – doplň dole v Údaje a limity.`) : null));
    const rows: any[] = m.bookings || [];
    bookingsBox.replaceChildren(rows.length
      ? h("ul", { class: "sec-list" }, ...rows.map((b) => h("li", {},
        h("span", {}, icon(b.kind === "flight" ? "airplane-tilt" : "bed"), ` ${b.name} · ${day(b.start)} – ${day(b.end)} · ${money(b.total, b.currency)}`,
          b.sandbox ? h("i", { class: "muted" }, " (zkušební)") : null),
        h("span", { class: "row-actions" },
          b.status === "cancelled" ? h("span", { class: "muted" }, "zrušeno")
            : h("span", { class: b.free_cancel_until ? "sec-ok" : "muted" }, b.free_cancel_until ? `zrušení zdarma do ${day(b.free_cancel_until)}` : b.refundable ? "vratná" : "nevratná"),
          b.status !== "cancelled" ? h("button", { class: "btn sm", type: "button", onclick: () => ask(`Za kolik jde zrušit rezervace ${b.id} (${b.name})?`) }, "Zrušit…") : null))))
      : h("p", { class: "muted" }, "Žádná rezervace od JARVISe. Rezervace z e-mailu (lety, vlaky) najdeš v Mé cesty v chatu."));
    const ws: any[] = m.watches || [];
    watchesBox.replaceChildren(
      h("p", { class: "help" }, "„Dej vědět, až bude Řím 12.–15. 3. pod 4 000 Kč“ – JARVIS se dívá dvakrát denně a ozve se. Zarezervovaný hotel se zrušením zdarma hlídá sám: když zlevní o 5 % a víc, řekne ti to (nic nemění bez tebe)."),
      ws.length ? h("ul", { class: "sec-list" }, ...ws.map((w) => h("li", {},
        h("span", {}, `${w.criteria?.city || `${w.criteria?.origin || ""}→${w.criteria?.destination || ""}`} pod ${money(w.max_price, w.currency)}`,
          w.last_price ? h("i", { class: "muted" }, ` · naposled ${money(w.last_price, w.currency)}`) : null),
        h("button", { class: "icon-btn sm", type: "button", "aria-label": "Přestat hlídat", onclick: () => client.send("travel_watch_stop", { id: w.id }) }, icon("x")))))
        : h("p", { class: "muted" }, "Nic nehlídám."));
    const sp = m.spend || { by_month: {}, total_czk: 0, business_czk: 0, year: new Date().getFullYear() };
    const lim = m.limits || {};
    const max = Math.max(1, ...Object.values(sp.by_month as Record<string, number>));
    spendBox.replaceChildren(...nodes(
      h("div", { class: "row" }, h("strong", {}, "Tento měsíc"), h("span", {}, `${money(m.month_czk || 0, "Kč")}${lim.monthly_budget ? ` z ${money(lim.monthly_budget, "Kč")}` : ""}`)),
      lim.monthly_budget ? h("div", { class: "meter", role: "meter", "aria-valuemin": "0", "aria-valuemax": String(lim.monthly_budget), "aria-valuenow": String(m.month_czk || 0), "aria-label": "Rozpočet na cesty" },
        h("i", { style: { width: `${Math.min(100, ((m.month_czk || 0) / lim.monthly_budget) * 100)}%` } })) : null,
      h("div", { class: "row" }, h("strong", {}, `Rok ${sp.year}`), h("span", {}, money(sp.total_czk, "Kč") + (sp.business_czk ? ` · služebně ${money(sp.business_czk, "Kč")}` : ""))),
      Object.keys(sp.by_month).length ? h("div", { class: "trip-bars", "aria-label": "Útrata po měsících" }, ...Object.entries(sp.by_month as Record<string, number>).map(([mo, v]) =>
        h("div", { class: "trip-bar", title: `${+mo}. měsíc: ${money(v, "Kč")}` }, h("i", { style: { height: `${Math.max(6, (v / max) * 100)}%` } }), h("span", {}, String(+mo))))) : null,
      h("p", { class: "help" }, "Služební cesty se zapisují i do Dokumenty → JARVIS → Cesty → naklady.csv (pro účetní); potvrzení každé cesty je ve složce té cesty.")));
  });

  const renderSettings = () => {
    settingsBox.replaceChildren(
      field("Limit na jednu rezervaci (Kč)", "max_per_booking", { type: "number", min: 0, help: "Dražší rezervaci JARVIS neudělá (0 = bez limitu)." }),
      field("Měsíční rozpočet na cesty (Kč)", "monthly_budget", { type: "number", min: 0, help: "Rezervace, která by ho přetáhla, se nezaplatí (0 = bez rozpočtu)." }),
      sw("Přednost zrušení zdarma", "Nabídky, které jdou zrušit bez poplatku, jdou nahoru.", "prefer_free_cancel"),
      sw("Přednost platby na hotelu", "Nabídky, které se platí až na místě, jdou nahoru.", "prefer_pay_at_hotel"),
      pick("Kde hledat", "provider", [["auto", "Automaticky (co je připojené)"], ["liteapi", "LiteAPI"], ["duffel", "Duffel"], ["browser", "Prohlížeč (Booking.com)"]]),
      pick("Platba u LiteAPI", "liteapi_payment", [["ACC_CREDIT_CARD", "Karta uložená v účtu LiteAPI"], ["WALLET", "Peněženka LiteAPI"]], "JARVIS číslo karty nikdy nevidí."),
      field("Měna", "currency", { placeholder: "CZK" }),
      field("Státní příslušnost (kód)", "nationality", { placeholder: "CZ", help: "Ceny hotelů se podle ní liší." }),
      h("h3", { class: "group-label" }, "Údaje cestujícího (zůstávají jen na tomhle PC)"),
      field("Jméno", "first_name"), field("Příjmení", "last_name"),
      field("E-mail pro potvrzení", "email", { type: "email" }), field("Telefon", "phone", { type: "tel", placeholder: "+420 …" }),
      field("Datum narození (letenky)", "born_on", { type: "date" }),
      pick("Oslovení (letenky)", "title", [["mr", "Pan (Mr)"], ["ms", "Paní (Ms)"], ["mrs", "Paní (Mrs)"], ["miss", "Slečna (Miss)"], ["dr", "Dr."]]),
      pick("Pohlaví (letenky)", "gender", [["m", "Muž"], ["f", "Žena"]]),
      field("Pas platí do", "passport_until", { type: "date", help: "Upozorním, když by pas na cestu nestačil (mnoho zemí chce 6 měsíců po návratu)." }),
      h("h3", { class: "group-label" }, "Po rezervaci"),
      sw("Připomínky", "Konec zrušení zdarma (den a 3 hodiny předem), online check-in, počasí v cíli, co sbalit.", "reminders"),
      sw("Hlídat, jestli hotel nezlevnil", "U rezervací se zrušením zdarma: o 5 % levněji → dám vědět.", "price_watch"));
  };
  const sync = (st: any) => { s = st || {}; renderSettings(); };
  client.on("welcome", (m) => sync(m.settings));
  client.on("settings_changed", (m) => sync(m.settings));

  const refresh = () => client.send("travel_get");
  const el = h("section", { class: "tasks-view travel-view" },
    hero(HEROES.travel, "Cesty", "Hotely a letenky podle tvého popisu. Platí se až po tvém potvrzení – dvakrát, s přesnou částkou.", [
      h("button", { class: "btn", type: "button", onclick: refresh }, icon("arrow-clockwise"), "Obnovit")]),
    h("h2", { class: "group-label" }, "Najít"), searchBox,
    h("h2", { class: "group-label" }, "Rezervace"), bookingsBox,
    h("h2", { class: "group-label" }, "Hlídání cen"), watchesBox,
    h("h2", { class: "group-label" }, "Kolik stály cesty"), spendBox,
    h("h2", { class: "group-label" }, "Odkud JARVIS rezervuje"), statusBox,
    h("h2", { class: "group-label" }, "Údaje a limity"), settingsBox);
  return { el, show: refresh };
}
