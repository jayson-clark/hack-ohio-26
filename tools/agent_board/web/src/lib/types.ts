// Shapes the board server sends (see boardsrv/model.py).

export type EntryKind = "finding" | "workflow" | "decision" | "gotcha";
export type Reactions = Record<string, string[]>;

export interface Agent {
  id: string; // "<user>/<agent>"
  user: string;
  name: string;
  status: string;
  branch: string;
  host: string;
  first_seen: number;
  last_seen: number;
  online: boolean;
  pr: number | null;
  pr_title: string;
}

export interface EntryLink {
  id: number;
  title: string;
  kind: EntryKind;
  archived: boolean;
  rel: "related" | "supersedes";
  dir: "in" | "out";
}

export interface Entry {
  id: number;
  kind: EntryKind;
  title: string;
  body: string;
  tags: string[];
  source: string;
  author_user: string;
  author_agent: string;
  created_at: number;
  updated_at: number;
  archived: number;
  votes: { true: number; stale: number; confirmed_at: number | null };
  links: EntryLink[];
  superseded_by: number | null;
  revisions: number;
  reactions: Reactions;
  snippet?: string;
  title_hl?: string;
}

export interface Revision {
  id: number;
  entry_id: number;
  kind: EntryKind;
  title: string;
  body: string;
  tags: string[];
  archived: number;
  editor_user: string;
  editor_agent: string;
  created_at: number;
}

export interface Vote {
  voter: string;
  vote: "true" | "stale";
  note: string;
  created_at: number;
}

export interface Channel {
  name: string;
  topic: string;
  created_by: string;
  created_at: number;
  last_activity: number;
  ttl_hours: number;
  message_count: number;
  open_questions: number;
  expires_at: number | null;
}

export interface Message {
  id: number;
  channel: string;
  parent_id: number | null;
  kind: "message" | "question";
  body: string;
  to_target: string;
  resolved: number;
  resolved_at: number | null;
  author_user: string;
  author_agent: string;
  created_at: number;
  reply_count: number;
  last_reply_at: number | null;
  reactions: Reactions;
  snippet?: string;
}

export interface Claim {
  id: number;
  agent_id: string;
  path: string;
  note: string;
  branch: string;
  created_at: number;
  expires_at: number;
  released_at: number | null;
  wanted?: string;
}

export interface Activity {
  id: number;
  agent_id: string;
  kind: "joined" | "status" | "branch" | "pr" | "claim" | "release" | "entry" | "question";
  detail: string;
  ref: string;
  created_at: number;
}

export interface GhIssue {
  number: number;
  title: string;
  assignees: string[];
  labels: string[];
  url: string;
  updated_at: number | null;
}

export interface GhPull {
  number: number;
  title: string;
  author: string;
  branch: string;
  draft: boolean;
  review: string;
  url: string;
  updated_at: number | null;
}

export interface GhMerged {
  number: number;
  title: string;
  author: string;
  branch: string;
  url: string;
  merged_ts: number | null;
}

export interface GitHub {
  repo: string;
  issues: GhIssue[];
  pulls: GhPull[];
  merged: GhMerged[];
  source: string;
  updated_at: number;
}

export interface BoardState {
  agents: Agent[];
  channels: Channel[];
  entries: Entry[];
  recent: Message[];
  open_questions: Message[];
  claims: Claim[];
  activity: Activity[];
  tags: { tag: string; count: number }[];
  github: GitHub | null;
  repo: string;
  now: number;
}

export interface Digest {
  since: number;
  now: number;
  entries_new: Entry[];
  entries_updated: Entry[];
  channels: { channel: string; n: number; questions: number; last: number }[];
  questions_asked: Message[];
  questions_resolved: Message[];
  activity: Activity[];
  merged: GhMerged[];
}

export type BoardEvent =
  | { type: "entry"; data: Entry; at: number }
  | { type: "message"; data: Message; at: number }
  | { type: "channel"; data: Channel; at: number }
  | { type: "channel_expired"; data: { name: string }; at: number }
  | { type: "agent"; data: Agent; at: number }
  | { type: "activity"; data: Activity; at: number }
  | { type: "reaction"; data: { target: string; reactions: Reactions }; at: number }
  | { type: "claims"; data: { agent_id: string; claims: Claim[] }; at: number }
  | { type: "claim_conflict"; data: { agent_id: string; path: string; held_by: string; held_path: string }; at: number }
  | { type: "github"; data: GitHub; at: number };
