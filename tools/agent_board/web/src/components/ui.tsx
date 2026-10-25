import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { enhance, renderMarkdown } from "../lib/markdown";
import { hrefs } from "../lib/route";
import { useBoard } from "../lib/store";
import type { EntryKind } from "../lib/types";
import { KINDS, ago, cls, fullTime, highlightParts, initials, userColor } from "../lib/util";

const P = { fill: "none", stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round", strokeLinejoin: "round" } as const;
const ICONS: Record<string, ReactNode> = {
  grid: (<><rect x="2" y="2" width="5" height="5" rx="1.3" {...P} /><rect x="9" y="2" width="5" height="5" rx="1.3" {...P} /><rect x="2" y="9" width="5" height="5" rx="1.3" {...P} /><rect x="9" y="9" width="5" height="5" rx="1.3" {...P} /></>),
  doc: (<><path d="M3 2.5h7.5L13 5v8.5H3z" {...P} /><path d="M5.5 7.5h5M5.5 10h5" {...P} /></>),
  question: (<><circle cx="8" cy="8" r="6" {...P} /><path d="M6.3 6.3a1.8 1.8 0 1 1 2.4 1.7c-.5.2-.7.6-.7 1.1v.4" {...P} /><circle cx="8" cy="11.6" r=".5" fill="currentColor" /></>),
  lock: (<><rect x="3" y="7" width="10" height="7" rx="1.5" {...P} /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" {...P} /></>),
  pr: (<><circle cx="4.5" cy="3.5" r="1.5" {...P} /><circle cx="4.5" cy="12.5" r="1.5" {...P} /><circle cx="11.5" cy="12.5" r="1.5" {...P} /><path d="M4.5 5v6M11.5 11V6.5a2 2 0 0 0-2-2H7.5M9 3l-1.5 1.5L9 6" {...P} /></>),
  spark: (<path d="M8 1.8v3M8 11.2v3M1.8 8h3M11.2 8h3M3.6 3.6l2 2M10.4 10.4l2 2M3.6 12.4l2-2M10.4 5.6l2-2" {...P} />),
  pulse: (<path d="M1.5 8.5h3l1.5-4 3 8 1.5-4h4" {...P} />),
  tag: (<><path d="M2.5 2.5h5l6 6-5 5-6-6z" {...P} /><circle cx="5.3" cy="5.3" r=".9" fill="currentColor" /></>),
  search: (<><circle cx="7" cy="7" r="5" {...P} /><path d="m11 11 3.5 3.5" {...P} /></>),
  menu: <path d="M2 4h12M2 8h12M2 12h12" {...P} />,
  user: (<><circle cx="8" cy="5.5" r="2.8" {...P} /><path d="M2.8 14c.7-2.8 2.8-4.2 5.2-4.2s4.5 1.4 5.2 4.2" {...P} /></>),
  theme: (<><circle cx="8" cy="8" r="5.5" {...P} /><path d="M8 2.5a5.5 5.5 0 0 1 0 11z" fill="currentColor" /></>),
  bell: (<><path d="M4 11V7a4 4 0 0 1 8 0v4l1.2 1.5H2.8z" {...P} /><path d="M6.5 14a1.6 1.6 0 0 0 3 0" {...P} /></>),
  bellOff: (<><path d="M4 11V7a4 4 0 0 1 6.5-3.1M12 7v4l1.2 1.5H5" {...P} /><path d="M2 2l12 12" {...P} /></>),
  x: <path d="M4 4l8 8M12 4l-8 8" {...P} />,
  reply: <path d="M6.5 4 2.5 8l4 4M3 8h6.5a4 4 0 0 1 4 4v1" {...P} />,
  smile: (<><circle cx="8" cy="8" r="6" {...P} /><path d="M5.5 9.5a3 3 0 0 0 5 0" {...P} /><circle cx="6" cy="6.5" r=".6" fill="currentColor" /><circle cx="10" cy="6.5" r=".6" fill="currentColor" /></>),
  check: <path d="m3 8.5 3 3 7-7" {...P} />,
  link: (<><path d="M6.5 9.5a3 3 0 0 0 4.2 0l2-2a3 3 0 0 0-4.2-4.2l-.7.7" {...P} /><path d="M9.5 6.5a3 3 0 0 0-4.2 0l-2 2a3 3 0 0 0 4.2 4.2l.7-.7" {...P} /></>),
  history: (<><path d="M2.5 8a5.5 5.5 0 1 0 1.6-3.9L2.5 5.7" {...P} /><path d="M2.5 2.5v3.2h3.2M8 5v3.2l2 1.3" {...P} /></>),
  edit: <path d="M10.5 2.5l3 3L6 13H3v-3z" {...P} />,
  archive: (<><rect x="2" y="3" width="12" height="3" rx="1" {...P} /><path d="M3 6v7h10V6M6.5 9h3" {...P} /></>),
  plus: <path d="M8 3v10M3 8h10" {...P} />,
  hash: <path d="M5.5 2 4.5 14M11.5 2l-1 12M2.5 5.5h11M2 10.5h11" {...P} />,
  bot: (<><rect x="3" y="5" width="10" height="8" rx="2.2" {...P} /><path d="M8 2.5V5M6 9h.01M10 9h.01" {...P} strokeWidth={2} /></>),
  keyboard: (<><rect x="1.5" y="4" width="13" height="8" rx="1.5" {...P} /><path d="M4 7h.01M6.5 7h.01M9 7h.01M11.5 7h.01M5 9.5h6" {...P} /></>),
  copy: (<><rect x="5" y="5" width="8.5" height="8.5" rx="1.5" {...P} /><path d="M3 10.5V3.5A1 1 0 0 1 4 2.5h6.5" {...P} /></>),
  external: (<><path d="M9 2.5h4.5V7M13.5 2.5 7.5 8.5" {...P} /><path d="M11.5 9.5v3a1 1 0 0 1-1 1h-7a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3" {...P} /></>),
};

export function Icon({ name, size = 15 }: { name: keyof typeof ICONS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

export function Avatar({ user, size = "" }: { user: string; size?: "" | "sm" | "lg" }) {
  if (user === "github")
    return (
      <span className={cls("avatar", size)} style={{ background: "var(--surface-3)", color: "var(--text-2)" }} title="GitHub">
        <Icon name="pr" size={size === "sm" ? 11 : 14} />
      </span>
    );
  return (
    <span className={cls("avatar", size)} style={{ background: userColor(user) }} title={user}>
      {initials(user)}
    </span>
  );
}

/** An agent's name, quietly: who did it matters, but it shouldn't shout. */
export function AgentChip({ agent }: { agent: string }) {
  if (!agent) return null;
  return (
    <span className="agent-name" title="Agent">
      {agent}
    </span>
  );
}

export function Byline({ user, agent }: { user: string; agent: string }) {
  if (user === "github") return <span className="byline"><b>GitHub</b></span>;
  return (
    <span className="byline">
      <a href={hrefs.user(user)}>
        <b>{user}</b>
      </a>
      {agent && (
        <>
          <span className="slash">/</span>
          <AgentChip agent={agent} />
        </>
      )}
    </span>
  );
}

export function KindBadge({ kind }: { kind: EntryKind | string }) {
  const k = KINDS[kind as EntryKind];
  return (
    <span className="kind" style={{ ["--k" as string]: k?.color || "var(--muted)" }}>
      {k?.label || kind}
    </span>
  );
}

export function Ago({ t, prefix = "" }: { t: number; prefix?: string }) {
  return (
    <span title={fullTime(t)}>
      {prefix}
      {ago(t)}
    </span>
  );
}

export function Hl({ text }: { text: string }) {
  return (
    <>
      {highlightParts(text).map((p, i) => (p.hit ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>))}
    </>
  );
}

export function Markdown({ src, className = "" }: { src: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const html = renderMarkdown(src);
  const entries = useBoard((s) => s.entries.length); // [[id]] links pick up titles once entries load
  useLayoutEffect(() => {
    if (ref.current && ref.current.innerHTML !== html) ref.current.innerHTML = html;
  }, [html]);
  useEffect(() => {
    if (ref.current) enhance(ref.current);
  }, [html, entries]);
  return <div ref={ref} className={cls("md", className)} />;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <b>{title}</b>
      {children}
    </div>
  );
}

export function SectionTitle({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div className="section-title">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Presence({ on }: { on: boolean }) {
  return <span className={cls("presence", on && "on")} />;
}

/** How long a question has waited, coloured as it gets old. */
export function Waiting({ since, until }: { since: number; until?: number | null }) {
  const s = (until || Date.now() / 1000) - since;
  const c = until ? "fresh" : s > 7200 ? "red" : s > 1800 ? "amber" : "fresh";
  const label = s < 60 ? "<1m" : s < 3600 ? `${Math.round(s / 60)}m` : s < 86400 ? `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m` : `${Math.round(s / 86400)}d`;
  return <span className={cls("wait", c)}>{label}</span>;
}
