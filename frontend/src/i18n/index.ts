import { messageCatalogs } from './catalog';
import { getLocale, useLocale } from './locale';
import type { Locale } from './locale';
export { getLocale, setLocale, useLocale, LOCALE_STORAGE_KEY } from './locale';
export type { Locale } from './locale';
export { DEFAULT_LOCALE, SUPPORTED_LANGUAGES } from './languages';
export type MessageValues = Readonly<Record<string, string | number | boolean | null | UiError>>;

export function formatMessage(
  source: string,
  values: MessageValues = {},
  locale: Locale = getLocale(),
): string {
  return formatAtDepth(source, values, locale, 0);
}
function formatAtDepth(
  source: string,
  values: MessageValues,
  locale: Locale,
  depth: number,
): string {
  const template = locale === 'zh-CN' ? source : (messageCatalogs[locale][source] ?? source);
  return template.replace(/\{([A-Za-z][A-Za-z0-9_]*)\}/g, (whole, key: string) => {
    if (!Object.hasOwn(values, key)) return whole;
    const value = values[key];
    return value instanceof UiError && depth < 8
      ? formatAtDepth(value.source, value.values, locale, depth + 1)
      : String(value ?? '');
  });
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
