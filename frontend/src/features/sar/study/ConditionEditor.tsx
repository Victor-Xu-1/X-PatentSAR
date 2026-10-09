import type { Dataset } from '../../../api/sarTypes';
import type { StudyContext } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { sourceHash } from '../presentation';
import { conditionFields, declarationFromDraft, missingCondition } from './conditionDraft';
import type { ConditionDraft } from './conditionDraft';

const labels = {
  target: '靶点',
  assay: '实验方法',
  cell_line: '细胞系',
  duration: '处理时长',
} as const;
export function ConditionEditor({
  dataset,
  context,
  draft,
  onChange,
}: {
  dataset: Dataset;
  context: StudyContext;
  draft: ConditionDraft;
  onChange: (draft: ConditionDraft) => void;
}) {
  const { t } = useTranslation();
  const missing = conditionFields.filter((key) => missingCondition(context.context[key]));
  const rawPage = Number(draft.pages.trim().split(/[,，\s]+/)[0]);
  const page =
    Number.isInteger(rawPage) && rawPage >= 1 && rawPage <= (dataset.source_page_count ?? 0)
      ? rawPage
      : null;
  if (!missing.length) return null;
  if (
    dataset.source_kind !== 'project' ||
    !dataset.source_document_sha256 ||
    !dataset.source_page_count
  ) {
    return (
      <p className="sar-hint">
        {t('实验条件未完整记录。完整 CSV 可映射条件列；旧项目快照请重新创建后核对原文。')}
      </p>
    );
  }
  return (
    <details className="sar-condition-editor">
      <summary>{t('核对并记录缺失的实验条件')}</summary>
      <label className="sar-checkbox">
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(event) => onChange({ ...draft, enabled: event.target.checked })}
        />
        {t('我已核对原文，在本研究中记录条件')}
      </label>
      {draft.enabled && (
        <>
          <p className="sar-hint">{t('只补充缺失字段；不改原始数据，不替代科学验收。')}</p>
          <div className="sar-form-grid">
            {missing.map((key) => (
              <label key={key}>
                {t(labels[key])}
                <input
                  maxLength={1000}
                  value={draft.fields[key] ?? ''}
                  onChange={(event) =>
                    onChange({ ...draft, fields: { ...draft.fields, [key]: event.target.value } })
                  }
                />
              </label>
            ))}
            <label>
              {t('原文页码（逗号分隔）')}
              <input
                maxLength={100}
                inputMode="numeric"
                value={draft.pages}
                onChange={(event) => onChange({ ...draft, pages: event.target.value })}
              />
            </label>
          </div>
          <label>
            {t('原文核对说明')}
            <textarea
              rows={2}
              maxLength={2000}
              value={draft.note}
              onChange={(event) => onChange({ ...draft, note: event.target.value })}
            />
          </label>
          {sourceHash(dataset) && (
            <a href={sourceHash(dataset, undefined, page)!}>{t('查看原文')}</a>
          )}
          {!declarationFromDraft(dataset, context, draft) && (
            <output>{t('填写实际条件、有效页码与核对说明后方可提交。')}</output>
          )}
        </>
      )}
    </details>
  );
}
