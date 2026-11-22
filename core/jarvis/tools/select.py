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
