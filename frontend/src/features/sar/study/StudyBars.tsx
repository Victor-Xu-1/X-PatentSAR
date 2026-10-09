import { useState } from 'react';
import type { StudyBin } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { StudyComposition, ChartLegend } from './StudyComposition';
import { chartColor, compactBinLabel } from './chartPresentation';
import type { CountingUnit } from './chartPresentation';
export function StudyBars({
  bins,
  layout = 'bars',
  controlledUnit,
  direction = 'lower',
  showLegend = true,
  countingContract,
}: {
  bins: StudyBin[];
  layout?: 'bars' | 'donut' | 'stack';
  controlledUnit?: CountingUnit;
  direction?: 'lower' | 'higher' | undefined;
  showLegend?: boolean;
  countingContract?: 'legacy-per-bin-members' | 'unique-molecules-v2' | undefined;
}) {
  const { t } = useTranslation(),
    [localUnit, setUnit] = useState<CountingUnit>('molecules');
  const historical = countingContract !== 'unique-molecules-v2';
  const unit = historical ? 'observations' : (controlledUnit ?? localUnit);
  const presentation = historical && layout === 'stack' ? 'bars' : layout;
  const max = bins.reduce((maximum, bin) => Math.max(maximum, bin[unit]), 1);
  return (
    <div className={'sar-study-bars sar-chart-layout-' + presentation}>
      {!controlledUnit && (
        <label>
          {t('统计单位')}
          <select value={unit} onChange={(e) => setUnit(e.target.value as typeof unit)}>
            <option value="molecules" disabled={historical}>
              {t('原始编号 / 记录')}
            </option>
            <option value="observations">{t('观察数')}</option>
          </select>
        </label>
      )}
      {presentation !== 'bars' && (
        <StudyComposition bins={bins} unit={unit} layout={presentation} direction={direction} />
      )}
      {presentation !== 'stack' && (
        <ul className="sar-chart-values">
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
              <span title={bin.label}>
                {['missing', 'unsupported', 'unresolved'].includes(bin.kind)
                  ? t(
                      bin.kind === 'missing'
                        ? '无活性记录'
                        : bin.kind === 'unsupported'
                          ? '未支持读数'
                          : '重复读数未确定',
                    )
                  : compactBinLabel(bin.label)}
              </span>
              <meter
                className="sar-chart-track"
                min={0}
                max={max}
                value={bin[unit]}
                style={{ color: chartColor(bin, index, direction) }}
                aria-label={
                  bin.label + ' · ' + t(unit === 'molecules' ? '原始编号 / 记录' : '观察数')
                }
              />
              <strong>{bin[unit]}</strong>
            </li>
          ))}
        </ul>
      )}
      {presentation === 'stack' && showLegend && <ChartLegend bins={bins} direction={direction} />}
      {historical && (
        <small className="sar-chart-legacy">
          {t('旧报告按原始观察展示；重跑研究可得到不重叠的编号分布。')}
        </small>
      )}
      {!bins.length && <p>{t('无分布记录')}</p>}
    </div>
  );
}
