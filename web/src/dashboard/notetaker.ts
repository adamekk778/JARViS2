// Nahrávání hovorů (3.0 Notetaker): record a call (your mic + what the PC plays), then a transcript person by
// person, a summary, the key points and the to-dos. The audio is deleted once the transcript is written.
import { copyText, h, icon } from "../shared/dom";
import { hero, HEROES } from "../shared/hero";
import type { JarvisClient } from "../shared/ws";

const clock = (s: number) => `${Math.floor(s / 3600) ? `${Math.floor(s / 3600)}:` : ""}${String(Math.floor((s % 3600) / 60)).padStart(Math.floor(s / 3600) ? 2 : 1, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const mins = (s: number) => (s < 60 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`);

export function buildNotetaker(client: JarvisClient) {
  let state = "idle";
  let selected = "";
  const status = h("div", { class: "nt-status" });
  const startBtn = h("button", { class: "btn primary", type: "button", onclick: () => client.send("note_start") }, icon("record", "ph-fill"), "Nahrát hovor");
  const band = hero(HEROES.notetaker, "Nahrávání hovorů",
    "Discord, Teams, Meet, telefon přes PC… JARVIS nahraje tvůj mikrofon i zvuk z počítače. Žádný bot se do hovoru nepřipojí.",
    [startBtn, status]);
  const list = h("div", { class: "nt-list" });
  const detail = h("div", { class: "nt-detail card" }, h("p", { class: "help" }, "Vyber nahrávku ze seznamu."));
  const el = h("section", { class: "page-view" },
    h("div", { class: "page-inner" }, band,
      h("div", { class: "hub-warn" }, icon("info"), " Řekni lidem v hovoru, že nahráváš. Zvuk se po přepsání smaže, zůstane jen text."),
      h("div", { class: "nt-cols" }, h("div", {}, h("p", { class: "group-label" }, "Nahrávky"), list), detail)));

  function paintStatus(m: any) {
    state = m.state;
    startBtn.hidden = state !== "idle";
    if (state === "recording") {
      const meter = (label: string, v: number) => h("div", { class: "nt-meter" }, h("span", {}, label), h("div", { class: "meter" }, h("i", { style: { width: `${Math.round((v || 0) * 100)}%` } })));
      status.replaceChildren(
        h("div", { class: "nt-rec" }, h("span", { class: "rec-dot" }), h("b", {}, clock(m.seconds || 0))),
        meter("Ty", m.mic), meter("Ostatní", m.sys),
        h("button", { class: "btn primary", type: "button", onclick: () => client.send("note_stop") }, icon("stop", "ph-fill"), "Ukončit a přepsat"),
        h("button", { class: "btn", type: "button", onclick: () => { if (confirm("Zahodit nahrávku bez přepisu?")) client.send("note_cancel"); } }, "Zahodit"));
    } else if (state === "processing") {
      const p = Math.round((m.progress || 0) * 100);
      status.replaceChildren(h("div", { class: "nt-proc" }, h("span", {}, `Přepisuji a shrnuji… ${p} %`), h("div", { class: "meter" }, h("i", { style: { width: `${p}%` } }))));
    } else status.replaceChildren();
  }

  function paintList(items: any[]) {
    if (!items.length) {
      list.replaceChildren(h("div", { class: "card d-empty" }, icon("record"), h("p", {}, "Zatím žádné nahrávky. Klikni na Nahrát hovor, nebo řekni „Jarvisi, nahraj tenhle hovor“.")));
      return;
    }
    list.replaceChildren(h("div", { class: "d-entries" }, ...items.map((n) => h("button", {
      type: "button", class: `nt-item ${n.id === selected ? "on" : ""}`, onclick: () => { selected = n.id; client.send("note_get", { id: n.id }); paintList(items); },
    },
      h("div", { class: "nt-item-text" }, h("strong", {}, n.title || "Hovor"),
        h("span", {}, `${new Date(n.created * 1000).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })} · ${mins(n.seconds || 0)}`)),
      n.status === "done" ? null : h("span", { class: `tag ${n.status}` }, n.status === "failed" ? "Chyba" : n.status === "recording" ? "Nahrávám" : "Zpracovávám")))));
  }

  function paintDetail(n: any) {
    if (!n) { detail.replaceChildren(h("p", { class: "help" }, "Nahrávka neexistuje.")); return; }
    if (n.status === "failed") {
      detail.replaceChildren(h("h2", {}, n.title || "Hovor"), h("p", { class: "help" }, n.error || "Zpracování selhalo."),
        h("div", { class: "btn-row" }, h("button", { class: "btn danger", type: "button", onclick: () => { client.send("note_delete", { id: n.id }); detail.replaceChildren(); } }, icon("trash"), "Smazat")));
      return;
    }
    const text = [`# ${n.title}`, n.summary, "", "Hlavní body:", ...n.points.map((p: string) => `- ${p}`), "", "Úkoly:",
      ...n.todos.map((t: string) => `- [ ] ${t}`), "", "Přepis:", ...n.transcript.map((l: any) => `${l.who}: ${l.text}`)].join("\n");
    detail.replaceChildren(...([
      h("div", { class: "nt-head" }, h("div", {}, h("h2", {}, n.title),
        h("span", { class: "help" }, `${new Date(n.created * 1000).toLocaleString("cs-CZ")} · ${mins(n.seconds || 0)}`)),
        h("div", { class: "btn-row" },
          h("button", { class: "btn sm", type: "button", onclick: () => copyText(text) }, icon("copy"), "Kopírovat"),
          h("button", { class: "btn sm danger", type: "button", onclick: () => { if (confirm("Smazat tuhle nahrávku?")) { client.send("note_delete", { id: n.id }); selected = ""; detail.replaceChildren(); } } }, icon("trash")))),
      n.summary ? h("p", { class: "nt-summary" }, n.summary) : null,
      n.points.length ? h("div", {}, h("p", { class: "group-label" }, "Hlavní body"), h("ul", { class: "nt-points" }, ...n.points.map((p: string) => h("li", {}, p)))) : null,
      n.todos.length ? h("div", {}, h("p", { class: "group-label" }, "Úkoly"), h("ul", { class: "nt-todos" }, ...n.todos.map((t: string) => h("li", {}, icon("square"), h("span", {}, t))))) : null,
      h("p", { class: "group-label" }, "Přepis"),
      h("div", { class: "nt-transcript" }, ...n.transcript.map((l: any) =>
        h("div", { class: `nt-line ${l.who === "Já" ? "me" : ""}` }, h("span", { class: "nt-who" }, l.who, h("small", {}, clock(l.start))), h("p", {}, l.text)))),
    ].filter(Boolean) as Node[]));
  }

  client.on("notes", (m) => { paintStatus({ state: m.state }); if (!el.hidden) paintList(m.items || []); });
  client.on("note", (m) => paintDetail(m.note));
  client.on("notetaker", (m) => {
    paintStatus(m);
    if (m.done && !el.hidden) { client.send("notes_get"); if (m.done === selected) client.send("note_get", { id: selected }); }
  });
  return { el, show: () => client.send("notes_get") };
}
