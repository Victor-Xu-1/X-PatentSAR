import { useSyncExternalStore } from 'react';
import { DEFAULT_LOCALE, isLocale } from './languages';
import type { Locale } from './languages';
export type { Locale } from './languages';
export const LOCALE_STORAGE_KEY = 'x-patentsar.locale';
let current: Locale = DEFAULT_LOCALE;
let initialized = false;
const listeners = new Set<() => void>();

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
    if (isLocale(stored)) current = stored;
  } catch {
    // A blocked browser preference store must not block the application.
  }
  document.documentElement.lang = current;
  window.addEventListener('storage', (event) => {
    if (event.storageArea && event.storageArea !== window.localStorage) return;
    if (event.key === LOCALE_STORAGE_KEY || event.key === null)
      apply(isLocale(event.newValue) ? event.newValue : DEFAULT_LOCALE);
  });
}
export function getLocale(): Locale {
  initialize();
  return current;
}
export function setLocale(value: Locale) {
  if (!isLocale(value)) throw new Error('Unsupported interface language');
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
  return useSyncExternalStore(subscribe, getLocale, () => DEFAULT_LOCALE);
}
