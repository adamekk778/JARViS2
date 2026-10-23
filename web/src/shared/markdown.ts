import DOMPurify from "dompurify";
import hljs from "highlight.js/lib/common";
import { Marked } from "marked";

const md = new Marked({ gfm: true, breaks: true });
md.use({
  renderer: {
    code({ text, lang }) {
      const language = lang && hljs.getLanguage(lang) ? lang : undefined;
      const html = language ? hljs.highlight(text, { language }).value : hljs.highlightAuto(text).value;
      return `<div class="code"><div class="code-head"><span>${language || "kód"}</span><button class="code-copy" type="button"><i class="ph ph-copy"></i> Kopírovat</button></div><pre><code class="hljs">${html}</code></pre></div>`;
    },
    link({ href, text }) {
      return `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`;
    },
  },
});

export function renderMarkdown(src: string): string {
  const html = md.parse(src || "", { async: false }) as string;
  return DOMPurify.sanitize(html, { ADD_ATTR: ["target"] });
}

export function wireCodeCopy(root: HTMLElement) {
  root.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest(".code-copy") as HTMLButtonElement | null;
    if (!btn) return;
    const code = btn.closest(".code")?.querySelector("code")?.textContent || "";
    navigator.clipboard?.writeText(code);
    btn.innerHTML = '<i class="ph ph-check"></i> Zkopírováno';
    setTimeout(() => (btn.innerHTML = '<i class="ph ph-copy"></i> Kopírovat'), 1500);
  });
}
