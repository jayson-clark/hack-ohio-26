import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Composer } from "../components/Composer";
import { ChannelForm } from "../components/Forms";
import { MessageView } from "../components/Message";
import { react } from "../components/Reactions";
import { Empty } from "../components/ui";
import { openModal, modalOpen } from "../lib/modal";
import { go, hrefs, useRoute } from "../lib/route";
import { api, lastRead, loadChannel, markRead, useBoard } from "../lib/store";
import type { Message } from "../lib/types";
import { dayLabel } from "../lib/util";

export function ChannelView({ name }: { name: string }) {
  const route = useRoute();
  const all = useBoard((s) => s.messages[name]);
  const channel = useBoard((s) => s.channels.find((c) => c.name === name));
  const flash = useBoard((s) => s.flash);
  const scroller = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [readAt] = useState(() => ({ name, t: lastRead(name) }));
  const unreadSince = readAt.name === name ? readAt.t : lastRead(name);
  const atBottom = useRef(true);
  const lastName = useRef("");

  useEffect(() => {
    if (!all) loadChannel(name);
    setSelected(null);
  }, [name, all]);

  const { top, byParent } = useMemo(() => {
    const top: Message[] = [];
    const byParent: Record<number, Message[]> = {};
    for (const m of all || []) {
      if (m.parent_id) (byParent[m.parent_id] ||= []).push(m);
      else top.push(m);
    }
    return { top, byParent };
  }, [all]);

  // Stay pinned to the newest message unless the reader scrolled up.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || !all) return;
    if (lastName.current !== name) {
      lastName.current = name;
      const firstUnread = top.find((m) => m.created_at > unreadSince);
      const target = firstUnread && document.getElementById(`m${firstUnread.id}`);
      if (target && top.indexOf(firstUnread!) > 0) target.scrollIntoView({ block: "center" });
      else el.scrollTop = el.scrollHeight;
    } else if (atBottom.current) el.scrollTop = el.scrollHeight;
    markRead(name);
  }, [all, name, top, unreadSince]);

  // Diagrams and images render late; keep the newest message in view while they grow the page.
  useEffect(() => {
    const el = scroller.current;
    const inner = el?.firstElementChild;
    if (!el || !inner) return;
    const ro = new ResizeObserver(() => {
      if (atBottom.current) el.scrollTop = el.scrollHeight;
    });
    ro.observe(inner);
    return () => ro.disconnect();
  }, [all !== undefined, name]);

  useEffect(() => {
    if (selected) document.getElementById(`m${selected}`)?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  // j/k/r/e on the selected message.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || modalOpen() || /INPUT|TEXTAREA|SELECT/.test((e.target as HTMLElement).tagName)) return;
      const idx = selected ? top.findIndex((m) => m.id === selected) : top.length;
      if (e.key === "j" || e.key === "k") {
        e.preventDefault();
        const next = e.key === "j" ? Math.min(idx + 1, top.length - 1) : Math.max(idx - 1, 0);
        if (top[next]) setSelected(top[next].id);
      } else if (e.key === "r" && selected) {
        e.preventDefault();
        go(hrefs.thread(name, selected));
      } else if (e.key === "e" && selected) {
        e.preventDefault();
        react(`m${selected}`, "✅");
      } else if (e.key === "Enter" && selected) {
        go(hrefs.thread(name, selected));
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [selected, top, name]);

  if (!all) return <div className="content"><div className="stream"><div className="day">Loading…</div></div></div>;

  let day = "";
  let unreadShown = false;
  return (
    <>
      <div
        className="content"
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
        }}
      >
        {!top.length ? (
          <div className="pad">
            <Empty title={`#${name} is quiet`}>
              Post below, or from an agent: <code>board.py post "…" -c {name}</code>
            </Empty>
          </div>
        ) : (
          <div className="stream">
            {all.length >= 500 && (
              <button className="btn sm loadmore" onClick={() => loadChannel(name, all[0].created_at)}>
                Load earlier messages
              </button>
            )}
            {top.map((m) => {
              const d = dayLabel(m.created_at);
              const sep = d !== day ? <div className="day">{d}</div> : null;
              day = d;
              const showUnread = !unreadShown && unreadSince > 0 && m.created_at > unreadSince && top[0] !== m;
              if (showUnread) unreadShown = true;
              return (
                <div key={m.id}>
                  {sep}
                  {showUnread && <div className="unread-line">New</div>}
                  <MessageView m={m} replies={byParent[m.id] || []} selected={selected === m.id || route.thread === m.id} flash={flash.has("m" + m.id)} />
                </div>
              );
            })}
          </div>
        )}
      </div>
      {channel ? (
        <Composer
          draftKey={`c:${name}`}
          placeholder={`Message #${name}`}
          onSend={(text, o) => api("POST", "/api/messages", { channel: name, body: text, kind: o.question ? "question" : "message" }).then(() => (atBottom.current = true))}
        />
      ) : (
        <div className="composer">
          <div className="composer-box" style={{ padding: 12, color: "var(--muted)", fontSize: 13 }}>
            #{name} has expired. <a href="#" onClick={(e) => (e.preventDefault(), openModal(<ChannelForm />))}>Start a new channel</a>
          </div>
        </div>
      )}
    </>
  );
}

export function ThreadPanel({ channel, id }: { channel: string; id: number }) {
  const all = useBoard((s) => s.messages[channel]);
  const flash = useBoard((s) => s.flash);
  const body = useRef<HTMLDivElement>(null);
  const root = all?.find((m) => m.id === id);
  const replies = useMemo(() => (all || []).filter((m) => m.parent_id === id), [all, id]);
  const [missing, setMissing] = useState(false);
  const tried = useRef(new Set<number>());

  useEffect(() => {
    if (!all) loadChannel(channel);
  }, [all, channel]);
  useEffect(() => {
    // A link to an old message that isn't in the loaded page: fetch the thread itself.
    if (all && !root && !tried.current.has(id)) {
      tried.current.add(id);
      api<{ message: Message; replies: Message[] }>("GET", `/api/messages/${id}`)
        .then((t) => {
          if (t.message.channel !== channel) go(hrefs.thread(t.message.channel, t.message.id));
          else if (t.message.id !== id) go(hrefs.thread(channel, t.message.id));
          else loadChannel(channel, t.message.created_at + 1);
        })
        .catch(() => setMissing(true));
    }
  }, [all, root, id, channel]);
  useLayoutEffect(() => {
    if (body.current) body.current.scrollTop = body.current.scrollHeight;
  }, [replies.length, id]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !modalOpen() && !(e.target as HTMLElement).closest?.("textarea")) go(hrefs.channel(channel));
    };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [channel]);

  const close = () => go(hrefs.channel(channel));
  return (
    <aside className="thread" aria-label="Thread">
      <div className="thread-head">
        <h3>
          Thread <span className="muted">in #{channel}</span>
        </h3>
        <button className="iconbtn" onClick={close} aria-label="Close thread" title="Close (Esc)">
          ✕
        </button>
      </div>
      <div className="thread-body" ref={body}>
        {root ? (
          <>
            <MessageView m={root} inThread flash={flash.has("m" + root.id)} />
            <div className="thread-sep">
              {replies.length} {replies.length === 1 ? "reply" : "replies"}
            </div>
            {replies.map((r) => (
              <MessageView key={r.id} m={r} inThread flash={flash.has("m" + r.id)} />
            ))}
          </>
        ) : (
          <div className="empty" style={{ margin: 12 }}>
            {missing ? "That message is gone (its channel may have expired)." : "Loading…"}
          </div>
        )}
      </div>
      {root && (
        <Composer
          key={id}
          draftKey={`t:${id}`}
          placeholder="Reply…"
          allowQuestion={false}
          canResolve={root.kind === "question" && !root.resolved}
          autoFocus
          onCancel={close}
          onSend={(text, o) => api("POST", "/api/messages", { parent_id: id, body: text, resolve: o.resolve })}
        />
      )}
    </aside>
  );
}
