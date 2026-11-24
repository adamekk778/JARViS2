"""Which tools go to the AI with a message.

JARVIS has ~650 tools. Sending every description with every message is ~85 000 tokens – free tiers (Groq: ~8 000
tokens a minute, ~200 000 a day) ran out after one or two messages, and every answer was slow and costly. Now a
message carries a small everyday set, the tools its words point to, the ones used in the last turn, and `find_tools`:
when nothing offered fits, the AI asks for more by describing what it needs and gets them in the next step. Nothing
JARVIS can do is lost; it just is not all sent every time.
"""
from __future__ import annotations

import re
import unicodedata

# what people ask for every day – always offered (only those that exist and are allowed are sent)
CORE = (
    "open_app", "close_app", "open_url", "web_search", "web_read", "get_time", "weather", "set_timer", "set_reminder",
    "media_control", "volume", "youtube_play", "remember", "search_memory", "clipboard_get", "type_text", "press_keys",
    "window_control", "screenshot", "system_info", "send_to_phone", "google_ask", "world_news",
)
MAX_EXTRA = 10          # tools picked by the message's words
MAX_FOUND = 8           # tools one find_tools call adds
FIND = "find_tools"

_STOP = {"a", "i", "o", "u", "v", "z", "s", "k", "na", "se", "si", "je", "to", "ten", "ta", "do", "od", "po", "pro",
         "jak", "co", "kde", "kdy", "mi", "me", "mne", "muj", "moje", "tu", "ty", "the", "and", "for", "with", "prosim",
         "jarvis", "jarvisi", "muzes", "udelej", "dej", "chci", "bych", "by", "aby", "nebo", "ale", "tak", "jen", "uz"}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def stems(text: str) -> set[str]:
    """Rough Czech/English word stems: no accents, first 5 letters (so "fotku", "fotky", "fotka" meet)."""
    out = set()
    for w in re.findall(r"[a-z0-9]+", _norm(text).replace("_", " ")):
        if len(w) < 3 or w in _STOP:
            continue
        out.add(w[:5])
    return out


_INDEX: dict[str, tuple[set[str], set[str]]] = {}    # tool name → (stems of its name + category, stems of its description)


def _index(registry: dict) -> dict:
    if len(_INDEX) != len(registry) or any(n not in _INDEX for n in list(registry)[:5]):
        _INDEX.clear()
        for name, spec in registry.items():
            _INDEX[name] = (stems(name + " " + spec.category), stems(spec.description))
    return _INDEX


def _hits(q: set[str], words: set[str]) -> int:
    """How many of the query's stems the tool has – also when one is the start of the other ("web" ~ "websi")."""
    n = 0
    for w in q:
        if w in words or any(len(x) >= 3 and (x.startswith(w) or w.startswith(x)) for x in words):
            n += 1
    return n


def search(registry: dict, query: str, limit: int = MAX_FOUND, exclude: set[str] = frozenset()) -> list[str]:
    """Tool names that fit a few words, best first (a word in the tool's name or category counts more)."""
    q = stems(query)
    if not q:
        return []
    scored = []
    for name, (head, desc) in _index(registry).items():
        if name in exclude or name == FIND:
            continue
        s = 3 * _hits(q, head) + _hits(q, desc)
        if s:
            scored.append((s, name))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [n for _, n in scored[:limit]]


# 3.14 (návrh 5): Czech ways of saying things the word stems miss ("uspi", "vypni počítač", "kolik stojí bitcoin") –
# found by the evals (python -m jarvis.evals); each pattern runs on the text without accents, lower case
INTENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"\b(vypn\w*|uspi|usp[ai]t|restartuj|restart|hibern\w*|odhlas\w*)\b.*\b(pocitac\w*|pc|kompl?\w*|notebook\w*|system\w*)\b"
     r"|\b(uspi|restartuj)\b", ("system_power",)),
    (r"\b(kolik stoj\w*|cen\w* (bitcoin\w*|akci\w*|zlat\w*)|kurz\w*|bitcoin\w*|ethereum|akci\w* \w+)\b", ("price", "exchange_rate")),
    (r"\b(tramvaj\w*|autobus\w*|metr[oa]\w*|mhd|odjezd\w*|spoj\w*|vlak\w*|jede\b)", ("transit_departures", "transit_connection")),
    (r"\bnajdi\b.*\b(soubor\w*|dokument\w*|faktur\w*|fotk\w*|pdf|slozk\w*)\b", ("find_file", "windows_search")),
    (r"\b(prejmenuj|prejmenovat)\w*\b", ("rename_files", "smart_rename")),
    (r"\b(text\w*)\b.*\b(pisn\w*|pisnick\w*|song\w*)\b.*\b(spatn\w*|nesedi|jiny|neni)\b|\b(spatn\w*|jiny|neni (to )?ten)\b.*\btext\w*\b.*\b(pisn\w*|pisnick\w*)",
     ("lyrics_wrong",)),
    (r"\b(jak\w* (ai|model|mozek)|kter\w* (ai|model|mozek))\b.*\b(pouzivas|odpovida|mas)\b|\b(prepni|pouzij)\b.*\b(mozek|model|ai)\b",
     ("brain_switch",)),
    (r"\b(rekni|oznam|zahlas|vyhlas)\w*\b.*\b(do |v )?(kuchyn\w*|obyvak\w*|loznic\w*|pokoj\w*|vsem|celem dome|reproduktor\w*)",
     ("house_announce",)),
    (r"\b(elektrin\w*|proud\w*|spotov\w*)\b", ("electricity_prices", "energy_plan")),
    (r"\b(nejlevnej\w*)\b.*\b(hodin\w*|elektrin\w*|proud)\b|\b(pracku|mycku|nabij\w*)\b.*\bnejlevn\w*", ("energy_plan",)),
    (r"\b(zapni|probud|nastartuj)\b.*\b(herni pc|herni pocitac|notebook\w*|server\w*|druh\w* pc|druh\w* pocitac)", ("node_wake",)),
    (r"\b(zeptej se|posli|rekni)\b.*\b(notebook\w*|herni\w* (pc|pocitac\w*)|server\w*|druh\w* (pc|pocitac\w*))", ("node_ask",)),
    (r"\b(satelit\w*|hlasov\w* asistent\w* v)\b", ("satellite_setup",)),
    (r"\b(leti nad|letadl\w*|iss|vesmirn\w* stanic\w*|druzic\w*)\b", ("sky_overhead",)),
    (r"\b(kdo (sedi|je) (u|pred)|kdo je doma)\b", ("who_is_here",)),
    (r"\b(obliceje?|oblicej\w*)\b", ("face_enroll", "faces_setup", "face_forget", "who_is_here")),
    (r"\b(sleduj|hlidej|divej se)\b.*\b(obrazovk\w*|monitor\w*)\b", ("screen_buddy",)),
    (r"\b(hlidej|poslouchej)\b.*\b(zvuk\w*|dum|byt|doma)\b|\bkourov\w* (hlasic|alarm)", ("sound_watch",)),
    (r"\b(pomoc|upadl\w*|je mi zle|zachrank\w*|sos)\b", ("emergency_help", "emergency_ok")),
    (r"\bjsem v poradku\b|\bto byl omyl\b", ("emergency_ok",)),
    (r"\b(bezpecnostn\w* (prehled|brifink)|unik\w* (hesel|dat|e-?mail\w*))", ("security_briefing",)),
    (r"\bdetsk\w* rezim\w*\b", ("kids_mode",)),
    (r"\bholo\w*\b.*\bploch\w*\b|\bholo ?ploch\w*\b", ("hud_control",)),
    (r"\b(ziv\w* tapet\w*|tapet\w* (s |se )?(reaktor\w*|globus\w*))\b|\b(efekt\w*) na ploch\w*\b|\b(kvalit\w*) (efekt\w*|animac\w*)\b|"
     r"\b(motiv\w*|schema|barv\w*) (na )?(mark|friday|stealth|stark)\b", ("update_setting",)),
    (r"\b(priblizi?|oddali?|zvetsi|zmensi)\w*\b.*\b(map\w*|globus\w*|zem\w*)\b|\b(globus|zemekouli|3d map\w*)\b|"
     r"\b(schovej|skryj|ukaz|vrat)\w*\b.*\bpanel\w*\b|\b(hud|holo)\w*\b.*\b(minimal\w*|soustredeni|prezentac\w*|rozlozeni)\b",
     ("hud_control", "world_map")),
    # 3.15 Dílna (sekce C)
    (r"\b(navrhni|nakresli|vymodeluj|namodeluj|udelej|vytvor|navrhnes)\w*\b.*\b(krabick\w*|krabic\w*|drzak\w*|uhelnik\w*|desk\w* s (dir|otvor)\w*|"
     r"sloupek|sloupk\w*|hacek|hack\w*|knoflik\w*|3d model\w*|dil\w* (na|pro) (3d )?tisk|pouzdr\w*)|\b(cad|text na cad)\b|"
     r"\bo \d+(?:[.,]\d+)? ?(mm|cm|%|procent)\w* (sirs|uzs|delsi|kratsi|vyss|nizs|tluss|silnejs|tenc|vets|mens)\w*|"
     r"\b(sten\w*|dir\w*|der) (na )?\d+(?:[.,]\d+)? ?mm\b|\bna srouby m\d|\b(moje|vsechny) dily\b|\bpredchozi verz\w* dilu\b",
     ("cad_part",)),
    (r"\b(ukaz|otevri|zobraz|nacti)\w*\b.*\b(model\w*|stl|step|stp|3mf|glb|sestav\w*)\b(?!.*\b(jazykov|ai|umel)\w*)",
     ("model_view", "model_explode")),
    (r"\b(rozloz|sloz)\w* (ten |tu )?(model|sestav\w*|dil\w*)\b|\brozlozen\w* pohled\b|\b(otoc|toc)\w* model\w*\b",
     ("model_explode",)),
    (r"\b3d tisk\w*|\btiskarn\w*\b.*\b(3d|tisk\w*|tryska|podlozk\w*|filament\w*)|\b(stav|prubeh) tisku\b|"
     r"\b(pozastav|zastav|zrus|pokracuj|obnov)\w* (v )?tisk\w*\b|\bjak (je|jde) (na tom )?tisk\b|\bkolik zbyva\b.*\btisk\w*|"
     r"\b(spaget\w*|odlepil\w*)\b|\b(posli|dej)\b.*\bna tiskarn\w*|\bkamer\w* (na |u )?tiskarn\w*",
     ("printer_control",)),
    (r"\b(zaloz|novy|nov\w*) projekt\w*\b|\bdo projektu\b|\bdenik\w* (projekt\w*|dilny)\b|\bco mi chybi (na|do|k)\b|"
     r"\bdily (na|do|pro|k) \w+|\b(muj|moje|vsechny) projekt\w*\b|\b(stav|verz\w*) projekt\w*\b|\bkusovnik projekt\w*",
     ("workshop_project",)),
    (r"\b(simul\w*|spocitej|vydrzi|unese|ohne)\b.*\b(nosnik\w*|tyc\w*|polic\w*|profil\w*|trubk\w*|traverz\w*)|\bprohyb\w*|"
     r"\bteplot\w* (desk\w*|na desce|chladic\w*)|\b(jak|kolik) se (to )?zahrej\w*|\b(simul\w*|spocitej|vyres)\w* (obvod|zapojeni)\w*|"
     r"\bnapeti v uzl\w*|\bnabijeni kondenzator\w*|\bcasov\w* konstant\w*|\bnabeh proudu\b",
     ("simulate",)),
    (r"\b(co ses|co jsi se|cos) (v noci |dnes |vcera )?(naucil|naucila)\b|\bnocni uceni\b|\bprojdi (dnesni |svoje )?chyby\b",
     ("night_learn",)),
    (r"\bco jsem (delal|delala|resil|resila|dela)\b|\bna cem jsem (pracoval|delal)\w*\b", ("life_day",)),
    (r"\b(zapis|zapsat|poznamenej)\w*\b.*\b(do )?(deniku|pameti zivota)\b", ("life_note",)),
    (r"\bpamet\w* zivota\b", ("life_log_set", "life_day")),
    (r"\b(hlidej|sleduj|zjistuj|monitoruj)\b.*\b(cel\w* tyden|nekolik dni|dny|tydny|mesic\w*|dlouhodob\w*|dokud)\b|"
     r"\b(hlidej|sleduj)\b.*\b(byt\w*|nabid\w*|cen\w*|inzerat\w*)\b.*\b(dej vedet|ozvi se|napis)", ("quest_start", "quests_list")),
    (r"\b(jake|ktere|bezici) mise\b|\bmise\b.*\b(bezi|stav)\b", ("quests_list",)),
    (r"\b(zastav|zrus|ukonci)\w*\b.*\bmisi\b", ("quest_stop",)),
    (r"\bco kdyz\b|\b(simul\w*|spocitej)\b.*\b(sporeni|sporit|investic\w*|uver\w*|hypotek\w*|pujck\w*|projekt\w*)", ("what_if",)),
    (r"\b(vysavac\w*|vysav\w*|robot\w* vysavac\w*|roborock\w*)\b|\b(uklid|vysaj)\w*\b.*\b(kuchyn\w*|obyvak\w*|loznic\w*|byt|pokoj\w*|chodb\w*)",
     ("vacuum_control", "robots_status")),
    (r"\b(sekack\w*|posekej|sekat|pokos)\w*\b", ("mower_control", "robots_status")),
    (r"\b(dron\w*|tello|vzletni|vzlet\w*|pristan\w*|oblet\w*)\b", ("drone",)),
    (r"\b(sekretar\w*|prepojen\w* hovor\w*|presmerovan\w* hovor\w*|hovory? (co|ktere) nevezmu)\b", ("secretary_setup", "calls_history")),
    (r"\b(zavolej|volej|obvolej)\b.*\b(za mne|za me|mym jmenem|misto mne|misto me)\b|"
     r"\b(zavolej|zatelefonuj)\w*\b.*\b(a )?(zarezervuj|rezerv\w*|objednej|objednat|zjisti|domluv|zeptej)", ("call_for_me",)),
    (r"\b(kdo (mi )?volal|zmeskan\w* hovor\w*|vyridil\w* hovor\w*|historie hovor\w*)\b", ("calls_history", "phone_messages")),
    (r"\b(shrn\w*|prehled|co (mi )?(psal|psali|napsal\w*))\b.*\b(chat\w*|zprav\w*|whatsapp\w*|messenger\w*|telegram\w*|sms)\b|"
     r"\bco je nov\w* (na|v) (whatsapp\w*|messenger\w*|chat\w*)", ("chat_digest", "phone_messages")),
    (r"\b(odpovez|odepis|napis)\w*\b.*\b(na whatsapp\w*|na messenger\w*|v chatu|zpravu|na zpravu)\b|\bodpovez\b \w+\w*,? ze\b", ("chat_reply",)),
    (r"\b(najdi|propoj|nastav|pridej)\w*\b.*\b(aut[oa]|vuz|vozidl\w*)\b", ("car_setup", "car_status")),
    (r"\b(predehr\w*|vyhrej\w*|vytop\w*|klimatizac\w*)\b.*\b(aut[oau]|vuz|vozidl\w*)\b|\b(aut[oa])\b.*\b(predehr\w*|topen\w*|klimatiz\w*)",
     ("car_climate", "car_ready")),
    (r"\bpriprav\w* aut[oa]\b", ("car_ready", "car_climate")),
    (r"\b(zamkn\w*|zamkl\w*|odemkn\w*|odemcen\w*|zamcen\w*)\b.*\b(aut[oa]|vuz)\b|\b(aut[oa])\b.*\b(zamc\w*|zamkn\w*|odemk\w*)", ("car_lock", "car_status")),
    (r"\b(aut[oau]|vuz|vozidl\w*)\b.*\b(stav|dojezd|baterie|baterk\w*|nabit\w*|palivo|nadrz\w*|kde (je|stoji)|jak je na tom)|"
     r"\b(kde (je|stoji|mam)|jak je na tom|dojezd)\b.*\b(aut[oa]|vuz)\b|\bkolik mam dojezd", ("car_status",)),
    (r"\b(kdy|v kolik)\b.*\b(letim|leti|odlet\w*|jede\w*|odjizd\w*|odjezd\w*)\b.*\b(let|vlak|letadl\w*|mi)?|\bmoje (cesty|lety|letenky)\b|"
     r"\bkdy (mam )?vyrazit\b", ("trips_list", "flight_status")),
    (r"\b(pridej|zapis|uloz)\w*\b.*\b(let|vlak)\b", ("trip_add",)),
    (r"\b(smaz|zrus|odeber)\w*\b.*\b(let|vlak|cest\w*)\b", ("trip_remove",)),
    (r"\b(zpozdeni|gate|terminal\w*)\b|\b(kde je|stav)\b.*\b(letadl\w*|let\w*)\b", ("flight_status", "trips_list")),
    (r"\b(hlidej|sleduj|pridej)\w*\b.*\b(balik\w*|zasilk\w*)\b", ("parcel_add", "parcels_list")),
    (r"\b(nehlidej|prestan hlidat|smaz|odeber)\w*\b.*\b(balik\w*|zasilk\w*)\b", ("parcel_remove",)),
    (r"\b(balik\w*|zasilk\w*|dopravc\w*|packet\w*)\b", ("parcels_list", "parcel_add")),
    # 3.19 Cesty 2
    (r"\b(vlak\w*|vlakem|autobus\w*|regiojet\w*|jizdenk\w*|leo express)\b.*\b(z|do|na)\b|\b(z|do)\b.*\b(vlakem|autobusem)\b",
     ("train_search", "transit_connection")),
    (r"\b(viz\w*|vizum|pas\b|pasu|obcank\w*|esta|eta|etias|vstupni podminky)\b.*\b(do|na)\b|\bco (potrebuju|potrebuji) do\b",
     ("entry_requirements",)),
    (r"\bcestovni kart\w*|\b(rezervac\w*|cest\w*|hotel\w*)\b.*\b(do telefonu|offline)\b", ("trip_pack",)),
    (r"\b(stravne|stravneho|cestovni nahrad\w*|diet\w*)\b", ("travel_allowance",)),
    (r"\bspolucestujic\w*", ("travel_companions",)),
    # 3.18 Cesty: hledat, porovnat, rezervovat (a platit) až po potvrzení
    (r"\b(hotel\w*|ubytovan\w*|penzion\w*|apartman\w*|airbnb|booking)\b", ("hotel_search", "travel_offers", "booking_list")),
    (r"\b(letenk\w*|letet|odlet\w* z|let z|lety z|letadlem)\b.*\b(do|na|z)\b|\bnajdi\b.*\blet\w*\b", ("flight_search", "travel_offers")),
    (r"\b(vylet|dovolen\w*|cest\w*|vikend)\b.*\b(naplanuj|planuj|zarid|vymysli|priprav)\w*|\b(naplanuj|zarid)\w*\b.*\b(cest\w*|vylet|dovolen\w*|vikend)",
     ("trip_plan", "hotel_search", "flight_search")),
    (r"\b(beru|bereme|vezmu|vezmeme|rezervuj|zarezervuj|objednej)\b.*\b(jednick\w*|dvojk\w*|trojk\w*|ctyrk\w*|petk\w*|prvni|druh[yaeou]|"
     r"tret[iy]|ctvrt[yaeou]|pat[yaeou]|cislo \d|nabidk\w*|ten hotel|ten let|\d)\b|\b(rezervuj|zarezervuj)\w*\b", ("travel_book", "travel_offers")),
    (r"\b(zrus|storn\w*|posun|zmen)\w*\b.*\b(rezervac\w*|hotel\w*|letenk\w*|ubytovan\w*)\b",
     ("booking_cancel_check", "booking_cancel", "booking_change", "booking_list")),
    (r"\b(moje |me )?rezervac\w*\b", ("booking_list", "booking_cancel_check")),
    (r"\b(napis|posli)\w*\b.*\bhotel\w*\b|\b(pozdni prijezd|postylk\w*)\b", ("hotel_message", "email_send")),
    (r"\b(vstupenk\w*|listk\w* na|prohlidk\w*|zazitk\w*|muze\w*|getyourguide)\b", ("experiences",)),
    (r"\b(dej vedet|hlidej|upozorni)\w*\b.*\b(cen\w*|pod \d+|zlevn\w*|levnejs\w*)\b", ("travel_watch",)),
    (r"\b(kolik|utrat\w*|stal\w*)\b.*\b(cest\w*|dovolen\w*|hotel\w*|letenk\w*)\b", ("travel_spend",)),
    (r"\b(mapa? svet\w*|mapu svet\w*|radar\w*|mapu (pocasi|srazek))\b", ("world_map",)),
    (r"\b(stav system\w*|jak jsem (se )?(\w+ )?vyspal\w*|jak jsem (\w+ )?spal\w*|kolik jsem (\w+ )?spal\w*|klidov\w* tep\w*|muj tep\w*|variabilit\w* tep\w*)",
     ("body_status", "body_history")),
    (r"\b(spanek|spani|tep\w*|kroky|kroku)\b.*\b(tyden|tydnu|mesic\w*|poslednich|trend\w*)\b", ("body_history",)),
    (r"\b(pitn\w* rezim\w*|pripomin\w*.*\b(pit|vod\w*|spat|spanek)|drzeni tela|hrbim|hrbit|narovn\w*)", ("health_reminders", "posture_calibrate")),
    (r"\b(ted|uz) sedim (dobre|rovne|spravne)\b", ("posture_calibrate",)),
    (r"\b(kamer\w*|zvonek|zvonku|frigate)\b", ("cameras_status",)),
    (r"\b(co (to )?hraje|kdo to zpiva|interpret\w*|zpevak\w*)\b.*\b(pisn\w*|pisnick\w*|hraje|song\w*)?", ("now_playing_info",)),
    (r"\b(lehk\w*|jednoduch\w*)\b.*\b(tezk\w*|slozit\w*)\b|\brozdel\w*\b.*\b(mozk\w*|ai)\b", ("brain_split",)),
    (r"\b(oprav\w*|nefung\w*|spadl\w*|pada\w*)\b.*\b(dovednost\w*|skill\w*)\b|\b(dovednost\w*|skill\w*)\b.*\b(nefung\w*|spadl\w*|pada\w*)",
     ("skill_fix", "list_skills")),
    (r"\b(nainstaluj|nainstalovat|instaluj|stahni a nainstaluj)\b", ("app_search", "app_install")),
    (r"\b(odinstaluj|odinstalovat|odeber program|smaz program)\w*", ("app_uninstall",)),
    (r"\b(sluzb\w*)\b.*\b(vypni|zapni|automatick\w*|rucn\w*|zakaz\w*|vrat\w*)\b|\b(vypni|zakaz)\w* sluzb\w*", ("service_start_type", "service_revert")),
    (r"\b(ovladac\w* (grafik\w*|graficke)|driver\w* (gpu|grafik\w*)|aktualni ovladac)\b", ("gpu_driver_check",)),
    (r"\b(fps|snimk\w* za sekundu)\b", ("game_fps", "fps_by_settings")),
    (r"\b(uloz|ulozit|nahraj) (to|klip|highlight|moment)\b|\bto bylo (dobry|dobre|epick\w*)\b|\bhighlight\w*", ("save_highlight",)),
    (r"\bobs\b|\b(prepni|zmen) scen\w*|\b(zacni|spust|ukonci|zastav) (nahravani|stream\w*|vysilani)\b", ("obs_scene", "obs_record", "obs_stream")),
    (r"\b(zabal|sdilej|exportuj) dovednost\w*|\bjarvisskill\b|\bnainstaluj dovednost\w*|\bkatalog\w* dovednost\w*",
     ("skill_pack", "skill_install_package", "skill_catalog")),
    (r"\b(zaloh\w*|backup)\b", ("backup_folder", "auto_backup", "check_backups")),
    (r"\b(modr\w* obrazovk\w*|bsod|spadl\w*|pad\w* (pocitac|system|pc)|minidump\w*)\b", ("crash_dumps", "explain_crash_code")),
    (r"\b(wifi|wi fi|siti|sit\b|router\w*)\b.*\b(zarizeni|pripojen\w*|kdo)\b|\bzarizeni\b.*\b(wifi|siti)\b", ("network_devices",)),
    (r"\b(probud\w*|wake on lan|zapni\w* (druhy|jiny) pocitac)\b", ("wake_device",)),
    (r"\b(kolik (casu|hodin)|cas u pocitace|stravil\w*|screen time)\b", ("screen_time",)),
    (r"\b(kopiroval\w*|zkopiroval\w*|historie schranky|predtim zkopirovan\w*)\b", ("clipboard_history",)),
    (r"\b(spust|pust|rozbehni)\w* testy\b|\btesty\b.*\bspust\w*", ("run_tests",)),
    (r"\b(web\w*|strank\w*|landing\w*|eshop\w*)\b.*\b(udelej|vytvor|naprogramuj|postav)\w*|\b(udelej|vytvor|postav)\w*\b.*\b(web\w*|strank\w*)\b",
     ("make_website",)),
    (r"\b(v kodu|ve zdrojac\w*|v projektu)\b.*\b(najdi|kde)\b|\bnajdi\b.*\bv kodu\b", ("find_in_files",)),
    (r"\b(hesl\w*|token\w*|klic\w*|secret\w*)\b.*\b(projekt\w*|kod\w*|repozitar\w*|gitu?)\b"
     r"|\b(projekt\w*|kod\w*|repozitar\w*)\b.*\b(hesl\w*|token\w*|secret\w*)\b", ("scan_secrets",)),
    (r"\b(nespolehliv\w*|flaky|obcas pad\w*)\b.*\btest\w*", ("find_flaky_tests", "flaky_tests")),
    (r"\b(tabulk\w*|schema\w*|sloupc\w*)\b.*\b(databaz\w*|db|sql)\b|\bdatabaz\w*\b.*\b(tabulk\w*|schema)", ("db_schema",)),
    (r"\b(vygeneruj|nakresli|namaluj|vytvor)\w*\b.*\b(obrazek|obrazku|obraz|fotku|ilustrac\w*|logo)\b", ("generate_image",)),
    (r"\b(nahled\w*|thumbnail\w*|miniatur\w*)\b", ("make_thumbnail",)),
    (r"\b(odstran|vystrihni|smaz)\w* (ticho|pauzy|mezery)\b", ("remove_silence",)),
    (r"\b(hlasovk\w*|nahravk\w*|audio)\b.*\b(na text|prepis\w*)\b|\bprepis\w*\b.*\b(hlasovk\w*|nahravk\w*)\b",
     ("read_attachment", "clean_speech")),
    (r"\b(barevn\w* (schema|paletu|paleta|kombinac\w*)|paleta barev|barvy pro)\b", ("color_theme",)),
    (r"\b(slab\w*|nejde mi|potize)\b.*\b(matemat\w*|fyzi\w*|chemi\w*|anglictin\w*|predmet\w*|uceni|ucen\w*)\b", ("learning_weak_spots",)),
    (r"\bprevod\w*|\bprevedd?\b.*\b(na|do)\b.*\b(km|kilometr\w*|mil\w*|metr\w*|kil\w*|liber\w*|stupn\w*|palc\w*|litr\w*)\b"
     r"|\b\d+ (mil|liber|palcu|stop|galonu|uncí|unci)\b", ("unit_calc",)),
    (r"\bvyslovnost\w*", ("pronunciation_practice",)),
    (r"\b(kazd\w* (den|rano|vecer|tyden|pondeli|hodin\w*)|vzdy (kdyz|v)|pravideln\w*)\b", ("create_automation", "schedule_task")),
    (r"\b(naucit|nauc) se\b|\bukazu ti\b|\bnahraj (postup|co delam)\b", ("record_workflow_start", "workflow_record")),
    (r"\b(nedodelal\w*|nedokoncil\w*|rozdelan\w*|zapomnel\w* udelat)\b", ("forgotten_work", "pinned_tasks")),
    (r"\b(dari|daril\w*|statistik\w*|winrate|kolik jsem hral\w*)\b.*\b(hra|hrach|hre|hraju|valorant\w*|cs2|lol)\b", ("game_stats", "gaming_stats")),
    (r"\b(mluv|mluvit) (rychle|pomale|potise|hlasite|jinak)\w*|\bzmen\w*\b.*\b(barv\w*|hlas\w*|jmen\w*|velikost\w*)\b"
     r"|\b(postavick\w*|mochi)\b.*\b(barv\w*|velk\w*|mal\w*)\b|\bnastav\w*\b.*\b(hlas|notch|vzhled)\b", ("update_setting",)),
)
_INTENT_RX: list = []


def intents(text: str) -> list[str]:
    """Tools these words mean, by the INTENTS patterns (most specific first, at most 6)."""
    if not _INTENT_RX:
        _INTENT_RX.extend((re.compile(rx), names) for rx, names in INTENTS)
    t = re.sub(r"[^a-z0-9 ]", " ", _norm(text or ""))
    t = " ".join(t.split())
    out: list[str] = []
    for rx, names in _INTENT_RX:
        if rx.search(t):
            out += [n for n in names if n not in out]
    return out[:6]


def pick(registry: dict, allowed: set[str], text: str, recent: list[str] = (), extra: int = MAX_EXTRA) -> list[str]:
    """The tool names to send with this message: the everyday set, what the words point to, the last turn's tools.
    extra: how many the words may add (3.13: fewer for an AI on this PC – every tool is text it must read first)."""
    names = [n for n in CORE if n in allowed]
    for n in recent:
        if n in allowed and n not in names:
            names.append(n)
    for n in intents(text):                         # 3.14 what the words mean, before what they look like
        if n in allowed and n in registry and n not in names:
            names.append(n)
    for n in search(registry, text, extra * 3, exclude=set(names)):
        if n in allowed and n not in names:
            names.append(n)
            if len(names) >= len(CORE) + len(recent) + extra:
                break
    if FIND in allowed:
        names.append(FIND)
    return names
