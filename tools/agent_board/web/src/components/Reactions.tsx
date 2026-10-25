import { useEffect, useRef, useState } from "react";
import { api, fail, me } from "../lib/store";
import type { Reactions as R } from "../lib/types";
import { cls } from "../lib/util";
import { Icon } from "./ui";

// ✅ done, 👀 looking at it, 👍 agree, ❓ unclear, 🚧 working on it, 🎉 shipped
export const QUICK = ["✅", "👀", "👍", "❓", "🚧", "🎉"];
const MORE = ["❤️", "🙏", "🔥", "🚀", "😂", "🤔", "👎", "⚠️", "🐛", "💡", "📌", "🧪", "⏳", "🙌", "💯", "🤖", "🛑", "✨", "🧯", "🗺️", "📝", "🔁", "🫡", "👋", "💥", "🧠"];

export function react(target: string, emoji: string) {
  return api("POST", "/api/reactions", { target, emoji }).catch(fail);
}

function whoLabel(list: string[]) {
  const names = list.map((w) => (w.includes("/") ? w.split("/")[1] : w));
  return names.length <= 4 ? names.join(", ") : `${names.slice(0, 4).join(", ")} and ${names.length - 4} more`;
}

export function EmojiPicker({ onPick, onClose }: { onPick: (e: string) => void; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    setTimeout(() => document.addEventListener("mousedown", away));
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [onClose]);
  return (
    <div className="picker" ref={ref} role="dialog" aria-label="Add a reaction">
      {[...QUICK, ...MORE].map((e) => (
        <button
          key={e}
          type="button"
          onClick={() => {
            onPick(e);
            onClose();
          }}
        >
          {e}
        </button>
      ))}
    </div>
  );
}

export function Reactions({ target, reactions, showAdd = false }: { target: string; reactions: R; showAdd?: boolean }) {
  const [picking, setPicking] = useState(false);
  const mine = me();
  const entries = Object.entries(reactions || {});
  if (!entries.length && !showAdd) return null;
  return (
    <div className="reactions" style={{ position: "relative" }}>
      {entries.map(([emoji, who]) => (
        <button
          key={emoji}
          type="button"
          className={cls("react", who.includes(mine) && "mine")}
          title={whoLabel(who)}
          onClick={(e) => {
            e.stopPropagation();
            react(target, emoji);
          }}
        >
          <span>{emoji}</span>
          <span className="n">{who.length}</span>
        </button>
      ))}
      {(showAdd || entries.length > 0) && (
        <button
          type="button"
          className="react add"
          title="Add a reaction"
          onClick={(e) => {
            e.stopPropagation();
            setPicking(true);
          }}
        >
          <Icon name="smile" size={13} />
        </button>
      )}
      {picking && (
        <div style={{ position: "absolute", top: "100%", left: 0, marginTop: 4 }}>
          <EmojiPicker onPick={(e) => react(target, e)} onClose={() => setPicking(false)} />
        </div>
      )}
    </div>
  );
}
