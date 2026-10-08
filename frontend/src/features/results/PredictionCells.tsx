import { useTranslation } from '../../i18n';
import type { Compound } from '../../api/types';
import { METRIC_SPECS } from '../../api/predictionTypes';
import type { PredictionMetric } from '../../api/predictionTypes';
import { effectiveProperty, propertyObservation } from '../../model/propertyValues';

const statusLabels = {
  not_run: '未计算',
  pending: '等待计算',
  running: '计算中',
  complete: '已计算',
  failed: '计算失败',
  stale: '需重算',
  unavailable: '无有效结构',
} as const;

export function PredictionCells({
  row,
  visibleColumns,
}: {
  row: Compound;
  visibleColumns?: ReadonlySet<string> | undefined;
}) {
  const { t } = useTranslation();
  return (
    <>
      {METRIC_SPECS.filter(
        (spec) => !visibleColumns || visibleColumns.has(`property:${spec.key}`),
      ).map((spec) => {
        const metric = effectiveProperty(row, spec.key);
        const prediction = propertyObservation(row, spec.key);
        const status = prediction?.status ?? 'not_run';
        const label = t(statusLabels[status]);
        return (
          <td
            className="prediction-column"
            key={spec.key}
            data-property={spec.key}
            title={
              metric.manual
                ? t('{label} · {unit} · 手工修正{blank}', {
                    label: spec.label,
                    unit: spec.unit,
                    blank: metric.value === null ? t('（留空）') : '',
                  })
                : metric.value !== null
                  ? `${spec.label} · ${spec.unit} · ${spec.kind === 'prediction' ? t('模型预测，非专利实测') : t('结构计算，非专利实测')}`
                  : prediction?.error
                    ? t('{label}：{error}', { label, error: prediction.error.message })
                    : label
            }
          >
            {metric.value !== null ? (
              <span className={`prediction-value${metric.manual ? ' manually-edited' : ''}`}>
                {Number.isInteger(metric.value) ? String(metric.value) : metric.value.toFixed(2)}
              </span>
            ) : (
              <span
                className={status === 'failed' ? 'prediction-failed' : 'muted'}
                aria-label={`${spec.label} ${metric.manual ? t('手工留空') : label}`}
              >
                —
              </span>
            )}
          </td>
        );
      })}
    </>
  );
}

function ObservedMetrics({ properties }: { properties: PredictionMetric[] }) {
  return (
    <dl>
      {properties.map((metric) => (
        <div key={metric.key}>
          <dt>{metric.label}</dt>
          <dd>
            {metric.value} {metric.unit}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function PredictionEvidence({ row }: { row: Compound }) {
  const { t } = useTranslation();
  const prediction = row.admet;
  const descriptors = row.descriptors;
  return (
    <details className="prediction-evidence">
      <summary>
        {descriptors
          ? t('五项计算 · {descriptors}；LogS · {prediction}', {
              descriptors: t(statusLabels[descriptors.status]),
              prediction: t(statusLabels[prediction?.status ?? 'not_run']),
            })
          : t('六项指标 · {status}', { status: t(statusLabels[prediction?.status ?? 'not_run']) })}
      </summary>
      <p className="muted">
        {t('MW、LogP、TPSA、HBD、HBA 为结构计算；LogS 为模型预测，均不是专利实测数据。')}
      </p>
      {prediction?.error && <p className="error-notice">{prediction.error.message}</p>}
      {descriptors?.error && <p className="error-notice">{descriptors.error.message}</p>}
      {descriptors?.status === 'complete' && (
        <>
          <ObservedMetrics properties={descriptors.properties} />
          <p className="muted">
            {descriptors.engine?.name} {descriptors.engine?.version} · {descriptors.generated_at}
          </p>
          <p className="muted">
            {t('算法校验：{hash}', { hash: descriptors.engine?.algorithm_sha256 ?? null })}
          </p>
        </>
      )}
      {prediction?.status === 'complete' && (
        <>
          <ObservedMetrics properties={prediction.properties} />
          <p className="muted">
            {prediction.engine?.name} {prediction.engine?.version} · {prediction.generated_at}
          </p>
          <p className="muted">
            {t('模型校验：{hash}', { hash: prediction.engine?.model_sha256 ?? null })}
          </p>
        </>
      )}
      {prediction?.warnings.map((warning, index) => (
        <p className="muted" key={index}>
          {warning}
        </p>
      ))}
    </details>
  );
}
