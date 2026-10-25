import { useEffect, useMemo, useRef, useState } from "react";
import { openModal } from "../lib/modal";
import { go, hrefs } from "../lib/route";
import { api, people, toggleNotifications, useBoard } from "../lib/store";
import type { Entry, Message } from "../lib/types";
import { KINDS, cls, debounce, plain } from "../lib/util";
import { ChannelForm, EntryForm, NameForm, ShortcutsHelp } from "./Forms";
import { toggleTheme } from "./Shell";
import { Avatar, Hl, Icon, KindBadge } from "./ui";

interface Item {
  key: string;
  group: string;
  icon: React.ReactNode;
  title: React.ReactNode;
  sub?: React.ReactNode;
  hint?: string;
  text: string; // what the filter matches
  run: () => void;
}

const score = (text: string, q: string) => {
  if (!q) return 1;
  const t = text.toLowerCase();
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.every((w) => t.includes(w))) return 0;
  return words.reduce((s, w) => s + (t.startsWith(w) ? 3 : new RegExp(`\\b${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(t) ? 2 : 1), 0);
};

export function Palette({ onClose }: { onClose: () => void }) {
  const s = useBoard();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const [remote, setRemote] = useState<{ entries: Entry[]; messages: Message[] } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => input.current?.focus(), []);
  const search = useMemo(
    () =>
      debounce((text: string) => {
        if (text.trim().length < 2) return setRemote(null);
        api<{ entries: Entry[]; messages: Message[] }>("GET", `/api/search?q=${encodeURIComponent(text)}&limit=8`).then(setRemote, () => setRemote(null));
      }, 140),
    [],
  );
  useEffect(() => search(q), [q, search]);

  const items = useMemo(() => {
    const run = (f: () => void) => () => {
      onClose();
      f();
    };
    const nav: Item[] = [
      ["Overview", "#/", "grid"],
      ["Since you last looked", "#/digest", "spark"],
      ["Open questions", "#/questions", "question"],
      ["Claims: who's editing what", "#/claims", "lock"],
      ["Pull requests and issues", "#/github", "pr"],
      ["Activity", "#/activity", "pulse"],
      ["All knowledge", "#/knowledge", "doc"],
      ["Tags", "#/tags", "tag"],
      ...Object.entries(KINDS).map(([k, v]) => [`${v.label}s`, `#/knowledge?kind=${k}`, "doc"]),
    ].map(([title, href, icon]) => ({ key: "n" + href, group: "Go to", icon: <Icon name={icon} />, title, text: title, run: run(() => go(href)) }));
    const actions: Item[] = [
      { key: "a-entry", group: "Actions", icon: <Icon name="plus" />, title: "New knowledge entry", hint: "n", text: "new entry knowledge add finding gotcha decision workflow", run: run(() => openModal(<EntryForm />)) },
      { key: "a-channel", group: "Actions", icon: <Icon name="hash" />, title: "New channel", text: "new channel create", run: run(() => openModal(<ChannelForm />)) },
      { key: "a-theme", group: "Actions", icon: <Icon name="theme" />, title: "Toggle light/dark theme", text: "theme dark light toggle", run: run(toggleTheme) },
      { key: "a-notify", group: "Actions", icon: <Icon name="bell" />, title: "Toggle notifications", text: "notifications notify mentions bell", run: run(toggleNotifications) },
      { key: "a-name", group: "Actions", icon: <Icon name="user" />, title: "Change your name", text: "name identity who am i user", run: run(() => openModal(<NameForm />)) },
      { key: "a-keys", group: "Actions", icon: <Icon name="keyboard" />, title: "Keyboard shortcuts", hint: "?", text: "keyboard shortcuts help keys", run: run(() => openModal(<ShortcutsHelp />)) },
    ];
    const channels: Item[] = s.channels.map((c) => ({ key: "c" + c.name, group: "Channels", icon: <Icon name="hash" />, title: c.name, sub: c.topic, text: `#${c.name} ${c.topic}`, run: run(() => go(hrefs.channel(c.name))) }));
    const ppl: Item[] = people(s).flatMap((p) => [
      { key: "u" + p.user, group: "People", icon: <Avatar user={p.user} size="sm" />, title: p.user, sub: `${p.agents.length} agents`, text: p.user, run: run(() => go(hrefs.user(p.user))) },
      ...p.agents.map((a) => ({ key: "g" + a.id, group: "People", icon: <Avatar user={a.user} size="sm" />, title: a.id, sub: a.status || a.branch, text: a.id, run: run(() => go(hrefs.user(a.user))) })),
    ]);
    const entries: Item[] = s.entries.map((e) => ({ key: "e" + e.id, group: "Knowledge", icon: <KindBadge kind={e.kind} />, title: e.title, sub: e.tags.map((t) => "#" + t).join(" "), text: `${e.id} ${e.title} ${e.tags.join(" ")}`, run: run(() => go(hrefs.entry(e.id))) }));
    const tags: Item[] = s.tags.map((t) => ({ key: "t" + t.tag, group: "Tags", icon: <Icon name="tag" />, title: `#${t.tag}`, sub: `${t.count} entries`, text: `#${t.tag} tag`, run: run(() => go(hrefs.tag(t.tag))) }));

    const local = [...nav, ...actions, ...channels, ...entries, ...ppl, ...tags]
      .map((it) => ({ it, sc: score(it.text, q) }))
      .filter((x) => x.sc > 0);
    if (!q) return local.filter((x) => x.it.group === "Go to" || x.it.group === "Actions" || x.it.group === "Channels").map((x) => x.it);
    const byGroup = new Map<string, Item[]>(["Go to", "Actions", "Channels", "Knowledge", "People", "Tags"].map((g) => [g, []]));
    for (const { it } of local.sort((a, b) => b.sc - a.sc)) {
      const g = byGroup.get(it.group) || [];
      if (g.length < (it.group === "Knowledge" ? 4 : 5)) g.push(it);
      byGroup.set(it.group, g);
    }
    const out = [...byGroup.values()].flat();
    const seen = new Set(out.filter((i) => i.group === "Knowledge").map((i) => i.key));
    for (const e of remote?.entries || [])
      if (!seen.has("e" + e.id))
        out.push({
          key: "se" + e.id,
          group: "Search: knowledge",
          icon: <KindBadge kind={e.kind} />,
          title: e.title_hl ? <Hl text={e.title_hl} /> : e.title,
          sub: e.snippet ? <Hl text={e.snippet} /> : undefined,
          text: e.title,
          run: run(() => go(hrefs.entry(e.id))),
        });
    for (const m of remote?.messages || [])
      out.push({
        key: "sm" + m.id,
        group: "Search: messages",
        icon: <Avatar user={m.author_user} size="sm" />,
        title: <Hl text={m.snippet || plain(m.body, 100)} />,
        sub: `#${m.channel} · ${m.author_agent || m.author_user}`,
        text: m.body,
        run: run(() => go(hrefs.thread(m.channel, m.parent_id || m.id))),
      });
    out.push({ key: "all", group: "Search", icon: <Icon name="search" />, title: `Search knowledge for “${q}”`, text: q, run: run(() => go(`#/knowledge?q=${encodeURIComponent(q)}`)) });
    return out;
  }, [s, q, remote, onClose]);

  useEffect(() => setSel(0), [q]);
  useEffect(() => {
    list.current?.querySelector(".opt.on")?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || (e.ctrlKey && e.key === "n")) {
      e.preventDefault();
      setSel((x) => Math.min(x + 1, items.length - 1));
    } else if (e.key === "ArrowUp" || (e.ctrlKey && e.key === "p")) {
      e.preventDefault();
      setSel((x) => Math.max(x - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      items[sel]?.run();
    } else if (e.key === "Escape") onClose();
  };

  let group = "";
  return (
    <div className="palette-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="palette" role="dialog" aria-label="Search and jump">
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} placeholder="Search knowledge and messages, jump to a channel or person, or run a command…" aria-label="Search" />
        <div className="results" ref={list}>
          {items.map((it, i) => {
            const head = it.group !== group ? <div className="group">{it.group}</div> : null;
            group = it.group;
            return (
              <div key={it.key}>
                {head}
                <div className={cls("opt", i === sel && "on")} onMouseEnter={() => setSel(i)} onClick={it.run}>
                  {it.icon}
                  <div className="txt">
                    <div className="t1">{it.title}</div>
                    {it.sub && <div className="t2">{it.sub}</div>}
                  </div>
                  {it.hint && <kbd>{it.hint}</kbd>}
                </div>
              </div>
            );
          })}
          {!items.length && <div className="group">No matches</div>}
        </div>
        <div className="foot">
          <span><kbd>↑</kbd> <kbd>↓</kbd> move</span>
          <span><kbd>↵</kbd> open</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}
