import DOMPurify from "dompurify";
import { copyText } from "./dom";
import { Marked } from "marked";

const esc = (t: string) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
let hljs: any = null;
let loading: Promise<void> | null = null;
function loadHljs() {
  loading ??= import("highlight.js/lib/common").then((m) => {
    hljs = m.default;
    document.querySelectorAll<HTMLElement>("code[data-hl]").forEach((el) => {
      const lang = el.dataset.hl || "";
      const text = el.textContent || "";
      el.innerHTML = lang && hljs.getLanguage(lang) ? hljs.highlight(text, { language: lang }).value : hljs.highlightAuto(text).value;
      el.removeAttribute("data-hl");
    });
  }).catch(() => { loading = null; });
}

const md = new Marked({ gfm: true, breaks: true });
md.use({
  renderer: {
    code({ text, lang }) {
      // 3.12 highlight.js (~ a third of the chat code) loads only when the first code block shows up; until then the
      // block is plain text and gets its colours a moment later – every window and the notch start faster
      const want = (lang || "").replace(/[^\w+#.-]/g, "").slice(0, 24);
      const language = hljs ? (want && hljs.getLanguage(want) ? want : undefined) : want || undefined;
      const html = hljs ? (language ? hljs.highlight(text, { language }).value : hljs.highlightAuto(text).value) : esc(text);
      if (!hljs) loadHljs();
      const lines = text.split("\n").length;
      return `<div class="code"><div class="code-head"><span class="code-lang"><i class="ph ph-code"></i>${language || "kód"}<em>${lines} ${lines === 1 ? "řádek" : lines < 5 ? "řádky" : "řádků"}</em></span><button class="code-copy" type="button"><i class="ph ph-copy"></i> Kopírovat</button></div><pre><code class="hljs"${hljs ? "" : ` data-hl="${language || ""}"`}>${html}</code></pre></div>`;
    },
    link({ href, text }) {
      return `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`;
    },
  },
});

export function renderMarkdown(src: string): string {
  const html = md.parse(src || "", { async: false }) as string;
  // tables scroll sideways inside a rounded frame instead of stretching the message (3.12)
  return DOMPurify.sanitize(html, { ADD_ATTR: ["target"] }).replace(/<table>/g, '<div class="tbl"><table>').replace(/<\/table>/g, "</table></div>");
}

export function wireCodeCopy(root: HTMLElement) {
  root.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest(".code-copy") as HTMLButtonElement | null;
    if (!btn) return;
    const code = btn.closest(".code")?.querySelector("code")?.textContent || "";
    copyText(code, "");
    btn.innerHTML = '<i class="ph ph-check"></i> Zkopírováno';
    setTimeout(() => (btn.innerHTML = '<i class="ph ph-copy"></i> Kopírovat'), 1500);
  });
}
