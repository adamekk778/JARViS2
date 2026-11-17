// 3.12 on the phone: what the business agents prepared and waits for your click (send this e-mail, change this DNS…)
// and a step-by-step permissions guide (Android 13+ blocks some of them for an app installed from a file).
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import { native, type PhoneStatus } from "./native";

interface Proposal { id: number; agent: string; description: string; details: string[] }

/** "Ke schválení" – shown only while something waits. */
export function approvalsCard(c: JarvisClient): HTMLElement {
  let items: Proposal[] = [];
  let busy = 0;
  const el = h("div", { class: "card m-appr", hidden: true });
  const paint = () => {
    el.hidden = !items.length;
    el.replaceChildren(
      h("div", { class: "m-appr-h" }, icon("seal-check", "ph-fill"), h("strong", {}, `Ke schválení (${items.length})`),
        h("span", {}, "Připravili agenti – nic se nestalo, dokud neschválíš.")),
      ...items.slice(0, 5).map((p) => h("div", { class: "m-appr-item" },
        h("b", {}, p.agent), h("span", {}, p.description),
        p.details?.length ? h("pre", {}, p.details.slice(0, 12).join("\n")) : "",
        h("div", { class: "btn-row" },
          h("button", { class: "btn", type: "button", disabled: !!busy, onclick: () => { busy = p.id; c.send("bizproposal_decide", { id: p.id, approve: false }); } }, "Zamítnout"),
          h("button", { class: "btn primary", type: "button", disabled: !!busy, onclick: () => {
            busy = p.id; native.haptic(); c.send("bizproposal_decide", { id: p.id, approve: true });
          } }, icon("check", "ph-bold"), "Schválit")))));
  };
  c.on("bizagents", (m: any) => {
    items = Array.isArray(m.proposals) ? m.proposals : [];
    if (busy && m.message) toast(String(m.message).slice(0, 140), m.ok === false ? "error" : "ok", 4000);
    busy = 0;
    paint();
  });
  c.onStatus((s) => { if (s === "open") c.send("bizagents_get"); });
  c.on("notify", (m: any) => { if (/ke schválení/i.test(String(m.title || ""))) c.send("bizagents_get"); });
  return el;
}

const WIZ = "jarvis.permwiz.v1";
const android13 = () => { const m = navigator.userAgent.match(/Android (\d+)/); return m ? Number(m[1]) >= 13 : true; };

/** The permissions one by one, each with its own button; ✓ when Android says it is on. */
export function permissionsWizard(force = false): void {
  if (!native.phone.available) return;
  try { if (!force && localStorage.getItem(WIZ)) return; } catch { /* no storage */ }
  const list = h("div", { class: "m-wiz-list" });
  const step = (done: boolean, title: string, text: string, label: string, fn: () => void) => h("div", { class: `m-wiz-step ${done ? "done" : ""}` },
    h("span", { class: "m-wiz-ico" }, icon(done ? "check-circle" : "circle", done ? "ph-fill" : undefined)),
    h("div", {}, h("strong", {}, title), h("span", {}, text)),
    done ? "" : h("button", { class: "btn sm primary", type: "button", onclick: fn }, label));
  const paint = (st: PhoneStatus) => list.replaceChildren(
    android13() && !st.notifAccess ? step(false, "1. Odemknout omezená nastavení",
      "Android blokuje některá oprávnění u aplikací ze souboru. Klepni Odemknout → vpravo nahoře ⋮ → Povolit omezená nastavení. "
      + "Když tam ⋮ není, nejdřív klepni na Povolit u kroku 3 (Android jednou napíše „odepřen přístup“) a pak sem.", "Odemknout",
      () => native.phone.openAppDetails()) : "",
    step(st.phone, "2. Volání, SMS a kontakty", "„Zavolej mámě“, „pošli SMS…“. Když se Android nezeptá, zapni je v Oprávnění.", "Povolit",
      async () => { const s = await native.phone.requestPhone(); paint(s); if (!s.phone) native.phone.openAppDetails(); }),
    step(st.notifAccess, "3. Oznámení na PC", "JARVIS na PC řekne, kdo ti píše a volá.", "Povolit", () => native.phone.openNotificationAccess()),
    step(st.overlay, "4. Zobrazovat přes jiné aplikace", "Pro hovor od JARVISe a notch na telefonu.", "Povolit", () => native.phone.openOverlay()),
    step(st.battery, "5. Bez uspávání baterií", "Jinak Android spojení s PC v noci uspí.", "Povolit", () => native.phone.openBattery()),
    step(st.fullScreen, "6. Zvonění přes zamčenou obrazovku", "Aby hovor od JARVISe zazvonil jako opravdový.", "Nastavit", () => native.phone.openFullScreen()));
  const close = () => { try { localStorage.setItem(WIZ, "1"); } catch { /* no storage */ } sheet.remove(); document.removeEventListener("visibilitychange", again); };
  const refresh = async () => { try { paint(await native.phone.status()); } catch { /* not ready */ } };
  const again = () => { if (!document.hidden) refresh(); };          // back from Android's settings: ticks update
  document.addEventListener("visibilitychange", again);
  const sheet = h("div", { class: "m-wiz" }, h("div", { class: "m-wiz-card" },
    h("div", { class: "m-wiz-head" }, h("strong", {}, "Nastavení telefonu"), h("button", { class: "icon-btn", type: "button", "aria-label": "Zavřít", onclick: close }, icon("x"))),
    h("p", { class: "m-wiz-sub" }, "Projdi kroky shora dolů. Každý otevře správné místo v Androidu – po návratu se tu objeví ✓."),
    list, h("button", { class: "btn", type: "button", onclick: close }, "Hotovo – zbytek později")));
  document.body.append(sheet);
  refresh();
}
