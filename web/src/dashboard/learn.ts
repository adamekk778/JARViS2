// Dashboard → Učení (OMEGA §10 JARVIS Teacher, §36 Learning Lab): flashcards with spaced repetition (show the answer,
// then say how well you knew it), cards from a document, a math step checker, exam plans, weak spots and statistics.
import { hero, HEROES } from "../shared/hero";
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";

export function buildLearn(client: JarvisClient) {
  let deck = "";
  let card: any = null;
  const decksBox = h("div", { class: "ln-decks" });
  const reviewBox = h("div", { class: "card ln-review", "aria-live": "polite" });
  const statsBox = h("div", { class: "rs-out" });
  const out = h("div", { class: "rs-out" });

  const renderCard = () => {
    if (!card) {
      reviewBox.replaceChildren(h("p", { class: "muted" }, deck ? `V balíčku „${deck}“ teď není co opakovat.` : "Teď není co opakovat – přidej kartičky nebo je nech udělat z dokumentu."));
      return;
    }
    const back = h("div", { class: "ln-back", hidden: true }, h("p", {}, card.back),
      h("div", { class: "btn-row" }, ...([[1, "Nevěděl jsem", "danger"], [3, "Těžké", ""], [4, "Dobře", ""], [5, "Snadné", "primary"]] as [number, string, string][])
        .map(([g, label, cls]) => h("button", { class: `btn ${cls}`, type: "button", onclick: () => client.send("learn_grade", { id: card.id, grade: g, deck }) }, label))));
    const show = h("button", { class: "btn primary", type: "button", onclick: () => { back.hidden = false; show.remove(); } }, icon("eye"), "Ukázat odpověď");
    reviewBox.replaceChildren(h("span", { class: "muted" }, card.deck), h("p", { class: "ln-front" }, card.front), show, back);
  };
  client.on("learn_card", (m) => { card = m.card; renderCard(); });
  client.on("learn", (m) => {
    decksBox.replaceChildren(...(m.decks.length ? m.decks.map((d: any) => h("button", { class: `rs-chip${d.deck === deck ? " on" : ""}`, type: "button",
      onclick: () => { deck = deck === d.deck ? "" : d.deck; client.send("learn_get"); client.send("learn_next", { deck }); } },
      `${d.deck} · ${d.cards}`, d.due ? h("span", { class: "ln-due" }, String(d.due)) : "")) : [h("span", { class: "muted" }, "Zatím žádné balíčky.")]));
    const s = m.stats, w = m.weak;
    statsBox.replaceChildren(
      h("div", { class: "rs-stats" }, ...[["Opakování (14 dní)", String(s.reviews)], ["Úspěšnost", s.accuracy != null ? `${s.accuracy} %` : "—"],
        ["Odpovědi v testech", String(s.answers)], ["Dní v řadě", String(s.streak)]].map(([k, v]) => h("div", {}, h("strong", {}, v), h("span", { class: "muted" }, k)))),
      w.topics.length ? h("p", {}, h("strong", {}, "Slabá místa: "), w.topics.slice(0, 5).map((t: any) => `${t.topic} (${t.avg} %)`).join(", ")) : "",
      w.hard_cards.length ? h("p", {}, h("strong", {}, "Pořád zapomínáš: "), w.hard_cards.slice(0, 5).map((c: any) => c.front).join(", ")) : "",
      ...m.exams.map((e: any) => h("p", {}, icon("calendar-check"), ` ${e.name}: za ${e.days_left} dní (${e.topics.join(", ")})`)));
  });
  client.on("learn_result", (m) => { out.replaceChildren(h("p", { class: m.ok ? "" : "rs-f bad" }, m.summary)); if (m.tool === "flashcards_from") client.send("learn_next", { deck }); });

  const f = (ph: string, label: string, v = "") => h("input", { class: "input", placeholder: ph, "aria-label": label, value: v }) as HTMLInputElement;
  const fFront = f("otázka", "Otázka"), fBack = f("odpověď", "Odpověď"), fDeck = f("balíček", "Balíček", "Obecné");
  const src = f("soubor (PDF, Word, poznámky) nebo text", "Podklad"), srcDeck = f("balíček", "Balíček z dokumentu");
  const math = h("textarea", { class: "input ln-math", rows: 4, placeholder: "2x + 3 = 7\n2x = 4\nx = 2", "aria-label": "Kroky výpočtu" }) as HTMLTextAreaElement;
  const exName = f("zkouška, např. Biologie", "Zkouška"), exDate = h("input", { class: "input sm", type: "date", "aria-label": "Datum zkoušky" }) as HTMLInputElement;
  const exTopics = f("témata oddělená čárkou", "Témata");
  const tool = (name: string, args: any) => { out.replaceChildren(h("p", { class: "muted" }, "Pracuju…")); client.send("learn_tool", { tool: name, args }); };

  const el = h("section", { class: "tasks-view learn-view" },
    hero(HEROES.learn, "Učení", "Kartičky s chytrým opakováním, testy z tvých materiálů, kontrola výpočtů krok po kroku a plán před zkouškou.", []),
    h("h2", { class: "group-label" }, "Opakování"), decksBox, reviewBox,
    h("h2", { class: "group-label" }, "Výsledek"), h("div", { class: "card sec-card" }, out),
    h("h2", { class: "group-label" }, "Nové kartičky"), h("div", { class: "card sec-card" },
      h("div", { class: "list-add" }, fFront, fBack, fDeck, h("button", { class: "btn", type: "button", onclick: () => {
        if (!fFront.value.trim() || !fBack.value.trim()) { toast("Vyplň otázku i odpověď", "error"); return; }
        client.send("learn_add", { deck: fDeck.value.trim() || "Obecné", front: fFront.value.trim(), back: fBack.value.trim() }); fFront.value = ""; fBack.value = "";
      } }, icon("plus"), "Přidat")),
      h("div", { class: "list-add" }, src, srcDeck,
        h("button", { class: "btn", type: "button", onclick: () => src.value.trim() && tool("flashcards_from", { source: src.value.trim(), deck: srcDeck.value.trim() }) }, icon("cards"), "Kartičky z dokumentu"),
        h("button", { class: "btn", type: "button", onclick: () => src.value.trim() && tool("quiz_from", { source: src.value.trim() }) }, icon("exam"), "Test"),
        h("button", { class: "btn", type: "button", onclick: () => src.value.trim() && tool("mind_map", { source: src.value.trim() }) }, icon("tree-structure"), "Myšlenková mapa"))),
    h("h2", { class: "group-label" }, "Kontrola výpočtu"), h("div", { class: "card sec-card" }, math,
      h("div", { class: "btn-row" }, h("button", { class: "btn primary", type: "button", onclick: () => math.value.trim() && tool("check_math_steps", { steps: math.value }) }, icon("function"), "Zkontrolovat kroky")),
      h("p", { class: "help" }, "Každý krok na nový řádek. JARVIS kroky doopravdy přepočítá a najde první chybný.")),
    h("h2", { class: "group-label" }, "Zkouška"), h("div", { class: "card sec-card" },
      h("div", { class: "list-add" }, exName, exDate, exTopics, h("button", { class: "btn", type: "button", onclick: () => {
        if (!exName.value.trim() || !exDate.value || !exTopics.value.trim()) { toast("Vyplň název, datum a témata", "error"); return; }
        tool("exam_plan", { name: exName.value.trim(), date: exDate.value, topics: exTopics.value.split(",").map((x) => x.trim()).filter(Boolean) });
      } }, icon("calendar-plus"), "Naplánovat"))),
    h("h2", { class: "group-label" }, "Jak se mi daří"), h("div", { class: "card sec-card" }, statsBox));
  return { el, show: () => { client.send("learn_get"); client.send("learn_next", { deck }); } };
}
