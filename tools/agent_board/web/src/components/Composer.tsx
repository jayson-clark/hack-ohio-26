import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { openModal } from "../lib/modal";
import { api, fail, me, toast, useBoard } from "../lib/store";
import type { EntryKind } from "../lib/types";
import { cls, store } from "../lib/util";
import { EntryForm, ShortcutsHelp } from "./Forms";
import { Markdown } from "./ui";

interface Option {
  insert: string;
  label: string;
  detail?: string;
}

const COMMANDS: { name: string; args: string; detail: string }[] = [
  { name: "ask", args: "<question>", detail: "Post as a question (tracked until resolved)" },
  { name: "finding", args: "<title>", detail: "Save a finding to knowledge" },
  { name: "workflow", args: "<title>", detail: "Save a workflow to knowledge" },
  { name: "decision", args: "<title>", detail: "Save a decision to knowledge" },
  { name: "gotcha", args: "<title>", detail: "Save a gotcha to knowledge" },
  { name: "claim", args: "<path> [path…]", detail: "Claim files you're editing, as yourself" },
  { name: "release", args: "[path…]", detail: "Release your claims" },
  { name: "keys", args: "", detail: "Keyboard shortcuts" },
];

export interface SendOpts {
  question: boolean;
  resolve: boolean;
}

export function Composer({
  draftKey,
  placeholder,
  onSend,
  allowQuestion = true,
  canResolve = false,
  onCancel,
  autoFocus = false,
  banner,
}: {
  draftKey: string;
  placeholder: string;
  onSend: (text: string, opts: SendOpts) => Promise<unknown>;
  allowQuestion?: boolean;
  canResolve?: boolean;
  onCancel?: () => void;
  autoFocus?: boolean;
  banner?: React.ReactNode;
}) {
  const [text, setText] = useState(() => store.get<string>("draft:" + draftKey, ""));
  const [question, setQuestion] = useState(false);
  const [resolve, setResolve] = useState(false);
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState(0);
  const [caret, setCaret] = useState(0);
  const ta = useRef<HTMLTextAreaElement>(null);
  const agents = useBoard((s) => s.agents);
  const entries = useBoard((s) => s.entries);

  useEffect(() => {
    setText(store.get<string>("draft:" + draftKey, ""));
    setQuestion(false);
    setResolve(false);
    setPreview(false);
  }, [draftKey]);
  useEffect(() => store.set("draft:" + draftKey, text), [draftKey, text]);
  useEffect(() => {
    if (autoFocus) ta.current?.focus();
  }, [autoFocus, draftKey]);
  useEffect(() => {
    const t = ta.current;
    if (!t) return;
    t.style.height = "auto";
    t.style.height = Math.min(t.scrollHeight, 240) + "px";
  }, [text, preview]);

  const people = useMemo(() => {
    const ids = new Set<string>();
    for (const a of agents) {
      ids.add(a.user);
      ids.add(a.id);
    }
    for (const e of entries) ids.add(e.author_user);
    ids.delete("github");
    return [...ids].sort();
  }, [agents, entries]);

  // What the caret is in the middle of: an @mention, a /command at the start, or [[entry
  const before = text.slice(0, caret);
  const mention = before.match(/(?:^|[\s(])@([\w/-]*)$/);
  const slash = text.startsWith("/") && !text.includes("\n") && !/\s/.test(before) ? before.slice(1) : null;
  const entryRef = before.match(/\[\[([^\]\n]*)$/);
  let options: Option[] = [];
  let replaceFrom = caret;
  if (mention) {
    const q = mention[1].toLowerCase();
    options = people
      .filter((p) => p.toLowerCase().includes(q))
      .slice(0, 8)
      .map((p) => ({ insert: "@" + p + " ", label: "@" + p, detail: p.includes("/") ? agents.find((a) => a.id === p)?.status : "person" }));
    replaceFrom = caret - mention[1].length - 1;
  } else if (slash !== null) {
    options = COMMANDS.filter((c) => c.name.startsWith(slash.toLowerCase())).map((c) => ({
      insert: "/" + c.name + " ",
      label: `/${c.name} ${c.args}`,
      detail: c.detail,
    }));
    replaceFrom = 0;
  } else if (entryRef) {
    const q = entryRef[1].toLowerCase();
    options = entries
      .filter((e) => !q || e.title.toLowerCase().includes(q) || String(e.id) === q)
      .slice(0, 8)
      .map((e) => ({ insert: `[[${e.id}]] `, label: `[[${e.id}]] ${e.title}`, detail: e.kind }));
    replaceFrom = caret - entryRef[1].length - 2;
  }
  const showOptions = options.length > 0 && !preview && document.activeElement === ta.current;

  // Where to put the caret after the next render (setting it in rAF races with fast typing).
  const pendingCaret = useRef<number | null>(null);
  useLayoutEffect(() => {
    const pos = pendingCaret.current;
    if (pos === null || !ta.current) return;
    pendingCaret.current = null;
    ta.current.focus();
    ta.current.setSelectionRange(pos, pos);
  }, [text]);

  function pick(o: Option) {
    const next = text.slice(0, replaceFrom) + o.insert + text.slice(caret);
    const pos = replaceFrom + o.insert.length;
    pendingCaret.current = pos;
    setText(next);
    setCaret(pos);
    setSel(0);
  }

  async function runCommand(raw: string): Promise<boolean> {
    const m = raw.match(/^\/(\w+)\s*([\s\S]*)$/);
    if (!m) return false;
    const [, cmd, rest] = m;
    if (cmd === "ask") {
      if (!rest.trim()) return true;
      await onSend(rest.trim(), { question: true, resolve: false });
      return true;
    }
    if (["finding", "workflow", "decision", "gotcha"].includes(cmd)) {
      const [title, ...body] = rest.split("\n");
      openModal(<EntryForm prefill={{ kind: cmd as EntryKind, title: title.trim(), body: body.join("\n").trim() }} />);
      return true;
    }
    if (cmd === "claim" || cmd === "release") {
      const paths = rest.split(/[\s,]+/).filter(Boolean);
      if (cmd === "claim" && !paths.length) return true;
      const r = await api<{ conflicts: { wanted: string; path: string; agent_id: string }[] }>(
        "POST",
        cmd === "claim" ? "/api/claims" : "/api/claims/release",
        cmd === "claim" ? { paths, note: "from the web UI" } : { paths },
      );
      if (cmd === "claim" && r.conflicts?.length) toast(`Claimed, but ${r.conflicts.map((c) => `${c.wanted} overlaps ${c.agent_id}'s ${c.path}`).join("; ")}`, "#/claims");
      else toast(cmd === "claim" ? `Claimed ${paths.join(", ")}` : "Released", "#/claims");
      return true;
    }
    if (cmd === "keys" || cmd === "help") {
      openModal(<ShortcutsHelp />);
      return true;
    }
    return false;
  }

  async function send() {
    const body = text.trim();
    if (!body || busy) return;
    if (!me()) {
      fail(new Error("Set your name first (bottom left)"));
      return;
    }
    setBusy(true);
    try {
      if (!(body.startsWith("/") && (await runCommand(body)))) await onSend(body, { question, resolve });
      setText("");
      setQuestion(false);
      setResolve(false);
      setPreview(false);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (showOptions) {
      if (e.key === "ArrowDown" || (e.key === "n" && e.ctrlKey)) {
        e.preventDefault();
        setSel((s) => (s + 1) % options.length);
        return;
      }
      if (e.key === "ArrowUp" || (e.key === "p" && e.ctrlKey)) {
        e.preventDefault();
        setSel((s) => (s - 1 + options.length) % options.length);
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey && !(slash !== null && COMMANDS.some((c) => "/" + c.name === text.trim())))) {
        e.preventDefault();
        pick(options[Math.min(sel, options.length - 1)]);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    } else if (e.key === "Escape") {
      if (onCancel) onCancel();
      else ta.current?.blur();
    }
  }

  return (
    <div className="composer">
      <div className="composer-box">
        {banner}
        {showOptions && (
          <div className="suggest" role="listbox">
            {options.map((o, i) => (
              <div key={o.insert + i} className={cls("opt", i === sel && "on")} onMouseDown={(e) => (e.preventDefault(), pick(o))} role="option" aria-selected={i === sel}>
                <span>{o.label}</span>
                {o.detail && <span className="d">{o.detail}</span>}
              </div>
            ))}
          </div>
        )}
        {preview ? (
          <div className="preview" onClick={() => setPreview(false)}>
            {text.trim() ? <Markdown src={text} /> : <span className="muted">Nothing to preview</span>}
          </div>
        ) : (
          <textarea
            ref={ta}
            rows={1}
            value={text}
            placeholder={placeholder}
            onChange={(e) => {
              setText(e.target.value);
              setCaret(e.target.selectionStart);
              setSel(0);
            }}
            onSelect={(e) => setCaret((e.target as HTMLTextAreaElement).selectionStart)}
            onKeyDown={onKey}
            onBlur={() => setTimeout(() => setCaret((c) => c), 0)}
            aria-label={placeholder}
          />
        )}
        <div className="composer-row">
          <div className="tabs">
            <button type="button" className={cls(!preview && "on")} onClick={() => setPreview(false)}>
              Write
            </button>
            <button type="button" className={cls(preview && "on")} onClick={() => setPreview(true)}>
              Preview
            </button>
          </div>
          {allowQuestion && (
            <label className="toggle">
              <input type="checkbox" checked={question} onChange={(e) => setQuestion(e.target.checked)} /> Ask as a question
            </label>
          )}
          {canResolve && (
            <label className="toggle">
              <input type="checkbox" checked={resolve} onChange={(e) => setResolve(e.target.checked)} /> Mark resolved
            </label>
          )}
          <span className="grow hint">{me() ? <>Markdown · <b>@</b> mention · <b>/</b> commands · <b>[[</b> link knowledge</> : "Set your name to post"}</span>
          <button className="btn primary" disabled={!text.trim() || busy} onClick={send}>
            {busy ? "Sending…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
