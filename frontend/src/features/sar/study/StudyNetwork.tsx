import { useMemo, useState } from 'react';
import type { StudyReport } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { GroupPager } from './GroupPager';
import { StudyImage } from './StudyImage';
import { StudyRegionMap } from './StudyRegionMap';
import { NetworkBranches } from './NetworkBranches';
import { coreChoices, orderCores } from './coreChoices';
import type { CoreOrder } from './coreChoices';

export function StudyNetwork({
  report,
  jobId,
  active,
  strongest = false,
  fragments = false,
  onSource,
  onRows,
}: {
  report: StudyReport;
  jobId: string;
  active: boolean;
  strongest?: boolean;
  fragments?: boolean;
  onSource: (id: string) => void;
  onRows?: ((reference: string, region: string) => void) | undefined;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState(''),
    [page, setPage] = useState(1);
  const [reference, setReference] = useState(''),
    [site, setSite] = useState('');
  const [allSites, setAllSites] = useState(false);
  const [order, setOrder] = useState<CoreOrder>('alternatives');
  const collection = useMemo(() => coreChoices(report), [report]);
  const centres = useMemo(() => orderCores(collection, order), [collection, order]);
  const multiple = centres.length > 1;
  const filtered = multiple
    ? centres.filter((centre) => centre.label.toLowerCase().includes(search.toLowerCase().trim()))
    : centres;
  // Search is gallery navigation, not authority to replace a working reference
  // or its selected site. Only explicit core selection changes that context.
  const selected = centres.find((centre) => centre.id === reference) ?? centres[0];
  const compact = selected?.compact ?? [];
  const visibleSites = allSites ? (selected?.sites ?? []) : compact;
  const summary = visibleSites.find((item) => item.region.id === site);
  const mapSites = visibleSites.map((item, index) =>
    item.origin === 'single_site'
      ? { ...item, region: { ...item.region, name: 'R' + (index + 1) } }
      : item,
  );
  const showing = multiple ? filtered.slice((page - 1) * 6, page * 6) : filtered;
  const matches = useMemo(
    () =>
      new Set(
        report.regions.flatMap((item) =>
          item.fragments
            .filter((fragment) => !fragment.is_reference)
            .flatMap((fragment) =>
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
        {multiple && (
          <>
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
            <select
              aria-label={t('核心排序')}
              value={order}
              onChange={(event) => {
                const next = event.target.value;
                if (next !== 'alternatives' && next !== 'identifier') return;
                // Reordering the gallery must not discard the current reference,
                // selected region or an in-progress inspection.
                setReference(selected?.id ?? '');
                setOrder(next);
                const index = orderCores(collection, next)
                  .filter((core) => core.label.toLowerCase().includes(search.toLowerCase().trim()))
                  .findIndex((core) => core.id === selected?.id);
                setPage(Math.floor(Math.max(0, index) / 6) + 1);
              }}
            >
              <option value="alternatives">{t('改造最多')}</option>
              <option value="identifier">{t('按原文编号')}</option>
            </select>
          </>
        )}
        <span>
          {t(centres.length === 1 ? '1 个核心' : '{count} 个核心', { count: centres.length })} ·{' '}
          {t(matches.size === 1 ? '1 对变化' : '{count} 对变化', { count: matches.size })}
        </span>
      </div>
      {multiple && (
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
                  if (centre.id !== selected?.id) setSite('');
                }}
              >
                <strong>{centre.label}</strong>
                <small>
                  {t(centre.alternativeCount === 1 ? '1 个改造' : '{count} 个改造', {
                    count: centre.alternativeCount,
                  })}
                </small>
              </button>
            </article>
          ))}
        </div>
      )}
      {multiple && <GroupPager page={page} size={6} total={filtered.length} onPage={setPage} />}
      {!showing.length && (
        <p>
          {t(
            !report.discovery && !report.regions.length
              ? '本研究未选择区域。保存区域后可明确运行新研究。'
              : centres.length > 0 && search.trim()
                ? '未找到匹配的核心'
                : '没有可显示的核心结构',
          )}
        </p>
      )}
      {selected && visibleSites.length > 0 && (
        <>
          <div className="sar-network-view-tools">
            <button
              type="button"
              className="button secondary"
              aria-pressed={!summary}
              onClick={() => setSite('')}
            >
              {t('全部改造方向')}
            </button>
            {onRows && (
              <button
                type="button"
                className="button secondary"
                onClick={() => onRows(selected.id, summary?.region.id ?? '')}
              >
                {t('查看分子')}
              </button>
            )}
          </div>
          <div className={'sar-network-layout' + (fragments ? '' : ' sar-network-matrix-layout')}>
            <div className="sar-network-map">
              <StudyRegionMap
                report={{ ...report, regions: mapSites }}
                active={active}
                selected={summary?.region.id}
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
              key={(summary?.region.id ?? selected.id) + ':' + strongest + ':' + fragments}
              report={report}
              summary={mapSites.find((item) => item.region.id === summary?.region.id)}
              summaries={mapSites}
              referenceId={selected.id}
              jobId={jobId}
              active={active}
              strongest={strongest}
              fragments={fragments}
              onSource={onSource}
            />
          </div>
        </>
      )}
      {report.discovery && (
        <details className="sar-compact sar-network-scope">
          <summary>{t('搜索范围')}</summary>
          <p>
            {t(
              report.discovery?.method === 'single-region-three-port-multiple-h-v6'
                ? '单一区域，最多三个连接点；支持芳香环、非立体多重键、氢位点与桥环变化。固定结构严格不变；氢与双键边界手性及更多连接点仍受限。'
                : report.discovery?.method === 'single-region-three-port-aromatic-h-v5'
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
      )}
    </section>
  );
}
