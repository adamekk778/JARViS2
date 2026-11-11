/* 3.12 search music across services, right in the notch's music screen: type an artist or a song, pick where it
   should play (Spotify, YouTube, YouTube Music, Apple Music, SoundCloud, Amazon Music, Deezer) and click.
   Top result, artists with photos, songs with covers, an artist's page with top songs (musicsearch.py). */
import { brandEl, MEDIA, type Brand } from "../shared/brands";
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import "./musichub.css";

const SERVICES: { id: string; name: string; note: string; brand?: Brand }[] = [
  { id: "auto", name: "Automaticky", note: "pustí se hned (YouTube)" },
  { id: "spotify", name: "Spotify", note: "otevře skladbu ve Spotify", brand: MEDIA.spotify },
  { id: "youtube", name: "YouTube", note: "pustí se hned", brand: MEDIA.youtube },
  { id: "youtubemusic", name: "YouTube Music", note: "v prohlížeči", brand: MEDIA.youtubemusic },
  { id: "applemusic", name: "Apple Music", note: "v prohlížeči", brand: MEDIA.applemusic },
  { id: "soundcloud", name: "SoundCloud", note: "v prohlížeči", brand: MEDIA.soundcloud },
  { id: "amazonmusic", name: "Amazon Music", note: "v prohlížeči", brand: MEDIA.amazonmusic },
  { id: "deezer", name: "Deezer", note: "přesně tahle skladba", brand: MEDIA.deezer },
];
const KEY = "jarvis.music.service";
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s) % 60).padStart(2, "0")}`;
const fans = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1).replace(".0", "")} mil. fanoušků` : n >= 1e3 ? `${Math.round(n / 1e3)} tis. fanoušků` : n ? `${n} fanoušků` : "");

export function createMusicHub(client: JarvisClient, onActive: (on: boolean) => void) {
  let service = (() => { try { return localStorage.getItem(KEY) || "auto"; } catch { return "auto"; } })();
  let q = "", timer = 0, view: "none" | "results" | "artist" = "none", lastResults: any = null;
  const input = h("input", { class: "mh-input", type: "search", placeholder: "Hledat písničku nebo interpreta…", "aria-label": "Hledat hudbu", spellcheck: "false" }) as HTMLInputElement;
  const clearBtn = h("button", { type: "button", class: "mh-clear", "aria-label": "Zrušit hledání", hidden: true, onclick: () => reset() }, icon("x"));
  const svcBtn = h("button", { type: "button", class: "mh-svc", "aria-haspopup": "menu", onclick: (e: Event) => { e.stopPropagation(); toggleMenu(); } });
  const menu = h("div", { class: "mh-menu", role: "menu", hidden: true });
  const bar = h("div", { class: "mh-bar" }, h("div", { class: "mh-field" }, icon("magnifying-glass"), input, clearBtn), svcBtn, menu);
  const results = h("div", { class: "mh-results", hidden: true });

  const svcLogo = (s: (typeof SERVICES)[number]) => (s.brand ? brandEl(s.brand, "brand-logo mh-logo") : h("span", { class: "mh-logo auto" }, icon("sparkle", "ph-fill")));
  function paintSvc() {
    const s = SERVICES.find((x) => x.id === service) || SERVICES[0];
    svcBtn.replaceChildren(svcLogo(s), h("span", {}, s.name), icon("caret-down"));
    svcBtn.title = `Kde pustit: ${s.name}`;
    menu.replaceChildren(...SERVICES.map((x) => h("button", { type: "button", role: "menuitemradio", "aria-checked": String(x.id === service), class: x.id === service ? "on" : "",
      onclick: () => { service = x.id; try { localStorage.setItem(KEY, service); } catch { /* private */ } paintSvc(); menu.hidden = true; } },
      svcLogo(x), h("div", {}, h("strong", {}, x.name), h("span", {}, x.note)), x.id === service ? icon("check") : "")));
  }
  function toggleMenu() {
    menu.hidden = !menu.hidden;
    if (!menu.hidden) {
      const off = (e: MouseEvent) => { if (!menu.contains(e.target as Node) && !svcBtn.contains(e.target as Node)) { menu.hidden = true; document.removeEventListener("pointerdown", off, true); } };
      document.addEventListener("pointerdown", off, true);
    }
  }
  function setView(v: typeof view) {
    view = v;
    results.hidden = v === "none";
    clearBtn.hidden = !q && v === "none";
    onActive(v !== "none");
  }
  function reset() {
    q = ""; input.value = ""; lastResults = null;
    window.clearTimeout(timer);
    setView("none");
  }
  function run(now = false) {
    window.clearTimeout(timer);
    q = input.value.trim().replace(/\s+/g, " ").slice(0, 120);     // as JARVIS normalises it (to match the answer)
    clearBtn.hidden = !q;
    if (!q) { setView("none"); return; }
    timer = window.setTimeout(() => {
      results.replaceChildren(h("div", { class: "mh-loading" }, h("i", { class: "mh-spin" }), "Hledám…"));
      setView("results");
      client.send("music_search", { q });
    }, now ? 0 : 380);
  }
  input.addEventListener("input", () => run());
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") run(true); if (e.key === "Escape") reset(); });

  const play = (t: any) => {
    client.send("music_play", { service, track: { id: t.id, title: t.title, artist: t.artist } });
    toast(`${t.title} – ${t.artist}`, "ok", 1800);
  };
  const trackRow = (t: any, i?: number) => h("button", { type: "button", class: "mh-track", title: `Pustit: ${t.title}`, onclick: () => play(t) },
    i !== undefined ? h("span", { class: "mh-n" }, String(i + 1)) : "",
    h("span", { class: "mh-cover" }, t.cover ? h("img", { src: t.cover, alt: "", loading: "lazy" }) : icon("music-note", "ph-fill"), h("i", { class: "mh-play" }, icon("play", "ph-fill"))),
    h("span", { class: "mh-tt" }, h("strong", {}, t.title, t.explicit ? h("em", { title: "Explicitní" }, "E") : ""), h("span", {}, t.artist)),
    h("span", { class: "mh-dur" }, t.duration ? mmss(t.duration) : ""));
  const artistChip = (a: any) => h("button", { type: "button", class: "mh-artist", title: a.name, onclick: () => openArtist(a.id) },
    h("span", { class: "mh-ph" }, a.picture ? h("img", { src: a.picture, alt: "", loading: "lazy" }) : icon("user", "ph-fill")), h("span", {}, a.name));

  function paintResults(m: any) {
    lastResults = m;
    if (m.error) { results.replaceChildren(h("div", { class: "mh-empty" }, icon("wifi-slash"), h("strong", {}, "Hledání teď nejde"), h("span", {}, m.error))); return; }
    if (!m.top && !m.tracks?.length) { results.replaceChildren(h("div", { class: "mh-empty" }, icon("music-notes-simple"), h("strong", {}, "Nic jsme nenašli"), h("span", {}, `Pro „${m.q}“ nic. Zkus jiný zápis.`))); return; }
    const top = m.top;
    const topCard = top ? h("button", { type: "button", class: `mh-top ${top.kind}`, onclick: () => (top.kind === "artist" ? openArtist(top.id) : play(top)) },
      h("span", { class: "mh-top-img" }, (top.kind === "artist" ? top.picture_big || top.picture : top.cover_big || top.cover) ? h("img", { src: top.kind === "artist" ? top.picture_big || top.picture : top.cover_big || top.cover, alt: "" }) : icon("music-note", "ph-fill")),
      h("strong", {}, top.kind === "artist" ? top.name : top.title),
      h("span", {}, top.kind === "artist" ? "Interpret" : `Skladba · ${top.artist}`),
      h("i", { class: "mh-top-play" }, icon(top.kind === "artist" ? "arrow-right" : "play", "ph-fill"))) : "";
    results.replaceChildren(
      h("section", { class: "mh-row1" },
        h("div", {}, h("h4", {}, "Nejlepší výsledek"), topCard),
        h("div", { class: "mh-col" }, h("h4", {}, "Skladby"), h("div", { class: "mh-tracks" }, ...(m.tracks || []).slice(0, 4).map((t: any) => trackRow(t))))),
      m.artists?.length ? h("section", {}, h("h4", {}, "Interpreti"), h("div", { class: "mh-artists" }, ...m.artists.map(artistChip))) : "",
      (m.tracks || []).length > 4 ? h("section", {}, h("h4", {}, "Další skladby"), h("div", { class: "mh-tracks" }, ...m.tracks.slice(4).map((t: any) => trackRow(t)))) : "");
    results.scrollTop = 0;
  }
  function openArtist(id: number) {
    results.replaceChildren(h("div", { class: "mh-loading" }, h("i", { class: "mh-spin" }), "Načítám interpreta…"));
    setView("artist");
    client.send("music_artist", { id });
  }
  function paintArtist(a: any) {
    if (view !== "artist") return;
    results.replaceChildren(
      h("div", { class: "mh-ahead" },
        h("button", { type: "button", class: "mh-back", "aria-label": "Zpět na výsledky", onclick: () => { if (lastResults) { setView("results"); paintResults(lastResults); } else reset(); } }, icon("caret-left")),
        h("span", { class: "mh-aph" }, a.picture_big || a.picture ? h("img", { src: a.picture_big || a.picture, alt: "" }) : icon("user", "ph-fill")),
        h("div", {}, h("strong", {}, a.name), h("span", {}, [fans(a.fans), a.albums_count ? `${a.albums_count} alb` : ""].filter(Boolean).join(" · "))),
        a.tracks?.[0] ? h("button", { type: "button", class: "mh-playall", onclick: () => play(a.tracks[0]) }, icon("play", "ph-fill"), "Pustit") : ""),
      h("h4", {}, "Nejposlouchanější"),
      h("div", { class: "mh-tracks" }, ...(a.tracks || []).map((t: any, i: number) => trackRow(t, i))));
    results.scrollTop = 0;
  }
  client.on("music_results", (m) => { if (view === "results" && m.q === q) paintResults(m); });
  client.on("music_artist_info", (m) => paintArtist(m));
  paintSvc();
  return { bar, results, reset, focus: () => input.focus() };
}
