import { useState } from "react";
import { openModal } from "../lib/modal";
import { go, hrefs } from "../lib/route";
import { api, fail, getState, mentionsMe, toast } from "../lib/store";
import type { Message } from "../lib/types";
import { clock, cls, fullTime, plain } from "../lib/util";
import { EntryForm } from "./Forms";
import { EmojiPicker, QUICK, Reactions, react } from "./Reactions";
import { Avatar, Byline, Icon, Markdown } from "./ui";

export function saveToKnowledge(m: Message) {
  const all = Object.values(getState().messages).flat();
  const replies = all.filter((r) => r.parent_id === m.id);
  const body = m.body + (replies.length ? "\n\n" + replies.map((r) => `**${r.author_agent || r.author_user}:** ${r.body}`).join("\n\n") : "");
  openModal(<EntryForm prefill={{ kind: "finding", title: plain(m.body, 90), body, source: `#${m.channel} message ${m.id}` }} />);
}

export function setResolved(m: Message, resolved: boolean) {
  return api("POST", `/api/messages/${m.id}/${resolved ? "resolve" : "reopen"}`, {}).catch(fail);
}

function copyLink(m: Message) {
  const url = `${location.origin}${location.pathname}${hrefs.thread(m.channel, m.parent_id || m.id)}`;
  navigator.clipboard?.writeText(url).then(() => toast("Link copied"), fail);
}

export function MessageView({
  m,
  replies = [],
  selected = false,
  flash = false,
  inThread = false,
  showChannel = false,
}: {
  m: Message;
  replies?: Message[];
  selected?: boolean;
  flash?: boolean;
  inThread?: boolean;
  showChannel?: boolean;
}) {
  const [picking, setPicking] = useState(false);
  const isQ = m.kind === "question" && !m.parent_id;
  const forMe = mentionsMe(m);
  const openThread = () => go(hrefs.thread(m.channel, m.parent_id || m.id));
  const replyAuthors = [...new Set(replies.map((r) => r.author_user))].slice(0, 4);
  const lastReply = replies.length ? replies[replies.length - 1].created_at : m.last_reply_at;
  const replyCount = Math.max(replies.length, m.reply_count || 0);

  return (
    <div
      className={cls("msg", isQ && "question", isQ && m.resolved && "resolved", selected && "selected", flash && "flash", forMe && !isQ && "for-me")}
      id={`m${m.id}`}
      data-mid={m.id}
    >
      <Avatar user={m.author_user} />
      <div style={{ minWidth: 0 }}>
        <div className="msg-head">
          <Byline user={m.author_user} agent={m.author_agent} />
          {isQ && <span className={cls("qbadge", m.resolved && "done")}>{m.resolved ? "Resolved" : "Question"}</span>}
          {m.to_target && <span className="to">→ @{m.to_target}</span>}
          {showChannel && (
            <a className="time" href={hrefs.channel(m.channel)}>
              #{m.channel}
            </a>
          )}
          <a className="time" title={fullTime(m.created_at)} href={hrefs.thread(m.channel, m.parent_id || m.id)}>
            {clock(m.created_at)}
          </a>
        </div>
        <Markdown src={m.body} />
        <Reactions target={`m${m.id}`} reactions={m.reactions} />
      </div>
      {!inThread && replyCount > 0 && (
        <button className="thread-link" onClick={openThread}>
          <span className="avs">
            {replyAuthors.map((u) => (
              <Avatar key={u} user={u} size="sm" />
            ))}
          </span>
          {replyCount} {replyCount === 1 ? "reply" : "replies"}
          {lastReply && <span className="muted">· last {clock(lastReply)}</span>}
        </button>
      )}
      <div className="actions" style={picking ? { opacity: 1 } : undefined}>
        {QUICK.slice(0, 2).map((e) => (
          <button key={e} title={`React ${e}`} onClick={() => react(`m${m.id}`, e)}>
            {e}
          </button>
        ))}
        <button title="More reactions" onClick={() => setPicking(true)}>
          <Icon name="smile" size={13} />
        </button>
        {!inThread && (
          <button onClick={openThread} title="Reply in thread (r)">
            <Icon name="reply" size={13} /> Reply
          </button>
        )}
        {isQ && <button onClick={() => setResolved(m, !m.resolved)}>{m.resolved ? "Reopen" : "Resolve"}</button>}
        {!m.parent_id && <button onClick={() => saveToKnowledge(m)}>Save to knowledge</button>}
        <button onClick={() => copyLink(m)} title="Copy link">
          <Icon name="link" size={13} />
        </button>
        {picking && (
          <div style={{ position: "absolute", top: "100%", right: 0, marginTop: 4 }}>
            <EmojiPicker onPick={(e) => react(`m${m.id}`, e)} onClose={() => setPicking(false)} />
          </div>
        )}
      </div>
    </div>
  );
}
