// The board's client state: loaded from /api/state, kept live by /api/events (SSE).
// Components read it with useBoard() and change it only through api() calls;
// the server's events come back and update everything.

import { useRef, useSyncExternalStore } from "react";
import type { Activity, Agent, BoardEvent, BoardState, Channel, Claim, Entry, GitHub, Message, Reactions } from "./types";
import { now, setSkew, store } from "./util";

export type FeedItem =
  | { key: string; kind: "entry" | "entry-update"; item: Entry; at: number }
  | { key: string; kind: "message"; item: Message; at: number }
  | { key: string; kind: "agent" | "status"; item: Agent; at: number }
  | { key: string; kind: "activity"; item: Activity; at: number }
  | { key: string; kind: "expired"; item: { name: string }; at: number };

export interface Toast {
  id: number;
  text: string;
  href?: string;
}

export interface State {
  loaded: boolean;
  connected: boolean;
  agents: Agent[];
  channels: Channel[];
  entries: Entry[];
  recent: Message[];
  openQuestions: Message[];
  claims: Claim[];
  activity: Activity[];
  tags: { tag: string; count: number }[];
  github: GitHub | null;
  repo: string;
  /** channel -> every message in it (top-level and replies), oldest first */
  messages: Record<string, Message[]>;
  feed: FeedItem[];
  /** ids ("m12", "e4") that just changed, for a flash animation */
  flash: Set<string>;
  toasts: Toast[];
  prompt: null | "name" | "token";
  /** bumped every 30 s so "5m ago" stays fresh */
  tick: number;
}

let S: State = {
  loaded: false,
  connected: false,
  agents: [],
  channels: [],
  entries: [],
  recent: [],
  openQuestions: [],
  claims: [],
  activity: [],
  tags: [],
  github: null,
  repo: "jayson-clark/hack-ohio-26",
  messages: {},
  feed: [],
  flash: new Set(),
  toasts: [],
  prompt: null,
  tick: 0,
};

const listeners = new Set<() => void>();
function set(patch: Partial<State> | ((s: State) => Partial<State>)) {
  S = { ...S, ...(typeof patch === "function" ? patch(S) : patch) };
  for (const l of listeners) l();
}
export const getState = () => S;
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
export function useBoard(): State;
export function useBoard<T>(pick: (s: State) => T): T;
export function useBoard<T>(pick?: (s: State) => T) {
  // Selectors may build new arrays; cache the result per state and selector so React sees a stable snapshot.
  const cache = useRef<{ s?: State; pick?: unknown; v?: unknown }>({});
  return useSyncExternalStore(subscribe, () => {
    if (!pick) return S;
    const c = cache.current;
    if (c.s !== S || c.pick !== pick) Object.assign(c, { s: S, pick, v: pick(S) });
    return c.v as T;
  });
}

// --- identity -----------------------------------------------------------------

export const me = () => store.get<string>("user", new URLSearchParams(location.search).get("user") || "");
export const token = () => store.get<string>("token", "");
export function setMe(name: string) {
  store.set("user", name.trim());
  set({ prompt: null });
}
export function setToken(t: string) {
  store.set("token", t.trim());
  set({ prompt: null });
}
export const askFor = (prompt: State["prompt"]) => set({ prompt });

// --- api ----------------------------------------------------------------------

export class ApiError extends Error {}

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (method !== "GET") {
    if (!me()) {
      askFor("name");
      throw new ApiError("Set your name first");
    }
    headers["X-Board-User"] = me();
    if (token()) headers["X-Board-Token"] = token();
  }
  const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401) {
    askFor("token");
    throw new ApiError(data.error || "unauthorized");
  }
  if (!r.ok) throw new ApiError(data.error || r.statusText);
  return data as T;
}

let toastId = 0;
export function toast(text: string, href?: string) {
  const t = { id: ++toastId, text, href };
  set((s) => ({ toasts: [...s.toasts.slice(-3), t] }));
  setTimeout(() => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== t.id) })), 3200);
}
export const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e));

// --- loading --------------------------------------------------------------------

export async function load() {
  const s = await api<BoardState>("GET", "/api/state");
  setSkew(s.now - Date.now() / 1000);
  const first = !S.loaded;
  set({
    loaded: true,
    agents: s.agents,
    channels: s.channels,
    entries: s.entries,
    recent: s.recent,
    openQuestions: s.open_questions,
    claims: s.claims,
    activity: s.activity,
    tags: s.tags,
    github: s.github,
    repo: s.github?.repo || s.repo || S.repo,
    feed: first || !S.feed.length ? initialFeed(s) : S.feed,
  });
  if (!store.get("visited", false)) {
    for (const c of s.channels) store.set("read:" + c.name, s.now);
    store.set("visited", true);
    store.set("lastVisit", s.now);
  }
}

function initialFeed(s: BoardState): FeedItem[] {
  const items: FeedItem[] = [
    ...s.recent.map((m): FeedItem => ({ key: "m" + m.id, kind: "message", item: m, at: m.created_at })),
    ...s.entries.slice(0, 40).map((e): FeedItem => ({ key: "e" + e.id, kind: "entry", item: e, at: e.created_at })),
    ...s.activity
      .filter((a) => a.kind !== "entry" && a.kind !== "question")
      .map((a): FeedItem => ({ key: activityKey(a), kind: "activity", item: a, at: a.created_at })),
  ];
  const seen = new Set<string>();
  return items
    .sort((a, b) => b.at - a.at)
    .filter((x) => !seen.has(x.key) && !!seen.add(x.key))
    .slice(0, 150);
}

const loading = new Set<string>();
export async function loadChannel(name: string, before?: number) {
  const key = name + (before || "");
  if (loading.has(key)) return;
  loading.add(key);
  try {
    const q = before ? `?before=${before}&limit=300` : "";
    const rows = await api<Message[]>("GET", `/api/channels/${encodeURIComponent(name)}/messages${q}`);
    set((s) => {
      const have = before ? s.messages[name] || [] : [];
      const ids = new Set(have.map((m) => m.id));
      const merged = [...rows.filter((m) => !ids.has(m.id)), ...have].sort((a, b) => a.created_at - b.created_at);
      return { messages: { ...s.messages, [name]: merged } };
    });
  } catch (e) {
    set((s) => ({ messages: { ...s.messages, [name]: s.messages[name] || [] } }));
    fail(e);
  } finally {
    loading.delete(key);
  }
}

// --- live events ------------------------------------------------------------------

function upsert<T>(list: T[], item: T, key: (x: T) => unknown, front = true): T[] {
  const k = key(item);
  const i = list.findIndex((x) => key(x) === k);
  if (i >= 0) {
    const copy = list.slice();
    copy[i] = item;
    return copy;
  }
  return front ? [item, ...list] : [...list, item];
}

function pushFeed(feed: FeedItem[], item: FeedItem) {
  return [item, ...feed.filter((x) => x.key !== item.key)].slice(0, 250);
}

// An agent's newer status replaces its older one in the feed.
const activityKey = (a: Activity) => (a.kind === "status" ? "s:" + a.agent_id : "a" + a.id);

function flash(key: string) {
  S.flash.add(key);
  setTimeout(() => {
    S.flash.delete(key);
    set({});
  }, 1700);
}

function patchReactions(target: string, reactions: Reactions) {
  const id = Number(target.slice(1));
  if (target[0] === "e") {
    set((s) => ({ entries: s.entries.map((e) => (e.id === id ? { ...e, reactions } : e)) }));
    entryListeners.forEach((l) => l(id));
    return;
  }
  const fix = (list: Message[]) => list.map((m) => (m.id === id ? { ...m, reactions } : m));
  set((s) => ({
    recent: fix(s.recent),
    openQuestions: fix(s.openQuestions),
    messages: Object.fromEntries(Object.entries(s.messages).map(([k, v]) => [k, fix(v)])),
  }));
}

/** Pages that fetched an entry themselves (history, votes) refresh when it changes. */
export const entryListeners = new Set<(id: number) => void>();

function onEvent(ev: BoardEvent) {
  switch (ev.type) {
    case "entry": {
      const d = ev.data;
      const fresh = !S.entries.some((e) => e.id === d.id);
      set((s) => ({
        entries: d.archived ? s.entries.filter((e) => e.id !== d.id) : upsert(s.entries, d, (e) => e.id).sort((a, b) => b.updated_at - a.updated_at),
        feed: pushFeed(s.feed, { key: "e" + d.id + (fresh ? "" : ":" + ev.at), kind: fresh ? "entry" : "entry-update", item: d, at: ev.at }),
      }));
      flash("e" + d.id);
      entryListeners.forEach((l) => l(d.id));
      break;
    }
    case "message": {
      const d = ev.data;
      const fresh = !S.recent.some((m) => m.id === d.id) && !(S.messages[d.channel] || []).some((m) => m.id === d.id);
      set((s) => {
        const ch = s.messages[d.channel];
        const isOpen = d.kind === "question" && !d.resolved && !d.parent_id;
        return {
          recent: upsert(s.recent, d, (m) => m.id).slice(0, 200),
          messages: ch ? { ...s.messages, [d.channel]: upsert(ch, d, (m) => m.id, false) } : s.messages,
          openQuestions: isOpen ? upsert(s.openQuestions, d, (m) => m.id) : s.openQuestions.filter((m) => m.id !== d.id),
          feed: fresh ? pushFeed(s.feed, { key: "m" + d.id, kind: "message", item: d, at: ev.at }) : s.feed,
        };
      });
      if (fresh) {
        flash("m" + d.id);
        notifyIfForMe(d);
      }
      break;
    }
    case "channel":
      set((s) => ({ channels: upsert(s.channels, ev.data, (c) => c.name) }));
      break;
    case "channel_expired":
      set((s) => {
        const messages = { ...s.messages };
        delete messages[ev.data.name];
        return {
          channels: s.channels.filter((c) => c.name !== ev.data.name),
          messages,
          openQuestions: s.openQuestions.filter((m) => m.channel !== ev.data.name),
          feed: pushFeed(s.feed, { key: "x" + ev.data.name, kind: "expired", item: ev.data, at: ev.at }),
        };
      });
      break;
    case "agent": {
      const d = ev.data;
      const fresh = !S.agents.some((a) => a.id === d.id);
      set((s) => ({ agents: upsert(s.agents, d, (a) => a.id) }));
      if (fresh) set((s) => ({ feed: pushFeed(s.feed, { key: "g" + d.id, kind: "agent", item: d, at: ev.at }) }));
      break;
    }
    case "activity": {
      const a = ev.data;
      set((s) => ({
        activity: [a, ...s.activity].slice(0, 400),
        // entries and questions already show up as their own feed items
        feed: a.kind === "entry" || a.kind === "question" || a.kind === "joined" ? s.feed : pushFeed(s.feed, { key: activityKey(a), kind: "activity", item: a, at: a.created_at }),
      }));
      break;
    }
    case "reaction":
      patchReactions(ev.data.target, ev.data.reactions);
      break;
    case "claims":
      set((s) => ({ claims: [...s.claims.filter((c) => c.agent_id !== ev.data.agent_id), ...ev.data.claims] }));
      break;
    case "claim_conflict": {
      const d = ev.data;
      const mine = me();
      if (mine && (d.held_by === mine || d.held_by.startsWith(mine + "/")))
        toast(`${d.agent_id} is editing ${d.path}, which overlaps your claim on ${d.held_path}`, "#/claims");
      break;
    }
    case "github":
      set({ github: ev.data, repo: ev.data.repo || S.repo });
      break;
  }
}

let es: EventSource | null = null;
export function connect() {
  es?.close();
  es = new EventSource("/api/events");
  es.onopen = () => {
    set({ connected: true });
    load().catch(fail);
    for (const k of Object.keys(S.messages)) loadChannel(k);
  };
  es.onmessage = (m) => {
    try {
      onEvent(JSON.parse(m.data));
    } catch (e) {
      console.error(e);
    }
  };
  es.onerror = () => set({ connected: false });
  setInterval(() => set((s) => ({ tick: s.tick + 1 })), 30_000);
}

// --- notifications --------------------------------------------------------------------

export function mentionsMe(m: Message, user = me()) {
  if (!user) return false;
  if (m.to_target === user || m.to_target.startsWith(user + "/")) return true;
  return new RegExp(`(^|[^\\w])@${user.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\w-])`).test(m.body);
}

function repliesToMe(m: Message, user: string) {
  if (!m.parent_id) return false;
  const parent = S.recent.find((x) => x.id === m.parent_id) || Object.values(S.messages).flat().find((x) => x.id === m.parent_id);
  return !!parent && parent.author_user === user && !parent.author_agent;
}

export const notificationsOn = () => store.get("notify", false) && "Notification" in window && Notification.permission === "granted";

export async function toggleNotifications() {
  if (!("Notification" in window)) return toast("This browser can't show notifications");
  if (notificationsOn()) {
    store.set("notify", false);
    set({});
    return toast("Notifications off");
  }
  const p = await Notification.requestPermission();
  store.set("notify", p === "granted");
  set({});
  toast(p === "granted" ? "You'll be notified when someone mentions you" : "Notifications are blocked for this site");
}

function notifyIfForMe(m: Message) {
  const user = me();
  if (!user || (m.author_user === user && !m.author_agent)) return;
  if (!mentionsMe(m, user) && !repliesToMe(m, user)) return;
  const href = `#/c/${encodeURIComponent(m.channel)}/t/${m.parent_id || m.id}`;
  const by = m.author_agent ? `${m.author_user}/${m.author_agent}` : m.author_user;
  if (document.hidden && notificationsOn()) {
    const n = new Notification(`${by} in #${m.channel}`, { body: m.body.slice(0, 180), tag: "m" + m.id });
    n.onclick = () => {
      window.focus();
      location.hash = href;
    };
  } else if (!document.hidden) toast(`${by} mentioned you in #${m.channel}`, href);
  store.set("unseenMentions", store.get<number>("unseenMentions", 0) + 1);
}

// --- small derived helpers --------------------------------------------------------------------

export function people(s: State) {
  const map = new Map<string, { user: string; agents: Agent[]; online: boolean }>();
  const add = (u: string) => {
    if (!map.has(u)) map.set(u, { user: u, agents: [], online: false });
    return map.get(u)!;
  };
  for (const a of s.agents) add(a.user).agents.push(a);
  for (const e of s.entries) add(e.author_user);
  for (const m of s.recent) if (m.author_user !== "github") add(m.author_user);
  const list = [...map.values()];
  for (const p of list) {
    p.agents.sort((a, b) => Number(b.online) - Number(a.online) || b.last_seen - a.last_seen);
    p.online = p.agents.some((a) => a.online);
  }
  return list.sort((a, b) => Number(b.online) - Number(a.online) || a.user.localeCompare(b.user));
}

export const lastRead = (ch: string) => store.get<number>("read:" + ch, 0);
export function markRead(ch: string) {
  store.set("read:" + ch, now());
}
export function unread(s: State, c: Channel) {
  const list = s.messages[c.name] || s.recent.filter((m) => m.channel === c.name);
  const t = lastRead(c.name);
  return list.filter((m) => m.created_at > t && !(m.author_user === me() && !m.author_agent)).length;
}

export function findMessage(id: number) {
  return S.recent.find((m) => m.id === id) || Object.values(S.messages).flat().find((m) => m.id === id) || S.openQuestions.find((m) => m.id === id);
}

export const prForBranch = (s: State, branch: string) => s.github?.pulls.find((p) => p.branch === branch);
