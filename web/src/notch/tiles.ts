import { fmtSize, h, icon, KIND_ICON, toast } from "../shared/dom";
import { renderMarkdown } from "../shared/markdown";
import type { Attachment, ServerMsg } from "../shared/protocol";
import type { JarvisClient } from "../shared/ws";

export interface TileCtx {
  client: JarvisClient;
  pin: (v: boolean) => void;
  openChat: (view?: string) => void;
  shelf: Attachment[];
}

export interface Tile {
  el: HTMLElement;
  on?: (m: ServerMsg) => void;
  update?: (data: any) => void;
  state?: () => unknown;
  delta?: (t: string) => void;
  done?: (t: string) => void;
  attach?: (a: Attachment) => void;
}

const tile = (name: string, title: string, ic: string, width: number, ...body: (Node | null)[]) =>
  h("section", { class: `tile tile-${name}`, "data-tile": name, style: { width: `${width}px` } },
    h("header", {}, icon(ic), h("span", {}, title)), ...body);

export function buildTiles(ctx: TileCtx): Record<string, Tile> {
  const { client } = ctx;
  const quick = (action: string, args: any = {}) => client.send("quick_action", { action, args });
  const tiles: Record<string, Tile> = {};

  // ---- Ask ----
  {
    const input = h("input", { class: "n-input", placeholder: "Zeptej se JARVISe…", "aria-label": "Zeptej se" }) as HTMLInputElement;
    const answer = h("div", { class: "ask-answer md" });
    const atts: Attachment[] = [];
    const attRow = h("div", { class: "ask-atts" });
    let text = "";
    const send = () => {
      const v = input.value.trim();
      if (!v && !atts.length) return;
      client.send("user_text", { text: v, attachments: atts.map((a) => a.id) });
      input.value = "";
      atts.length = 0;
      attRow.replaceChildren();
      text = "";
      answer.innerHTML = '<span class="muted">…</span>';
    };
    input.addEventListener("focus", () => ctx.pin(true));
    input.addEventListener("blur", () => ctx.pin(false));
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); if (e.key === "Escape") input.blur(); });
    const file = h("input", { type: "file", hidden: true, multiple: true }) as HTMLInputElement;
    file.onchange = async () => { for (const f of [...(file.files || [])]) tiles.ask.attach!(await client.upload(f, f.name)); file.value = ""; };
    const el = tile("ask", "Zeptej se", "sparkle", 300,
      h("div", { class: "ask-row" }, input,
        h("button", { class: "n-btn", type: "button", "aria-label": "Přiložit", onclick: () => file.click() }, icon("paperclip")),
        h("button", { class: "n-btn", type: "button", "aria-label": "Mluvit", title: "Mluvit (Ctrl+Mezerník)", onclick: () => client.send("push_to_talk") }, icon("microphone")),
        h("button", { class: "n-btn accent", type: "button", "aria-label": "Odeslat", onclick: send }, icon("arrow-up", "ph-bold")), file),
      attRow, answer);
    tiles.ask = {
      el,
      delta: (t) => { text += t; answer.innerHTML = renderMarkdown(text.length > 500 ? "…" + text.slice(-500) : text); answer.scrollTop = answer.scrollHeight; },
      done: (t) => { text = t; answer.innerHTML = renderMarkdown(t); answer.scrollTop = answer.scrollHeight; },
      attach: (a) => { atts.push(a); attRow.append(h("span", { class: "n-chip" }, icon(KIND_ICON[a.kind] || "file"), a.name)); },
    };
  }

  // ---- Now playing ----
  {
    let st: any = {};
    const art = h("div", { class: "media-art" }, icon("music-notes"));
    const title = h("div", { class: "media-title" }, "Nic nehraje");
    const artist = h("div", { class: "media-artist" }, "");
    const playBtn = h("button", { class: "n-btn big", type: "button", "aria-label": "Play/pauza", onclick: () => quick("media_control", { action: "play_pause" }) }, icon("play", "ph-fill"));
    const el = tile("media", "Právě hraje", "music-notes", 250,
      h("div", { class: "media-top" }, art, h("div", { class: "media-meta" }, title, artist)),
      h("div", { class: "media-ctl" },
        h("button", { class: "n-btn", type: "button", "aria-label": "Předchozí", onclick: () => quick("media_control", { action: "previous" }) }, icon("skip-back", "ph-fill")),
        playBtn,
        h("button", { class: "n-btn", type: "button", "aria-label": "Další", onclick: () => quick("media_control", { action: "next" }) }, icon("skip-forward", "ph-fill"))));
    tiles.media = {
      el,
      state: () => st,
      update: (m) => {
        st = m || {};
        title.textContent = st.title || "Nic nehraje";
        artist.textContent = st.artist || (st.title ? "" : "Řekni: pusť hudbu");
        playBtn.replaceChildren(icon(st.playing ? "pause" : "play", "ph-fill"));
        art.replaceChildren(st.thumb ? h("img", { src: st.thumb, alt: "" }) : icon("music-notes"));
        el.classList.toggle("playing", !!st.playing);
      },
    };
  }

  // ---- Shelf ----
  {
    const list = h("div", { class: "shelf-list" });
    const el = tile("shelf", "Police", "tray", 220, list);
    const render = (items: Attachment[]) => {
      ctx.shelf = items || [];
      list.replaceChildren(...(ctx.shelf.length ? ctx.shelf.map((a) =>
        h("div", { class: "shelf-item", title: `${a.name} (${fmtSize(a.size)})` },
          a.thumb ? h("img", { src: client.url(a.thumb), alt: "" }) : icon(KIND_ICON[a.kind] || "file"),
          h("span", { class: "shelf-name" }, a.name),
          h("button", { class: "n-btn sm", type: "button", title: "Otevřít na PC", "aria-label": "Otevřít", onclick: () => quick("save_attachment", { id: a.id, open: true }) }, icon("arrow-square-out")),
          h("button", { class: "n-btn sm", type: "button", title: "Zeptat se JARVISe", "aria-label": "Zeptat se", onclick: () => client.send("user_text", { text: "Co je v tomhle souboru?", attachments: [a.id] }) }, icon("sparkle")),
          h("button", { class: "n-btn sm", type: "button", title: "Odebrat", "aria-label": "Odebrat", onclick: () => client.send("shelf_remove", { attachment_id: a.id }) }, icon("x"))))
        : [h("div", { class: "shelf-empty" }, icon("tray-arrow-down"), "Přetáhni sem soubory")]));
    };
    render(ctx.shelf);
    tiles.shelf = { el, update: render };
  }

  // ---- Quick actions ----
  {
    const b = (ic: string, label: string, fn: () => void) =>
      h("button", { class: "q-btn", type: "button", title: label, "aria-label": label, onclick: fn }, icon(ic), h("span", {}, label));
    const el = tile("quick", "Rychlé akce", "lightning", 220,
      h("div", { class: "q-grid" },
        b("speaker-slash", "Ztlumit", () => quick("volume", { action: "mute" })),
        b("speaker-low", "Tišeji", () => quick("volume", { action: "down", level: 10 })),
        b("speaker-high", "Hlasitěji", () => quick("volume", { action: "up", level: 10 })),
        b("camera", "Snímek", () => quick("screenshot")),
        b("moon", "Tmavý", () => quick("set_dark_mode", { dark: true })),
        b("lock", "Zamknout", () => quick("system_power", { action: "lock" }))));
    tiles.quick = { el };
  }

  // ---- Timers ----
  {
    let items: any[] = [];
    const list = h("div", { class: "timer-list" });
    const render = () => {
      list.replaceChildren(...(items.length ? items.map((t) => {
        const r = Math.max(0, Math.round(t.ends_at - Date.now() / 1000));
        return h("div", { class: "timer" }, h("span", { class: "t-left" }, `${Math.floor(r / 60)}:${String(r % 60).padStart(2, "0")}`),
          h("span", { class: "t-label" }, t.label),
          h("button", { class: "n-btn sm", type: "button", "aria-label": "Zrušit", onclick: () => quick("cancel_timer", { id_or_label: t.id }) }, icon("x")));
      }) : [h("div", { class: "muted small" }, "Žádný časovač")]));
    };
    setInterval(render, 1000);
    const add = (min: number) => () => quick("set_timer", { seconds: min * 60, label: `${min} min` });
    const el = tile("timers", "Časovače", "timer", 200, list,
      h("div", { class: "t-add" }, ...[1, 5, 10, 25].map((m) => h("button", { class: "n-pill", type: "button", onclick: add(m) }, `+${m}`))));
    tiles.timers = { el, state: () => items, update: (x) => { items = x || []; render(); }, on: (m) => { if (m.type === "quick_result" && /timer/.test(m.action)) client.send("timers_get"); } };
  }

  // ---- System ----
  {
    const vals = { cpu: h("b"), ram: h("b"), disk: h("b"), bat: h("b") };
    const cell = (ic: string, label: string, v: HTMLElement) => h("div", { class: "sys" }, icon(ic), h("span", {}, label), v);
    const batCell = cell("battery-high", "Baterie", vals.bat);
    const el = tile("system", "Systém", "cpu", 190,
      h("div", { class: "sys-grid" }, cell("cpu", "CPU", vals.cpu), cell("memory", "RAM", vals.ram), cell("hard-drives", "Disk", vals.disk), batCell));
    const poll = () => { if (document.visibilityState === "visible") client.send("system_get"); };
    setInterval(poll, 5000);
    tiles.system = {
      el,
      on: (m) => {
        if (m.type === "welcome") poll();
        if (m.type !== "system") return;
        vals.cpu.textContent = `${Math.round(m.cpu_percent)} %`;
        vals.ram.textContent = `${Math.round(m.ram_percent)} %`;
        vals.disk.textContent = `${Math.round(m.disk_percent)} %`;
        batCell.hidden = m.battery_percent == null;
        vals.bat.textContent = m.battery_percent != null ? `${m.battery_percent} %${m.charging ? " ⚡" : ""}` : "";
      },
    };
  }

  // ---- Weather ----
  {
    const temp = h("div", { class: "w-temp" }, "--°");
    const desc = h("div", { class: "w-desc" }, "");
    const days = h("div", { class: "w-days" });
    const el = tile("weather", "Počasí", "cloud-sun", 200, h("div", { class: "w-now" }, temp, desc), days);
    let last = 0;
    const poll = () => { if (Date.now() - last > 15 * 60 * 1000) { last = Date.now(); client.send("weather_get"); } };
    setInterval(poll, 60 * 1000);
    tiles.weather = {
      el,
      on: (m) => {
        if (m.type === "welcome") { last = 0; poll(); }
        if (m.type !== "weather") return;
        if (m.error) { desc.textContent = "nedostupné"; return; }
        temp.textContent = `${Math.round(m.temp)}°`;
        desc.textContent = `${m.city}, ${m.desc}`;
        const dn = ["Ne", "Po", "Út", "St", "Čt", "Pá", "So"];
        days.replaceChildren(...(m.days || []).slice(1, 4).map((d: any) =>
          h("div", { class: "w-day" }, h("span", {}, dn[new Date(d.date).getDay()]), h("b", {}, `${Math.round(d.max)}°`), h("span", { class: "muted" }, `${Math.round(d.min)}°`))));
      },
    };
  }

  // ---- Phone ----
  {
    const status = h("div", { class: "ph-status" }, "Nepřipojen");
    const el = tile("phone", "Telefon", "device-mobile", 190, status,
      h("button", { class: "n-pill", type: "button", onclick: () => ctx.openChat("phone") }, icon("qr-code"), " Spárovat"));
    let devices = 0;
    tiles.phone = {
      el,
      on: (m) => {
        if (m.type === "pairing") devices = (m.devices || []).length;
        if (m.type === "welcome") client.send("pairing_get");
        if (m.type === "pairing" || m.type === "welcome") {
          status.replaceChildren(icon(devices ? "check-circle" : "circle-dashed"), devices ? ` Připojeno (${devices})` : " Nepřipojen");
        }
        if (m.type === "quick_result" && m.action === "share") toast("Přijato z telefonu", "ok");
      },
    };
  }
  return tiles;
}
