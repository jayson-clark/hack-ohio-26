// Header switch between the light and dark UI (#143).

import { setTheme, useTheme } from "../shared/theme";
import { ThemeIcon } from "./icons";

export default function ThemeToggle() {
  const theme = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      title={`Switch to ${next} mode`}
      aria-label={`Switch to ${next} mode`}
      onClick={() => setTheme(next)}
      className="flex h-7 w-7 items-center justify-center rounded-lg border border-edge bg-surface-1 text-fg-subtle transition-colors hover:text-fg"
    >
      <ThemeIcon dark={theme === "dark"} />
    </button>
  );
}
