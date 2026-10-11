import type { StudyPreview } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { useScrollFocus } from '../../../components/useScrollFocus';
import { differenceText, propertyText, studyProperties } from './tablePresentation';

export function PreviewProperties({ data }: { data: StudyPreview }) {
  const { t } = useTranslation();
  const { viewport, content } = useScrollFocus<HTMLElement, HTMLTableElement>('x');
  return (
    <section
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
              const value = data.property_differences[property.key];
              return (
                <td key={property.key}>
                  {value != null && value > 0 ? '+' : ''}
                  {differenceText(value, property.key)}
                </td>
              );
            })}
          </tr>
        </tbody>
      </table>
    </section>
  );
}
