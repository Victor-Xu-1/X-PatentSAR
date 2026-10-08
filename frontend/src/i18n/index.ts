import { englishCatalog } from './catalog';
import { getLocale, useLocale } from './locale';
import type { Locale } from './locale';
export { getLocale, setLocale, useLocale, LOCALE_STORAGE_KEY } from './locale';
export type { Locale } from './locale';
export type MessageValues = Readonly<Record<string, string | number | boolean | null>>;

export function formatMessage(
  source: string,
  values: MessageValues = {},
  locale: Locale = getLocale(),
): string {
  const template = locale === 'en' ? (englishCatalog[source] ?? source) : source;
  return template.replace(/\{([A-Za-z][A-Za-z0-9_]*)\}/g, (whole, key: string) =>
    Object.hasOwn(values, key) ? String(values[key] ?? '') : whole,
  );
}
/** Translate only explicitly marked application-owned copy, never arbitrary data. */
export const t = formatMessage;
export function useTranslation() {
  const locale = useLocale();
  return { locale, t };
}
export class UiError extends Error {
  constructor(
    readonly source: string,
    readonly values: MessageValues = {},
  ) {
    super(formatMessage(source, values, 'zh-CN'));
    this.name = 'UiError';
  }
}
export const errorText = (error: Error): string =>
  error instanceof UiError ? t(error.source, error.values) : t(error.message);
