import type { ReactNode } from "react";
import { useSyncExternalStore } from "react";

let current: ReactNode = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function openModal(node: ReactNode) {
  current = node;
  emit();
}
export function closeModal() {
  current = null;
  emit();
}
export const modalOpen = () => current !== null;

export function useModal() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
  );
}
