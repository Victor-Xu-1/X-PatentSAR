import { Languages } from 'lucide-react';
import { setLocale, SUPPORTED_LANGUAGES, useTranslation } from '../i18n';
import type { Locale } from '../i18n';

export function LanguageSwitch() {
  const { locale, t } = useTranslation();
  return (
    <label className="language-switch" title={t('界面语言')}>
      <Languages size={15} aria-hidden="true" />
      <select
        aria-label={t('界面语言')}
        value={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        {SUPPORTED_LANGUAGES.map((language) => (
          <option key={language.id} value={language.id} lang={language.id}>
            {language.label}
          </option>
        ))}
      </select>
    </label>
  );
}
