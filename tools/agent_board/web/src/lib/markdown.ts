// Markdown for posts and knowledge: GitHub-flavoured (tables, task lists,
// strikethrough, autolinks) via marked, sanitized with DOMPurify, code
// highlighted with highlight.js, mermaid diagrams rendered lazily.
//
// After sanitizing, text is linkified for this repo: #123 -> issue/PR,
// engine/sim/fire.py:42 -> the file on GitHub, commit SHAs, @mentions, and
// [[12]] -> knowledge entry 12.

import DOMPurify from "dompurify";
import { Marked } from "marked";
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import diff from "highlight.js/lib/languages/diff";
import ini from "highlight.js/lib/languages/ini";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import makefile from "highlight.js/lib/languages/makefile";
import markdown from "highlight.js/lib/languages/markdown";
import python from "highlight.js/lib/languages/python";
import rust from "highlight.js/lib/languages/rust";
import shell from "highlight.js/lib/languages/shell";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";

const LANGS = { bash, css, diff, ini, javascript, json, makefile, markdown, python, rust, shell, sql, typescript, xml, yaml };
for (const [name, lang] of Object.entries(LANGS)) hljs.registerLanguage(name, lang);
const ALIASES: Record<string, string> = {
  sh: "bash", zsh: "bash", console: "shell", py: "python", ts: "typescript", tsx: "typescript", js: "javascript",
  jsx: "javascript", html: "xml", svg: "xml", toml: "ini", yml: "yaml", md: "markdown", rs: "rust", make: "makefile",
};

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

const marked = new Marked({ gfm: true, breaks: true });
marked.use({
  renderer: {
    code({ text, lang }) {
      const l = (lang || "").trim().split(/\s+/)[0].toLowerCase();
      if (l === "mermaid") return `<div class="mermaid"><pre><code>${esc(text)}</code></pre></div>`;
      const name = ALIASES[l] || l;
      const body = name && hljs.getLanguage(name) ? hljs.highlight(text, { language: name, ignoreIllegals: true }).value : esc(text);
      return `<div class="codeblock"><pre><code class="hljs${name ? " language-" + esc(name) : ""}">${body}</code></pre>${l ? `<span class="lang">${esc(l)}</span>` : ""}</div>`;
    },
  },
});

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    const href = node.getAttribute("href") || "";
    if (/^https?:/i.test(href)) {
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer");
    }
  }
  if (node.tagName === "INPUT") node.setAttribute("disabled", "");
});

// --- repo-aware linkify -------------------------------------------------------------------

let REPO = "jayson-clark/hack-ohio-26";
export function setRepo(r: string) {
  if (r && r !== REPO) {
    REPO = r;
    cache.clear();
  }
}

// Paths only count when they start at a top-level folder of the repo (or are a root file), so prose doesn't turn into links.
const ROOTS = "(?:engine|app|tools|assets|\\.claude|\\.github)";
const ROOT_FILES = "(?:PLAN|AGENTS|CLAUDE|README)\\.md|Makefile|\\.env\\.example";
// A path ends in a file with an extension or in "/" (a directory), so branch names like app/demo-mode stay text.
const PATH = `(?:${ROOTS}/(?:[\\w.@+-]+/)*(?:[\\w@+-][\\w.@+-]*\\.[A-Za-z0-9]+)?|${ROOT_FILES})(?::(\\d+)(?:-(\\d+))?)?`;
const PATH_RE = new RegExp(`^${PATH}$`);
const LINKIFY_RE = new RegExp(
  [
    `(?<path>(?<![\\w/.-])${PATH}(?![\\w/]))`,
    `(?<issue>(?<![\\w&/#])#(?<num>\\d{1,6})\\b)`,
    `(?<entry>\\[\\[(?<eid>\\d+)\\]\\])`,
    `(?<mention>(?<![\\w@.])@(?<who>[A-Za-z0-9][\\w-]*(?:/[a-z][\\w-]*)?))`,
    `(?<sha>(?<![\\w/#-])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\\d)[0-9a-f]{7,40}(?![\\w-]))`,
  ].join("|"),
  "g",
);

function pathHref(p: string) {
  const m = p.match(/^(.*?)(?::(\d+)(?:-(\d+))?)?$/)!;
  const [, file, a, b] = m;
  const line = a ? `#L${a}${b ? `-L${b}` : ""}` : "";
  const kind = file.endsWith("/") ? "tree" : "blob";
  return `https://github.com/${REPO}/${kind}/main/${file.replace(/\/$/, "")}${line}`;
}

function linkNode(text: string, href: string, cls: string) {
  const a = document.createElement("a");
  a.textContent = text;
  a.href = href;
  a.className = cls;
  if (href.startsWith("http")) {
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  }
  return a;
}

function linkifyText(node: Text) {
  const text = node.data;
  LINKIFY_RE.lastIndex = 0;
  if (!LINKIFY_RE.test(text)) return;
  LINKIFY_RE.lastIndex = 0;
  const frag = document.createDocumentFragment();
  let last = 0;
  for (const m of text.matchAll(LINKIFY_RE)) {
    const g = m.groups!;
    const i = m.index!;
    if (i > last) frag.append(text.slice(last, i));
    if (g.path) frag.append(linkNode(g.path, pathHref(g.path), "ref path"));
    else if (g.issue) frag.append(linkNode(g.issue, `https://github.com/${REPO}/issues/${g.num}`, "ref issue"));
    else if (g.entry) {
      const a = linkNode(`entry ${g.eid}`, `#/e/${g.eid}`, "ref entry");
      a.dataset.entry = g.eid;
      frag.append(a);
    }
    else if (g.mention) {
      const s = document.createElement("a");
      s.className = "mention";
      s.textContent = g.mention;
      s.href = `#/u/${encodeURIComponent(g.who.split("/")[0])}`;
      frag.append(s);
    } else if (g.sha) frag.append(linkNode(g.sha.slice(0, 7), `https://github.com/${REPO}/commit/${g.sha}`, "ref sha"));
    last = i + m[0].length;
  }
  if (last < text.length) frag.append(text.slice(last));
  node.replaceWith(frag);
}

function linkify(root: HTMLElement) {
  // `engine/protocol.py` in backticks is the usual way agents write a path; link those too.
  for (const code of root.querySelectorAll("code")) {
    if (code.closest("pre, a")) continue;
    const t = code.textContent || "";
    if (PATH_RE.test(t)) code.replaceWith(Object.assign(linkNode("", pathHref(t), "ref path code"), { innerHTML: code.outerHTML }));
  }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement?.closest("a, code, pre") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  const texts: Text[] = [];
  while (walker.nextNode()) texts.push(walker.currentNode as Text);
  texts.forEach(linkifyText);
}

const cache = new Map<string, string>();

export function renderMarkdown(src: string): string {
  const hit = cache.get(src);
  if (hit !== undefined) return hit;
  const raw = marked.parse(src, { async: false }) as string;
  const clean = DOMPurify.sanitize(raw, { ADD_ATTR: ["target"], FORBID_TAGS: ["style", "form"], FORBID_ATTR: ["style"] });
  const div = document.createElement("div");
  div.innerHTML = clean;
  linkify(div);
  const html = div.innerHTML;
  if (cache.size > 800) cache.delete(cache.keys().next().value!);
  cache.set(src, html);
  return html;
}

// --- mermaid, loaded from a CDN only when a post has a diagram ---------------------------------

type Mermaid = { initialize: (o: object) => void; render: (id: string, src: string) => Promise<{ svg: string }> };
let mermaidP: Promise<Mermaid | null> | null = null;
let mermaidN = 0;

const MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs";

function loadMermaid() {
  mermaidP ||= import(/* @vite-ignore */ MERMAID_URL)
    .then((m) => {
      const mm = m.default as Mermaid;
      const dark = document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
      mm.initialize({ startOnLoad: false, theme: dark ? "dark" : "default", securityLevel: "strict", flowchart: { htmlLabels: false } });
      return mm;
    })
    .catch(() => null);
  return mermaidP;
}

let entryTitle: (id: number) => string | undefined = () => undefined;
export function setEntryTitles(f: typeof entryTitle) {
  entryTitle = f;
}

/** Fill in entry titles, render mermaid blocks and add copy buttons inside a rendered markdown element. */
export async function enhance(root: HTMLElement) {
  for (const a of root.querySelectorAll<HTMLAnchorElement>("a.ref.entry[data-entry]")) {
    const t = entryTitle(Number(a.dataset.entry));
    if (t) {
      a.textContent = `📄 ${t}`;
      a.title = `Knowledge entry ${a.dataset.entry}`;
    }
  }
  for (const block of root.querySelectorAll<HTMLElement>(".codeblock:not([data-copy])")) {
    block.dataset.copy = "1";
    const b = document.createElement("button");
    b.className = "copy";
    b.type = "button";
    b.textContent = "Copy";
    b.onclick = (e) => {
      e.stopPropagation();
      navigator.clipboard?.writeText(block.querySelector("code")?.textContent || "");
      b.textContent = "Copied";
      setTimeout(() => (b.textContent = "Copy"), 1200);
    };
    block.append(b);
  }
  const diagrams = root.querySelectorAll<HTMLElement>(".mermaid:not([data-done])");
  if (!diagrams.length) return;
  const mm = await loadMermaid();
  if (!mm) return;
  for (const d of diagrams) {
    d.dataset.done = "1";
    try {
      const { svg } = await mm.render(`mmd${++mermaidN}`, d.querySelector("code")?.textContent || "");
      d.innerHTML = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true }, ADD_TAGS: ["foreignObject"] });
    } catch (e) {
      console.warn("mermaid:", String(e));
      d.classList.add("mermaid-error");
    }
  }
}
