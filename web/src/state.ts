// Small cross-view state. "Packing" mode survives reloads (localStorage) so a
// long session filling one bin isn't lost if the phone kills the tab.

import { api, type Status } from "./api";

const PACK_KEY = "inventory.packing";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, v: string | null): void {
  try {
    if (v === null) localStorage.removeItem(key);
    else localStorage.setItem(key, v);
  } catch {
    /* private mode */
  }
}

type Listener = () => void;
const listeners = new Set<Listener>();

export const state = {
  packing: read(PACK_KEY) as string | null,
  /** A photo captured from the Add button, consumed by the add view. */
  pendingPhoto: null as File | null,
  status: null as Status | null,
  checkedOut: 0,
};

export function onChange(fn: Listener): void {
  listeners.add(fn);
}

export function emit(): void {
  listeners.forEach((fn) => fn());
}

export function setPacking(code: string | null): void {
  state.packing = code;
  write(PACK_KEY, code);
  emit();
}

export async function refreshStatus(): Promise<Status | null> {
  try {
    state.status = await api.status();
    state.checkedOut = state.status.checked_out;
    emit();
  } catch {
    /* offline: keep the last known */
  }
  return state.status;
}

export function categories(): string[] {
  return state.status?.categories ?? [];
}
