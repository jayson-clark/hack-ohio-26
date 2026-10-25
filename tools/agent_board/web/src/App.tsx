import { useEffect, useState } from "react";
import { ChannelForm, EntryForm, ModalHost, NameForm, ShortcutsHelp, TokenForm } from "./components/Forms";
import { Palette } from "./components/Palette";
import { Rail, Sidebar } from "./components/Shell";
import { Icon } from "./components/ui";
import { setRepo } from "./lib/markdown";
import { modalOpen, openModal } from "./lib/modal";
import { go, useRoute, type Route } from "./lib/route";
import { useBoard } from "./lib/store";
import { KINDS, cls, expiresIn } from "./lib/util";
import type { EntryKind } from "./lib/types";
import { ChannelView, ThreadPanel } from "./views/Channel";
import { DigestView, Overview } from "./views/Dashboard";
import { EntryPage, KnowledgeView, TagsView } from "./views/Knowledge";
import { ActivityView, ClaimsView, GitHubView, PersonView, QuestionsView } from "./views/Work";

function Title({ r }: { r: Route }) {
  const channel = useBoard((s) => s.channels.find((c) => c.name === r.arg));
  const entry = useBoard((s) => (r.view === "e" ? s.entries.find((e) => e.id === Number(r.arg)) : undefined));
  let h: React.ReactNode = null;
  let desc: React.ReactNode = null;
  switch (r.view) {
    case "overview":
      h = "Overview";
      desc = "What every agent is doing and asking, live.";
      break;
    case "digest":
      h = "Since you last looked";
      desc = "Merges, knowledge, questions and what agents did.";
      break;
    case "questions":
      h = "Questions";
      desc = "Open questions, oldest first. Answer what you can.";
      break;
    case "claims":
      h = "Claims";
      desc = "Who's editing what, so nobody clobbers anyone.";
      break;
    case "github":
      h = "PRs and issues";
      desc = "Open work on GitHub, matched to the agents on each branch.";
      break;
    case "activity":
      h = "Activity";
      desc = "Joins, status changes, claims and PRs.";
      break;
    case "knowledge": {
      const k = r.params.get("kind") as EntryKind | null;
      const tag = r.params.get("tag");
      h = k ? KINDS[k]?.label + "s" : tag ? `#${tag}` : "Knowledge";
      desc = k ? KINDS[k]?.hint : "Persistent findings, workflows, decisions and gotchas.";
      break;
    }
    case "tags":
      h = "Tags";
      break;
    case "e":
      h = <span className="ellipsis">{entry ? entry.title : `Entry #${r.arg}`}</span>;
      desc = (
        <a href="#/knowledge" className="muted">
          ← Knowledge
        </a>
      );
      break;
    case "c":
      h = (
        <>
          <span style={{ color: "var(--muted)" }}>#</span>
          {r.arg}
          {channel ? (
            <button className="pill" style={{ border: 0 }} title="Channel settings" onClick={() => openModal(<ChannelForm channel={channel} />)}>
              {channel.expires_at ? expiresIn(channel.expires_at) : "permanent"}
            </button>
          ) : (
            <span className="pill">expired</span>
          )}
        </>
      );
      desc = channel?.topic;
      break;
    case "u":
      h = r.arg;
      desc = "Agents, timeline and posts";
      break;
    default:
      h = "Not found";
  }
  return (
    <div className="title">
      <h2>{h}</h2>
      {desc && <div className="desc">{desc}</div>}
    </div>
  );
}

function Content({ r }: { r: Route }) {
  switch (r.view) {
    case "overview":
      return <div className="content"><Overview /></div>;
    case "digest":
      return <div className="content"><DigestView /></div>;
    case "questions":
      return <div className="content"><QuestionsView /></div>;
    case "claims":
      return <div className="content"><ClaimsView /></div>;
    case "github":
      return <div className="content"><GitHubView /></div>;
    case "activity":
      return <div className="content"><ActivityView /></div>;
    case "knowledge":
      return <div className="content"><KnowledgeView key={r.params.toString()} params={r.params} /></div>;
    case "tags":
      return <div className="content"><TagsView /></div>;
    case "e":
      return <div className="content"><EntryPage id={Number(r.arg)} /></div>;
    case "c":
      return <ChannelView name={r.arg} />;
    case "u":
      return <div className="content"><PersonView user={r.arg} /></div>;
    default:
      return <div className="content"><div className="pad">Nothing at {r.hash}. <a href="#/">Go to the overview</a>.</div></div>;
  }
}

function Toasts() {
  const toasts = useBoard((s) => s.toasts);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) =>
        t.href ? (
          <a key={t.id} className="t" href={t.href}>
            {t.text}
          </a>
        ) : (
          <div key={t.id} className="t">
            {t.text}
          </div>
        ),
      )}
    </div>
  );
}

const CHORDS: Record<string, string> = { o: "#/", d: "#/digest", q: "#/questions", k: "#/knowledge", c: "#/claims", p: "#/github", a: "#/activity", t: "#/tags" };

export function App() {
  const r = useRoute();
  const connected = useBoard((s) => s.connected);
  const loaded = useBoard((s) => s.loaded);
  const prompt = useBoard((s) => s.prompt);
  const repo = useBoard((s) => s.repo);
  const openQ = useBoard((s) => s.openQuestions.length);
  const [palette, setPalette] = useState(false);
  const [menu, setMenu] = useState(false);

  useEffect(() => setRepo(repo), [repo]);
  useEffect(() => {
    if (prompt === "name") openModal(<NameForm />);
    if (prompt === "token") openModal(<TokenForm />);
  }, [prompt]);
  useEffect(() => {
    document.title = openQ ? `(${openQ}) Agent Board` : "Agent Board";
  }, [openQ]);
  useEffect(() => setMenu(false), [r.hash]);

  useEffect(() => {
    let chord = 0;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
        return;
      }
      const typing = /INPUT|TEXTAREA|SELECT/.test((e.target as HTMLElement).tagName) || (e.target as HTMLElement).isContentEditable;
      if (typing || e.metaKey || e.ctrlKey || e.altKey || modalOpen() || palette) return;
      if (chord && Date.now() - chord < 1200 && CHORDS[e.key]) {
        e.preventDefault();
        chord = 0;
        go(CHORDS[e.key]);
        return;
      }
      chord = 0;
      if (e.key === "g") chord = Date.now();
      else if (e.key === "/") {
        e.preventDefault();
        setPalette(true);
      } else if (e.key === "?") openModal(<ShortcutsHelp />);
      else if (e.key === "n") {
        e.preventDefault();
        openModal(<EntryForm />);
      } else if (e.key === "c") {
        const ta = document.querySelector<HTMLTextAreaElement>(".thread .composer textarea") || document.querySelector<HTMLTextAreaElement>(".main .composer textarea");
        if (ta) {
          e.preventDefault();
          ta.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [palette]);

  const thread = r.view === "c" && r.thread ? r.thread : null;
  return (
    <>
      <div className={cls("app", thread && "with-thread")}>
        <Sidebar r={r} open={menu} onClose={() => setMenu(false)} />
        <main className="main">
          <header className="topbar">
            <button className="iconbtn menu-btn" onClick={() => setMenu(true)} aria-label="Menu">
              <Icon name="menu" size={16} />
            </button>
            <Title r={r} />
            <button className="searchbtn" onClick={() => setPalette(true)} aria-label="Search">
              <Icon name="search" size={14} />
              <span className="label">Search or jump…</span>
              <span className="k">⌘K</span>
            </button>
            <span className="live">
              <span className={cls("presence", connected && "on")} />
              {connected ? "Live" : loaded ? "Reconnecting…" : "Connecting"}
            </span>
          </header>
          <Content r={r} />
        </main>
        {thread ? <ThreadPanel key={thread} channel={r.arg} id={thread} /> : <Rail />}
      </div>
      {palette && <Palette onClose={() => setPalette(false)} />}
      <ModalHost />
      <Toasts />
    </>
  );
}
