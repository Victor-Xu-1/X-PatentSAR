import { ArrowUpRight, FileText } from 'lucide-react';
import type { StudyMatrix, StudyRegionSummary } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { StudyImage } from './StudyImage';
import { regionMarker } from './regionMarker';

export function MatrixHead({
  data,
  sites,
  siteOrder,
  jobId,
  active,
  onSelect,
  onCompare,
  onSource,
}: {
  data: StudyMatrix;
  sites: StudyRegionSummary[][];
  siteOrder: ReadonlyMap<string, number>;
  jobId: string;
  active: boolean;
  onSelect: (molecule: string, region: string) => void;
  onCompare: (site: StudyRegionSummary, molecule: string, button: HTMLButtonElement) => void;
  onSource: (id: string) => void;
}) {
  const { t } = useTranslation();
  const first = data.previews[0]!;
  const rows = [first.reference, ...data.previews.map((preview) => preview.candidate)];
  return (
    <thead>
      <tr>
        <th scope="col">
          <span className="sr-only">{t('记录值')}</span>
        </th>
        {rows.map((row, index) => {
          const preview = data.previews[index - 1];
          const choices = sites[index - 1] ?? [];
          const site = preview && choices.find((item) => item.region.id === preview.region.id);
          return (
            <th
              key={row.molecule_id}
              scope="col"
              className={index === 0 ? 'sar-matrix-baseline' : undefined}
            >
              <div className="sar-matrix-identity">
                {site ? (
                  <button
                    type="button"
                    className="sar-network-compare"
                    aria-label={t('比较 {identifier}', { identifier: row.label })}
                    onClick={(event) => onCompare(site, row.molecule_id, event.currentTarget)}
                  >
                    <strong>{row.label}</strong>
                    <ArrowUpRight size={15} />
                  </button>
                ) : (
                  <strong>{row.label}</strong>
                )}
                <button
                  type="button"
                  className="icon-button"
                  aria-label={t('来源详情 · {identifier}', { identifier: row.label })}
                  onClick={() => onSource(row.molecule_id)}
                >
                  <FileText size={15} />
                </button>
              </div>
              <StudyImage
                jobId={jobId}
                kind="molecule"
                identifier={row.molecule_id}
                label={row.label}
                active={active}
                inspectable
                providedDrawing={
                  index === 0 ? data.reference_drawing : preview!.drawings!.candidate
                }
              />
              {site && choices.length > 1 ? (
                <select
                  aria-label={t('变化区域') + ' · ' + row.label}
                  value={site.region.id}
                  onChange={(event) => onSelect(row.molecule_id, event.target.value)}
                >
                  {choices.map((choice, position) => (
                    <option key={choice.region.id} value={choice.region.id}>
                      {
                        regionMarker(choice.region, siteOrder.get(choice.region.id) ?? position)
                          .caption
                      }
                    </option>
                  ))}
                </select>
              ) : (
                <span className="sar-matrix-site">
                  {site
                    ? regionMarker(site.region, siteOrder.get(site.region.id) ?? 0).caption
                    : t('参考分子')}
                </span>
              )}
              {preview?.drawings?.layout === 'independent' && (
                <small className="sar-preview-layout">{t('独立布局')}</small>
              )}
            </th>
          );
        })}
      </tr>
    </thead>
  );
}
