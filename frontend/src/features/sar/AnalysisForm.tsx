import { useState } from 'react';
import { sarApi } from '../../api/sarApi';
import type { AnalysisRequest, Dataset, Region, SARJob } from '../../api/sarTypes';
import { useTranslation } from '../../i18n';
import { gradeOrder, newRequestId } from './presentation';
import { MutationNotice } from './MutationNotice';
import { useSARMutation } from './useSARMutation';
export function AnalysisForm({
  dataset,
  region,
  busy,
  onJob,
  active = true,
  scope = '',
}: {
  dataset: Dataset;
  region: Region | null;
  busy: boolean;
  onJob: (job: SARJob) => void;
  active?: boolean;
  scope?: string;
}) {
  const { t } = useTranslation();
  const [metricId, setMetricId] = useState('');
  const [direction, setDirection] = useState<'lower' | 'higher' | ''>('');
  const [grades, setGrades] = useState('');
  const [confirm, setConfirm] = useState(false);
  const mutation = useSARMutation({
    active,
    scope: JSON.stringify([scope, dataset.id, dataset.revision]),
  });
  const order = gradeOrder(grades);
  const current = Boolean(
    region &&
    region.dataset_id === dataset.id &&
    region.dataset_revision === dataset.revision &&
    !dataset.stale,
  );
  const valid =
    current &&
    dataset.metrics.some((metric) => metric.id === metricId) &&
    direction !== '' &&
    order.valid &&
    active &&
    !busy;
  return (
    <section className="sar-panel" aria-label={t('分析设置')}>
      <h2>{t('分析设置')}</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!valid || !region || mutation.locked) return;
          const payload: AnalysisRequest = {
            request_id: newRequestId(),
            expected_dataset_revision: dataset.revision,
            region_id: region.id,
            metric_id: metricId,
            direction,
            grade_order: order.values,
            confirm_context: confirm,
          };
          void mutation.run(() => sarApi.analyse(dataset.id, payload), onJob, payload.request_id);
        }}
      >
        <fieldset disabled={!active || mutation.locked || dataset.stale || busy}>
          <div className="sar-form-grid">
            <label>
              {t('活性指标')}
              <select value={metricId} onChange={(e) => setMetricId(e.target.value)}>
                <option value="">{t('请选择活性指标')}</option>
                {dataset.metrics.map((metric) => (
                  <option value={metric.id} key={metric.id}>
                    {[metric.name, metric.unit, metric.target, metric.assay]
                      .filter((v) => v !== null)
                      .join(' · ')}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t('活性方向')}
              <select
                value={direction}
                onChange={(e) => setDirection(e.target.value as typeof direction)}
              >
                <option value="">{t('请选择方向')}</option>
                <option value="lower">{t('越低越强')}</option>
                <option value="higher">{t('越高越强')}</option>
              </select>
            </label>
          </div>
          <label>
            {t('等级顺序（可选，最强在前，每行一个原始等级）')}
            <textarea
              value={grades}
              maxLength={6000}
              rows={3}
              onChange={(e) => setGrades(e.target.value)}
            />
          </label>
          <p className="sar-hint">{t('不猜测 A–G 或其他等级顺序；留空时不使用等级约定。')}</p>
          {!order.valid && <p role="alert">{t('等级最多 32 项且不能重复。')}</p>}
          <label className="sar-checkbox">
            <input
              type="checkbox"
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />
            {t('我仅确认缺失的实验条件允许比较；已知条件差异仍禁止比较。')}
          </label>
          <button type="submit" className="primary" disabled={!valid}>
            {t('开始参考比较')}
          </button>
        </fieldset>
      </form>
      <MutationNotice mutation={mutation} disabled={!active || busy || dataset.stale} />
    </section>
  );
}
