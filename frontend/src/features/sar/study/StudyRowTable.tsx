import type { ResultColumn } from '../../../model/resultColumns';
import type { StudyContext, StudyRow } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { TableScroll } from '../TableScroll';
import { StudyImage } from './StudyImage';
import { candidateLabels } from './RowFacts';
import { contextLabel } from './policyDraft';
import { propertyText, studyProperties } from './tablePresentation';
export function studyColumns(
  contexts: StudyContext[],
  translate: (source: string) => string,
): ResultColumn[] {
  return [
    { id: 'label', label: translate('原文编号') },
    { id: 'structure', label: translate('研究结构') },
    ...contexts.map((c) => ({
      id: 'context:' + c.id,
      label: contextLabel(c),
      context: Object.entries(c.context)
        .map(([key, value]) => key + ': ' + (value ?? '—'))
        .join(' · '),
    })),
    ...studyProperties.map((p) => ({ id: 'property:' + p.key, label: p.label, context: p.unit })),
    { id: 'lead', label: 'Lead' },
    { id: 'source', label: translate('来源详情') },
  ].map((c) => ({ ...c, className: '', width: 120, min: 64, max: 480 }));
}
export function StudyRowTable({
  jobId,
  rows,
  columns,
  hidden,
  active,
  onSource,
}: {
  jobId: string;
  rows: StudyRow[];
  columns: ResultColumn[];
  hidden: string[];
  active: boolean;
  onSource: (id: string, row: StudyRow) => void;
}) {
  const { t } = useTranslation(),
    visible = columns.filter((c) => !hidden.includes(c.id));
  function cell(row: StudyRow, column: ResultColumn) {
    if (column.id === 'label') return row.label;
    if (column.id === 'structure')
      return row.eligible ? (
        <StudyImage
          jobId={jobId}
          kind="molecule"
          identifier={row.molecule_id}
          label={row.label}
          active={active}
        />
      ) : (
        t('不可分析')
      );
    if (column.id.startsWith('context:')) {
      const id = column.id.slice(8);
      return (
        <span title={row.activity_status[id]}>
          {(row.values[id] ?? []).map((value, index) => (
            <div key={index}>{value}</div>
          ))}
        </span>
      );
    }
    if (column.id.startsWith('property:')) {
      const key = column.id.slice(9),
        value = row.properties[key];
      return (
        <span
          title={[
            value == null ? '—' : String(value),
            row.property_origins[key] ?? 'not_provided',
          ].join(' · ')}
        >
          {propertyText(value)}
        </span>
      );
    }
    if (column.id === 'lead')
      return (
        <button
          type="button"
          className="sar-lead-mark"
          title={row.reasons.join(' · ')}
          onClick={() => onSource(row.molecule_id, row)}
        >
          {t(candidateLabels[row.candidate_status])}
          {row.priority_group !== null && <small> · {row.priority_group}</small>}
        </button>
      );
    return (
      <button type="button" onClick={() => onSource(row.molecule_id, row)}>
        {t('来源详情')}
      </button>
    );
  }
  return (
    <TableScroll label={t('研究活性表')}>
      <table className="sar-study-table">
        <thead>
          <tr>
            {visible.map((column) => (
              <th key={column.id} title={column.context}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.molecule_id}>
              {visible.map((column) =>
                column.id === 'label' ? (
                  <th scope="row" key={column.id}>
                    {cell(row, column)}
                  </th>
                ) : (
                  <td key={column.id}>{cell(row, column)}</td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}
