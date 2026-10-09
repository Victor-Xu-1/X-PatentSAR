import type { StudyFilter, StudyReport } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';

export function StudyTableFilters({
  report,
  filter,
  onFilter,
}: {
  report: StudyReport;
  filter: StudyFilter;
  onFilter: (filter: StudyFilter) => void;
}) {
  const { t } = useTranslation();
  function change(patch: Partial<StudyFilter>) {
    onFilter({ ...filter, ...patch });
  }
  return (
    <div className="sar-study-filters">
      <label>
        {t('研究行范围')}
        <select
          value={filter.scope}
          onChange={(e) => change({ scope: e.target.value as StudyFilter['scope'] })}
        >
          <option value="all">{t('全部研究行')}</option>
          <option value="strong">{t('强活性')}</option>
          <option value="leads">{t('研究先导候选')}</option>
        </select>
      </label>
      <label>
        {t('研究骨架')}
        <select
          value={filter.scaffold_id}
          onChange={(e) => change({ scaffold_id: e.target.value })}
        >
          <option value="">{t('全部状态')}</option>
          {report.scaffolds.map((scaffold, index) => (
            <option key={scaffold.id} value={scaffold.id}>
              {t('母核 {index}', { index: index + 1 })} · {scaffold.molecule_count}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t('变化区域')}
        <select
          value={filter.region_id}
          onChange={(e) => change({ region_id: e.target.value, fragment_id: '' })}
        >
          <option value="">{t('全部状态')}</option>
          {report.regions.map(({ region }, index) => (
            <option key={region.id} value={region.id}>
              {region.name ?? 'R' + (index + 1)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t('研究片段')}
        <select
          value={filter.fragment_id}
          onChange={(e) => change({ fragment_id: e.target.value })}
          disabled={!filter.region_id}
        >
          <option value="">{t('全部状态')}</option>
          {report.regions
            .find(({ region }) => region.id === filter.region_id)
            ?.fragments.map((fragment, index) => (
              <option key={fragment.id} value={fragment.id}>
                {t('片段 {index}', { index: index + 1 })} · {fragment.molecule_count}
              </option>
            ))}
        </select>
      </label>
    </div>
  );
}
