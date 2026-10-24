// The incident commander's side of the console (#29): its briefings and
// answers, and a box to ask it things. The engine doesn't echo questions
// back, so the ones asked here are kept locally and slotted into the
// transcript where they were asked.

import { useEffect, useRef, useState } from "react";
import { askCommander, useEngine } from "../shared/engine";
import type { CommanderMessage } from "../shared/protocol";
import { Panel } from "./ui";

const SUGGESTIONS = ["Which town is most at risk?", "What if the wind shifts west?", "Where should the next crew go?"];

interface Asked {
  text: string;
  /** transcript length when it was asked: it renders before that message */
  at: number;
}

export default function CommanderPanel() {
  const { status, hello, transcript } = useEngine();
  const [asked, setAsked] = useState<Asked[]>([]);
  const [draft, setDraft] = useState("");
  const scroller = useRef<HTMLDivElement>(null);

  // Waiting while the newest question has no answer after it yet.
  const last = asked[asked.length - 1];
  const waiting = !!last && !transcript.slice(last.at).some((m) => m.kind === "answer");

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [transcript.length, asked.length, waiting]);

  const online = status === "open";
  function ask(text: string) {
    const q = text.trim();
    if (!q || !online) return;
    askCommander(q);
    setAsked((a) => [...a, { text: q, at: transcript.length }]);
    setDraft("");
  }

  const minutesPerTick = hello?.sim_minutes_per_tick ?? 1;
  const items: ({ q: Asked } | { m: CommanderMessage; i: number })[] = [];
  transcript.forEach((m, i) => {
    asked.filter((a) => a.at === i).forEach((q) => items.push({ q }));
    items.push({ m, i });
  });
  asked.filter((a) => a.at >= transcript.length).forEach((q) => items.push({ q }));

  return (
    <Panel title="Commander">
      <div ref={scroller} className="-mx-1 max-h-72 space-y-2 overflow-y-auto px-1">
        {items.length === 0 && (
          <p className="py-2 text-[11px] leading-relaxed text-fg-subtle">
            Briefs you when towns are threatened or roads close, and answers questions from the simulation's own
            numbers.
          </p>
        )}
        {items.map((it) =>
          "q" in it ? (
            <div key={`q${it.q.at}-${it.q.text}`} className="ml-6 rounded-lg bg-surface-3 px-2.5 py-1.5 text-xs text-fg">
              {it.q.text}
            </div>
          ) : (
            <Message key={`m${it.i}`} m={it.m} minutesPerTick={minutesPerTick} />
          ),
        )}
        {waiting && (
          <div className="flex items-center gap-1.5 px-1 text-[11px] text-fg-subtle">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ember-400" />
            Checking the simulation…
          </div>
        )}
      </div>

      {asked.length === 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              disabled={!online}
              onClick={() => ask(s)}
              className="rounded-full border border-edge bg-surface-2 px-2 py-0.5 text-[11px] text-fg-muted hover:border-edge-strong hover:text-fg disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <form
        className="mt-2 flex gap-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          ask(draft);
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          maxLength={500}
          disabled={!online}
          placeholder={online ? "Ask the commander…" : "Engine offline"}
          className="h-8 min-w-0 flex-1 rounded-lg border border-edge bg-surface-2 px-2.5 text-xs text-fg outline-none select-text placeholder:text-fg-subtle focus:border-edge-strong"
        />
        <button
          type="submit"
          disabled={!online || !draft.trim()}
          className="h-8 rounded-lg bg-ember-500 px-3 text-xs font-medium text-black hover:bg-ember-400 disabled:bg-surface-3 disabled:text-fg-subtle"
        >
          Ask
        </button>
      </form>
    </Panel>
  );
}

const EVENT_LABEL: Record<string, string> = {
  road_cut: "Road cut",
  route_changed: "Reroute",
  no_safe_route: "No safe route",
  town_threatened: "Threatened",
  town_safe: "All clear",
  forecast_shift: "Forecast",
};

function Message({ m, minutesPerTick }: { m: CommanderMessage; minutesPerTick: number }) {
  const briefing = m.kind === "briefing";
  return (
    <div className={`rounded-lg border px-2.5 py-1.5 ${briefing ? "border-ember-500/25 bg-ember-500/5" : "border-edge bg-surface-2"}`}>
      <div className="mb-0.5 flex items-center gap-1.5 text-[10px]">
        <span className={`font-semibold uppercase tracking-wide ${briefing ? "text-ember-300" : "text-sky-300"}`}>
          {briefing ? (m.event ? (EVENT_LABEL[m.event] ?? "Briefing") : "Briefing") : "Answer"}
        </span>
        <span className="font-mono tabular-nums text-fg-subtle">T+{Math.round(m.tick * minutesPerTick)}m</span>
        {!m.grounded && (
          <span
            className="rounded bg-amber-500/15 px-1 text-amber-300"
            title="This answer has a number the simulation tools didn't produce"
          >
            unverified
          </span>
        )}
      </div>
      <p className="text-xs leading-relaxed text-fg">{m.text}</p>
    </div>
  );
}
