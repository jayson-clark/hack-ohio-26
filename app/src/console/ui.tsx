// UI building blocks for the console and exercise control (#130). Styling
// lives here so screens stay consistent: neutral surfaces, the accent only
// on actions, status colors only for status.

import type { ReactNode } from "react";
import { Icon, type IconName } from "./icons";

export type Tone = "crit" | "warn" | "ok" | "info" | "neutral";

export const TONE: Record<Tone, { text: string; soft: string; line: string; solid: string; hex: string }> = {
  crit: { text: "text-crit", soft: "bg-crit-soft", line: "border-crit-line", solid: "bg-crit", hex: "var(--color-crit)" },
  warn: { text: "text-warn", soft: "bg-warn-soft", line: "border-warn-line", solid: "bg-warn", hex: "var(--color-warn)" },
  ok: { text: "text-ok", soft: "bg-ok-soft", line: "border-ok-line", solid: "bg-ok", hex: "var(--color-ok)" },
  info: { text: "text-accent", soft: "bg-accent-soft", line: "border-accent-line", solid: "bg-accent", hex: "var(--color-accent)" },
  neutral: { text: "text-ink-2", soft: "bg-sunken", line: "border-line", solid: "bg-ink-3", hex: "var(--color-ink-3)" },
};

export function Button({
  children,
  onClick,
  variant = "secondary",
  size = "md",
  className = "",
  title,
  disabled,
  icon,
}: {
  children?: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  className?: string;
  title?: string;
  disabled?: boolean;
  icon?: IconName;
}) {
  const styles = {
    primary: "bg-accent text-white shadow-card hover:bg-accent-hover",
    secondary: "border border-line-strong bg-panel text-ink shadow-card hover:bg-hover",
    ghost: "text-ink-2 hover:bg-hover hover:text-ink",
    danger: "border border-crit-line bg-panel text-crit hover:bg-crit-soft",
  }[variant];
  const sizes = size === "sm" ? "h-7 px-2.5 text-xs gap-1.5" : "h-8 px-3 text-[13px] gap-2";
  return (
    <button
      onClick={onClick}
      title={title}
      disabled={disabled}
      className={`inline-flex shrink-0 items-center justify-center rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${sizes} ${styles} ${className}`}
    >
      {icon && <Icon name={icon} size={size === "sm" ? 14 : 15} />}
      {children}
    </button>
  );
}

export function IconButton({
  icon,
  onClick,
  title,
  active = false,
  className = "",
}: {
  icon: IconName;
  onClick?: () => void;
  title: string;
  active?: boolean;
  className?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      aria-pressed={active}
      className={`flex h-8 w-8 items-center justify-center rounded-md transition-colors ${
        active ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-hover hover:text-ink"
      } ${className}`}
    >
      <Icon name={icon} />
    </button>
  );
}

export function Badge({ tone = "neutral", children, dot = false }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  const t = TONE[tone];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-px text-[11px] font-medium leading-[18px] ${t.soft} ${t.text} ${t.line}`}
    >
      {dot && <span className={`h-1.5 w-1.5 rounded-full ${t.solid}`} />}
      {children}
    </span>
  );
}

/** A titled block of the sidebar. */
export function Section({
  title,
  count,
  action,
  children,
  className = "",
}: {
  title: string;
  count?: number | string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`border-b border-line px-4 py-4 last:border-b-0 ${className}`}>
      <header className="mb-3 flex items-center gap-2">
        <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
        {count !== undefined && (
          <span className="rounded-full bg-sunken px-1.5 text-[11px] font-medium leading-[18px] text-ink-2 tnum">{count}</span>
        )}
        <div className="flex-1" />
        {action}
      </header>
      {children}
    </section>
  );
}

/** Small uppercase label above a value or group. */
export function Label({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`text-[11px] font-medium text-ink-3 ${className}`}>{children}</div>;
}

export function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-line bg-panel px-3 py-2.5">
      <Label>{label}</Label>
      <div className={`mt-0.5 truncate text-[19px] font-semibold leading-tight tnum ${tone ? TONE[tone].text : "text-ink"}`}>
        {value}
      </div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-ink-3">{sub}</div>}
    </div>
  );
}

/** A share with its interval: the solid bar is the estimate, the faint band the 90% range. */
export function Meter({ value, lo, hi, tone }: { value: number; lo?: number; hi?: number; tone: Tone }) {
  return (
    <div className="relative h-1.5 overflow-hidden rounded-full bg-sunken ring-1 ring-line ring-inset">
      {lo !== undefined && hi !== undefined && (
        <div
          className={`absolute inset-y-0 opacity-25 ${TONE[tone].solid}`}
          style={{ left: `${lo * 100}%`, width: `${Math.max(0, hi - lo) * 100}%` }}
        />
      )}
      <div className={`absolute inset-y-0 left-0 rounded-full ${TONE[tone].solid}`} style={{ width: `${value * 100}%` }} />
    </div>
  );
}

/** Mutually exclusive options. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  size = "md",
}: {
  value: T;
  options: { value: T; label: string; icon?: ReactNode }[];
  onChange: (v: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div className="inline-flex rounded-lg bg-sunken p-0.5 ring-1 ring-line ring-inset">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`flex items-center gap-1.5 rounded-md font-medium transition-colors ${
            size === "sm" ? "h-6 px-2 text-[11px]" : "h-7 px-3 text-xs"
          } ${value === o.value ? "bg-panel text-ink shadow-card ring-1 ring-line" : "text-ink-2 hover:text-ink"}`}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Independent on/off chips (exercise control's layer toggles). */
export function ToggleGroup<K extends string>({
  items,
  onToggle,
}: {
  items: { key: K; label: string; on: boolean }[];
  onToggle: (k: K) => void;
}) {
  return (
    <div className="flex rounded-lg border border-line bg-panel/95 p-0.5 shadow-float backdrop-blur">
      {items.map((it) => (
        <button
          key={it.key}
          onClick={() => onToggle(it.key)}
          aria-pressed={it.on}
          className={`flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors ${
            it.on ? "text-ink" : "text-ink-3 hover:text-ink-2"
          }`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${it.on ? "bg-accent" : "bg-line-strong"}`} />
          {it.label}
        </button>
      ))}
    </div>
  );
}

/** A floating card over the map. */
export function Floating({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-line bg-panel/97 shadow-float backdrop-blur ${className}`}>{children}</div>;
}

export function Chip({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-line bg-panel/95 px-2.5 py-1.5 text-[11px] text-ink-2 shadow-float backdrop-blur ${className}`}>
      {children}
    </div>
  );
}

/** Exercise control's titled card. */
export function Panel({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <header className="flex h-10 items-center justify-between border-b border-line px-3.5">
        <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
        {right}
      </header>
      <div className="p-3.5">{children}</div>
    </section>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-line-strong bg-panel px-1 font-mono text-[10px] text-ink-3">
      {children}
    </kbd>
  );
}

/** Engine connection state, for a window's header. */
export function ConnectionBadge({ status }: { status: string }) {
  const open = status === "open";
  return (
    <span className="flex items-center gap-1.5 text-xs text-ink-2" title={open ? "Connected to the engine" : "Engine not connected"}>
      <span className={`h-2 w-2 rounded-full ${open ? "bg-ok" : status === "connecting" ? "animate-pulse bg-warn" : "bg-crit"}`} />
      {open ? "Live" : status === "connecting" ? "Connecting" : "Offline"}
    </span>
  );
}

/** Empty or waiting state inside a section. */
export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-line px-3 py-4 text-center text-xs leading-relaxed text-ink-3">{children}</p>;
}
