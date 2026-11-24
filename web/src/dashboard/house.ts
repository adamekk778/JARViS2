// 3.14 JARVIS v celém domě – settings on the Domov page: house speakers (whole house / per room), Home Assistant's own
// voice instead of JARVIS's, home / away (person entity), the welcome, "follow me", other PCs (nodes) and the address
// for the voice satellites.
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";

type Node = { name: string; url: string; mac?: string };

export function houseCard(client: JarvisClient) {
  let home: any = {};
  const box = h("div", { class: "card house-card" });
  const set = (patch: any) => client.send("settings_set", { patch: { home: patch } });
  const field = (label: string, val: string, ph: string, put: (v: string) => void, help = "") => {
    const inp = h("input", { class: "input", value: val, placeholder: ph, "aria-label": label }) as HTMLInputElement;
    inp.onchange = () => put(inp.value.trim());
    return h("label", { class: "pe-row" }, h("span", {}, label), inp, help ? h("small", { class: "help" }, help) : "");
  };
  const sw = (label: string, help: string, on: boolean, put: (v: boolean) => void) => {
    const cb = h("input", { type: "checkbox", role: "switch", "aria-label": label }) as HTMLInputElement;
    cb.checked = on;
    cb.onchange = () => put(cb.checked);
    return h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, label), h("span", { class: "help" }, help)),
      h("span", { class: "switch" }, cb, h("span")));
  };

  function rooms(): HTMLElement {
    const entries = Object.entries((home.room_speakers || {}) as Record<string, string>);
    const name = h("input", { class: "input", placeholder: "místnost (kuchyň)", "aria-label": "Místnost" }) as HTMLInputElement;
    const ent = h("input", { class: "input", placeholder: "media_player.kuchyn", "aria-label": "Reproduktor" }) as HTMLInputElement;
    return h("div", { class: "house-rooms" },
      ...entries.map(([r, e]) => h("div", { class: "row" }, h("span", {}, `${r} → ${e}`),
        h("button", { class: "icon-btn sm", type: "button", "aria-label": `Odebrat ${r}`, onclick: () => {
          const next = { ...(home.room_speakers || {}) }; delete next[r]; set({ room_speakers: next });
        } }, icon("trash")))),
      h("div", { class: "house-add" }, name, ent, h("button", { class: "btn sm", type: "button", onclick: () => {
        if (!name.value.trim() || !ent.value.trim()) return;
        set({ room_speakers: { ...(home.room_speakers || {}), [name.value.trim()]: ent.value.trim() } });
      } }, icon("plus"), "Přidat")));
  }

  function nodes(): HTMLElement {
    const list: Node[] = home.nodes || [];
    const inp = (ph: string, label: string, type = "text") => h("input", { class: "input", placeholder: ph, "aria-label": label, type }) as HTMLInputElement;
    const n = inp("herní PC", "Jméno"), u = inp("http://192.168.1.20:8765", "Adresa"), t = inp("párovací klíč toho PC", "Klíč", "password"),
      mac = inp("MAC (volitelné, pro zapnutí po síti)", "MAC");
    return h("div", { class: "house-nodes" },
      ...list.map((x, i) => h("div", { class: "row" }, h("span", {}, icon("desktop"), ` ${x.name} · ${x.url}${x.mac ? " · WoL" : ""}`),
        h("button", { class: "icon-btn sm", type: "button", "aria-label": `Odebrat ${x.name}`, onclick: () => client.send("node_remove", { name: list[i].name }) }, icon("trash")))),
      h("div", { class: "house-add" }, n, u, t, mac, h("button", { class: "btn sm", type: "button", onclick: () => {
        if (!n.value.trim() || !u.value.trim()) { toast("Vyplň jméno a adresu", "error"); return; }
        client.send("node_add", { name: n.value.trim(), url: u.value.trim(), token: t.value.trim(), mac: mac.value.trim() });   // the key → the keyring
      } }, icon("plus"), "Přidat počítač")));
  }

  function paint() {
    box.replaceChildren(
      h("p", { class: "help" }, "JARVIS nejen v počítači: mluví do reproduktorů v domě, ví, že jsi přišel domů, a ovládá i tvoje další počítače."),
      h("h3", {}, "Reproduktory"),
      field("Celý dům", (home.speakers || []).join(", "), "media_player.obyvak, media_player.kuchyn",
        (v) => set({ speakers: v.split(",").map((x) => x.trim()).filter(Boolean) }), "Kam zazní „řekni všem…“."),
      rooms(),
      field("Hlas Home Assistantu", home.tts_entity || "", "prázdné = hlas JARVISe", (v) => set({ tts_entity: v }),
        "Jen když reproduktor neumí přehrát zvuk z tohoto PC (pak zadej tts.…)."),
      h("h3", {}, "Příchod domů"),
      field("Osoba v Home Assistantu", home.person_entity || "", "person.adam (prázdné = podle telefonu na Wi-Fi)", (v) => set({ person_entity: v })),
      sw("Uvítat doma", "Po návratu (aspoň 20 min pryč): „Vítejte doma, pane. Zatímco jste byl pryč…“ a protokol Vítej doma.", home.welcome !== false, (v) => set({ welcome: v })),
      sw("Následuj mě", "Upozornění zazní tam, kde jsi – v místnosti se satelitem.", home.follow_me !== false, (v) => set({ follow_me: v })),
      h("h3", {}, "Hlasové satelity v místnostech"),
      h("p", { class: "help" }, "Řekni JARVISovi „jak připojím satelit v kuchyni“ – dá ti adresu pro Home Assistant (integrace Ollama)."),
      h("h3", {}, "Kamery a zvonek"),
      field("Frigate", home.frigate_url || "", "http://frigate.local:5000", (v) => set({ frigate_url: v }),
        "Rozpoznání osob na kamerách domu – v noci a když nejsi doma hlásí každou osobu i s fotkou."),
      field("Zóny i přes den", (home.camera_zones || []).join(", "), "vchod, zahrada",
        (v) => set({ camera_zones: v.split(",").map((x) => x.trim()).filter(Boolean) })),
      field("Zvonek", home.doorbell_entity || "", "binary_sensor.zvonek", (v) => set({ doorbell_entity: v })),
      field("Kamera u dveří", home.door_camera || "", "camera.vchod", (v) => set({ door_camera: v }), "Její obraz přijde s „Někdo zvoní“."),
      h("h3", {}, "Zvuky domu"),
      (() => {
        const sel = h("select", { class: "input", "aria-label": "Hlídání zvuků" },
          ...([["off", "Vypnuto"], ["away", "Jen když nejsem doma"], ["always", "Pořád"]] as const).map(([v, l]) =>
            h("option", { value: v, selected: (home.sound_watch || "off") === v }, l))) as HTMLSelectElement;
        sel.onchange = () => set({ sound_watch: sel.value });
        return h("label", { class: "pe-row" }, h("span", {}, "Kouřový hlásič a rány"), sel,
          h("small", { class: "help" }, "Mikrofon PC poslouchá jen tyhle zvuky; nic se nenahrává."));
      })(),
      h("h3", {}, "Robotický vysavač"),
      field("Místnosti", Object.entries(home.vacuum_rooms || {}).map(([k, v]) => `${k}: ${(v as number[]).join(", ")}`).join("; "),
        "Kuchyň: 16, 17; Obývák: 18", (v) => set({ vacuum_rooms: parseRooms(v) }),
        "Čísla segmentů z aplikace vysavače (Roborock / Xiaomi) – pak „ukliď kuchyň“ uklidí jen ji."),
      h("h3", {}, "Moje počítače"),
      nodes());
  }

  const sync = (s: any) => { home = s?.home || {}; paint(); };
  client.on("welcome", (m: any) => sync(m.settings));
  client.on("settings_changed", (m: any) => sync(m.settings));
  paint();
  return box;
}

/** "Kuchyň: 16, 17; Obývák: 18" → { Kuchyň: [16, 17], Obývák: [18] } */
export function parseRooms(text: string): Record<string, number[]> {
  const out: Record<string, number[]> = {};
  for (const part of text.split(";")) {
    const [name, nums] = part.split(":");
    const ids = (nums || "").split(/[,\s]+/).map((n) => parseInt(n, 10)).filter((n) => Number.isFinite(n) && n >= 0);
    if (name?.trim() && ids.length) out[name.trim()] = ids;
  }
  return out;
}
