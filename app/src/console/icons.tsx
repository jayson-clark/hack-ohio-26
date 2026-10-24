// Inline stroke icons (16px grid), so the console needs no icon dependency.

import type { ReactNode } from "react";

function Icon({ children, size = 14 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}

export const CubeIcon = () => (
  <Icon>
    <path d="M8 1.75 13.5 4.75v6.5L8 14.25 2.5 11.25v-6.5z" />
    <path d="M2.5 4.75 8 7.75l5.5-3M8 7.75v6.5" />
  </Icon>
);

export const ProjectorIcon = () => (
  <Icon>
    <rect x="1.75" y="2.75" width="12.5" height="9" rx="1.5" />
    <path d="M5.5 14.25h5" />
  </Icon>
);

export const CameraIcon = () => (
  <Icon>
    <path d="M1.75 5.25c0-.83.67-1.5 1.5-1.5h1.5l1-1.5h4.5l1 1.5h1.5c.83 0 1.5.67 1.5 1.5v6.5c0 .83-.67 1.5-1.5 1.5h-9.5c-.83 0-1.5-.67-1.5-1.5z" />
    <circle cx="8" cy="8.25" r="2.5" />
  </Icon>
);

export const PinIcon = () => (
  <Icon size={13}>
    <path d="M8 14.25s4.75-4.1 4.75-8A4.75 4.75 0 0 0 3.25 6.25c0 3.9 4.75 8 4.75 8Z" />
    <circle cx="8" cy="6.25" r="1.6" />
  </Icon>
);

export const CloseIcon = () => (
  <Icon size={12}>
    <path d="m4 4 8 8M12 4l-8 8" />
  </Icon>
);

export const PlayIcon = () => (
  <Icon size={13}>
    <path d="M4.75 2.75v10.5L13 8z" fill="currentColor" />
  </Icon>
);

export const PauseIcon = () => (
  <Icon size={13}>
    <path d="M5 3v10M11 3v10" strokeWidth={2.25} />
  </Icon>
);

export const StepIcon = () => (
  <Icon size={13}>
    <path d="M3.75 3.25v9.5L10.5 8z" fill="currentColor" />
    <path d="M12.75 3.25v9.5" strokeWidth={1.75} />
  </Icon>
);

export const SoundIcon = ({ on }: { on: boolean }) => (
  <Icon size={13}>
    <path d="M2.75 6.25h2.5L8.5 3.5v9l-3.25-2.75h-2.5z" />
    {on ? <path d="M11 5.75a3.25 3.25 0 0 1 0 4.5M12.75 4a5.75 5.75 0 0 1 0 8" /> : <path d="m11 6 3 4m0-4-3 4" />}
  </Icon>
);

export const RefreshIcon = () => (
  <Icon size={13}>
    <path d="M13.25 8a5.25 5.25 0 1 1-1.54-3.71M13.25 2.5v2.75H10.5" />
  </Icon>
);

export function FlameMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
      <defs>
        <linearGradient id="fw-flame" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#ff4d1a" />
          <stop offset="1" stopColor="#ffc46b" />
        </linearGradient>
      </defs>
      <path
        fill="url(#fw-flame)"
        d="M12 2.5c.6 3.1-1.2 4.6-2.6 6.2C8 10.3 7 11.8 7 14a5 5 0 0 0 10 0c0-2-1-3.4-1.8-4.4-.3 1.3-1 2.2-2 2.6.6-3.6-.2-7-1.2-9.7Z"
      />
      <path fill="#0a0b0d" opacity="0.35" d="M12 21a2.6 2.6 0 0 1-2.6-2.6c0-1.5 1.2-2.5 2.6-4 1.4 1.5 2.6 2.5 2.6 4A2.6 2.6 0 0 1 12 21Z" />
    </svg>
  );
}
