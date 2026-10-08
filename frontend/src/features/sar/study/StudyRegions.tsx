import { useState } from 'react';
import type { StudyFragment, StudyRegionSummary, StudyReport } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { StudyImage } from './StudyImage';
import { StudyBars } from './StudyBars';
import { GroupPager } from './GroupPager';
function FragmentCard({
  fragment,
  index,
  regionId,
  jobId,
  active,
  onRows,
}: {
  fragment: StudyFragment;
  index: number;
  regionId: string;
  jobId: string;
  active: boolean;
  onRows: (region: string, fragment: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <article className="sar-study-card">
      <h4>
        {t('片段 {index}', { index })}
        {fragment.is_reference && <small> · {t('参考')}</small>}
      </h4>
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
      <StudyBars bins={fragment.bins} />
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
}: {
  summary: StudyRegionSummary;
  index: number;
  jobId: string;
  active: boolean;
  strongest: boolean;
  onRows: (region: string, fragment: string) => void;
}) {
  const { t } = useTranslation(),
    [page, setPage] = useState(1);
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
      {!strongest && (
        <StudyImage
          jobId={jobId}
          kind="molecule"
          identifier={summary.region.molecule_id}
          atomRegionId={summary.region.id}
          label={summary.reference_label}
          active={active}
        />
      )}
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
          />
        ))}
      </div>
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
      {report.regions.map((summary, index) => (
        <RegionGroup
          key={summary.region.id}
          index={index + 1}
          summary={summary}
          jobId={jobId}
          active={active}
          strongest={strongest}
          onRows={onRows}
        />
      ))}
      {!report.regions.length && <p>{t('本研究未选择区域。保存区域后可明确运行新研究。')}</p>}
    </div>
  );
}
