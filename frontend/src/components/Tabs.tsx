import { useId, useRef } from 'react';
import { useTranslation } from '../i18n';
export function Tabs<T extends string>({
  label,
  tabs,
  value,
  onChange,
}: {
  label: string;
  tabs: { value: T; label: string; ariaLabel?: string; disabled?: boolean }[];
  value: T;
  onChange: (value: T) => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div
      ref={ref}
      className="tabs"
      role="tablist"
      tabIndex={-1}
      aria-label={t(label)}
      onKeyDown={(event) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const enabled = tabs.filter((tab) => !tab.disabled);
        const current = enabled.findIndex((tab) => tab.value === value);
        const next =
          event.key === 'Home'
            ? 0
            : event.key === 'End'
              ? enabled.length - 1
              : (current + (event.key === 'ArrowLeft' ? -1 : 1) + enabled.length) % enabled.length;
        const tab = enabled[next];
        if (tab) {
          onChange(tab.value);
          ref.current
            ?.querySelector<HTMLButtonElement>(`[data-tab-index="${tabs.indexOf(tab)}"]`)
            ?.focus();
        }
      }}
    >
      {tabs.map((tab, index) => (
        <button
          key={tab.value}
          id={`${id}-${tab.value}`}
          role="tab"
          type="button"
          data-tab-index={index}
          aria-label={tab.ariaLabel ? t(tab.ariaLabel) : undefined}
          aria-selected={value === tab.value}
          tabIndex={value === tab.value ? 0 : -1}
          disabled={tab.disabled}
          className={value === tab.value ? 'tab active' : 'tab'}
          onClick={() => onChange(tab.value)}
        >
          {t(tab.label)}
        </button>
      ))}
    </div>
  );
}
