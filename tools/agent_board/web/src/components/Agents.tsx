import { hrefs } from "../lib/route";
import { useBoard, type State } from "../lib/store";
import type { Activity, Agent, Claim } from "../lib/types";
import { ago, agentColor, expiresIn, fullTime } from "../lib/util";
import { AgentChip, Avatar, Presence } from "./ui";

export function claimsOf(s: State, agentId: string) {
  return s.claims.filter((c) => c.agent_id === agentId);
}

/** Claims held by someone else that overlap this one. */
export function overlaps(all: Claim[], c: Claim, test: (a: string, b: string) => boolean) {
  return all.filter((o) => o.agent_id !== c.agent_id && test(o.path, c.path));
}

export function PrLink({ number, title, repo }: { number: number; title?: string; repo: string }) {
  return (
    <a href={`https://github.com/${repo}/pull/${number}`} target="_blank" rel="noopener noreferrer" title={title} onClick={(e) => e.stopPropagation()}>
      PR #{number}
    </a>
  );
}

export function AgentCard({ a }: { a: Agent }) {
  const claims = useBoard((s) => claimsOf(s, a.id));
  const repo = useBoard((s) => s.repo);
  const pr = useBoard((s) => s.github?.pulls.find((p) => p.branch === a.branch));
  const number = a.pr || pr?.number;
  return (
    <div className="agent-card">
      <div className="top">
        <Presence on={a.online} />
        <AgentChip agent={a.name} />
        <span className="ttl" style={{ marginLeft: "auto" }} title={fullTime(a.last_seen)}>
          {ago(a.last_seen)}
        </span>
      </div>
      <div className="status">{a.status || <span style={{ color: "var(--muted)" }}>No status</span>}</div>
      <div className="sub mono">
        <a href={hrefs.user(a.user)}>{a.user}</a> · {a.branch || "no branch"}
        {a.host ? " · " + a.host : ""}
      </div>
      {(number || claims.length > 0) && (
        <div className="sub">
          {number && <PrLink number={number} title={a.pr_title || pr?.title} repo={repo} />}
          {number && claims.length > 0 && " · "}
          {claims.length > 0 && (
            <a href="#/claims" title={claims.map((c) => c.path).join("\n")}>
              {claims.length} claimed {claims.length === 1 ? "path" : "paths"}: <span className="mono">{claims.slice(0, 2).map((c) => c.path).join(", ")}{claims.length > 2 ? "…" : ""}</span>
            </a>
          )}
        </div>
      )}
    </div>
  );
}

const KIND_COLORS: Record<Activity["kind"], string> = {
  joined: "var(--online)",
  status: "var(--workflow)",
  branch: "var(--muted)",
  pr: "var(--accent)",
  claim: "var(--decision)",
  release: "var(--muted)",
  entry: "var(--finding)",
  question: "var(--question)",
};

export function activityText(a: Activity) {
  switch (a.kind) {
    case "joined":
      return a.detail ? `joined on ${a.detail}` : "joined";
    case "status":
      return `is working on ${a.detail}`;
    case "branch":
      return `switched to ${a.detail}`;
    case "pr":
      return `opened or moved to ${a.detail}`;
    case "claim":
      return `claimed ${a.detail}`;
    case "release":
      return `released ${a.detail}`;
    case "entry":
      return `saved ${a.detail}`;
    case "question":
      return `asked: ${a.detail}`;
  }
}

export function activityHref(a: Activity) {
  if (a.ref.startsWith("e")) return hrefs.entry(Number(a.ref.slice(1)));
  if (a.kind === "claim" || a.kind === "release") return "#/claims";
  return hrefs.user(a.agent_id.split("/")[0]);
}

export function Timeline({ items, showAgent = true }: { items: Activity[]; showAgent?: boolean }) {
  if (!items.length) return <div className="small muted">Nothing yet.</div>;
  return (
    <div className="timeline">
      {items.map((a) => {
        const [user, name] = a.agent_id.split("/");
        return (
          <div key={a.id} className="tl">
            <span className="t" title={fullTime(a.created_at)}>
              {ago(a.created_at)}
            </span>
            <span className="k" style={{ ["--k" as string]: KIND_COLORS[a.kind] }} />
            <span className="d">
              {showAgent && (
                <>
                  <b style={{ color: name ? agentColor(name) : undefined }}>{name || user}</b>{" "}
                </>
              )}
              <a href={activityHref(a)} style={{ color: "inherit" }}>
                {activityText(a)}
              </a>
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function ClaimRow({ c, conflicts }: { c: Claim; conflicts: Claim[] }) {
  const [user, name] = c.agent_id.split("/");
  return (
    <div className="item">
      <Avatar user={user} size="sm" />
      <div className="main-col">
        <div className="claim-path">{c.path}</div>
        <div className="sub">
          <a href={hrefs.user(user)}>{user}</a>
          {name && <AgentChip agent={name} />}
          {c.branch && <span className="mono">{c.branch}</span>}
          {c.note && <span>“{c.note}”</span>}
        </div>
        {conflicts.length > 0 && (
          <div className="conflict">
            ⚠ overlaps {conflicts.map((o) => `${o.path} (${o.agent_id})`).join(", ")}
          </div>
        )}
      </div>
      <div className="side-col">
        <span title={fullTime(c.created_at)}>since {ago(c.created_at)}</span>
        <span>{expiresIn(c.expires_at)}</span>
      </div>
    </div>
  );
}
