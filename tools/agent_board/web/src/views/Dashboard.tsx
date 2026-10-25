import { useEffect, useMemo, useState } from "react";
import { AgentCard, Timeline } from "../components/Agents";
import { Ago, Avatar, Byline, Empty, Icon, Markdown, SectionTitle, Waiting } from "../components/ui";
import { go, hrefs } from "../lib/route";
import { api, fail, useBoard } from "../lib/store";
import type { Digest, Message } from "../lib/types";
import { ago, cls, fullTime, now, plain, store } from "../lib/util";
import { EntryCard } from "./Knowledge";

function Stat({ label, value, color, href, sub }: { label: string; value: React.ReactNode; color?: string; href?: string; sub?: string }) {
  const body = (
    <>
      <div className="label">
        {color && <span className="dot" style={{ background: color }} />}
        {label}
      </div>
      <div className="value">
        {value}
        {sub && <span style={{ color: "var(--muted)", fontSize: 15, fontWeight: 500 }}> {sub}</span>}
      </div>
    </>
  );
  return href ? (
    <a className="stat" href={href} style={{ color: "inherit", textDecoration: "none" }}>
      {body}
    </a>
  ) : (
    <div className="stat">{body}</div>
  );
}

export function QuestionRow({ m }: { m: Message }) {
  return (
    <div className="item link" onClick={() => go(hrefs.thread(m.channel, m.id))}>
      <Avatar user={m.author_user} />
      <div className="main-col">
        <div className="sub">
          <Byline user={m.author_user} agent={m.author_agent} />
          {m.to_target && <span className="to" style={{ color: "var(--accent-text)" }}>→ @{m.to_target}</span>}
          <span>in #{m.channel}</span>
        </div>
        <Markdown src={m.body.length > 600 ? m.body.slice(0, 600) + "…" : m.body} />
      </div>
      <div className="side-col">
        <span title={`asked ${fullTime(m.created_at)}`}>
          {m.resolved ? "took " : "waiting "}
          <Waiting since={m.created_at} until={m.resolved_at} />
        </span>
        <span className={cls("pill", m.reply_count ? "" : "q")}>{m.reply_count ? `${m.reply_count} ${m.reply_count === 1 ? "reply" : "replies"}` : "no replies"}</span>
      </div>
    </div>
  );
}

export function Overview() {
  const s = useBoard();
  const online = s.agents.filter((a) => a.online);
  const open = useMemo(() => [...s.openQuestions].sort((a, b) => a.created_at - b.created_at), [s.openQuestions]);
  const merged = (s.github?.merged || []).filter((p) => (p.merged_ts || 0) > now() - 86400).slice(0, 5);
  const stale = s.entries.filter((e) => e.superseded_by || e.votes.stale > e.votes.true).length;
  return (
    <div className="pad">
      <div className="stats">
        <Stat label="Agents online" value={online.length} sub={`/ ${s.agents.length}`} color="var(--online)" href="#/activity" />
        <Stat label="Open questions" value={s.openQuestions.length} color="var(--question)" href="#/questions" />
        <Stat label="Knowledge entries" value={s.entries.length} sub={stale ? `${stale} stale` : undefined} color="var(--finding)" href="#/knowledge" />
        <Stat label="Claimed paths" value={s.claims.length} color="var(--decision)" href="#/claims" />
      </div>
      {online.length > 0 && (
        <>
          <SectionTitle title="Working now">
            <a href="#/activity">Activity →</a>
          </SectionTitle>
          <div className="agent-cards">
            {online.map((a) => (
              <AgentCard key={a.id} a={a} />
            ))}
          </div>
        </>
      )}
      <SectionTitle title="Open questions">{open.length > 0 && <a href="#/questions">All questions →</a>}</SectionTitle>
      {open.length ? (
        <div className="list">
          {open.slice(0, 6).map((m) => (
            <QuestionRow key={m.id} m={m} />
          ))}
        </div>
      ) : (
        <Empty title="No open questions">
          Agents ask with <code>board.py ask "…"</code>
        </Empty>
      )}
      {merged.length > 0 && (
        <>
          <SectionTitle title="Merged today">
            <a href="#/github">PRs and issues →</a>
          </SectionTitle>
          <div className="list">
            {merged.map((p) => (
              <a key={p.number} className="item link" href={p.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none" }}>
                <Icon name="pr" />
                <div className="main-col">
                  <div className="title">
                    #{p.number} {p.title}
                  </div>
                  <div className="sub">
                    {p.author} · <span className="mono">{p.branch}</span>
                  </div>
                </div>
                <div className="side-col">{p.merged_ts && ago(p.merged_ts)}</div>
              </a>
            ))}
          </div>
        </>
      )}
      <SectionTitle title="Latest knowledge">
        <a href="#/knowledge">View all →</a>
      </SectionTitle>
      {s.entries.length ? (
        <div className="grid">
          {s.entries.slice(0, 6).map((e) => (
            <EntryCard key={e.id} e={e} flash={s.flash.has("e" + e.id)} />
          ))}
        </div>
      ) : (
        <Empty title="Nothing saved yet">
          Agents add findings with <code>board.py add finding "…"</code>
        </Empty>
      )}
    </div>
  );
}

const RANGES: [string, number | "visit"][] = [
  ["Since my last visit", "visit"],
  ["Last hour", 3600],
  ["Last 8 hours", 8 * 3600],
  ["Last day", 86400],
  ["Last week", 7 * 86400],
];

/**
 * When "since you last looked" starts: the last time this browser had the board open before this session
 * (kept in sessionStorage, so reloads don't reset it). Reading the digest counts as catching up.
 */
export function lastVisit() {
  try {
    const v = sessionStorage.getItem("board:since");
    if (v) return Number(v);
    const prev = store.get<number>("lastVisit", 0) || now() - 8 * 3600;
    sessionStorage.setItem("board:since", String(prev));
    return prev;
  } catch {
    return store.get<number>("lastVisit", 0) || now() - 8 * 3600;
  }
}
export function caughtUp() {
  try {
    sessionStorage.setItem("board:since", String(now()));
  } catch {
    /* ignore */
  }
}
export function trackVisits() {
  lastVisit();
  const save = () => store.set("lastVisit", now());
  document.addEventListener("visibilitychange", () => document.hidden && save());
  window.addEventListener("pagehide", save);
}

export function DigestView() {
  const [range, setRange] = useState<number | "visit">("visit");
  const [d, setD] = useState<Digest | null>(null);
  const tick = useBoard((s) => s.feed.length);
  const [since] = useState(lastVisit);
  useEffect(() => {
    const t = range === "visit" ? since : now() - range;
    api<Digest>("GET", `/api/digest?since=${t}`).then(setD, fail);
  }, [range, since, tick]);
  useEffect(() => () => caughtUp(), []);

  return (
    <div className="pad">
      <div className="digest-range">
        {RANGES.map(([label, r]) => (
          <button key={label} className={cls("seg", range === r && "on")} onClick={() => setRange(r)}>
            {label}
          </button>
        ))}
      </div>
      {!d ? (
        <div className="muted">Loading…</div>
      ) : (
        <>
          <div className="statline">
            <span><b>{d.merged.length}</b>merged PRs</span>
            <span><b>{d.entries_new.length}</b>new entries</span>
            <span><b>{d.entries_updated.length}</b>updated</span>
            <span><b>{d.questions_asked.length}</b>questions asked</span>
            <span><b>{d.questions_resolved.length}</b>resolved</span>
            <span><b>{d.channels.reduce((n, c) => n + c.n, 0)}</b>messages</span>
            <span className="muted small" style={{ alignSelf: "center" }}>since {ago(d.since)} ({fullTime(d.since)})</span>
          </div>
          <div className="cols">
            <div>
              {d.merged.length > 0 && (
                <>
                  <h4 className="subtle-head">Merged</h4>
                  <div className="list" style={{ marginBottom: 16 }}>
                    {d.merged.map((p) => (
                      <a key={p.number} className="item link" href={p.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none" }}>
                        <Icon name="pr" />
                        <div className="main-col">
                          <div className="title">#{p.number} {p.title}</div>
                          <div className="sub">{p.author}</div>
                        </div>
                      </a>
                    ))}
                  </div>
                </>
              )}
              <h4 className="subtle-head">Knowledge</h4>
              <div className="list" style={{ marginBottom: 16 }}>
                {[...d.entries_new.map((e) => ({ e, label: "new" })), ...d.entries_updated.map((e) => ({ e, label: "updated" }))].map(({ e, label }) => (
                  <a key={e.id} className="item link" href={hrefs.entry(e.id)} style={{ color: "inherit", textDecoration: "none" }}>
                    <span className={cls("pill", label === "new" ? "ok" : "")}>{label}</span>
                    <div className="main-col">
                      <div className="title">{e.title}</div>
                      <div className="sub">
                        {e.kind} · {e.author_agent || e.author_user} · {ago(label === "new" ? e.created_at : e.updated_at)}
                      </div>
                    </div>
                  </a>
                ))}
                {!d.entries_new.length && !d.entries_updated.length && <div className="empty-row">No knowledge changes</div>}
              </div>
              <h4 className="subtle-head">Channels</h4>
              <div className="list">
                {d.channels.map((c) => (
                  <a key={c.channel} className="item link" href={hrefs.channel(c.channel)} style={{ color: "inherit", textDecoration: "none" }}>
                    <span className="muted">#</span>
                    <div className="main-col">
                      <div className="title">{c.channel}</div>
                      <div className="sub">
                        {c.n} messages{c.questions ? `, ${c.questions} questions` : ""} · last {ago(c.last)}
                      </div>
                    </div>
                  </a>
                ))}
                {!d.channels.length && <div className="empty-row">Quiet</div>}
              </div>
            </div>
            <div>
              <h4 className="subtle-head">Questions</h4>
              <div className="list" style={{ marginBottom: 16 }}>
                {d.questions_asked.map((m) => (
                  <a key={m.id} className="item link" href={hrefs.thread(m.channel, m.id)} style={{ color: "inherit", textDecoration: "none" }}>
                    <span className={cls("pill", m.resolved ? "ok" : "q")}>{m.resolved ? "resolved" : "open"}</span>
                    <div className="main-col">
                      <div className="title">{plain(m.body, 120)}</div>
                      <div className="sub">
                        {m.author_agent || m.author_user} in #{m.channel} · <Ago t={m.created_at} />
                      </div>
                    </div>
                  </a>
                ))}
                {!d.questions_asked.length && <div className="empty-row">No new questions</div>}
              </div>
              <h4 className="subtle-head">Agents</h4>
              <div className="panel" style={{ marginTop: 0 }}>
                <Timeline items={d.activity.slice(0, 40)} />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
