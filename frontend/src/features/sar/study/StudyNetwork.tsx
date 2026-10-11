import { useMemo, useState } from 'react';
import type { StudyRegionSummary, StudyReport } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { GroupPager } from './GroupPager';
import { StudyImage } from './StudyImage';
import { StudyRegionMap } from './StudyRegionMap';
import { NetworkBranches } from './NetworkBranches';
import { compactNetworkSites } from './networkSites';

export function StudyNetwork({
  report,
  jobId,
  active,
  strongest = false,
  fragments = false,
  onSource,
}: {
  report: StudyReport;
  jobId: string;
  active: boolean;
  strongest?: boolean;
  fragments?: boolean;
  onSource: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState(''),
    [page, setPage] = useState(1);
  const [reference, setReference] = useState(''),
    [site, setSite] = useState('');
  const [allSites, setAllSites] = useState(false);
  const centres = useMemo(() => {
    const groups = new Map<string, { label: string; sites: StudyRegionSummary[] }>();
    for (const summary of report.regions) {
      if (!summary.matched || summary.no_variation) continue;
      const group = groups.get(summary.region.molecule_id) ?? {
        label: summary.reference_label,
        sites: [],
      };
      group.sites.push(summary);
      groups.set(summary.region.molecule_id, group);
    }
    return [...groups.entries()]
      .map(([id, group]) => ({ id, ...group, compact: compactNetworkSites(group.sites) }))
      .toSorted((a, b) => a.label.localeCompare(b.label, 'en', { numeric: true }));
  }, [report.regions]);
  const filtered = centres.filter((centre) =>
    centre.label.toLowerCase().includes(search.toLowerCase().trim()),
  );
  const selected = filtered.find((centre) => centre.id === reference) ?? filtered[0];
  const compact = selected?.compact ?? [];
  const visibleSites = allSites ? (selected?.sites ?? []) : compact;
  const summary = visibleSites.find((item) => item.region.id === site) ?? visibleSites[0];
  const mapSites = visibleSites.map((item, index) =>
    item.origin === 'single_site'
      ? { ...item, region: { ...item.region, name: 'R' + (index + 1) } }
      : item,
  );
  const showing = filtered.slice((page - 1) * 6, page * 6);
  const matches = useMemo(
    () =>
      new Set(
        report.regions.flatMap((item) =>
          item.fragments.flatMap((fragment) =>
            fragment.molecule_ids
              .filter((id) => id !== item.region.molecule_id)
              .map((id) => [id, item.region.molecule_id].sort().join('\0')),
          ),
        ),
      ),
    [report.regions],
  );
  return (
    <section className="sar-network" aria-label={t('单点结构对比')}>
      <div className="sar-network-tools">
        <input
          aria-label={t('查找核心编号')}
          placeholder={t('查找核心编号')}
          value={search}
          maxLength={200}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
        />
        <span>
          {t('{count} 个核心', { count: centres.length })} ·{' '}
          {t('{count} 对变化', { count: matches.size })}
        </span>
      </div>
      <div className="sar-core-gallery" aria-label={t('核心结构')}>
        {showing.map((centre) => (
          <article
            key={centre.id}
            className="sar-core-card"
            data-selected={selected?.id === centre.id}
          >
            <StudyImage
              jobId={jobId}
              kind="molecule"
              identifier={centre.id}
              label={centre.label}
              active={active}
            />
            <button
              type="button"
              aria-label={t('选择核心 {identifier}', { identifier: centre.label })}
              aria-pressed={selected?.id === centre.id}
              onClick={() => {
                setReference(centre.id);
                setSite('');
              }}
            >
              <strong>{centre.label}</strong>
              <small>
                {t('{count} 个位点', {
                  count: allSites ? centre.sites.length : centre.compact.length,
                })}
              </small>
            </button>
          </article>
        ))}
      </div>
      <GroupPager page={page} size={6} total={filtered.length} onPage={setPage} />
      {!showing.length && <p>{t('没有可显示的核心结构')}</p>}
      {selected && summary && (
        <div className="sar-network-layout">
          <div className="sar-network-map">
            <StudyRegionMap
              report={{ ...report, regions: mapSites }}
              active={active}
              selected={summary.region.id}
              onSelect={setSite}
            />
            {selected.sites.length !== compact.length && (
              <button
                type="button"
                className="button secondary"
                aria-pressed={allSites}
                onClick={() => setAllSites((value) => !value)}
              >
                {allSites
                  ? t('精简位点')
                  : t('全部位点（{count}）', { count: selected.sites.length })}
              </button>
            )}
          </div>
          <NetworkBranches
            key={summary.region.id + ':' + strongest + ':' + fragments}
            report={report}
            summary={summary}
            jobId={jobId}
            active={active}
            strongest={strongest}
            fragments={fragments}
            onSource={onSource}
          />
        </div>
      )}
      <details className="sar-compact sar-network-scope">
        <summary>{t('搜索范围')}</summary>
        <p>
          {t(
            report.discovery?.method === 'single-region-three-port-aromatic-h-v5'
              ? '单一区域，最多三个连接点；支持芳香环局部替换、氢位点、支链与桥环。固定结构严格不变；氢边界手性及更多连接点尚未自动枚举。'
              : report.discovery?.method === 'single-region-one-to-three-cut-h-v4'
                ? '单一区域，最多三个连接点；支持氢位点、支链与非芳香桥环变化。固定结构严格不变；氢边界手性、芳香切割及更多连接点尚未自动枚举。'
                : report.discovery?.method === 'single-region-one-two-cut-h-v3'
                  ? '单一变化区域，支持普通氢位点、一至两个连接点及非芳香环片段；其余结构严格不变。氢边界手性、芳香切割及更多连接点仍不支持自动枚举。'
                  : report.discovery?.method === 'single-region-one-two-cut-v2'
                    ? '单一变化区域，支持一至两个连接点及非芳香环片段；其余完整结构严格不变。隐式氢、芳香边界及更多连接点仍需手工区域。'
                    : '自动枚举单个非环单键的连接点，其他完整结构由严格匹配器确认。隐式氢、环内和多连接点变化尚未自动枚举，可继续使用手工区域。',
          )}
        </p>
      </details>
    </section>
  );
}
