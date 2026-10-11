import { useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import type { StudyRegionSummary, StudyReport, StudyRow } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { StudyImage } from './StudyImage';
import { NetworkBranchReadings } from './NetworkBranchReadings';
import { regionMarker } from './regionMarker';

export function NetworkBranchCard({
  row,
  report,
  sites,
  siteOrder,
  jobId,
  active,
  fragments,
  onCompare,
}: {
  row: StudyRow;
  report: StudyReport;
  sites: StudyRegionSummary[];
  siteOrder?: ReadonlyMap<string, number>;
  jobId: string;
  active: boolean;
  fragments: boolean;
  onCompare: (site: StudyRegionSummary, molecule: string, trigger: HTMLButtonElement) => void;
}) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState('');
  const site = sites.find((item) => item.region.id === selected) ?? sites[0];
  const fragment = fragments
    ? site?.fragments.find(
        (item) => !item.is_reference && item.molecule_ids.includes(row.molecule_id),
      )
    : undefined;
  const available = !!site && (!fragments || !!fragment);
  function marker(item: StudyRegionSummary, index: number) {
    return regionMarker(item.region, siteOrder?.get(item.region.id) ?? index);
  }
  return (
    <article className="sar-network-branch">
      {available ? (
        <StudyImage
          jobId={jobId}
          kind={fragment ? 'fragment' : 'molecule'}
          identifier={fragment?.id ?? row.molecule_id}
          {...(fragment ? { regionId: site!.region.id } : { atomRegionId: site!.region.id })}
          label={fragment ? t('{identifier} · 变化片段', { identifier: row.label }) : row.label}
          active={active}
          inspectable
        />
      ) : (
        <div className="sar-structure-pending">{t('片段结构不可用')}</div>
      )}
      {fragment?.representation === 'aromatic_graph' && <small>{t('芳香子图')}</small>}
      <div className="sar-branch-sites" aria-label={t('变化区域')}>
        {sites.length > 3 ? (
          <select
            aria-label={t('变化区域') + ' · ' + row.label}
            value={site?.region.id ?? ''}
            onChange={(event) => setSelected(event.target.value)}
          >
            {sites.map((item, index) => (
              <option key={item.region.id} value={item.region.id}>
                {marker(item, index).caption}
              </option>
            ))}
          </select>
        ) : sites.length === 1 ? (
          <span className="sar-branch-site-label">{marker(sites[0]!, 0).caption}</span>
        ) : (
          sites.map((item, index) => {
            const region = marker(item, index);
            return (
              <button
                key={item.region.id}
                type="button"
                aria-label={t('查看区域 {region}', { region: region.caption })}
                aria-pressed={site?.region.id === item.region.id}
                onClick={() => setSelected(item.region.id)}
              >
                {region.caption}
              </button>
            );
          })
        )}
      </div>
      <button
        type="button"
        className="sar-network-compare"
        disabled={!available}
        onClick={(event) => {
          if (site) onCompare(site, row.molecule_id, event.currentTarget);
        }}
        aria-label={t('比较 {identifier}', { identifier: row.label })}
      >
        <strong>{row.label}</strong>
        <ArrowUpRight size={16} />
      </button>
      <NetworkBranchReadings row={row} report={report} />
    </article>
  );
}
