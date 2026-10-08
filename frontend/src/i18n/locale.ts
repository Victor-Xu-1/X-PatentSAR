import { useSyncExternalStore } from 'react';

export type Locale = 'zh-CN' | 'en';
export const LOCALE_STORAGE_KEY = 'x-patentsar.locale';
let current: Locale = 'zh-CN';
let initialized = false;
const listeners = new Set<() => void>();

const valid = (value: unknown): value is Locale => value === 'zh-CN' || value === 'en';
function apply(value: Locale) {
  current = value;
  if (typeof document !== 'undefined') document.documentElement.lang = value;
  for (const listener of listeners) listener();
}
function initialize() {
  if (initialized || typeof window === 'undefined') return;
  initialized = true;
  try {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    if (valid(stored)) current = stored;
  } catch {
    // A blocked browser preference store must not block the application.
  }
  document.documentElement.lang = current;
  window.addEventListener('storage', (event) => {
    if (event.key === LOCALE_STORAGE_KEY && (valid(event.newValue) || event.newValue === null))
      apply(event.newValue ?? 'zh-CN');
  });
}
export function getLocale(): Locale {
  initialize();
  return current;
}
export function setLocale(value: Locale) {
  if (!valid(value)) throw new Error('Unsupported interface language');
  initialize();
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, value);
  } catch {
    // Keep the explicit session choice even if persistence is unavailable.
  }
  apply(value);
}
function subscribe(listener: () => void) {
  initialize();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function useLocale(): Locale {
  return useSyncExternalStore(subscribe, getLocale, () => 'zh-CN');
}
