// The incident commander (#29, #130), docked in the map's corner. Collapsed,
// it shows the latest briefing; open, the conversation, a box to ask, and
// push-to-talk. The engine doesn't echo questions back, so the ones asked
// here are kept locally and slotted in where they were asked.

import { useEffect, useRef, useState } from "react";
import { askCommander, pttStart, pttStop, setVoiceMode, useEngine } from "../shared/engine";
import type { CommanderMessage, VoiceMode } from "../shared/protocol";
import { formatSimMinutes } from "../shared/round";
import { speechSupported } from "../shared/speech";
import { Icon } from "./icons";
import { Floating, IconButton } from "./ui";

const SUGGESTIONS = ["Which town is most at risk?", "What if the wind shifts west?", "Where should the next crew go?"];

interface Asked {
  text: string;
  at: number; // transcript length when asked: it shows before that message
}

export default function CommanderDock() {
  const { status, hello, transcript, voiceMode, listening, heard } = useEngine();
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState<Asked[]>([]);
  const [draft, setDraft] = useState("");
  const [seen, setSeen] = useState(0);
  const scroller = useRef<HTMLDivElement>(null);

  const last = asked[asked.length - 1];
  const waiting = !!last && !transcript.slice(last.at).some((m) => m.kind === "answer");
  const online = status === "open";
  const perTick = hello?.sim_minutes_per_tick ?? 1;
  const latest = transcript[transcript.length - 1];
  const unread = open ? 0 : transcript.length - seen;

  useEffect(() => {
    if (open) setSeen(transcript.length);
  }, [open, transcript.length]);
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [open, transcript.length, asked.length, waiting]);
  // Speaking opens the dock, so the answer is in view.
  useEffect(() => {
    if (listening) setOpen(true);
  }, [listening]);

  function ask(text: string) {
    const q = text.trim();
    if (!q || !online) return;
    askCommander(q);
    setAsked((a) => [...a, { text: q, at: transcript.length }]);
    setDraft("");
    setOpen(true);
  }

  const items: ({ q: Asked } | { m: CommanderMessage; i: number })[] = [];
  transcript.forEach((m, i) => {
    asked.filter((a) => a.at === i).forEach((q) => items.push({ q }));
    items.push({ m, i });
  });
  asked.filter((a) => a.at >= transcript.length).forEach((q) => items.push({ q }));

  if (!open) {
    return (
      <Floating className="w-[340px]">
        <button onClick={() => setOpen(true)} className="flex w-full items-start gap-3 p-3 text-left">
          <span className="relative mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink text-white">
            <Icon name="message" size={15} />
            {unread > 0 && <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-crit" />}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2 text-[13px] font-semibold text-ink">
              Commander
              {latest && <span className="text-[11px] font-normal text-ink-3">T+{formatSimMinutes(latest.tick * perTick)}</span>}
            </span>
            <span className="mt-0.5 line-clamp-2 block text-xs leading-relaxed text-ink-2">
              {latest ? latest.text : "Briefs you when towns are threatened or roads close. Ask it anything about the fire."}
            </span>
          </span>
          <Icon name="chevronUp" size={16} className="mt-1 text-ink-3" />
        </button>
      </Floating>
    );
  }

  return (
    <Floating className="flex h-[min(480px,calc(100vh-180px))] w-[380px] flex-col overflow-hidden">
      <header className="flex items-center gap-2 border-b border-line px-3 py-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-ink text-white">
          <Icon name="message" size={14} />
        </span>
        <span className="flex-1 text-[13px] font-semibold text-ink">Commander</span>
        <VoiceMenu mode={voiceMode} />
        <IconButton icon="chevronDown" title="Minimize" onClick={() => setOpen(false)} />
      </header>

      <div ref={scroller} className="flex-1 space-y-2.5 overflow-y-auto px-3 py-3">
        {items.length === 0 && (
          <p className="px-1 text-xs leading-relaxed text-ink-3">
            Briefings appear here when towns are threatened or roads close. Answers come from the simulation's own numbers.
          </p>
        )}
        {items.map((it) =>
          "q" in it ? (
            <div key={`q${it.q.at}-${it.q.text}`} className="ml-10 rounded-xl rounded-br-sm bg-accent px-3 py-2 text-[13px] text-white">
              {it.q.text}
            </div>
          ) : (
            <Message key={`m${it.i}`} m={it.m} perTick={perTick} />
          ),
        )}
        {waiting && (
          <div className="flex items-center gap-2 px-1 text-xs text-ink-3">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
            Checking the simulation…
          </div>
        )}
      </div>

      {asked.length === 0 && (
        <div className="flex flex-wrap gap-1.5 px-3 pb-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              disabled={!online}
              onClick={() => ask(s)}
              className="rounded-full border border-line px-2.5 py-1 text-xs text-ink-2 hover:border-line-strong hover:text-ink disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <form
        className="flex items-center gap-1.5 border-t border-line p-2"
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
          placeholder={listening ? "Listening…" : online ? "Ask about the fire…" : "Engine offline"}
          className="h-9 min-w-0 flex-1 rounded-lg border border-line bg-sunken px-3 text-[13px] text-ink outline-none select-text placeholder:text-ink-3 focus:border-accent focus:bg-panel"
        />
        <button
          type="button"
          disabled={!online || !(hello?.speech_to_text ?? false)}
          title={hello?.speech_to_text ? "Hold to talk (or hold Space)" : "Speech-to-text isn't installed: cd engine && uv sync --extra voice"}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            pttStart();
          }}
          onPointerUp={pttStop}
          onPointerCancel={pttStop}
          className={`flex h-9 w-9 items-center justify-center rounded-lg border transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
            listening ? "border-crit bg-crit-soft text-crit" : "border-line text-ink-2 hover:bg-hover"
          }`}
        >
          <Icon name="mic" size={16} />
        </button>
        <button
          type="submit"
          disabled={!online || !draft.trim()}
          title="Ask"
          className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-white hover:bg-accent-hover disabled:bg-sunken disabled:text-ink-3"
        >
          <Icon name="send" size={15} />
        </button>
      </form>
      {heard && (heard.text || heard.error) && (
        <p className="truncate px-3 pb-2 text-[11px] text-ink-3">{heard.text ? `Heard “${heard.text}”` : heard.error}</p>
      )}
    </Floating>
  );
}

const EVENT_LABEL: Record<string, string> = {
  road_cut: "Road cut",
  route_changed: "Reroute",
  no_safe_route: "No safe route",
  town_threatened: "Town threatened",
  town_safe: "All clear",
  forecast_shift: "Forecast",
  evacuate_now: "Evacuate",
};

function Message({ m, perTick }: { m: CommanderMessage; perTick: number }) {
  const briefing = m.kind === "briefing";
  return (
    <div className={`mr-6 rounded-xl rounded-bl-sm border px-3 py-2 ${briefing ? "border-warn-line bg-warn-soft" : "border-line bg-sunken"}`}>
      <div className="mb-0.5 flex items-center gap-1.5 text-[11px]">
        <span className={`font-semibold ${briefing ? "text-warn" : "text-ink-2"}`}>
          {briefing ? (m.event ? (EVENT_LABEL[m.event] ?? "Briefing") : "Briefing") : "Answer"}
        </span>
        <span className="text-ink-3 tnum">T+{formatSimMinutes(m.tick * perTick)}</span>
        {!m.grounded && (
          <span className="rounded bg-warn-soft px-1 text-warn" title="Has a number the simulation tools didn't produce">
            unverified
          </span>
        )}
      </div>
      <p className="text-[13px] leading-relaxed text-ink">{m.text}</p>
    </div>
  );
}

// Off by default: an operator mostly wants briefings on screen.
function VoiceMenu({ mode }: { mode: VoiceMode }) {
  return (
    <select
      value={mode}
      onChange={(e) => setVoiceMode(e.target.value as VoiceMode)}
      title="Read briefings and answers aloud"
      className="h-7 rounded-md border border-line bg-panel px-1.5 text-xs text-ink-2 outline-none hover:border-line-strong"
    >
      <option value="off">Voice off</option>
      {speechSupported && <option value="console">Speak here</option>}
      <option value="mac">Mac speaker</option>
    </select>
  );
}
