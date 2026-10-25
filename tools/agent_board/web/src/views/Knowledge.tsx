import { useEffect, useMemo, useState } from "react";
import { EntryForm } from "../components/Forms";
import { Reactions } from "../components/Reactions";
import { Ago, Avatar, Byline, Empty, Hl, Icon, KindBadge, Markdown } from "../components/ui";
import { openModal } from "../lib/modal";
import { go, hrefs } from "../lib/route";
import { api, entryListeners, fail, me, toast, useBoard } from "../lib/store";
import type { Entry, EntryKind, Revision, Vote } from "../lib/types";
import { KINDS, ago, cls, debounce, fullTime, lineDiff, plain } from "../lib/util";

export function staleness(e: Entry): "superseded" | "stale" | null {
  if (e.superseded_by) return "superseded";
  if (e.votes.stale > e.votes.true) return "stale";
  return null;
}

export function EntryCard({ e, flash = false }: { e: Entry; flash?: boolean }) {
  const st = staleness(e);
  return (
    <article className={cls("card", flash && "flash", st && "dim")} onClick={() => go(hrefs.entry(e.id))}>
      <div className="meta">
        <KindBadge kind={e.kind} />
        <span className="sep">·</span>
        <Ago t={e.updated_at} />
        {e.revisions > 1 && (
          <>
            <span className="sep">·</span>
            <span>edited</span>
          </>
        )}
        {st === "superseded" && <span className="pill warn">superseded</span>}
        {st === "stale" && <span className="pill warn">may be stale</span>}
        {e.votes.true > 0 && st !== "stale" && <span className="pill ok" title="Votes that it's still true">✓ {e.votes.true}</span>}
      </div>
      <h4>{e.title_hl ? <Hl text={e.title_hl} /> : e.title}</h4>
      {e.snippet ? (
        <div className="snippet">
          <Hl text={e.snippet} />
        </div>
      ) : (
        e.body && <div className="excerpt">{plain(e.body, 220)}</div>
      )}
      <div className="meta" style={{ marginTop: "auto" }}>
        <Avatar user={e.author_user} size="sm" />
        <Byline user={e.author_user} agent={e.author_agent} />
        {e.tags.map((t) => (
          <a key={t} className="tag" href={hrefs.tag(t)} onClick={(ev) => ev.stopPropagation()}>
            #{t}
          </a>
        ))}
        {Object.keys(e.reactions).length > 0 && <span className="small">{Object.entries(e.reactions).map(([k, v]) => `${k}${v.length}`).join(" ")}</span>}
      </div>
    </article>
  );
}

export function KnowledgeView({ params }: { params: URLSearchParams }) {
  const entries = useBoard((s) => s.entries);
  const flash = useBoard((s) => s.flash);
  const kind = params.get("kind") as EntryKind | null;
  const tag = params.get("tag");
  const [q, setQ] = useState(params.get("q") || "");
  const [sort, setSort] = useState<"recent" | "stale" | "votes">("recent");
  const [hits, setHits] = useState<Entry[] | null>(null);

  const search = useMemo(
    () =>
      debounce((text: string, kind: string | null, tag: string | null) => {
        if (!text.trim()) return setHits(null);
        const p = new URLSearchParams({ q: text, limit: "100" });
        if (kind) p.set("kind", kind);
        if (tag) p.set("tag", tag);
        api<Entry[]>("GET", `/api/entries?${p}`).then(setHits, fail);
      }, 160),
    [],
  );
  useEffect(() => search(q, kind, tag), [q, kind, tag, search, entries]);

  const rows = useMemo(() => {
    let list = hits ?? entries.filter((e) => (!kind || e.kind === kind) && (!tag || e.tags.includes(tag)));
    if (!hits) {
      if (sort === "stale") list = [...list].sort((a, b) => Number(!!staleness(b)) - Number(!!staleness(a)) || a.updated_at - b.updated_at);
      if (sort === "votes") list = [...list].sort((a, b) => b.votes.true - a.votes.true || b.updated_at - a.updated_at);
    }
    return list;
  }, [hits, entries, kind, tag, sort]);

  const link = (k: string | null) => {
    const p = new URLSearchParams();
    if (k) p.set("kind", k);
    if (tag) p.set("tag", tag);
    return `#/knowledge${p.toString() ? "?" + p : ""}`;
  };

  return (
    <div className="pad">
      <div className="filters">
        <a className={cls("seg", !kind && "on")} href={link(null)}>
          All
        </a>
        {(Object.keys(KINDS) as EntryKind[]).map((k) => (
          <a key={k} className={cls("seg", kind === k && "on")} href={link(k)}>
            <span className="dot" style={{ background: KINDS[k].color }} />
            {KINDS[k].label}s
          </a>
        ))}
        {tag && (
          <a className="seg on" href={`#/knowledge${kind ? "?kind=" + kind : ""}`}>
            #{tag} ✕
          </a>
        )}
        <span style={{ flex: 1 }} />
        <a className="seg" href="#/tags">
          <Icon name="tag" size={13} /> Tags
        </a>
        <button className="btn primary" onClick={() => openModal(<EntryForm prefill={tag ? { tags: [tag] } : {}} />)}>
          New entry
        </button>
      </div>
      <div className="filters">
        <label className="search grow" style={{ maxWidth: 520 }}>
          <Icon name="search" size={14} />
          <input
            style={{ width: "100%", maxWidth: "none" }}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search knowledge: ranked, prefix and stem matching (calib → calibration)"
            autoFocus={!!params.get("q")}
          />
        </label>
        {!hits && (
          <select className="input" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} aria-label="Sort">
            <option value="recent">Recently updated</option>
            <option value="votes">Most confirmed</option>
            <option value="stale">Possibly stale first</option>
          </select>
        )}
        {hits && <span className="small muted">{hits.length} match{hits.length === 1 ? "" : "es"}, best first</span>}
      </div>
      {rows.length ? (
        <div className="grid">
          {rows.map((e) => (
            <EntryCard key={e.id} e={e} flash={flash.has("e" + e.id)} />
          ))}
        </div>
      ) : (
        <Empty title={entries.length ? "No matches" : "Nothing saved yet"}>
          {entries.length ? "Try other words or clear the filters." : <>Agents add entries with <code>board.py add finding "…"</code></>}
        </Empty>
      )}
    </div>
  );
}

export function TagsView() {
  const tags = useBoard((s) => s.tags);
  const max = Math.max(1, ...tags.map((t) => t.count));
  return (
    <div className="pad">
      {tags.length ? (
        <div className="tagcloud">
          {tags.map((t) => (
            <a key={t.tag} href={hrefs.tag(t.tag)} style={{ fontSize: 12.5 + (t.count / max) * 6 }}>
              #{t.tag}
              <span className="n">{t.count}</span>
            </a>
          ))}
        </div>
      ) : (
        <Empty title="No tags yet">Tag entries with <code>--tags vision,aruco</code></Empty>
      )}
    </div>
  );
}

function DiffView({ a, b }: { a: string; b: string }) {
  const lines = lineDiff(a, b);
  // Show changed lines with one line of context; collapse the rest.
  const keep = lines.map((l, i) => l.op !== " " || lines[i - 1]?.op !== " " || lines[i + 1]?.op !== " ");
  const out: React.ReactNode[] = [];
  let skipped = 0;
  lines.forEach((l, i) => {
    if (!keep[i]) {
      skipped++;
      return;
    }
    if (skipped) out.push(<div key={"g" + i} className="gap">… {skipped} unchanged line{skipped === 1 ? "" : "s"}</div>);
    skipped = 0;
    out.push(
      <div key={i} className={l.op === "+" ? "add" : l.op === "-" ? "del" : "ctx"}>
        {l.op} {l.line || " "}
      </div>,
    );
  });
  if (skipped) out.push(<div key="gend" className="gap">… {skipped} unchanged line{skipped === 1 ? "" : "s"}</div>);
  return <div className="diff">{out}</div>;
}

function History({ id }: { id: number }) {
  const [revs, setRevs] = useState<Revision[] | null>(null);
  useEffect(() => {
    const get = () => api<Revision[]>("GET", `/api/entries/${id}/history`).then(setRevs, fail);
    get();
    const l = (x: number) => x === id && get();
    entryListeners.add(l);
    return () => void entryListeners.delete(l);
  }, [id]);
  if (!revs) return <div className="muted small" style={{ padding: 12 }}>Loading…</div>;
  return (
    <div>
      {[...revs].reverse().map((r, i, list) => {
        const prev = list[i + 1];
        return (
          <div key={r.id} className="rev">
            <div className="who">
              <Avatar user={r.editor_user} size="sm" />
              <Byline user={r.editor_user} agent={r.editor_agent} />
              <span className="muted" title={fullTime(r.created_at)}>
                {prev ? "edited" : "created"} {ago(r.created_at)}
              </span>
              {prev && r.archived !== prev.archived && <span className="pill warn">{r.archived ? "archived" : "restored"}</span>}
            </div>
            {prev ? (
              <>
                {r.kind !== prev.kind && <div className="small" style={{ marginTop: 6 }}>kind: {prev.kind} → {r.kind}</div>}
                {r.title !== prev.title && <div className="small" style={{ marginTop: 6 }}>title: <del>{prev.title}</del> → {r.title}</div>}
                {r.tags.join() !== prev.tags.join() && <div className="small" style={{ marginTop: 6 }}>tags: {prev.tags.join(", ") || "none"} → {r.tags.join(", ") || "none"}</div>}
                {r.body !== prev.body && <DiffView a={prev.body} b={r.body} />}
              </>
            ) : (
              <div className="small muted" style={{ marginTop: 6 }}>{r.title}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Votes({ e }: { e: Entry }) {
  const [list, setList] = useState<Vote[]>([]);
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState("");
  const mine = list.find((v) => v.voter === me());
  useEffect(() => {
    api<Vote[]>("GET", `/api/entries/${e.id}/votes`).then(setList, fail);
  }, [e.id, e.votes.true, e.votes.stale]);
  const vote = (v: "true" | "stale" | "", n = "") => {
    setNoting(false);
    setNote("");
    api("POST", `/api/entries/${e.id}/vote`, { vote: v, note: n }).catch(fail);
  };
  return (
    <div className="panel">
      <h4>
        Still true?
        <span className="muted small" style={{ fontWeight: 400 }}>
          {e.votes.confirmed_at ? `last confirmed ${ago(e.votes.confirmed_at)}` : "nobody has confirmed it yet"}
        </span>
      </h4>
      <div className="row wrap">
        <button className={cls("btn sm", mine?.vote === "true" && "on")} onClick={() => vote(mine?.vote === "true" ? "" : "true")}>
          <Icon name="check" size={13} /> Still true · {e.votes.true}
        </button>
        <button className={cls("btn sm", mine?.vote === "stale" && "on")} onClick={() => (mine?.vote === "stale" ? vote("") : setNoting(true))}>
          ⚠️ Stale · {e.votes.stale}
        </button>
        <span className="small muted grow">
          {list.slice(0, 6).map((v) => `${v.voter.split("/").pop()} ${v.vote === "true" ? "✓" : "⚠"}${v.note ? ` (“${v.note}”)` : ""}`).join(" · ")}
        </span>
      </div>
      {noting && (
        <div className="linkform">
          <input className="input grow" autoFocus value={note} onChange={(x) => setNote(x.target.value)} placeholder="What changed? (optional)" onKeyDown={(x) => x.key === "Enter" && vote("stale", note)} />
          <button className="btn sm primary" onClick={() => vote("stale", note)}>
            Mark stale
          </button>
          <button className="btn sm ghost" onClick={() => setNoting(false)}>
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}

function Links({ e }: { e: Entry }) {
  const entries = useBoard((s) => s.entries);
  const [to, setTo] = useState("");
  const [rel, setRel] = useState<"related" | "supersedes">("related");
  const options = entries.filter((x) => x.id !== e.id && !e.links.some((l) => l.id === x.id));
  const add = () => {
    const id = Number(to.replace(/^#|\s.*$/g, "")) || options.find((x) => x.title.toLowerCase() === to.toLowerCase())?.id;
    if (!id) return toast("Pick an entry by number or title");
    api("POST", `/api/entries/${e.id}/links`, { to: id, rel }).then(() => setTo(""), fail);
  };
  const label = (l: Entry["links"][number]) =>
    l.rel === "supersedes" ? (l.dir === "out" ? "supersedes" : "superseded by") : "related";
  return (
    <div className="panel">
      <h4>
        <Icon name="link" size={13} /> Linked entries
      </h4>
      {e.links.length ? (
        <div className="links">
          {e.links.map((l) => (
            <div key={l.id + l.dir} className="row">
              <span className="rel">{label(l)}</span>
              <a href={hrefs.entry(l.id)} className="grow ellipsis" style={l.archived ? { opacity: 0.6 } : undefined}>
                <KindBadge kind={l.kind} /> {l.title}
              </a>
              <button className="btn ghost sm" title="Remove link" onClick={() => api("DELETE", `/api/entries/${e.id}/links/${l.id}`).catch(fail)}>
                ✕
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="small muted">None yet. Link related entries, or mark one this replaces.</div>
      )}
      <div className="linkform">
        <select className="input" value={rel} onChange={(x) => setRel(x.target.value as typeof rel)}>
          <option value="related">Related to</option>
          <option value="supersedes">Supersedes</option>
        </select>
        <input className="input grow" list={`link-${e.id}`} value={to} onChange={(x) => setTo(x.target.value)} placeholder="Entry number or title" onKeyDown={(x) => x.key === "Enter" && add()} />
        <datalist id={`link-${e.id}`}>
          {options.slice(0, 200).map((x) => (
            <option key={x.id} value={`${x.id} ${x.title}`} />
          ))}
        </datalist>
        <button className="btn sm" onClick={add}>
          Link
        </button>
      </div>
    </div>
  );
}

export function EntryPage({ id }: { id: number }) {
  const cached = useBoard((s) => s.entries.find((e) => e.id === id));
  const [fetched, setFetched] = useState<Entry | null>(null);
  const [missing, setMissing] = useState(false);
  const [tab, setTab] = useState<"details" | "history">("details");
  const e = cached || fetched;

  useEffect(() => {
    setTab("details");
    setFetched(null);
    setMissing(false);
  }, [id]);
  useEffect(() => {
    if (cached) return;
    const get = () => api<Entry>("GET", `/api/entries/${id}`).then(setFetched, () => setMissing(true));
    get();
    const l = (x: number) => x === id && get();
    entryListeners.add(l);
    return () => void entryListeners.delete(l);
  }, [id, cached]);

  if (!e) return <div className="pad">{missing ? <Empty title={`No entry #${id}`} /> : <div className="muted">Loading…</div>}</div>;
  const st = staleness(e);
  const archive = async () => {
    try {
      await api("PATCH", `/api/entries/${e.id}`, { archived: !e.archived });
      toast(e.archived ? "Restored" : "Archived");
    } catch (err) {
      fail(err);
    }
  };
  return (
    <div className="pad entry-page">
      <div className="meta">
        <KindBadge kind={e.kind} />
        <span className="sep">·</span>
        <span>#{e.id}</span>
        <span className="sep">·</span>
        <Ago t={e.created_at} prefix="created " />
        {e.revisions > 1 && (
          <>
            <span className="sep">·</span>
            <Ago t={e.updated_at} prefix="edited " />
          </>
        )}
        {e.archived ? <span className="pill">archived</span> : null}
      </div>
      <h1>{e.title}</h1>
      <div className="meta">
        <Avatar user={e.author_user} size="sm" />
        <Byline user={e.author_user} agent={e.author_agent} />
        {e.source && (
          <>
            <span className="sep">·</span>
            <span>
              from <Markdown src={e.source} className="inline" />
            </span>
          </>
        )}
        {e.tags.map((t) => (
          <a key={t} className="tag" href={hrefs.tag(t)}>
            #{t}
          </a>
        ))}
      </div>
      {st === "superseded" && (
        <div className="banner warn">
          ⚠️ Superseded by <a href={hrefs.entry(e.superseded_by!)}>{e.links.find((l) => l.id === e.superseded_by)?.title || `#${e.superseded_by}`}</a>. Prefer that one.
        </div>
      )}
      {st === "stale" && <div className="banner warn">⚠️ More people say this is stale than still true. Check before relying on it, then vote or update it.</div>}
      <div className="tabsbar">
        <button className={cls(tab === "details" && "on")} onClick={() => setTab("details")}>
          Details
        </button>
        <button className={cls(tab === "history" && "on")} onClick={() => setTab("history")}>
          <Icon name="history" size={13} /> History · {e.revisions}
        </button>
      </div>
      {tab === "details" ? (
        <>
          <div className="body">{e.body ? <Markdown src={e.body} /> : <span className="muted">No details.</span>}</div>
          <Reactions target={`e${e.id}`} reactions={e.reactions} showAdd />
          <Votes e={e} />
          <Links e={e} />
        </>
      ) : (
        <History id={e.id} />
      )}
      <div className="toolbar">
        <button className="btn sm" onClick={() => openModal(<EntryForm entry={e} />)}>
          <Icon name="edit" size={13} /> Edit
        </button>
        <button className="btn sm" onClick={() => navigator.clipboard?.writeText(`python3 tools/agent_board/board.py show ${e.id}`).then(() => toast("CLI command copied"))}>
          <Icon name="copy" size={13} /> Copy CLI command
        </button>
        <span className="grow" />
        <button className="btn ghost danger sm" onClick={archive}>
          <Icon name="archive" size={13} /> {e.archived ? "Restore" : "Archive"}
        </button>
      </div>
    </div>
  );
}
