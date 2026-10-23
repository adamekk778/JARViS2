import "./chat.css";
import { fmtSize, fmtTime, h, icon, KIND_ICON, toast, TOOL_ICON } from "./dom";
import { renderMarkdown, wireCodeCopy } from "./markdown";
import type { AgentState, Attachment, Message, ServerMsg, ToolCard } from "./protocol";
import type { JarvisClient } from "./ws";
import { Recorder } from "./recorder";
import { Blob } from "../character/blob";

const STATE_TEXT: Record<AgentState, string> = {
  idle: "", listening: "Poslouchám", thinking: "Přemýšlím", acting: "Pracuji", speaking: "Mluvím",
  waiting: "Čekám na potvrzení",
};

interface Pending {
  file: File;
  att?: Attachment;
  progress: number;
  error?: string;
  el: HTMLElement;
}

export interface ChatOptions {
  compact?: boolean; // mobile
  placeholder?: string;
  greeting?: string;        // empty-state headline
  subtitle?: string;
  suggestions?: string[];   // [] = none
  emptyAvatar?: boolean;    // big character in the empty state (default true)
}

const DEFAULT_SUGGESTIONS = ["Pusť na YouTube nějakou dobrou hudbu", "Jaké bude zítra počasí?",
  "Udělej screenshot a popiš, co je na obrazovce", "Najdi na webu dnešní zprávy z technologií"];

/** Static little JARVIS for message avatars (the animated Blob is reserved for live places). */
export const miniBlob = (live = false) => h("div", { class: `mini-blob ${live ? "live" : ""}`, "aria-hidden": "true" }, h("i"), h("i"));

export class ChatView {
  el: HTMLElement;
  private list: HTMLElement;
  private scroller: HTMLElement;
  private input: HTMLTextAreaElement;
  private sendBtn: HTMLButtonElement;
  private micBtn: HTMLButtonElement;
  private pendingBox: HTMLElement;
  private statusLine: HTMLElement;
  private pending: Pending[] = [];
  private live: { el: HTMLElement; body: HTMLElement; tools: HTMLElement; text: string; raf?: number } | null = null;
  private liveTools = new Map<string, HTMLElement>();
  private state: AgentState = "idle";
  private recorder = new Recorder();
  private conversation = "";
  private audio: HTMLAudioElement | null = null;
  private stickBottom = true;
  private empty: HTMLElement;
  private greetingEl!: HTMLElement;
  emptyBlob: Blob | null = null;

  setGreeting(text: string) {
    this.greetingEl.textContent = text;
  }

  /** Put text into the composer (quick cards: "Otevři …"). */
  prefill(text: string, file = false) {
    this.input.value = text;
    this.autosize();
    this.input.focus();
    this.input.setSelectionRange(text.length, text.length);
    if (file) (this.el.querySelector('input[type="file"]') as HTMLInputElement | null)?.click();
  }

  constructor(private client: JarvisClient, opts: ChatOptions = {}) {
    this.list = h("div", { class: "chat-list", role: "log", "aria-live": "polite" });
    this.greetingEl = h("h2", {}, opts.greeting || "Jak můžu pomoct?");
    const avatar = opts.emptyAvatar === false ? null : new Blob({ size: 96 });
    if (avatar) this.emptyBlob = avatar;
    this.empty = h("div", { class: "chat-empty" },
      avatar ? avatar.el : null,
      this.greetingEl,
      opts.subtitle ? h("p", { class: "chat-sub" }, opts.subtitle) : null,
      h("div", { class: "chat-suggest" },
        ...(opts.suggestions ?? DEFAULT_SUGGESTIONS)
          .map((s) => h("button", { class: "chip suggest", type: "button", onclick: () => this.sendText(s) }, s))));
    this.scroller = h("div", { class: "chat-scroll" }, this.empty, this.list);
    this.scroller.addEventListener("scroll", () => {
      const s = this.scroller;
      this.stickBottom = s.scrollHeight - s.scrollTop - s.clientHeight < 80;
    });
    wireCodeCopy(this.list);

    this.input = h("textarea", {
      class: "chat-input", rows: 1, placeholder: opts.placeholder || "Napiš JARVISovi… (Enter odešle, Shift+Enter nový řádek)",
      "aria-label": "Zpráva",
    });
    this.input.addEventListener("input", () => this.autosize());
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing && !opts.compact) {
        e.preventDefault();
        this.submit();
      }
    });
    this.input.addEventListener("paste", (e) => {
      const files = [...(e.clipboardData?.files || [])];
      if (files.length) {
        e.preventDefault();
        files.forEach((f) => this.addFile(f));
      }
    });
    const fileInput = h("input", { type: "file", multiple: true, hidden: true }) as HTMLInputElement;
    fileInput.addEventListener("change", () => {
      [...(fileInput.files || [])].forEach((f) => this.addFile(f));
      fileInput.value = "";
    });
    const attachBtn = h("button", { class: "icon-btn", type: "button", title: "Přiložit soubor", "aria-label": "Přiložit soubor", onclick: () => fileInput.click() }, icon("paperclip"));
    this.micBtn = h("button", { class: "icon-btn", type: "button", title: "Nahrát hlasovou zprávu", "aria-label": "Hlasová zpráva", onclick: () => this.toggleMic() }, icon("microphone"));
    this.sendBtn = h("button", { class: "send-btn", type: "button", "aria-label": "Odeslat", onclick: () => this.submit() }, icon("arrow-up", "ph-bold"));
    this.pendingBox = h("div", { class: "pending" });
    this.statusLine = h("div", { class: "chat-status" });
    const composer = h("div", { class: "composer" },
      this.pendingBox,
      h("div", { class: "composer-row" }, attachBtn, this.input, this.micBtn, this.sendBtn), fileInput);

    this.el = h("div", { class: `chat ${opts.compact ? "compact" : ""}` }, this.scroller, this.statusLine, composer);
    this.setupDrop();
    this.bind();
  }

  // ---------- server events ----------
  private bind() {
    const c = this.client;
    c.on("welcome", (m) => {
      this.conversation = m.conversation;
      this.renderHistory(m.history || []);
      this.setState(m.busy ? "thinking" : "idle");
      if (m.mood) this.emptyBlob?.setMood(m.mood.mood, m.mood);
      if (m.settings?.character) this.emptyBlob?.setColor(m.settings.character.color, m.settings.character.glow || undefined);
    });
    c.on("history", (m) => {
      if (m.prepend) this.prependHistory(m.messages);
      else {
        this.conversation = m.conversation;
        this.renderHistory(m.messages);
      }
    });
    c.on("user_message", (m) => this.appendMessage({ id: m.id, role: "user", text: m.text, attachments: m.attachments || [], source: m.source, created: Date.now() / 1000 }));
    c.on("transcript", (m) => {
      if (!m.final) this.statusLine.textContent = `„${m.text}“`;
    });
    c.on("state", (m) => this.setState(m.state));
    c.on("mood", (m) => this.emptyBlob?.setMood(m.mood, { badge: m.badge, progress: m.progress }));
    c.on("assistant_delta", (m) => this.delta(m.text));
    c.on("tool_start", (m) => this.toolStart(m));
    c.on("tool_end", (m) => this.toolEnd(m));
    c.on("assistant_done", (m) => this.done(m));
    c.on("confirm_request", (m) => this.confirmCard(m));
    c.on("confirm_timeout", (m) => this.list.querySelector(`[data-confirm="${m.id}"]`)?.classList.add("resolved"));
    c.on("confirm_resolved", (m) => this.list.querySelector(`[data-confirm="${m.id}"]`)?.classList.add("resolved"));
    c.on("error", (m) => toast(m.message, "error", 6000));
    c.on("tts_audio", (m) => this.play(c.url(m.attachment.url)));
    c.on("quick_result", (m) => m.summary && toast(m.summary, m.ok ? "ok" : "error"));
  }

  private setState(s: AgentState) {
    this.state = s;
    const busy = s !== "idle";
    this.sendBtn.classList.toggle("stop", busy);
    this.sendBtn.replaceChildren(icon(busy ? "stop" : "arrow-up", busy ? "ph-fill" : "ph-bold"));
    this.sendBtn.setAttribute("aria-label", busy ? "Zastavit" : "Odeslat");
    this.statusLine.replaceChildren(...(busy ? [h("span", { class: "dots" }, h("i"), h("i"), h("i")), STATE_TEXT[s]] : []));
  }

  // ---------- rendering ----------
  private renderHistory(msgs: Message[]) {
    this.list.replaceChildren(...msgs.map((m) => this.messageEl(m)));
    this.live = null;
    this.updateEmpty();
    this.scrollBottom(true);
    this.markLast();
  }

  private prependHistory(msgs: Message[]) {
    const prevH = this.scroller.scrollHeight;
    this.list.prepend(...msgs.map((m) => this.messageEl(m)));
    this.scroller.scrollTop += this.scroller.scrollHeight - prevH;
  }

  private updateEmpty() {
    this.empty.hidden = this.list.childElementCount > 0;
  }

  private markLast() {
    this.list.querySelectorAll(".msg.assistant.last").forEach((e) => e.classList.remove("last"));
    const all = this.list.querySelectorAll(".msg.assistant");
    all[all.length - 1]?.classList.add("last");
  }

  private appendMessage(m: Message) {
    if (m.id && this.list.querySelector(`[data-id="${m.id}"]`)) return;
    this.list.append(this.messageEl(m));
    this.updateEmpty();
    this.scrollBottom(m.role === "user");
  }

  private attachmentsEl(atts: Attachment[]): HTMLElement | null {
    if (!atts?.length) return null;
    const box = h("div", { class: "atts" });
    for (const a of atts) {
      if (a.missing) continue;
      if (a.kind === "image" && a.thumb) {
        box.append(h("a", { class: "att-img", href: this.client.url(a.url), target: "_blank", rel: "noopener", title: a.name },
          h("img", { src: this.client.url(a.thumb), alt: a.name, loading: "lazy" })));
      } else if (a.kind === "audio") {
        box.append(h("div", { class: "att-audio" }, h("audio", { controls: true, preload: "none", src: this.client.url(a.url) })));
      } else {
        box.append(h("a", { class: "att-file", href: this.client.url(a.url, true), target: "_blank", rel: "noopener", download: a.name },
          icon(KIND_ICON[a.kind] || "file"), h("span", { class: "att-name" }, a.name), h("span", { class: "att-size" }, fmtSize(a.size)),
          icon("download-simple")));
      }
    }
    return box;
  }

  private toolsEl(tools: ToolCard[] = []): HTMLElement {
    const box = h("div", { class: "tools" });
    for (const t of tools) box.append(this.toolChip(t.name, t.label, t.ok ? "ok" : "fail", t.summary));
    return box;
  }

  private toolChip(name: string, label: string, st: "run" | "ok" | "fail", summary = ""): HTMLElement {
    return h("div", { class: `tool ${st}`, title: summary, "data-name": name },
      icon(TOOL_ICON[name] || "gear-six"), h("span", { class: "tool-label" }, label.replace(/^[^\p{L}\p{N}]+/u, "")),
      st === "run" ? h("span", { class: "spin" }) : icon(st === "ok" ? "check" : "x"),
      summary && st !== "run" ? h("span", { class: "tool-sum" }, summary) : null);
  }

  private messageEl(m: Message): HTMLElement {
    if (m.role === "user") {
      const voice = (m.source || "").includes("voice");
      return h("div", { class: "msg user", "data-id": m.id },
        h("div", { class: "bubble" },
          voice ? h("span", { class: "voice-tag", title: "Hlasem" }, icon("microphone")) : null,
          m.text ? h("div", { class: "user-text" }, m.text) : null,
          this.attachmentsEl(m.attachments)),
        h("div", { class: "meta" }, fmtTime(m.created)));
    }
    const body = h("div", { class: "md", html: renderMarkdown(m.text) });
    return h("div", { class: "msg assistant", "data-id": m.id },
      miniBlob(),
      h("div", { class: "a-main" },
        this.toolsEl(m.meta?.tools),
        body,
        this.attachmentsEl(m.attachments),
        this.actions(m)));
  }

  private actions(m: Message): HTMLElement {
    return h("div", { class: "actions" },
      h("button", { class: "icon-btn sm", type: "button", title: "Kopírovat", "aria-label": "Kopírovat", onclick: () => { navigator.clipboard?.writeText(m.text); toast("Zkopírováno", "ok", 1500); } }, icon("copy")),
      h("button", { class: "icon-btn sm", type: "button", title: "Přečíst nahlas", "aria-label": "Přečíst nahlas", onclick: () => this.speak(m) }, icon("speaker-high")),
      h("button", { class: "icon-btn sm regen", type: "button", title: "Vygenerovat znovu", "aria-label": "Vygenerovat znovu", onclick: () => this.client.send("regenerate") }, icon("arrows-clockwise")),
      m.meta?.brain ? h("span", { class: "brain", title: "Odpověděl" }, m.meta.brain[0]) : null,
      h("span", { class: "meta" }, fmtTime(m.created)));
  }

  private ensureLive() {
    if (this.live) return this.live;
    const body = h("div", { class: "md" });
    const tools = h("div", { class: "tools" });
    const el = h("div", { class: "msg assistant live" }, miniBlob(true), h("div", { class: "a-main" }, tools, body));
    this.list.append(el);
    this.updateEmpty();
    this.live = { el, body, tools, text: "" };
    this.scrollBottom();
    return this.live;
  }

  private delta(text: string) {
    const l = this.ensureLive();
    l.text += text;
    if (!l.raf) {
      l.raf = requestAnimationFrame(() => {
        l.raf = undefined;
        l.body.innerHTML = renderMarkdown(l.text) + '<span class="caret"></span>';
        this.scrollBottom();
      });
    }
  }

  private toolStart(m: ServerMsg) {
    const l = this.ensureLive();
    const chip = this.toolChip(m.name, m.label || m.name, "run");
    this.liveTools.set(m.id, chip);
    l.tools.append(chip);
    this.scrollBottom();
  }

  private toolEnd(m: ServerMsg) {
    const chip = this.liveTools.get(m.id);
    if (!chip) return;
    const label = chip.querySelector(".tool-label")?.textContent || "";
    const fresh = this.toolChip(chip.dataset.name || "", label, m.ok ? "ok" : "fail", m.summary);
    chip.replaceWith(fresh);
    this.liveTools.set(m.id, fresh);
  }

  private done(m: ServerMsg) {
    const msg: Message = { id: m.id, role: "assistant", text: m.text, attachments: m.attachments || [], meta: { tools: m.tools }, created: Date.now() / 1000 };
    const el = this.messageEl(msg);
    if (this.live) {
      if (this.live.raf) cancelAnimationFrame(this.live.raf);
      this.live.el.replaceWith(el);
      this.live = null;
    } else {
      this.list.append(el);
    }
    this.liveTools.clear();
    this.updateEmpty();
    this.markLast();
    this.scrollBottom();
  }

  private confirmCard(m: ServerMsg) {
    const card = h("div", { class: "confirm", "data-confirm": m.id },
      icon("shield-warning", "ph-fill"),
      h("div", { class: "confirm-text" }, h("strong", {}, "Potvrdit akci?"), h("span", {}, String(m.description || "").replace(/^[^\p{L}\p{N}]+/u, ""))),
      h("div", { class: "confirm-btns" },
        h("button", { class: "btn danger", type: "button", onclick: () => answer(false) }, "Ne"),
        h("button", { class: "btn primary", type: "button", onclick: () => answer(true) }, "Ano, proveď")));
    const answer = (ok: boolean) => {
      this.client.send("confirm_response", { id: m.id, approved: ok });
      card.classList.add("resolved");
    };
    const l = this.ensureLive();
    l.tools.after(card);
    this.scrollBottom();
  }

  private scrollBottom(force = false) {
    if (force || this.stickBottom) requestAnimationFrame(() => (this.scroller.scrollTop = this.scroller.scrollHeight));
  }

  // ---------- composer ----------
  private autosize() {
    this.input.style.height = "auto";
    this.input.style.height = Math.min(this.input.scrollHeight, 220) + "px";
  }

  focus() {
    this.input.focus();
  }

  sendText(text: string) {
    this.client.send("user_text", { text, attachments: [] });
  }

  private submit() {
    if (this.state !== "idle" && !this.input.value.trim() && !this.pending.length) {
      this.client.send("stop");
      return;
    }
    if (this.pending.some((p) => !p.att && !p.error)) {
      toast("Počkej, ještě se nahrávají přílohy…");
      return;
    }
    const text = this.input.value.trim();
    const atts = this.pending.filter((p) => p.att).map((p) => p.att!.id);
    if (!text && !atts.length) return;
    this.client.send("user_text", { text, attachments: atts });
    this.input.value = "";
    this.autosize();
    this.pending = [];
    this.pendingBox.replaceChildren();
    this.stickBottom = true;
  }

  async addFile(file: File) {
    const bar = h("i", { class: "bar" });
    const el = h("div", { class: "pend" },
      file.type.startsWith("image/") ? h("img", { src: URL.createObjectURL(file), alt: "" }) : icon("file"),
      h("span", { class: "att-name" }, file.name), h("span", { class: "prog" }, bar),
      h("button", { class: "x", type: "button", "aria-label": "Odebrat", onclick: () => { this.pending = this.pending.filter((p) => p !== item); el.remove(); } }, icon("x")));
    const item: Pending = { file, progress: 0, el };
    this.pending.push(item);
    this.pendingBox.append(el);
    try {
      item.att = await this.client.upload(file, file.name, (p) => (bar.style.width = `${Math.round(p * 100)}%`));
      el.classList.add("ready");
    } catch (e: any) {
      item.error = e.message;
      el.classList.add("err");
      toast(e.message, "error");
    }
  }

  private setupDrop() {
    let depth = 0;
    this.el.addEventListener("dragenter", (e) => { if (e.dataTransfer?.types.includes("Files")) { depth++; this.el.classList.add("drop"); } });
    this.el.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; this.el.classList.remove("drop"); } });
    this.el.addEventListener("dragover", (e) => e.preventDefault());
    this.el.addEventListener("drop", (e) => {
      e.preventDefault();
      depth = 0;
      this.el.classList.remove("drop");
      [...(e.dataTransfer?.files || [])].forEach((f) => this.addFile(f));
    });
  }

  private async toggleMic() {
    if (this.recorder.active) {
      const blob = await this.recorder.stop();
      this.micBtn.classList.remove("rec");
      if (!blob || blob.size < 1500) return;
      try {
        const ext = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
        const att = await this.client.upload(blob, `hlasovka.${ext}`);
        this.client.send("voice_upload", { attachment_id: att.id });
      } catch (e: any) {
        toast(e.message, "error");
      }
      return;
    }
    try {
      await this.recorder.start();
      this.micBtn.classList.add("rec");
    } catch {
      toast("Nemám přístup k mikrofonu", "error");
    }
  }

  private speak(m: Message) {
    if (this.client.local) this.client.send("speak", { text: m.text });
    else this.client.send("tts_request", { text: m.text, message_id: m.id });
  }

  private play(url: string) {
    this.audio?.pause();
    this.audio = new Audio(url);
    this.audio.play().catch(() => toast("Přehrání se nepodařilo", "error"));
  }

  get conversationId() {
    return this.conversation;
  }
}

export function conversationList(client: JarvisClient, onPick?: () => void): HTMLElement {
  const list = h("nav", { class: "conv-list", "aria-label": "Konverzace" });
  let current = "";
  const render = (items: any[]) => {
    list.replaceChildren(...items.map((c) =>
      h("div", { class: `conv ${c.id === current ? "active" : ""}` },
        h("button", { class: "conv-open", type: "button", onclick: () => { client.send("switch_conversation", { id: c.id }); onPick?.(); } },
          h("span", { class: "conv-title" }, c.title || "Konverzace"), h("span", { class: "conv-time" }, fmtTime(c.updated))),
        h("button", { class: "icon-btn sm conv-del", type: "button", title: "Smazat", "aria-label": "Smazat konverzaci", onclick: () => { if (confirm("Smazat tuhle konverzaci?")) client.send("delete_conversation", { id: c.id }); } }, icon("trash")))));
    if (!items.length) list.append(h("p", { class: "help" }, "Zatím žádné konverzace."));
  };
  client.on("welcome", (m) => { current = m.conversation; render(m.conversations || []); });
  client.on("conversations", (m) => { current = m.current; render(m.items); });
  client.on("history", (m) => { if (!m.prepend && m.conversation !== current) { current = m.conversation; client.send("conversations_get"); } });
  client.on("assistant_done", () => client.send("conversations_get"));
  return list;
}
