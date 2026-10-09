import { useState } from 'react';
import type { StudyFragment, StudyRegionSummary, StudyReport } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { StudyImage } from './StudyImage';
import { StudyBars } from './StudyBars';
import { GroupPager } from './GroupPager';
import { ChartLegend } from './StudyComposition';
import { StudyRegionMap } from './StudyRegionMap';
import type { CountingUnit } from './chartPresentation';
function FragmentCard({
  fragment,
  index,
  regionId,
  jobId,
  active,
  onRows,
  unit,
  report,
}: {
  fragment: StudyFragment;
  index: number;
  regionId: string;
  jobId: string;
  active: boolean;
  onRows: (region: string, fragment: string) => void;
  unit: CountingUnit;
  report: StudyReport;
}) {
  const { t } = useTranslation();
  return (
    <article className="sar-study-card">
      <h4>
        {t('片段 {index}', { index })}
        {fragment.is_reference && <small> · {t('参考')}</small>}
      </h4>
      <StudyBars
        bins={fragment.bins}
        layout="stack"
        controlledUnit={unit}
        showLegend={false}
        countingContract={report.counting_contract}
        direction={report.policies[0]?.direction}
      />
      <StudyImage
        jobId={jobId}
        kind="fragment"
        identifier={fragment.id}
        regionId={regionId}
        label={fragment.smiles}
        active={active}
      />
      <p>
        {t('强活性 {strong}/{total}', {
          strong: fragment.strong_count,
          total: fragment.molecule_count,
        })}
      </p>
      <p>
        {t('更强 {better} · 更弱 {worse} · 未确定 {indeterminate} · 缺失 {missing}', {
          better: fragment.better,
          worse: fragment.worse,
          indeterminate: fragment.indeterminate,
          missing: fragment.missing,
        })}
      </p>
      <button type="button" onClick={() => onRows(regionId, fragment.id)}>
        {t('查看支持与反例')}
      </button>
    </article>
  );
}
function RegionGroup({
  summary,
  index,
  jobId,
  active,
  strongest,
  onRows,
  report,
}: {
  summary: StudyRegionSummary;
  index: number;
  jobId: string;
  active: boolean;
  strongest: boolean;
  onRows: (region: string, fragment: string) => void;
  report: StudyReport;
}) {
  const { t } = useTranslation(),
    [page, setPage] = useState(1);
  const [unit, setUnit] = useState<CountingUnit>('molecules');
  const fragments = strongest
    ? summary.fragments
        .filter((f) => f.strong_count > 0)
        .toSorted((a, b) => b.strong_count - a.strong_count)
    : summary.fragments;
  return (
    <article className="sar-region-group">
      <h3>
        {summary.region.name ?? 'R' + index} · {summary.reference_label}
      </h3>
      <p className="sar-hint">{t('一个固定背景中的严格参考证据，不是独立系列普遍规律。')}</p>
      <p>
        {t('匹配 {matched} · 未匹配 {not_matched} · 歧义 {ambiguous} · 不合格 {ineligible}', {
          matched: summary.matched,
          not_matched: summary.not_matched,
          ambiguous: summary.ambiguous,
          ineligible: summary.ineligible,
        })}
      </p>
      <p>
        {t('可比较数量')} {summary.comparable}
      </p>
      {summary.no_variation && <output>{t('该区域没有观察到结构变化。')}</output>}
      <div className="sar-fragment-controls">
        <label>
          {t('统计单位')}
          <select
            value={report.counting_contract === 'unique-molecules-v2' ? unit : 'observations'}
            onChange={(event) => setUnit(event.target.value as CountingUnit)}
          >
            <option value="molecules" disabled={report.counting_contract !== 'unique-molecules-v2'}>
              {t('原始编号 / 记录')}
            </option>
            <option value="observations">{t('观察数')}</option>
          </select>
        </label>
      </div>
      <div className="sar-fragment-strip">
        {fragments.slice((page - 1) * 6, page * 6).map((fragment) => (
          <FragmentCard
            key={fragment.id}
            index={summary.fragments.findIndex((f) => f.id === fragment.id) + 1}
            fragment={fragment}
            regionId={summary.region.id}
            jobId={jobId}
            active={active}
            onRows={onRows}
            unit={unit}
            report={report}
          />
        ))}
      </div>
      <ChartLegend
        bins={report.distributions[0]?.bins ?? []}
        direction={report.policies[0]?.direction}
      />
      {!fragments.length && <p>{t(strongest ? '无强活性支持片段' : '无片段记录')}</p>}
      <GroupPager page={page} total={fragments.length} size={6} onPage={setPage} />
    </article>
  );
}
export function StudyRegions({
  report,
  jobId,
  active,
  strongest = false,
  onRows,
}: {
  report: StudyReport;
  jobId: string;
  active: boolean;
  strongest?: boolean;
  onRows: (region: string, fragment: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div>
      {!strongest && <StudyRegionMap report={report} active={active} />}
      {report.regions.map((summary, index) => (
        <RegionGroup
          key={summary.region.id}
          index={index + 1}
          summary={summary}
          jobId={jobId}
          active={active}
          strongest={strongest}
          onRows={onRows}
          report={report}
        />
      ))}
      {!report.regions.length && <p>{t('本研究未选择区域。保存区域后可明确运行新研究。')}</p>}
    </div>
  );
}
