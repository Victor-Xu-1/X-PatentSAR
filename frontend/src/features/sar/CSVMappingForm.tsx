import { useState } from 'react';
import type { CSVMapping, CSVPreview } from '../../api/sarTypes';
import { useTranslation } from '../../i18n';
import { initialMapping, mappingValid } from './csvMapping';
import type { MappingDraft } from './csvMapping';
import { newRequestId } from './presentation';
export function CSVMappingForm({
  preview,
  disabled,
  onSubmit,
}: {
  preview: CSVPreview;
  disabled: boolean;
  onSubmit: (mapping: CSVMapping) => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(() => initialMapping(preview));
  const invalidLong = Boolean(draft.metric_column && draft.activity_columns.length !== 1);
  function column(key: keyof MappingDraft, label: string, optional = false) {
    return (
      <label>
        {t(label)}
        <select
          aria-invalid={(key === 'metric_column' && invalidLong) || undefined}
          value={String(draft[key] ?? '')}
          onChange={(e) =>
            setDraft((old) => ({ ...old, [key]: e.target.value || (optional ? null : '') }))
          }
        >
          <option value="">{t(optional ? '不映射' : '请选择活性指标')}</option>
          {preview.headers.map((header) => (
            <option value={header} key={header}>
              {header}
            </option>
          ))}
        </select>
      </label>
    );
  }
  return (
    <form
      className="sar-mapping"
      onSubmit={(event) => {
        event.preventDefault();
        if (!disabled && mappingValid(draft, preview))
          onSubmit({ ...draft, token: preview.token, request_id: newRequestId() });
      }}
    >
      <fieldset disabled={disabled}>
        <legend>{t('CSV 映射')}</legend>
        <p className="sar-hint">{t('建议列仅供参考，提交前请核对原始表头与样例。')}</p>
        <div className="sar-form-grid">
          <label>
            {t('数据集名称')}
            <input
              value={draft.title}
              maxLength={200}
              onChange={(e) => setDraft((old) => ({ ...old, title: e.target.value }))}
            />
          </label>
          {column('id_column', '原文编号列')}
          {column('smiles_column', 'SMILES 列')}
          {column('metric_column', '指标名称列（可选）', true)}
          {column('unit_column', '单位列（可选）', true)}
          {column('target_column', '靶点列（可选）', true)}
          {column('assay_column', '实验列（可选）', true)}
          {column('cell_line_column', '细胞系列（可选）', true)}
          {column('duration_column', '时长列（可选）', true)}
        </div>
        <fieldset className="sar-checklist">
          <legend>{t('活性指标列')}</legend>
          {preview.headers.map((header) => (
            <label key={header}>
              <input
                type="checkbox"
                checked={draft.activity_columns.includes(header)}
                onChange={(e) => {
                  const checked = e.target.checked;
                  setDraft((old) => ({
                    ...old,
                    activity_columns: checked
                      ? [...old.activity_columns, header]
                      : old.activity_columns.filter((column) => column !== header),
                  }));
                }}
              />
              {header}
            </label>
          ))}
        </fieldset>
        {invalidLong && (
          <p role="alert">
            {t('指标名称列（可选）')} · {t('活性指标列')}: 1
          </p>
        )}
        {!mappingValid(draft, preview) && <p>{t('请明确选择编号、SMILES 和至少一个活性列。')}</p>}
        <button className="primary" type="submit" disabled={!mappingValid(draft, preview)}>
          {t('创建 CSV 数据集')}
        </button>
      </fieldset>
    </form>
  );
}
