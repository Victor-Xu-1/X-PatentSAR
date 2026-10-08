import { useState } from 'react';
import type { StudyBin } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
export function StudyBars({ bins }: { bins: StudyBin[] }) {
  const { t } = useTranslation(),
    [unit, setUnit] = useState<'molecules' | 'observations'>('molecules');
  const max = bins.reduce((maximum, bin) => Math.max(maximum, bin[unit]), 1);
  return (
    <div className="sar-study-bars">
      <label>
        {t('统计单位')}
        <select value={unit} onChange={(e) => setUnit(e.target.value as typeof unit)}>
          <option value="molecules">{t('分子数')}</option>
          <option value="observations">{t('观察数')}</option>
        </select>
      </label>
      <ul>
        {bins.map((bin, index) => (
          <li
            key={index}
            className={
              bin.strong
                ? 'sar-bin-strong'
                : ['missing', 'unsupported'].includes(bin.kind)
                  ? 'sar-bin-unknown'
                  : ''
            }
          >
            <span title={bin.kind}>{bin.label}</span>
            <meter
              min={0}
              max={max}
              value={bin[unit]}
              aria-label={bin.label + ' · ' + t(unit === 'molecules' ? '分子数' : '观察数')}
            />
            <strong>{bin[unit]}</strong>
            {bin.strong && <small>{t('强活性')}</small>}
          </li>
        ))}
      </ul>
      {!bins.length && <p>{t('无分布记录')}</p>}
    </div>
  );
}
