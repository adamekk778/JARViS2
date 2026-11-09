/* 3.12 "Přizpůsobit" – your own look of the notch panel: the clock's colour (presets or any colour you pick), its look,
   and the panel's background – black, the colours of the music that plays, or your own photo, with how dark and how
   blurred it is. Remembered on this PC (the photo is shrunk to at most 1600 px first). */
import { h, icon, toast } from "../shared/dom";
import { CLOCK_COLORS, CLOCK_STYLES, STYLE_NAMES } from "./clock";
import { type Look, loadLook as load, loadPhoto, onLookChange, savePhoto, saveLook, shrinkPhoto as shrink } from "../shared/lookstore";

type Clock = { readonly style: string; readonly color: string; setColor: (c: string) => void; setStyle: (s: string) => void };
export function createLook(host: HTMLElement, clock: Clock) {
  let look = load(), photo = loadPhoto(), album = "";
  const layer = h("div", { class: "p-bgimg", "aria-hidden": "true" });
  host.prepend(layer);

  function apply() {
    const src = look.bg === "photo" ? photo : look.bg === "album" ? album : "";
    host.dataset.bg = src ? look.bg : "none";
    layer.style.backgroundImage = src ? `url("${src}")` : "";
    host.style.setProperty("--bg-dim", String(look.dim / 100));
    host.style.setProperty("--bg-blur", `${look.bg === "album" ? Math.max(look.blur, 28) : look.blur}px`);
  }
  function save() {
    saveLook(look);
    apply();
    paint();
  }
  // picked in the main window (Nastavení → Vzhled): the notch follows
  onLookChange(() => { look = load(); photo = loadPhoto(); apply(); if (!sheet.hidden) paint(); });

  // ---- the sheet ----
  const file = h("input", { type: "file", accept: "image/*", hidden: true }) as HTMLInputElement;
  file.onchange = async () => {
    const f = file.files?.[0];
    file.value = "";
    if (!f) return;
    try {
      photo = await shrink(f);
      if (!savePhoto(photo)) toast("Fotka je moc velká na uložení – zkus menší", "error");
      look.bg = "photo";
      save();
    } catch (e: any) { toast(e.message || "Fotku se nepodařilo načíst", "error"); }
  };
  const swatches = h("div", { class: "lk-swatches" });
  const custom = h("input", { type: "color", class: "lk-color", title: "Vlastní barva", "aria-label": "Vlastní barva hodin" }) as HTMLInputElement;
  custom.oninput = () => { clock.setColor(custom.value); paint(); };
  const styles = h("div", { class: "lk-chips" });
  const bgs = h("div", { class: "lk-bgs" });
  const dim = h("input", { type: "range", min: 0, max: 85, step: 1, class: "lk-range", "aria-label": "Ztmavení pozadí" }) as HTMLInputElement;
  const blur = h("input", { type: "range", min: 0, max: 30, step: 1, class: "lk-range", "aria-label": "Rozmazání pozadí" }) as HTMLInputElement;
  dim.oninput = () => { look.dim = Number(dim.value); dim.style.setProperty("--v", `${(look.dim / 85) * 100}%`); apply(); };
  blur.oninput = () => { look.blur = Number(blur.value); blur.style.setProperty("--v", `${(look.blur / 30) * 100}%`); apply(); };
  dim.onchange = blur.onchange = () => save();
  const sliders = h("div", { class: "lk-sliders" },
    h("label", {}, h("span", {}, "Ztmavení"), dim), h("label", {}, h("span", {}, "Rozmazání"), blur));

  function paint() {
    swatches.replaceChildren(...CLOCK_COLORS.map((c) => h("button", { type: "button", class: `lk-sw ${c === "grad" ? "grad" : ""} ${clock.color === c ? "on" : ""}`,
      style: c === "grad" ? {} : { background: c }, title: c === "grad" ? "Duhový přechod" : c, "aria-label": c === "grad" ? "Duhový přechod" : `Barva ${c}`,
      onclick: () => { clock.setColor(c); paint(); } })),
      h("label", { class: `lk-sw custom ${!(CLOCK_COLORS as readonly string[]).includes(clock.color) ? "on" : ""}`, title: "Vlastní barva",
        style: !(CLOCK_COLORS as readonly string[]).includes(clock.color) ? { background: clock.color } : {} }, icon("eyedropper"), custom));
    if (/^#[0-9a-f]{6}$/i.test(clock.color)) custom.value = clock.color;
    styles.replaceChildren(...CLOCK_STYLES.map((st) => h("button", { type: "button", class: `lk-chip ${clock.style === st ? "on" : ""}`,
      onclick: () => { clock.setStyle(st); paint(); } }, STYLE_NAMES[st])));
    const card = (k: Look["bg"], label: string, preview: Node) => h("button", { type: "button", class: `lk-bg ${look.bg === k ? "on" : ""}`,
      onclick: () => { if (k === "photo" && !photo) { file.click(); return; } look.bg = k; save(); } }, preview, h("span", {}, label));
    bgs.replaceChildren(
      card("none", "Černé", h("i", { class: "lk-prev black" })),
      card("album", "Barvy hudby", h("i", { class: "lk-prev album", style: album ? { backgroundImage: `url("${album}")` } : {} })),
      card("photo", "Moje fotka", photo ? h("i", { class: "lk-prev", style: { backgroundImage: `url("${photo}")` } }) : h("i", { class: "lk-prev add" }, icon("plus"))),
      h("button", { type: "button", class: "lk-pick", onclick: () => file.click() }, icon("image"), h("span", {}, photo ? "Jiná fotka" : "Vybrat fotku")));
    dim.value = String(look.dim); dim.style.setProperty("--v", `${(look.dim / 85) * 100}%`);
    blur.value = String(look.blur); blur.style.setProperty("--v", `${(look.blur / 30) * 100}%`);
    sliders.hidden = look.bg === "none";
  }
  const sheet = h("div", { class: "lk-sheet", role: "dialog", "aria-label": "Přizpůsobit vzhled", hidden: true },
    h("div", { class: "lk-head" }, h("strong", {}, "Přizpůsobit"),
      h("button", { type: "button", class: "lk-x", "aria-label": "Zavřít", onclick: () => open(false) }, icon("x"))),
    h("div", { class: "lk-body" },
      h("section", {}, h("h4", {}, "Barva hodin"), swatches),
      h("section", {}, h("h4", {}, "Vzhled hodin"), styles),
      h("section", {}, h("h4", {}, "Pozadí panelu"), bgs, sliders)),
    file);
  host.append(sheet);
  function open(on: boolean) {
    sheet.hidden = !on;
    if (on) { paint(); sheet.animate([{ opacity: 0, transform: "translateY(10px) scale(.98)" }, { opacity: 1, transform: "none" }], { duration: 280, easing: "cubic-bezier(.2,.9,.25,1)" }); }
  }
  const button = h("button", { class: "p-icon", type: "button", title: "Přizpůsobit vzhled (barvy, pozadí)", "aria-label": "Přizpůsobit vzhled",
    onclick: () => open(sheet.hidden) }, icon("paint-brush"));

  apply();
  return {
    button,
    close: () => open(false),
    /** the album art of the song playing (the "Barvy hudby" background) */
    setAlbum(thumb: string) { if (thumb === album) return; album = thumb; apply(); if (!sheet.hidden) paint(); },
  };
}
