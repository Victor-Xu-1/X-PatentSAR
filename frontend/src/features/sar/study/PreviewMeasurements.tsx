import { ArrowDownRight, ArrowUpRight } from 'lucide-react';
import type { StudyReport, StudyPreview } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { differenceText, previewValueText, propertyText } from './tablePresentation';
import { contextLabel } from '../presentation';
import { PreviewProperties } from './PreviewProperties';
import { PreviewRecordedRows } from './PreviewRecordedRows';
import { ContractError } from '../../../api/validation';
import { SARFailure } from '../SARFailure';
export function PreviewMeasurements({ data, report }: { data: StudyPreview; report: StudyReport }) {
  const { t } = useTranslation();
  if (
    data.recorded_measurements?.some(
      (reading) => !report.contexts.some((context) => context.id === reading.context_id),
    )
  )
    return <SARFailure error={new ContractError('$.preview.recorded_measurements')} />;
  return (
    <>
      <div className="sar-preview-data">
        <div className="sar-table-scroll">
          <table aria-label={t('记录值')}>
            <thead>
              <tr>
                <th scope="col">{t('记录值')}</th>
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
                      {previewValueText(measurement.reference_values)}
                    </td>
                    <td>
                      <span className="sar-preview-compound-label" aria-hidden="true">
                        {data.candidate.label}
                      </span>
                      {previewValueText(measurement.candidate_values)}
                    </td>
                    <td className="sar-preview-change">
                      <span className={'sar-delta is-' + measurement.comparison}>
                        {measurement.raw_difference !== null && measurement.raw_difference < 0 ? (
                          <ArrowDownRight size={15} />
                        ) : measurement.raw_difference !== null &&
                          measurement.raw_difference > 0 ? (
                          <ArrowUpRight size={15} />
                        ) : null}
                        {measurement.raw_difference !== null
                          ? t(
                              measurement.raw_difference < 0
                                ? '更低'
                                : measurement.raw_difference > 0
                                  ? '更高'
                                  : '相同',
                            )
                          : t(
                              (
                                {
                                  better: 'SAR 更强',
                                  worse: 'SAR 更弱',
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
              <PreviewRecordedRows data={data} report={report} />
            </tbody>
          </table>
        </div>
      </div>
      <PreviewProperties data={data} />
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
