// Icons: one 24-unit stroke set, drawn at 16 px by default. <Icon name=…/>
// for the console; the named exports below are what exercise control uses.

import type { CSSProperties } from "react";

const PATHS = {
  select: "M5 3l13 7-6 1.5L9.5 18z",
  crew: "M12 3l7 4v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V7z",
  dozer: "M3 17h18M5 17V9h6l3 4h4v4M7 21h0M17 21h0M5 21h14",
  air: "M12 3c3 5 5 8 5 11a5 5 0 01-10 0c0-3 2-6 5-11z",
  bus: "M5 17V6a2 2 0 012-2h10a2 2 0 012 2v11M5 11h14M5 17h14M7 20v-3M17 20v-3M8 14h.01M16 14h.01",
  layers: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5",
  plus: "M12 5v14M5 12h14",
  minus: "M5 12h14",
  fit: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  close: "M6 6l12 12M18 6L6 18",
  chevronRight: "M9 6l6 6-6 6",
  chevronDown: "M6 9l6 6 6-6",
  chevronUp: "M6 15l6-6 6 6",
  alert: "M12 4l9 16H3zM12 10v4M12 17h.01",
  check: "M5 12l4 4 10-10",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
  route: "M6 19a2 2 0 100-4 2 2 0 000 4zM18 9a2 2 0 100-4 2 2 0 000 4zM8 17h6a3 3 0 000-6h-4a3 3 0 010-6h6",
  home: "M4 11l8-7 8 7M6 10v10h12V10",
  users: "M9 11a4 4 0 100-8 4 4 0 000 8zM2 21v-1a6 6 0 0112 0v1M16 3.5a4 4 0 010 7.5M22 21v-1a6 6 0 00-4-5.6",
  flame: "M12 21c-4 0-7-2.7-7-6.5C5 10 9 8 9 3c3 2 4 4 4 6 1-1 1.5-2 1.5-3.5C17 7.5 19 10.5 19 14.5 19 18.3 16 21 12 21z",
  message: "M4 5h16v11H9l-5 4z",
  mic: "M12 15a3 3 0 003-3V6a3 3 0 00-6 0v6a3 3 0 003 3zM5 11a7 7 0 0014 0M12 18v3",
  send: "M4 12l16-8-6 16-2-6z",
  target: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 16a4 4 0 100-8 4 4 0 000 8z",
  pin: "M12 21s7-6 7-11a7 7 0 00-14 0c0 5 7 11 7 11zM12 12a2 2 0 100-4 2 2 0 000 4z",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  play: "M7 4l13 8-13 8z",
  pause: "M8 5v14M16 5v14",
  external: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  bulb: "M9 18h6M10 21h4M12 3a6 6 0 00-4 10.5c.8.8 1 1.5 1 2.5h6c0-1 .2-1.7 1-2.5A6 6 0 0012 3z",
  list: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
  history: "M3 12a9 9 0 103-6.7L3 8M3 3v5h5M12 7v5l3 2",
  compare: "M8 3v18M16 3v18M3 8h5M16 16h5",
  monitor: "M3 12h4l3-8 4 16 3-8h4",
  plan: "M9 4L3 6v14l6-2 6 2 6-2V4l-6 2zM9 4v14M15 6v14",
  review: "M9 11l3 3 8-8M20 12v7a2 2 0 01-2 2H6a2 2 0 01-2-2V5a2 2 0 012-2h9",
  wind: "M3 8h11a3 3 0 10-3-3M3 12h16a3 3 0 11-3 3M3 16h8",
  navigation: "M12 3l6 17-6-4-6 4z",
  sliders: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M16 4v4M10 10v4M18 16v4",
  sound: "M4 9v6h4l5 4V5L8 9zM16 9a4 4 0 010 6M19 6a8 8 0 010 12",
  mute: "M4 9v6h4l5 4V5L8 9zM17 9l4 6M21 9l-4 6",
  dot: "M12 13a1 1 0 100-2 1 1 0 000 2z",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({
  name,
  size = 16,
  className = "",
  strokeWidth = 1.75,
  style,
}: {
  name: IconName;
  size?: number;
  className?: string;
  strokeWidth?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
      style={style}
      aria-hidden
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

/** The product mark: a flame in a rounded square. */
export function FlameMark({ size = 22 }: { size?: number }) {
  return (
    <span
      className="flex items-center justify-center rounded-md bg-ink text-white"
      style={{ width: size, height: size }}
    >
      <Icon name="flame" size={size * 0.62} strokeWidth={2} />
    </span>
  );
}

// Exercise control's icons.
export const CubeIcon = () => <Icon name="layers" size={14} />;
export const ProjectorIcon = () => <Icon name="fit" size={14} />;
export const CameraIcon = () => <Icon name="target" size={14} />;
export const PinIcon = () => <Icon name="pin" size={14} />;
export const CloseIcon = () => <Icon name="close" size={14} />;
export const PlayIcon = () => <Icon name="play" size={12} />;
export const PauseIcon = () => <Icon name="pause" size={12} />;
export const StepIcon = () => <Icon name="chevronRight" size={14} />;
export const RefreshIcon = () => <Icon name="history" size={14} />;
export const SoundIcon = ({ on }: { on: boolean }) => <Icon name={on ? "sound" : "mute"} size={15} />;
