import { ArrowDownRight, ArrowUpRight } from 'lucide-react';
import type { StudyReport, StudyPreview } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { propertyText, studyProperties } from './tablePresentation';
import { contextLabel } from '../presentation';
export function differenceText(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '—';
  return value !== 0 && Math.abs(value) < 0.01 ? value.toPrecision(3) : value.toFixed(2);
}
export function PreviewMeasurements({ data, report }: { data: StudyPreview; report: StudyReport }) {
  const { t } = useTranslation();
  return (
    <>
      <div className="sar-preview-data">
        <div className="sar-table-scroll">
          <table aria-label={t('记录活性')}>
            <thead>
              <tr>
                <th scope="col">{t('记录活性')}</th>
                <th scope="col">{data.reference.label}</th>
                <th scope="col">{data.candidate.label}</th>
                <th scope="col">{t('变化')}</th>
              </tr>
            </thead>
            <tbody>
              {data.measurements.map((measurement) => {
                const context = report.contexts.find((item) => item.id === measurement.context_id);
                return (
                  <tr key={measurement.context_id}>
                    <th scope="row">{context && contextLabel(context)}</th>
                    <td>
                      <span className="sar-preview-compound-label" aria-hidden="true">
                        {data.reference.label}
                      </span>
                      {measurement.reference_values.join(' · ') || '—'}
                    </td>
                    <td>
                      <span className="sar-preview-compound-label" aria-hidden="true">
                        {data.candidate.label}
                      </span>
                      {measurement.candidate_values.join(' · ') || '—'}
                    </td>
                    <td className="sar-preview-change">
                      <span className={'sar-delta is-' + measurement.comparison}>
                        {measurement.raw_difference !== null && measurement.raw_difference < 0 ? (
                          <ArrowDownRight size={15} />
                        ) : measurement.raw_difference !== null &&
                          measurement.raw_difference > 0 ? (
                          <ArrowUpRight size={15} />
                        ) : null}
                        {t(
                          (
                            {
                              better: '更强',
                              worse: '更弱',
                              equal: '无数值变化',
                              indeterminate: '不可判定',
                              missing: '未测定',
                              context_mismatch: '条件不可比',
                            } as Record<string, string>
                          )[measurement.comparison] ?? '不可判定',
                        )}
                        {measurement.raw_difference !== null && (
                          <small>
                            Δ {measurement.raw_difference > 0 ? '+' : ''}
                            {differenceText(measurement.raw_difference)}
                          </small>
                        )}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <dl className="sar-property-deltas">
          {studyProperties.map((property) => (
            <div key={property.key}>
              <dt>{property.label}</dt>
              <dd>
                {propertyText(data.candidate.properties[property.key] ?? null, property.key)}
                <small>Δ {differenceText(data.property_differences[property.key] ?? null)}</small>
              </dd>
            </div>
          ))}
        </dl>
      </div>
      {Object.keys({ ...data.reference.predictions, ...data.candidate.predictions }).length > 0 && (
        <details className="sar-compact">
          <summary>{t('已有 ADMET 预测')}</summary>
          <div className="sar-table-scroll">
            <table className="sar-preview-predictions" aria-label={t('已有 ADMET 预测')}>
              <thead>
                <tr>
                  <th>{t('预测指标')}</th>
                  <th>{data.reference.label}</th>
                  <th>{data.candidate.label}</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys({ ...data.reference.predictions, ...data.candidate.predictions }).map(
                  (key) => (
                    <tr key={key}>
                      <th scope="row">{key}</th>
                      <td>{propertyText(data.reference.predictions[key])}</td>
                      <td>{propertyText(data.candidate.predictions[key])}</td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
          <small>{t('模型预测与实验活性分开，不把缺失当安全。')}</small>
        </details>
      )}
    </>
  );
}
