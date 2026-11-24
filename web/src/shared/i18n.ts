// 3.14 návrh 114: English UI. JARVIS is written in Czech; with Nastavení → Obecné → Jazyk = English every window
// translates what it shows through this dictionary – text, tooltips, placeholders and screen-reader labels – including
// whatever is drawn later (a MutationObserver). Your own content (chat messages, notes, file names, inputs) is never
// touched. A text that is not in the dictionary stays Czech; the dictionary grows with every release.

const EN: Record<string, string> = {
  // sidebar and groups
  "Hlavní": "Main", "Systém": "System", "Chat": "Chat", "Firemní agenti": "Business agents", "Propojení": "Connections",
  "Návyky a zdraví": "Habits & health", "Stark": "Stark", "Automatizace": "Automations", "Domov": "Home",
  "Paměť a projekty": "Memory & projects", "Učení": "Learning", "Soubory": "Files", "Záchrana a výkon": "Rescue & performance",
  "Bezpečí a soukromí": "Security & privacy", "E-mail a telefon": "E-mail & phone", "Úkoly": "Tasks",
  "Hlasový režim": "Voice mode", "Claude Code": "Claude Code", "Hra": "Game", "Diktování": "Dictation",
  "Nahrávání hovorů": "Call recording", "Statistiky": "Statistics", "Slovník a zkratky": "Dictionary & snippets",
  "Nastavení diktování": "Dictation settings", "Obecné": "General", "Mozek (AI)": "Brain (AI)", "Hlas": "Voice",
  "Notch": "Notch", "Vzhled": "Appearance", "Zkratky": "Shortcuts", "Oprávnění": "Permissions", "Nástroje": "Tools",
  "Integrace": "Integrations", "Telefon": "Phone", "Paměť": "Memory", "Rutiny": "Routines", "Záloha": "Backup",
  "Diagnostika": "Diagnostics", "Nastavení": "Settings", "Sekce": "Sections", "Agenti": "Agents",
  // common buttons and states
  "Zavřít": "Close", "Smazat": "Delete", "Načítám…": "Loading…", "Povolit": "Allow", "Zrušit": "Cancel", "Hotovo": "Done",
  "Další": "Next", "Připraven": "Ready", "PŘIPRAVEN": "READY", "Uložit": "Save", "Předchozí": "Previous", "Přidat": "Add",
  "Zamítnout": "Deny", "Nic nehraje": "Nothing playing", "Dnes": "Today", "Odebrat": "Remove", "Název": "Name", "Ne": "No",
  "Ano": "Yes", "Zpět": "Back", "Soustředění": "Focus", "Přizpůsobit": "Customize", "Přehrát / pauza": "Play / pause",
  "Pracuje": "Working", "Poslouchám": "Listening", "Poslouchám…": "Listening…", "Odpojit": "Disconnect", "Kopírovat": "Copy",
  "Vyzkoušet": "Try it", "Vypnout": "Turn off", "Zapnout": "Turn on", "Síť": "Network", "Spustit teď": "Run now",
  "Ranní brífink": "Morning briefing", "Brífink": "Briefing", "Procesor": "CPU", "Otevřít": "Open", "Odeslat": "Send",
  "Návyky": "Habits", "Nová konverzace": "New conversation", "Mluvit": "Talk", "Konverzace": "Conversations",
  "Chyba": "Error", "Aplikace": "Apps", "Akce": "Actions", "Zastavit": "Stop", "Zapnuto": "On", "Vypnuto": "Off",
  "Zapnutý": "On", "Velín firmy": "Company HQ", "Upravit": "Edit", "Týden soustředění": "Focus week",
  "Tento týden": "This week", "Připnout": "Pin", "Odepnout": "Unpin", "Přemýšlím…": "Thinking…", "Přemýšlím": "Thinking",
  "Přemýšlí": "Thinking", "Přehled": "Overview", "Poslat na PC": "Send to PC", "Otevřít celý chat": "Open full chat",
  "Obnovit": "Refresh", "Kdy": "When", "Chytrá domácnost": "Smart home", "Čeká na tebe": "Waiting for you",
  "Upozornění": "Notifications", "Ukončit": "Quit", "Týden": "Week", "Ty": "You", "Příkaz": "Command", "Připojit": "Connect",
  "Propojit": "Connect", "Plné": "Full", "Ok": "OK", "Načíst": "Load", "Ikona": "Icon", "Hry": "Games", "Hovor": "Call",
  "Hlasitost": "Volume", "Herní režim": "Game mode", "Grafika": "Graphics", "Dobré ráno": "Good morning",
  "Dobrou noc": "Good night", "Cíle": "Goals", "Barvy hudby": "Music colors", "Aktualizovat": "Update", "čeká": "waiting",
  "Černé": "Black", "úspěšnost": "success rate", "Ztmavení": "Dimming", "Ztlumit / zrušit ztlumení": "Mute / unmute",
  "Zprávy z telefonu na PC": "Phone messages on the PC", "Zpráva": "Message", "Zkusit znovu": "Try again",
  "Zkontrolovat": "Check", "Zkontrolovat síť": "Check the network", "Zapnout PC": "Wake the PC",
  "Zapnout PC z telefonu": "Wake the PC from the phone", "Vše": "All", "Včera": "Yesterday", "Výsledek": "Result",
  "Výkon": "Performance", "Více": "More", "Vytvořit": "Create", "Vrátit": "Undo", "Vlastní barva": "Custom color",
  "Ve světě": "In the world", "Upravit návyky": "Edit habits", "Uložit a vyzkoušet": "Save and try",
  "Test výkonu (6 s)": "Performance test (6 s)", "Telefon na monitoru PC": "Phone on the PC screen",
  "Zastavit vše (STOP)": "Stop everything (STOP)", "Zapnout / vypnout poslech": "Listening on / off",
  "Otevřít Stark HUD": "Open Stark HUD", "Hledat": "Search", "Hledat…": "Search…", "Napiš zprávu…": "Type a message…",
  "Zeptej se JARVISe…": "Ask JARVIS…", "Odpověď": "Answer", "Potvrdit": "Confirm", "Schválit": "Approve",
  "Zamítnuto": "Denied", "Povoleno": "Allowed", "Zkopírováno": "Copied", "Uloženo": "Saved", "Smazáno": "Deleted",
  "Bez připojení": "Offline", "Připojeno": "Connected", "Odpojeno": "Disconnected", "Připojuji…": "Connecting…",
  "Nahlásit chybu": "Report a bug", "Co je nového": "What's new", "Novinky": "What's new", "Nápověda": "Help",
  "Pondělí": "Monday", "Úterý": "Tuesday", "Středa": "Wednesday", "Čtvrtek": "Thursday", "Pátek": "Friday",
  "Sobota": "Saturday", "Neděle": "Sunday", "Po": "Mo", "Út": "Tu", "St": "We", "Čt": "Th", "Pá": "Fr", "So": "Sa",
  // page titles and their one-line descriptions
  "Úkoly a mise": "Tasks & missions",
  "Mission Control: plán, kroky, každá akce, důkazy a výsledky – co JARVIS dělá a co opravdu udělal.":
    "Mission Control: the plan, the steps, every action, proof and results – what JARVIS is doing and what it really did.",
  "Duplicity, podobné fotky, úklid složek, přejmenování, převody, archivy, metadata a záloha s ověřením. Nic se nesmaže natrvalo a hromadné změny jdou vrátit.":
    "Duplicates, similar photos, folder clean-up, renaming, conversions, archives, metadata and verified backups. Nothing is deleted for good and bulk changes can be undone.",
  "Chytrá domácnost, společné seznamy a tvoje síť – jako JARVIS v Starkově vile.":
    "Smart home, shared lists and your network – like JARVIS in Stark's mansion.",
  "Co JARVIS ví, odkud to ví a kde jste skončili. Všechno jde najít, opravit i smazat – a v soukromém režimu se nic neukládá.":
    "What JARVIS knows, where it knows it from and where you left off. Everything can be found, corrected or deleted – and private mode stores nothing.",
  "Proč PC padá, co ho brzdí, jestli je disk v pořádku a jestli je soubor nebo odkaz bezpečný. Jen čte a radí – měnit budeš ty.":
    "Why the PC crashes, what slows it down, whether the disk is healthy and whether a file or link is safe. It only reads and advises – you make the changes.",
  "Kartičky s chytrým opakováním, testy z tvých materiálů, kontrola výpočtů krok po kroku a plán před zkouškou.":
    "Flashcards with smart repetition, quizzes from your materials, step-by-step checks of calculations and an exam plan.",
  "Co jsi nadiktoval, jak rychle a kde. A co za tebe JARVIS udělal.": "What you dictated, how fast and where. And what JARVIS did for you.",
  "Co JARVIS smí, kolik smí utratit, co si pamatuje – a jak to všechno vypnout, vyexportovat nebo smazat.":
    "What JARVIS may do, how much it may spend, what it remembers – and how to switch it all off, export it or delete it.",
  "Co Claude Code právě dělá a schvalování jeho akcí z notche nebo z telefonu.":
    "What Claude Code is doing right now, and approving its actions from the notch or the phone.",
  "Jak se daří JARVISovi a tvému počítači.": "How JARVIS and your computer are doing.",
  "Protokoly, holografický HUD, ranní brífink a strážce – jako JARVIS z filmu.":
    "Protocols, the holographic HUD, the morning briefing and the guard – like JARVIS from the movie.",
  "„Když … tak …“ – JARVIS sám zareaguje na čas, aplikace, e-maily, zprávy na mobilu i na to, že odejdeš od PC.":
    "“When … then …” – JARVIS reacts on its own to the time, apps, e-mails, phone messages and to you leaving the PC.",
  "E-mail, telefon a kalendář": "E-mail, phone & calendar",
  "JARVIS čte a píše tvoje e-maily, volá ti, vytáčí, posílá SMS, ví, co tě čeká, a připomene to.":
    "JARVIS reads and writes your e-mails, calls you, dials, sends texts, knows what's ahead and reminds you.",
  // section labels
  "Archivy, převody, metadata": "Archives, conversions, metadata", "Bezpečnostní centrum": "Security center", "Bezpečí": "Safety",
  "Chování": "Behavior", "Co JARVIS dnes viděl a čeho se dotkl": "What JARVIS saw and touched today",
  "Co JARVIS ukládá": "What JARVIS stores", "Co o tobě vím": "What I know about you", "Dočasná oprávnění": "Temporary permissions",
  "E-mailové účty": "E-mail accounts", "Export, záloha, smazání": "Export, backup, deletion", "Fronta misí": "Mission queue",
  "Historie": "History", "Hlavní body": "Key points", "Hledat ve všem": "Search everything", "Hodnocení odpovědí": "Answer ratings",
  "Hra s postavičkou": "Character game", "Import z jiných AI a poznámek": "Import from other AIs and notes",
  "Jak se mi daří": "How I'm doing", "Kalendář": "Calendar", "Kontrola funkcí": "Feature check", "Kontrola výpočtu": "Calculation check",
  "Log (bez hesel a klíčů)": "Log (no passwords or keys)", "Mikrofon a kamera": "Microphone & camera", "Na tvém PC": "On your PC",
  "Nahrávky": "Recordings", "Najít a ochránit": "Find & protect", "Naposledy spuštěné": "Recently run",
  "Naučená pravidla": "Learned rules", "Nové e-maily": "New e-mails", "Nové kartičky": "New cards",
  "Nástroje, které nejčastěji selhávají": "Tools that fail most often", "Názvy": "Names", "Opakování": "Review",
  "Podprocesy": "Subprocesses", "Povaha a chování": "Personality & behavior", "Počítač": "Computer", "Projekty": "Projects",
  "Protokoly": "Protocols", "Přepis": "Transcript", "Příštích 7 dní": "Next 7 days", "Relace": "Sessions",
  "Rozpory v paměti": "Contradictions in memory", "Rychlost AI (do prvního slova)": "AI speed (to the first word)",
  "Rychlost AI (medián do prvního slova)": "AI speed (median to the first word)", "Schopnosti": "Abilities", "Seznamy": "Lists",
  "Soukromí": "Privacy", "Spotřeba AI": "AI usage", "Zdraví JARVISe": "JARVIS health", "Zkouška": "Exam",
  "Úklid paměti a šifrování": "Memory clean-up & encryption", "Úklid": "Clean-up", "Úplně offline": "Fully offline",
  "Časová osa": "Timeline", "Šablony": "Templates",
  // security page (3.14)
  "Režim jen pro čtení": "Read-only mode", "Dvojí potvrzení": "Double confirmation", "Soukromý režim": "Private mode",
  "Omezené prostředí pro kód": "Fenced code", "Kód smí na internet": "Code may use the internet",
  "Režim host (u PC sedí někdo jiný)": "Guest mode (someone else is at the PC)",
  "Režim host je zapnutý – nic osobního se neukazuje.": "Guest mode is on – nothing personal is shown.",
  "Dnes JARVIS na obrazovku, schránku ani ovládání nesáhl.": "Today JARVIS did not touch the screen, clipboard or controls.",
  // settings – general
  "Jazyk": "Language", "Jazyk řeči": "Speech language", "Jméno": "Name", "Město": "City", "Povaha": "Personality",
  "Automaticky": "Automatic", "Čeština": "Čeština", "Angličtina": "English", "Světlý": "Light", "Tmavý": "Dark",
  "Podle systému": "Follow the system",
  // chat
  "Pusť na YouTube nějakou dobrou hudbu": "Play some good music on YouTube", "Jaké bude zítra počasí?": "What's the weather tomorrow?",
  "Udělej screenshot a popiš, co je na obrazovce": "Take a screenshot and describe what's on the screen",
  "Najdi na webu dnešní zprávy z technologií": "Find today's tech news on the web", "Udělej mi web pro moji kavárnu": "Build a website for my café",
  "Co je teď na mé obrazovce?": "What's on my screen right now?", "Najdi dnešní zprávy z technologií": "Find today's tech news",
  "Napiš, řekni „Hey Jarvis“, nebo vyber jeden z návrhů.": "Type, say “Hey Jarvis”, or pick one of the suggestions.",
  "Napiš nebo nahraj hlasovou zprávu.": "Type or record a voice message.",
  "Napiš JARVISovi… (Enter odešle, Shift+Enter nový řádek)": "Message JARVIS… (Enter sends, Shift+Enter new line)",
  "Napiš JARVISovi…": "Message JARVIS…", "Celý chat": "Full chat", "Pracuji…": "Working…", "Mluvím…": "Speaking…",
  "Tančím": "Dancing", "Odpočívám": "Resting", "Dobré dopoledne": "Good morning", "Dobré odpoledne": "Good afternoon",
  "Dobrý večer": "Good evening", "pravý Ctrl": "right Ctrl", "levý Ctrl": "left Ctrl",
  // the phone before pairing
  "Spáruj telefon s počítačem. Na PC otevři JARVIS → Telefon a naskenuj QR kód.":
    "Pair the phone with your computer. On the PC open JARVIS → Phone and scan the QR code.",
  "Zadat ručně": "Enter manually", "Mluvit bez PC": "Talk without the PC",
  "Zdarma přes Groq nebo Gemini, přímo z telefonu": "Free via Groq or Gemini, right from the phone",
  "192.168.1.20:8765 TOKEN nebo odkaz z PC": "192.168.1.20:8765 TOKEN or the link from the PC",
  "Token už neplatí. Spáruj telefon znovu.": "The token is no longer valid. Pair the phone again.",
  // 3.14 who answers
  "Jiný text": "Other lyrics", "Text pozadu": "Lyrics late", "Text napřed": "Lyrics early", "Kdo odpovídá": "Who answers", "Která AI odpovídá": "Which AI answers", "Jen tento mozek": "Only this brain",
  "odpovídá": "answering", "záloha": "backup", "chybí klíč": "key missing", "přidat": "add", "v tomhle PC": "on this PC",
  "Načítám modely…": "Loading models…", "Model": "Model",
  "Ostatní AI se nepoužijí ani jako záloha.": "No other AI is used, not even as a backup.",
  "Když tahle AI nepůjde, zkusí JARVIS další v pořadí.": "If this AI fails, JARVIS tries the next one in line.",
  "Klikni na AI a od teď odpovídá ona. Pod ní přepneš model – u Ollamy ty, které máš stažené v PC, u Claude Opus, Sonnet, Haiku nebo Fable.":
    "Click an AI and it answers from now on. Below it you switch the model – for Ollama the ones downloaded on this PC, for Claude Opus, Sonnet, Haiku or Fable.",
  "O tobě": "About you", "Osobnost": "Personality", "Styl": "Style", "Tvoje jméno": "Your name",
  "Jak tě má oslovovat": "How to address you", "Domovské město": "Home city", "Pro počasí": "For the weather",
  "V jakém jazyce JARVIS odpovídá. English přepne do angličtiny i aplikaci.":
    "The language JARVIS answers in. English also switches the app to English.",
};

const ADDRESS: Record<string, string> = { pane: "sir", "šéfe": "boss", "paní": "ma'am", kámo: "mate" };
// texts built from parts ("Dobré ráno, Adame", "Připraven · drž pravý Ctrl"): the parts are translated one by one
const PATTERNS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^(Dobrou noc|Dobré ráno|Dobré dopoledne|Dobré odpoledne|Dobrý večer), (.+)$/, (m) => `${EN[m[1]] || m[1]}, ${ADDRESS[m[2]] || m[2]}`],
  [/^Připraven · drž (.+)$/, (m) => `Ready · hold ${EN[m[1]] || m[1]}`],
  [/^…a dalších (\d+)$/, (m) => `…and ${m[1]} more`],
];

let lang = "cs";
let observer: MutationObserver | null = null;
const ATTRS = ["title", "placeholder", "aria-label"];
// user content and anything typed: never translated
const SKIP = "textarea, input, pre, code, [contenteditable], [data-no-tr], .msg, .bubble, .chat-msg, .note-body, .md";

export function currentLang(): string {
  return lang;
}

export function tr(s: string): string {
  if (lang !== "en" || !s) return s;
  const key = s.trim();
  const v = EN[key];
  if (v) return s.replace(key, v);
  for (const [rx, fn] of PATTERNS) {
    const m = key.match(rx);
    if (m) return s.replace(key, fn(m));
  }
  return s;
}

function skip(el: Element | null): boolean {
  return !!el && !!el.closest(SKIP);
}

function translateNode(node: Node): void {
  if (node.nodeType === Node.TEXT_NODE) {
    const t = node.nodeValue || "";
    if (t.trim() && !skip(node.parentElement)) {
      const n = tr(t);
      if (n !== t) node.nodeValue = n;
    }
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  const el = node as Element;
  const field = el.matches("input, textarea");          // its hint is ours, its value is the user's
  if (skip(el) && !field) return;
  for (const a of ATTRS) {
    const v = el.getAttribute(a);
    if (v) {
      const n = tr(v);
      if (n !== v) el.setAttribute(a, n);
    }
  }
  if (!field) for (const c of Array.from(el.childNodes)) translateNode(c);
}

const KEY = "jarvis_ui_lang";

function remembered(): string {
  try { return localStorage.getItem(KEY) || ""; } catch { return ""; }
}

export function setLang(next: string | undefined, fromServer = true): void {
  const want = next === "en" ? "en" : "cs";
  if (fromServer) {
    try { localStorage.setItem(KEY, want); } catch { /* private window */ }
  }
  if (want === lang) return;
  if (lang === "en" && want === "cs") {           // the Czech originals were replaced → draw everything again
    location.reload();
    return;
  }
  lang = want;
  document.documentElement.lang = lang;
  translateNode(document.body);
  document.title = tr(document.title);
  observer = new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === "characterData") translateNode(m.target);
      else if (m.type === "attributes") translateNode(m.target);
      else m.addedNodes.forEach(translateNode);
    }
  });
  observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
}

export const DICTIONARY_SIZE = Object.keys(EN).length;

// before the PC has said which language (the phone's pairing screen, the first paint): the last one it said, else the
// device's own language
if (typeof document !== "undefined") {
  const first = remembered() || (/^en\b/i.test(navigator.language || "") ? "en" : "cs");
  if (first === "en") {
    const go = () => setLang("en", false);
    if (document.body) go(); else document.addEventListener("DOMContentLoaded", go, { once: true });
  }
}
