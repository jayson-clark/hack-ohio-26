import type { EntryKind } from "./types";

// localStorage under "board:", JSON-encoded. Same keys as the old single-file UI, so names and tokens carry over.
export const store = {
  get<T>(k: string, d: T): T {
    try {
      const v = localStorage.getItem("board:" + k);
      return v == null ? d : (JSON.parse(v) as T);
    } catch {
      return d;
    }
  },
  set(k: string, v: unknown) {
    try {
      localStorage.setItem("board:" + k, JSON.stringify(v));
    } catch {
      /* private mode */
    }
  },
};

let skew = 0;
export function setSkew(s: number) {
  skew = s;
}
export const now = () => Date.now() / 1000 + skew;

export function ago(t: number | null | undefined) {
  if (!t) return "never";
  const s = Math.max(0, now() - t);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function duration(s: number) {
  if (s < 60) return `${Math.max(0, Math.round(s))}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
  return `${Math.round(s / 86400)}d`;
}

export const clock = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
export const fullTime = (t: number) => new Date(t * 1000).toLocaleString();

export function dayLabel(t: number) {
  const d = new Date(t * 1000);
  const today = new Date();
  const y = new Date();
  y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
}

export function expiresIn(expires: number | null) {
  if (!expires) return "";
  const h = (expires - now()) / 3600;
  return h < 1 ? `${Math.max(1, Math.round(h * 60))}m left` : `${Math.round(h)}h left`;
}

function hue(s: string) {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h % 360;
}
export const userColor = (u: string) => `hsl(${hue(u)} 62% 52%)`;
export const agentColor = (a: string) => `hsl(${(hue(a) + 140) % 360} 70% 64%)`;
export function initials(u: string) {
  const p = u.split(/[-_. ]+/).filter(Boolean);
  return ((p[0]?.[0] || "?") + (p[1]?.[0] || "")).toUpperCase();
}

export const KINDS: Record<EntryKind, { label: string; color: string; hint: string }> = {
  finding: { label: "Finding", color: "var(--finding)", hint: "Something learned about the code, data or hardware." },
  workflow: { label: "Workflow", color: "var(--workflow)", hint: "Steps that worked; the start of a skill." },
  decision: { label: "Decision", color: "var(--decision)", hint: "A choice made and why." },
  gotcha: { label: "Gotcha", color: "var(--gotcha)", hint: "A trap someone will hit again." },
};

/** Plain text preview of markdown. */
export function plain(src: string, n = 140) {
  const t = src
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/[#*`>|]/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
  return t.length > n ? t.slice(0, n) + "…" : t;
}

export function cls(...xs: (string | number | false | null | undefined)[]) {
  return xs.filter(Boolean).join(" ");
}

/** Split a server snippet (\x02match\x03) into parts for highlighting. */
export function highlightParts(s: string): { text: string; hit: boolean }[] {
  const out: { text: string; hit: boolean }[] = [];
  const re = /\x02([\s\S]*?)\x03/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push({ text: s.slice(last, m.index), hit: false });
    out.push({ text: m[1], hit: true });
    last = m.index + m[0].length;
  }
  if (last < s.length) out.push({ text: s.slice(last), hit: false });
  return out;
}

export function debounce<A extends unknown[]>(fn: (...a: A) => void, ms: number) {
  let h = 0;
  return (...a: A) => {
    clearTimeout(h);
    h = window.setTimeout(() => fn(...a), ms);
  };
}

/** Line diff (LCS) for entry history. */
export function lineDiff(a: string, b: string): { op: " " | "+" | "-"; line: string }[] {
  const x = a.split("\n");
  const y = b.split("\n");
  const n = x.length;
  const m = y.length;
  if (n * m > 400_000) return [...x.map((line) => ({ op: "-" as const, line })), ...y.map((line) => ({ op: "+" as const, line }))];
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { op: " " | "+" | "-"; line: string }[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) {
      out.push({ op: " ", line: x[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ op: "-", line: x[i++] });
    else out.push({ op: "+", line: y[j++] });
  }
  while (i < n) out.push({ op: "-", line: x[i++] });
  while (j < m) out.push({ op: "+", line: y[j++] });
  return out;
}

/** Whether a claim path and a file path could overlap (mirror of boardsrv.model.paths_overlap, roughly). */
export function pathsOverlap(a: string, b: string) {
  const norm = (p: string) => p.replace(/^\.\//, "").replace(/^\/+/, "");
  a = norm(a);
  b = norm(b);
  if (!a || !b) return false;
  if (a.replace(/\/$/, "") === b.replace(/\/$/, "")) return true;
  const glob = (p: string) => /[*?[]/.test(p);
  const root = (p: string) => {
    const i = p.search(/[*?[]/);
    const lit = i < 0 ? p : p.slice(0, i);
    return lit.includes("/") ? lit.slice(0, lit.lastIndexOf("/") + 1) : "";
  };
  if (glob(a) || glob(b)) {
    const ra = glob(a) ? root(a) : a;
    const rb = glob(b) ? root(b) : b;
    return ra.startsWith(rb) || rb.startsWith(ra);
  }
  return b.startsWith(a.replace(/\/$/, "") + "/") || a.startsWith(b.replace(/\/$/, "") + "/");
}
