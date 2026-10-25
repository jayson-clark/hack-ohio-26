// Drafted dispatch orders and evacuation alerts (#132), right under the
// decision queue: a draft waiting for approval is a decision too. The operator
// reads, edits, sends or dismisses each one. "Send" only records it (the
// engine logs it for the after-action review); nothing is delivered anywhere.

import { useState } from "react";
import { draftAction, requestBriefing, useEngine } from "../shared/engine";
import type { Draft } from "../shared/protocol";
import { Button, Empty } from "./ui";

const KIND_LABEL: Record<Draft["kind"], string> = {
  unit_order: "Unit order",
  evac_alert: "Evacuation alert",
  briefing: "Briefing",
};

const SOURCE_LABEL: Record<Draft["source"], string> = {
  template: "from the engine's facts",
  llm: "worded by Claude, checked against the facts",
  operator: "edited by you",
};

export default function DispatchDrafts() {
  const { dispatchDrafts } = useEngine();
  const open = dispatchDrafts.filter((d) => d.status === "draft").reverse();
  const sent = dispatchDrafts.filter((d) => d.status === "sent").slice(-3).reverse();
  return (
    <div className="space-y-2 px-3 pb-3">
      {open.length === 0 && <Empty>No drafts. Sending a unit or ordering a town out writes one here.</Empty>}
      {open.map((d) => (
        <DraftCard key={d.id} draft={d} />
      ))}
      <div className="flex items-center justify-between pt-1">
        <Button size="sm" variant="ghost" icon="message" onClick={requestBriefing}>
          Draft a briefing
        </Button>
        {sent.length > 0 && <span className="text-[11px] text-ink-3">{sent.length} sent recently</span>}
      </div>
    </div>
  );
}

function DraftCard({ draft }: { draft: Draft }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(draft.text);
  const [spanish, setSpanish] = useState(false);
  const shown = spanish && draft.text_es ? draft.text_es : draft.text;
  return (
    <div className="rounded-lg border border-line bg-panel p-2.5 shadow-card">
      <div className="mb-1 flex items-center gap-2 text-[11px] text-ink-3">
        <span className="font-medium text-ink-2">{KIND_LABEL[draft.kind]}</span>
        <span>· {draft.subject}</span>
        {draft.text_es && (
          <button className="ml-auto underline-offset-2 hover:underline" onClick={() => setSpanish(!spanish)}>
            {spanish ? "English" : "Español"}
          </button>
        )}
      </div>
      {editing ? (
        <textarea
          className="w-full resize-y rounded-md border border-line-strong bg-panel p-1.5 text-xs leading-relaxed text-ink outline-none"
          rows={4}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      ) : (
        <p className="whitespace-pre-wrap text-xs leading-relaxed text-ink">{shown}</p>
      )}
      <div className="mt-1 text-[10px] text-ink-3" title="Nothing is sent anywhere real; sending records it for the review.">
        {SOURCE_LABEL[draft.source]}
        {draft.kind === "evac_alert" && ` · ${draft.text.length}/360 characters`}
      </div>
      <div className="mt-2 flex gap-1.5">
        {editing ? (
          <>
            <Button size="sm" variant="primary" onClick={() => (draftAction(draft.id, "edit", text), setEditing(false))}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => (setText(draft.text), setEditing(false))}>
              Cancel
            </Button>
          </>
        ) : (
          <>
            <Button size="sm" variant="primary" onClick={() => draftAction(draft.id, "send")}>
              Send
            </Button>
            <Button size="sm" onClick={() => (setText(draft.text), setEditing(true))}>
              Edit
            </Button>
            <Button size="sm" variant="ghost" onClick={() => draftAction(draft.id, "dismiss")}>
              Dismiss
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
