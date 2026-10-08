import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';
import { setLocale, LOCALE_STORAGE_KEY } from '../src/i18n';

// Existing golden interaction fixtures explicitly exercise Chinese. The new
// locale specifications and fresh installed browser test the English default.
beforeEach(() => setLocale('zh-CN'));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  if (typeof window !== 'undefined') window.location.hash = '';
  setLocale('zh-CN');
  window.localStorage.removeItem(LOCALE_STORAGE_KEY);
});
if (typeof window !== 'undefined') {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.setAttribute('open', '');
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.removeAttribute('open');
    },
  });
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  });
  if (!Blob.prototype.text)
    Object.defineProperty(Blob.prototype, 'text', {
      configurable: true,
      value(this: Blob) {
        return new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.onerror = () => reject(reader.error);
          reader.readAsText(this);
        });
      },
    });
}
