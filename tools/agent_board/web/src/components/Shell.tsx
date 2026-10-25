import { activityHref, activityText } from "./Agents";
import { ChannelForm, EntryForm, NameForm } from "./Forms";
import { Avatar, Icon } from "./ui";
import { openModal } from "../lib/modal";
import { go, hrefs, type Route } from "../lib/route";
import { me, notificationsOn, people, toggleNotifications, unread, useBoard, type FeedItem } from "../lib/store";
import type { EntryKind } from "../lib/types";
import { KINDS, ago, cls, expiresIn, pathsOverlap, plain, store } from "../lib/util";
import { lastVisit } from "../views/Dashboard";

function Nav({ href, active, icon, label, badge }: { href: string; active: boolean; icon: React.ReactNode; label: string; badge?: React.ReactNode }) {
  return (
    <a className={cls("nav", active && "active")} href={href}>
      <span className="icon">{icon}</span>
      <span className="grow">{label}</span>
      {badge}
    </a>
  );
}

export function toggleTheme() {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  const next = cur === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  store.set("theme", next);
}

export function Sidebar({ r, open, onClose }: { r: Route; open: boolean; onClose: () => void }) {
  const s = useBoard();
  const ppl = people(s);
  const counts = Object.fromEntries((Object.keys(KINDS) as EntryKind[]).map((k) => [k, s.entries.filter((e) => e.kind === k).length]));
  const since = lastVisit();
  const fresh = s.feed.filter((f) => f.at > since && f.kind !== "activity").length;
  const user = me();
  const conflicts = s.claims.filter((c) => s.claims.some((o) => o.agent_id !== c.agent_id && pathsOverlap(o.path, c.path))).length;
  return (
    <>
      <div className={cls("side-scrim", open && "open")} onClick={onClose} />
      <aside className={cls("side", open && "open")} onClick={(e) => (e.target as HTMLElement).closest("a") && onClose()}>
        <div className="brand">
          <span className="mark" aria-hidden="true">
            <svg width="14" height="14" viewBox="0 0 16 16">
              <path d="M3 4.5h10M3 8h7M3 11.5h4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </span>
          <div className="brand-text">
            <h1>Agent Board</h1>
            <div className="sub">{s.repo.split("/").pop()}</div>
          </div>
        </div>
        <div className="side-scroll">
          <Nav href="#/" active={r.view === "overview"} icon={<Icon name="grid" />} label="Overview" />
          <Nav href="#/digest" active={r.view === "digest"} icon={<Icon name="spark" />} label="Since you last looked" badge={fresh > 0 && r.view !== "digest" ? <span className="count strong">{fresh > 99 ? "99+" : fresh}</span> : undefined} />
          <Nav href="#/questions" active={r.view === "questions"} icon={<Icon name="question" />} label="Questions" badge={s.openQuestions.length ? <span className="count strong">{s.openQuestions.length}</span> : undefined} />
          <Nav href="#/claims" active={r.view === "claims"} icon={<Icon name="lock" />} label="Claims" badge={s.claims.length ? <span className={cls("count", conflicts && "danger")} title={conflicts ? `${conflicts} overlapping` : undefined}>{s.claims.length}</span> : undefined} />
          <Nav href="#/github" active={r.view === "github"} icon={<Icon name="pr" />} label="PRs and issues" badge={s.github?.pulls.length ? <span className="count">{s.github.pulls.length}</span> : undefined} />
          <Nav href="#/activity" active={r.view === "activity"} icon={<Icon name="pulse" />} label="Activity" />

          <h2>
            Knowledge
            <button title="Add an entry (n)" onClick={() => openModal(<EntryForm />)}>
              +
            </button>
          </h2>
          <Nav href="#/knowledge" active={r.view === "knowledge" && !r.params.get("kind") && !r.params.get("tag")} icon={<Icon name="doc" />} label="All entries" badge={<span className="count">{s.entries.length}</span>} />
          {(Object.keys(KINDS) as EntryKind[]).map((k) => (
            <Nav
              key={k}
              href={`#/knowledge?kind=${k}`}
              active={r.view === "knowledge" && r.params.get("kind") === k}
              icon={<span className="dot" style={{ background: KINDS[k].color }} />}
              label={KINDS[k].label + "s"}
              badge={<span className="count">{counts[k]}</span>}
            />
          ))}
          <Nav href="#/tags" active={r.view === "tags"} icon={<Icon name="tag" />} label="Tags" badge={<span className="count">{s.tags.length}</span>} />

          <h2>
            Channels
            <button title="New channel" onClick={() => openModal(<ChannelForm />)}>
              +
            </button>
          </h2>
          {s.channels.map((c) => {
            const active = r.view === "c" && r.arg === c.name;
            const n = active ? 0 : unread(s, c);
            return (
              <a key={c.name} className={cls("nav", active && "active", n > 0 && "unread")} href={hrefs.channel(c.name)} title={c.topic}>
                <span className="hash">#</span>
                <span className="grow">{c.name}</span>
                {c.open_questions > 0 && (
                  <span className="count" title={`${c.open_questions} open question${c.open_questions === 1 ? "" : "s"}`}>
                    {c.open_questions}?
                  </span>
                )}
                {n > 0 ? <span className="unread-dot" title={`${n} unread`} /> : c.expires_at ? <span className="ttl" title="Expires after inactivity">{expiresIn(c.expires_at)}</span> : null}
              </a>
            );
          })}

          <h2>People</h2>
          {ppl.map((p) => (
            <div key={p.user} className={cls("person", r.view === "u" && r.arg === p.user && "active")} onClick={() => go(hrefs.user(p.user))}>
              <div className="person-head">
                <Avatar user={p.user} size="sm" />
                <b>{p.user}</b>
                <span className="count">{p.agents.filter((a) => a.online).length || ""}</span>
              </div>
              {p.agents.length > 0 && (
                <div className="agents">
                  {p.agents.slice(0, 6).map((a) => (
                    <div key={a.id} className="agent-row" title={`${a.branch}${a.status ? " — " + a.status : ""}\nlast seen ${ago(a.last_seen)}`}>
                      <span className={cls("presence", a.online && "on")} />
                      <span className="name">{a.name}</span>
                      <span className="status">{a.status || a.branch}</span>
                      {a.pr && <span className="pr">#{a.pr}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          {!ppl.length && <div className="ttl" style={{ padding: "4px 9px" }}>Nobody yet.</div>}
        </div>
        <div className="side-foot">
          {user && <Avatar user={user} size="sm" />}
          <div className="grow">
            {user ? (
              <>
                <b>{user}</b> <span className="ttl">(you)</span>
              </>
            ) : (
              <a href="#" onClick={(e) => (e.preventDefault(), openModal(<NameForm />))}>
                Set your name
              </a>
            )}
          </div>
          <button className="iconbtn" onClick={toggleNotifications} title={notificationsOn() ? "Notifications on (mentions and replies)" : "Turn on notifications"}>
            <Icon name={notificationsOn() ? "bell" : "bellOff"} size={14} />
          </button>
          <button className="iconbtn" onClick={() => openModal(<NameForm />)} title="Change name">
            <Icon name="user" size={14} />
          </button>
          <button className="iconbtn" onClick={toggleTheme} title="Toggle theme">
            <Icon name="theme" size={14} />
          </button>
        </div>
      </aside>
    </>
  );
}

function feedLine(e: FeedItem): { line: React.ReactNode; snippet?: string; href: string; user: string } {
  switch (e.kind) {
    case "entry":
    case "entry-update": {
      const it = e.item;
      return {
        line: (
          <>
            <b>{it.author_agent || it.author_user}</b> {e.kind === "entry" ? "saved a" : "updated a"} {KINDS[it.kind]?.label.toLowerCase() || it.kind}
          </>
        ),
        snippet: it.title,
        href: hrefs.entry(it.id),
        user: it.author_user,
      };
    }
    case "message": {
      const it = e.item;
      const verb = it.parent_id ? "replied in" : it.kind === "question" ? "asked in" : "posted in";
      return {
        line: (
          <>
            <b>{it.author_user === "github" ? "GitHub" : it.author_agent || it.author_user}</b> {verb} <b>#{it.channel}</b>
          </>
        ),
        snippet: plain(it.body, 120),
        href: hrefs.thread(it.channel, it.parent_id || it.id),
        user: it.author_user,
      };
    }
    case "agent":
    case "status":
      return {
        line: (
          <>
            <b>{e.item.name}</b> joined for {e.item.user}
          </>
        ),
        snippet: e.item.branch,
        href: hrefs.user(e.item.user),
        user: e.item.user,
      };
    case "activity": {
      const [user, name] = e.item.agent_id.split("/");
      return {
        line: (
          <>
            <b>{name || user}</b> {activityText(e.item)}
          </>
        ),
        href: activityHref(e.item),
        user,
      };
    }
    case "expired":
      return { line: <><b>#{e.item.name}</b> expired</>, href: "#/", user: "#" };
  }
}

export function Rail() {
  const feed = useBoard((s) => s.feed);
  useBoard((s) => s.tick);
  return (
    <aside className="rail">
      <div className="rail-head">
        <h3>Activity</h3>
      </div>
      <div className="feed">
        {feed.map((e) => {
          const f = feedLine(e);
          return (
            <a key={e.key} className="ev" href={f.href}>
              <div className="line">{f.line}</div>
              {f.snippet && <div className="snippet">{f.snippet}</div>}
              <div className="t">{ago(e.at)}</div>
            </a>
          );
        })}
        {!feed.length && <div className="muted small" style={{ padding: 12 }}>Waiting for agents…</div>}
      </div>
    </aside>
  );
}
