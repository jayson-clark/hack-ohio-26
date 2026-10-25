import { useMemo, useState } from "react";
import { AgentCard, ClaimRow, PrLink, Timeline, overlaps } from "../components/Agents";
import { MessageView } from "../components/Message";
import { Avatar, Empty, Icon, SectionTitle } from "../components/ui";
import { hrefs } from "../lib/route";
import { api, fail, me, mentionsMe, toast, useBoard } from "../lib/store";
import type { Claim } from "../lib/types";
import { ago, cls, pathsOverlap } from "../lib/util";
import { QuestionRow } from "./Dashboard";
import { EntryCard } from "./Knowledge";

export function QuestionsView() {
  const s = useBoard();
  const [filter, setFilter] = useState<"all" | "mine" | "unanswered">("all");
  const user = me();
  const open = useMemo(
    () =>
      [...s.openQuestions]
        .filter((m) => filter === "all" || (filter === "mine" ? mentionsMe(m, user) : !m.reply_count))
        .sort((a, b) => a.created_at - b.created_at),
    [s.openQuestions, filter, user],
  );
  const resolved = useMemo(
    () => s.recent.filter((m) => m.kind === "question" && m.resolved && !m.parent_id).sort((a, b) => (b.resolved_at || 0) - (a.resolved_at || 0)).slice(0, 10),
    [s.recent],
  );
  return (
    <div className="pad">
      <div className="filters">
        {(["all", "unanswered", "mine"] as const).map((f) => (
          <button key={f} className={cls("seg", filter === f && "on")} onClick={() => setFilter(f)}>
            {f === "all" ? "All open" : f === "unanswered" ? "No replies yet" : "For me"}
          </button>
        ))}
        <span className="grow" />
        <span className="small muted">Oldest first. Amber after 30 min, red after 2 h.</span>
      </div>
      {open.length ? (
        <div className="list">
          {open.map((m) => (
            <QuestionRow key={m.id} m={m} />
          ))}
        </div>
      ) : (
        <Empty title={filter === "all" ? "No open questions" : "Nothing here"}>Agents ask with <code>board.py ask "…" --to person</code></Empty>
      )}
      {resolved.length > 0 && (
        <>
          <SectionTitle title="Recently resolved" />
          <div className="list">
            {resolved.map((m) => (
              <QuestionRow key={m.id} m={m} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export function ClaimsView() {
  const claims = useBoard((s) => s.claims);
  const [paths, setPaths] = useState("");
  const [note, setNote] = useState("");
  const user = me();
  const groups = useMemo(() => {
    const g = new Map<string, Claim[]>();
    for (const c of [...claims].sort((a, b) => a.path.localeCompare(b.path))) {
      if (!g.has(c.agent_id)) g.set(c.agent_id, []);
      g.get(c.agent_id)!.push(c);
    }
    return [...g.entries()];
  }, [claims]);
  const conflictCount = claims.filter((c) => overlaps(claims, c, pathsOverlap).length).length;
  const claim = async () => {
    const list = paths.split(/[\s,]+/).filter(Boolean);
    if (!list.length) return;
    try {
      const r = await api<{ conflicts: Claim[] }>("POST", "/api/claims", { paths: list, note });
      setPaths("");
      setNote("");
      toast(r.conflicts.length ? `Claimed, but it overlaps ${r.conflicts.map((c) => c.agent_id).join(", ")}` : "Claimed");
    } catch (e) {
      fail(e);
    }
  };
  return (
    <div className="pad">
      <p className="small muted" style={{ marginTop: 0 }}>
        Agents claim the files they're about to edit (<code>board.py claim engine/protocol.py</code>, or automatically with the edit hook) and get warned when a claim overlaps someone else's. Claims lapse after
        two hours unless renewed.
      </p>
      <div className="panel" style={{ marginTop: 0, marginBottom: 18 }}>
        <h4>
          <Icon name="lock" size={13} /> Claim paths as {user || "yourself"}
        </h4>
        <div className="linkform" style={{ marginTop: 0 }}>
          <input className="input grow mono" value={paths} onChange={(e) => setPaths(e.target.value)} placeholder="engine/protocol.py app/src/console/ app/**/*.css" onKeyDown={(e) => e.key === "Enter" && claim()} />
          <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" onKeyDown={(e) => e.key === "Enter" && claim()} />
          <button className="btn sm primary" onClick={claim}>
            Claim
          </button>
          {claims.some((c) => c.agent_id === user) && (
            <button className="btn sm" onClick={() => api("POST", "/api/claims/release", {}).then(() => toast("Released your claims"), fail)}>
              Release mine
            </button>
          )}
        </div>
      </div>
      {conflictCount > 0 && <div className="banner warn" style={{ marginBottom: 14 }}>{conflictCount} claims overlap another agent's. Whoever claimed second should check in with the first.</div>}
      {groups.length ? (
        <div className="cols">
          {groups.map(([agent, list]) => (
            <div key={agent}>
              <h4 className="subtle-head">
                <a href={hrefs.user(agent.split("/")[0])} style={{ color: "inherit" }}>
                  {agent}
                </a>{" "}
                · {list.length}
              </h4>
              <div className="list">
                {list.map((c) => (
                  <ClaimRow key={c.id} c={c} conflicts={overlaps(claims, c, pathsOverlap)} />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <Empty title="Nobody has claimed anything">Agents claim with <code>board.py claim &lt;paths&gt;</code></Empty>
      )}
    </div>
  );
}

export function GitHubView() {
  const gh = useBoard((s) => s.github);
  const agents = useBoard((s) => s.agents);
  const repo = useBoard((s) => s.repo);
  if (!gh || (!gh.issues.length && !gh.pulls.length && !gh.merged.length))
    return (
      <div className="pad">
        <Empty title="No GitHub data yet">
          Any agent's <code>board.py brief</code> pushes issues and PRs from <code>gh</code> (or run <code>board.py gh-sync</code>). A board with <code>GITHUB_TOKEN</code> set polls by itself.
        </Empty>
      </div>
    );
  const agentFor = (branch: string) => agents.filter((a) => a.branch === branch);
  return (
    <div className="pad">
      <p className="small muted" style={{ marginTop: 0 }}>
        {gh.repo || repo} · updated {ago(gh.updated_at)} {gh.source ? `by ${gh.source.replace(/^cli:/, "")}` : ""}
      </p>
      <div className="cols">
        <div>
          <h4 className="subtle-head">Open pull requests · {gh.pulls.length}</h4>
          <div className="list" style={{ marginBottom: 16 }}>
            {gh.pulls.map((p) => {
              const on = agentFor(p.branch);
              return (
                <a key={p.number} className="item link" href={p.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none" }}>
                  <Icon name="pr" />
                  <div className="main-col">
                    <div className="title">
                      #{p.number} {p.title}
                    </div>
                    <div className="sub">
                      <span>{p.author}</span>
                      <span className="mono">{p.branch}</span>
                      {p.draft && <span className="pill">draft</span>}
                      {p.review === "APPROVED" && <span className="pill ok">approved</span>}
                      {p.review === "CHANGES_REQUESTED" && <span className="pill danger">changes requested</span>}
                    </div>
                    {on.length > 0 && (
                      <div className="sub">
                        {on.map((a) => (
                          <span key={a.id}>
                            <span className={cls("presence", a.online && "on")} style={{ display: "inline-block", marginRight: 5 }} />
                            {a.id}: {a.status || "no status"}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="side-col">{p.updated_at && ago(p.updated_at)}</div>
                </a>
              );
            })}
            {!gh.pulls.length && <div className="empty-row">No open PRs</div>}
          </div>
          <h4 className="subtle-head">Recently merged</h4>
          <div className="list">
            {gh.merged.slice(0, 15).map((p) => (
              <a key={p.number} className="item link" href={p.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none" }}>
                <span className="pill ok">merged</span>
                <div className="main-col">
                  <div className="title">
                    #{p.number} {p.title}
                  </div>
                  <div className="sub">{p.author}</div>
                </div>
                <div className="side-col">{p.merged_ts && ago(p.merged_ts)}</div>
              </a>
            ))}
          </div>
        </div>
        <div>
          <h4 className="subtle-head">Open issues · {gh.issues.length}</h4>
          <div className="list">
            {gh.issues.map((i) => (
              <a key={i.number} className="item link" href={i.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none" }}>
                <span className="muted mono small">#{i.number}</span>
                <div className="main-col">
                  <div className="title">{i.title}</div>
                  <div className="sub">
                    {i.assignees.length ? i.assignees.map((a) => <span key={a}>@{a}</span>) : <span className="pill warn">unassigned</span>}
                    {i.labels.map((l) => (
                      <span key={l} className="tag">
                        {l}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="side-col">{i.updated_at && ago(i.updated_at)}</div>
              </a>
            ))}
            {!gh.issues.length && <div className="empty-row">No open issues</div>}
          </div>
        </div>
      </div>
    </div>
  );
}

export function ActivityView() {
  const activity = useBoard((s) => s.activity);
  const agents = useBoard((s) => s.agents);
  const [who, setWho] = useState("");
  const [kind, setKind] = useState("");
  const items = activity.filter((a) => (!who || a.agent_id === who) && (!kind || a.kind === kind));
  return (
    <div className="pad">
      <div className="filters">
        <select className="input" value={who} onChange={(e) => setWho(e.target.value)} aria-label="Agent">
          <option value="">Everyone</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.id}
            </option>
          ))}
        </select>
        <select className="input" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind">
          <option value="">All activity</option>
          {["joined", "status", "branch", "pr", "claim", "release", "entry", "question"].map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </div>
      <div className="panel" style={{ marginTop: 0 }}>
        <Timeline items={items} />
      </div>
    </div>
  );
}

export function PersonView({ user }: { user: string }) {
  const s = useBoard();
  const agents = s.agents.filter((a) => a.user === user);
  const entries = s.entries.filter((e) => e.author_user === user);
  const msgs = s.recent.filter((m) => m.author_user === user).slice(0, 15);
  const activity = s.activity.filter((a) => a.agent_id === user || a.agent_id.startsWith(user + "/")).slice(0, 60);
  const claims = s.claims.filter((c) => c.agent_id === user || c.agent_id.startsWith(user + "/"));
  const issues = s.github?.issues.filter((i) => i.assignees.includes(user)) || [];
  const prs = s.github?.pulls.filter((p) => p.author === user) || [];
  return (
    <div className="pad">
      <div className="profile">
        <Avatar user={user} size="lg" />
        <div>
          <h3>{user}</h3>
          <div className="ttl">
            {agents.length} agent{agents.length === 1 ? "" : "s"} · {entries.length} knowledge entr{entries.length === 1 ? "y" : "ies"}
            {claims.length > 0 && ` · ${claims.length} claimed paths`}
          </div>
        </div>
      </div>
      <SectionTitle title="Agents" />
      {agents.length ? (
        <div className="agent-list">
          {agents.map((a) => (
            <AgentCard key={a.id} a={a} />
          ))}
        </div>
      ) : (
        <Empty title={`No agents have checked in for ${user}`} />
      )}
      {(prs.length > 0 || issues.length > 0) && (
        <>
          <SectionTitle title="On GitHub" />
          <div className="list">
            {prs.map((p) => (
              <a key={"p" + p.number} className="item link" href={p.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none" }}>
                <Icon name="pr" />
                <div className="main-col">
                  <div className="title">
                    <PrLink number={p.number} repo={s.repo} /> {p.title}
                  </div>
                  <div className="sub mono">{p.branch}</div>
                </div>
              </a>
            ))}
            {issues.map((i) => (
              <a key={"i" + i.number} className="item link" href={i.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none" }}>
                <span className="muted mono small">#{i.number}</span>
                <div className="main-col">
                  <div className="title">{i.title}</div>
                  <div className="sub">assigned issue</div>
                </div>
              </a>
            ))}
          </div>
        </>
      )}
      <div className="cols" style={{ marginTop: 10 }}>
        <div>
          <SectionTitle title="Timeline" />
          <div className="panel" style={{ marginTop: 0 }}>
            <Timeline items={activity} />
          </div>
        </div>
        <div>
          <SectionTitle title="Recent messages" />
          {msgs.length ? (
            <div className="list" style={{ padding: 4 }}>
              {msgs.map((m) => (
                <MessageView key={m.id} m={m} showChannel />
              ))}
            </div>
          ) : (
            <Empty title="Nothing yet" />
          )}
        </div>
      </div>
      <SectionTitle title="Knowledge" />
      {entries.length ? (
        <div className="entry-list">
          {entries.map((e) => (
            <EntryCard key={e.id} e={e} />
          ))}
        </div>
      ) : (
        <Empty title="Nothing yet" />
      )}
    </div>
  );
}
