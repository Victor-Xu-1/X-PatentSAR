import type { StudyPreview } from '../../../api/sarStudyTypes';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useTranslation } from '../../../i18n';
import { useScrollFocus } from '../../../components/useScrollFocus';
import { propertyText, studyProperties } from './tablePresentation';
import { propertyComparisonMessage } from './propertyComparisonMessage';
import { propertyDelta } from './propertyDelta';

export function PreviewProperties({ data }: { data: StudyPreview }) {
  const { t } = useTranslation();
  const { viewport, content, edges, scrollPage } = useScrollFocus<HTMLDivElement, HTMLTableElement>(
    'x',
  );
  return (
    <section className="sar-property-panel" aria-label={t('性质')}>
      <div
        ref={viewport}
        className="sar-property-comparison sar-table-scroll"
        aria-label={t('性质')}
      >
        <table ref={content} className="sar-property-table" aria-label={t('性质')}>
          <thead>
            <tr>
              <th scope="col">{t('性质')}</th>
              {studyProperties.map((property) => (
                <th key={property.key} scope="col" title={property.unit}>
                  {property.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[data.reference, data.candidate].map((row) => (
              <tr key={row.molecule_id}>
                <th scope="row">{row.label}</th>
                {studyProperties.map((property) => (
                  <td key={property.key} title={row.property_origins[property.key] ?? undefined}>
                    {propertyText(row.properties[property.key], property.key)}
                  </td>
                ))}
              </tr>
            ))}
            <tr>
              <th scope="row">Δ</th>
              {studyProperties.map((property) => {
                const delta = propertyDelta(data, property.key);
                const reason = propertyComparisonMessage(data.property_statuses?.[property.key]);
                return (
                  <td
                    key={property.key}
                    title={
                      reason
                        ? t(reason)
                        : delta.raw != null
                          ? t('原始差值') + ': ' + delta.raw
                          : undefined
                    }
                  >
                    {delta.text}
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>
      {edges.overflow && (
        <div className="sar-property-controls">
          <button
            type="button"
            aria-label={t('向左滚动性质')}
            title={t('向左滚动性质')}
            disabled={!edges.start}
            onClick={() => scrollPage(-1)}
          >
            <ChevronLeft size={15} />
          </button>
          <button
            type="button"
            aria-label={t('向右滚动性质')}
            title={t('向右滚动性质')}
            disabled={!edges.end}
            onClick={() => scrollPage(1)}
          >
            <ChevronRight size={15} />
          </button>
        </div>
      )}
    </section>
  );
}
