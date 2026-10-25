import { useEffect, useRef, useState, type ReactNode } from "react";
import { closeModal, useModal } from "../lib/modal";
import { go, hrefs } from "../lib/route";
import { api, fail, me, setMe, setToken, toast, token, useBoard } from "../lib/store";
import type { Channel, Entry, EntryKind } from "../lib/types";
import { KINDS, cls } from "../lib/util";
import { Markdown } from "./ui";

export function ModalHost() {
  const node = useModal();
  useEffect(() => {
    if (!node) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && closeModal();
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [node]);
  if (!node) return null;
  return (
    <div className="scrim open" onMouseDown={(e) => e.target === e.currentTarget && closeModal()}>
      <div className="modal" role="dialog" aria-modal="true">
        {node}
      </div>
    </div>
  );
}

function Foot({ children }: { children: ReactNode }) {
  return <div className="modal-foot">{children}</div>;
}

function useAutofocus<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => ref.current?.focus(), []);
  return ref;
}

export function EntryForm({ entry, prefill = {} }: { entry?: Entry; prefill?: Partial<Pick<Entry, "kind" | "title" | "body" | "source">> & { tags?: string[] } }) {
  const allTags = useBoard((s) => s.tags);
  const v = { kind: "finding" as EntryKind, title: "", body: "", tags: [] as string[], source: "", ...entry, ...prefill };
  const [kind, setKind] = useState<EntryKind>(v.kind);
  const [title, setTitle] = useState(v.title);
  const [body, setBody] = useState(v.body);
  const [tags, setTags] = useState(v.tags.join(", "));
  const [source, setSource] = useState(v.source);
  const [supersedes, setSupersedes] = useState("");
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const titleRef = useAutofocus<HTMLInputElement>();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const data = { kind, title, body, tags, source, supersedes: supersedes.split(/[\s,#]+/).filter(Boolean).map(Number) };
      const saved = entry ? await api<Entry>("PATCH", `/api/entries/${entry.id}`, data) : await api<Entry>("POST", "/api/entries", data);
      closeModal();
      toast(entry ? "Saved" : "Added to knowledge");
      go(hrefs.entry(saved.id));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} onKeyDown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && submit(e)}>
      <div className="modal-head">
        <h2>{entry ? "Edit entry" : "New knowledge entry"}</h2>
      </div>
      <div className="modal-body">
        <div className="filters">
          {(Object.keys(KINDS) as EntryKind[]).map((k) => (
            <button type="button" key={k} className={cls("seg", kind === k && "on")} onClick={() => setKind(k)} title={KINDS[k].hint}>
              <span className="dot" style={{ background: KINDS[k].color }} />
              {KINDS[k].label}
            </button>
          ))}
        </div>
        <label className="field">
          Title
          <input ref={titleRef} required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="One line someone could search for" />
        </label>
        <div className="field">
          <div className="row">
            <span className="grow">Details (markdown: tables, ```code```, - [ ] tasks, [[12]] links an entry)</span>
            <div className="tabs">
              <button type="button" className={cls(!preview && "on")} onClick={() => setPreview(false)}>
                Write
              </button>
              <button type="button" className={cls(preview && "on")} onClick={() => setPreview(true)}>
                Preview
              </button>
            </div>
          </div>
          {preview ? (
            <div className="preview">{body.trim() ? <Markdown src={body} /> : <span className="muted">Nothing to preview</span>}</div>
          ) : (
            <textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="What, why, and how to apply it" />
          )}
        </div>
        <label className="field">
          Tags
          <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="vision, aruco" list="board-tags" />
          <datalist id="board-tags">
            {allTags.map((t) => (
              <option key={t.tag} value={tags.replace(/[^,]*$/, (m) => (m.trim() ? " " : "") + t.tag).replace(/^ /, "")} />
            ))}
          </datalist>
        </label>
        <div className="row wrap" style={{ gap: 12 }}>
          <label className="field grow">
            Source
            <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="PR #65, engine/sim/fire.py" />
          </label>
          {!entry && (
            <label className="field grow">
              Supersedes entries
              <input value={supersedes} onChange={(e) => setSupersedes(e.target.value)} placeholder="e.g. 12, 18" />
            </label>
          )}
        </div>
      </div>
      <Foot>
        <span className="grow small muted">⌘↵ to save</span>
        <button type="button" className="btn" onClick={closeModal}>
          Cancel
        </button>
        <button className="btn primary" disabled={busy || !title.trim()}>
          {entry ? "Save" : "Add entry"}
        </button>
      </Foot>
    </form>
  );
}

export function ChannelForm({ channel }: { channel?: Channel }) {
  const [name, setName] = useState(channel?.name || "");
  const [topic, setTopic] = useState(channel?.topic || "");
  const [ttl, setTtl] = useState(String(channel ? channel.ttl_hours : 24));
  const ref = useAutofocus<HTMLInputElement>();
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      const c = channel
        ? await api<Channel>("PATCH", `/api/channels/${encodeURIComponent(channel.name)}`, { topic, ...(channel.name === "general" ? {} : { ttl_hours: +ttl }) })
        : await api<Channel>("POST", "/api/channels", { name, topic, ttl_hours: +ttl });
      closeModal();
      go(hrefs.channel(c.name));
    } catch (err) {
      fail(err);
    }
  }
  return (
    <form onSubmit={submit}>
      <div className="modal-head">
        <h2>{channel ? `#${channel.name} settings` : "New channel"}</h2>
      </div>
      <div className="modal-body">
        {!channel && (
          <label className="field">
            Name
            <input ref={ref} required pattern="[a-z0-9][a-z0-9_\-]*" value={name} onChange={(e) => setName(e.target.value.toLowerCase())} placeholder="protocol-change" />
          </label>
        )}
        <label className="field">
          Topic
          <input ref={channel ? ref : undefined} value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="What it's for" />
        </label>
        {channel?.name !== "general" && (
          <label className="field">
            Expires after
            <select value={ttl} onChange={(e) => setTtl(e.target.value)}>
              <option value="4">4 hours quiet</option>
              <option value="24">24 hours quiet</option>
              <option value="72">3 days quiet</option>
              <option value="168">A week quiet</option>
              <option value="0">Never</option>
              {!["4", "24", "72", "168", "0"].includes(ttl) && <option value={ttl}>{ttl} hours quiet</option>}
            </select>
          </label>
        )}
      </div>
      <Foot>
        <span className="grow" />
        <button type="button" className="btn" onClick={closeModal}>
          Cancel
        </button>
        <button className="btn primary">{channel ? "Save" : "Create"}</button>
      </Foot>
    </form>
  );
}

export function NameForm() {
  const [v, setV] = useState(me());
  const ref = useAutofocus<HTMLInputElement>();
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setMe(v);
        closeModal();
      }}
    >
      <div className="modal-head">
        <h2>Who are you?</h2>
        <div className="ttl">Use your GitHub login so your posts line up with your agents.</div>
      </div>
      <div className="modal-body">
        <label className="field">
          Name
          <input ref={ref} required value={v} onChange={(e) => setV(e.target.value)} placeholder="jayson-clark" />
        </label>
      </div>
      <Foot>
        <span className="grow" />
        <button className="btn primary">Save</button>
      </Foot>
    </form>
  );
}

export function TokenForm() {
  const [v, setV] = useState(token());
  const ref = useAutofocus<HTMLInputElement>();
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setToken(v);
        closeModal();
      }}
    >
      <div className="modal-head">
        <h2>Board token</h2>
        <div className="ttl">This board needs a token to post: the shared BOARD_TOKEN, or your personal one from `board.py token`.</div>
      </div>
      <div className="modal-body">
        <label className="field">
          Token
          <input ref={ref} type="password" required value={v} onChange={(e) => setV(e.target.value)} />
        </label>
      </div>
      <Foot>
        <span className="grow" />
        <button className="btn primary">Save</button>
      </Foot>
    </form>
  );
}

export const SHORTCUTS: [string[], string][] = [
  [["⌘", "K"], "Search and jump anywhere"],
  [["/"], "Search"],
  [["g", "o"], "Overview"],
  [["g", "d"], "Digest: since you last looked"],
  [["g", "q"], "Open questions"],
  [["g", "k"], "Knowledge"],
  [["g", "c"], "Claims"],
  [["g", "p"], "Pull requests and issues"],
  [["g", "a"], "Activity"],
  [["j"], "Next message (in a channel)"],
  [["k"], "Previous message"],
  [["r"], "Reply to the selected message"],
  [["e"], "React ✅ to the selected message"],
  [["c"], "Focus the message box"],
  [["n"], "New knowledge entry"],
  [["Esc"], "Close a thread, dialog or palette"],
  [["?"], "This list"],
];

export function ShortcutsHelp() {
  return (
    <>
      <div className="modal-head">
        <h2>Keyboard shortcuts</h2>
      </div>
      <div className="modal-body">
        <div className="keys">
          {SHORTCUTS.map(([keys, label]) => (
            <div key={label} style={{ display: "contents" }}>
              <span className="combo">
                {keys.map((k) => (
                  <kbd key={k}>{k}</kbd>
                ))}
              </span>
              <span>{label}</span>
            </div>
          ))}
        </div>
      </div>
      <Foot>
        <span className="grow" />
        <button className="btn primary" onClick={closeModal}>
          Done
        </button>
      </Foot>
    </>
  );
}
