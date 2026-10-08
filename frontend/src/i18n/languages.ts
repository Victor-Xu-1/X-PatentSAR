/** Add a language here and its catalog at the same single authority. */
export const SUPPORTED_LANGUAGES = [
  { id: 'en', label: 'English' },
  { id: 'zh-CN', label: '中文' },
] as const;
export type Locale = (typeof SUPPORTED_LANGUAGES)[number]['id'];
export const DEFAULT_LOCALE: Locale = 'en';
export const isLocale = (value: unknown): value is Locale =>
  SUPPORTED_LANGUAGES.some((language) => language.id === value);
