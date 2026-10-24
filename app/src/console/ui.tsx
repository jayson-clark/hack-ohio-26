// Small console building blocks. Styling lives here so panels stay consistent.

import type { ReactNode } from "react";

export function Panel({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-edge bg-surface-1">
      <header className="flex h-9 items-center justify-between border-b border-edge px-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-fg-muted">{title}</h2>
        {right}
      </header>
      <div className="p-3">{children}</div>
    </section>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-edge-strong bg-surface-2 px-1 font-mono text-[10px] text-fg-muted">
      {children}
    </kbd>
  );
}

/** Pill group of mutually exclusive options, used as a floating toolbar. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string; icon?: ReactNode }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex rounded-lg border border-edge bg-surface-1/85 p-0.5 shadow-lg shadow-black/30 backdrop-blur">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors ${
            value === o.value ? "bg-surface-3 text-fg" : "text-fg-muted hover:text-fg"
          }`}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Floating toolbar of independent on/off chips. */
export function ToggleGroup<K extends string>({
  items,
  onToggle,
}: {
  items: { key: K; label: string; on: boolean }[];
  onToggle: (k: K) => void;
}) {
  return (
    <div className="flex rounded-lg border border-edge bg-surface-1/85 p-0.5 shadow-lg shadow-black/30 backdrop-blur">
      {items.map((it) => (
        <button
          key={it.key}
          onClick={() => onToggle(it.key)}
          aria-pressed={it.on}
          className={`flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors ${
            it.on ? "text-fg" : "text-fg-subtle hover:text-fg-muted"
          }`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${it.on ? "bg-ember-400" : "bg-surface-3"}`} />
          {it.label}
        </button>
      ))}
    </div>
  );
}

export function Chip({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-lg border border-edge bg-surface-1/85 px-2.5 py-1.5 text-[11px] text-fg-muted shadow-lg shadow-black/30 backdrop-blur ${className}`}
    >
      {children}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "secondary",
  className = "",
  title,
  disabled = false,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost";
  className?: string;
  title?: string;
  disabled?: boolean;
}) {
  const styles = {
    primary: "bg-ember-500 text-black hover:bg-ember-400",
    secondary: "border border-edge bg-surface-2 text-fg hover:bg-surface-3",
    ghost: "text-fg-muted hover:bg-surface-2 hover:text-fg",
  }[variant];
  return (
    <button
      onClick={onClick}
      title={title}
      disabled={disabled}
      className={`inline-flex h-8 items-center justify-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-colors disabled:opacity-40 ${styles} ${className}`}
    >
      {children}
    </button>
  );
}

/** Engine connection state, for a window's header. */
export function ConnectionBadge({ status }: { status: string }) {
  const open = status === "open";
  const color = open ? "bg-emerald-400" : status === "connecting" ? "bg-amber-400" : "bg-red-500";
  return (
    <span
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ${
        open ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300" : "border-edge bg-surface-1 text-fg-muted"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${color} ${open ? "" : "animate-pulse"}`} />
      {/* "Connected" on a laptop, "Engine connected" where there's room. */}
      <span className="hidden 2xl:inline">Engine </span>
      <span className="2xl:lowercase">{open ? "Connected" : status === "connecting" ? "Connecting…" : "Offline"}</span>
    </span>
  );
}

/** Small uppercase label above a group of values. */
export function Label({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`text-[10px] font-semibold uppercase tracking-[0.08em] text-fg-subtle ${className}`}>{children}</div>
  );
}
