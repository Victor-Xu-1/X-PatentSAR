import type { StudyContext } from '../../../api/sarStudyTypes';
import { useState } from 'react';
import { useTranslation } from '../../../i18n';
import { contextLabel, policyFromDraft } from './policyDraft';
import type { PolicyDraft } from './policyDraft';
export function PolicyEditor({
  context,
  draft,
  onChange,
}: {
  context: StudyContext;
  draft: PolicyDraft;
  onChange: (draft: PolicyDraft) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <fieldset className="sar-policy">
      <legend>{contextLabel(context)}</legend>
      <div className="sar-form-grid">
        <label>
          {t('活性方向')}
          <select
            value={draft.direction}
            onChange={(e) =>
              onChange({ ...draft, direction: e.target.value as PolicyDraft['direction'] })
            }
          >
            <option value="">{t('请选择方向')}</option>
            <option value="lower">{t('越低越强')}</option>
            <option value="higher">{t('越高越强')}</option>
          </select>
        </label>
        <details
          className="sar-compact"
          open={open}
          onToggle={(event) => setOpen(event.currentTarget.open)}
        >
          <summary>{t('研究等级与阈值（可选）')}</summary>
          <div hidden={!open}>
            <label>
              {t('强活性阈值（可选，原始数值）')}
              <input
                inputMode="decimal"
                maxLength={100}
                value={draft.threshold}
                onChange={(e) => onChange({ ...draft, threshold: e.target.value })}
              />
            </label>
            <label>
              {t('等级顺序（可选，最强在前，每行一个原始等级）')}
              <textarea
                maxLength={6000}
                rows={2}
                value={draft.grades}
                onChange={(e) => onChange({ ...draft, grades: e.target.value })}
              />
            </label>
            <label className="sar-checkbox">
              <input
                type="checkbox"
                checked={draft.inclusive}
                onChange={(e) => onChange({ ...draft, inclusive: e.target.checked })}
              />
              {t('阈值包含边界')}
            </label>
          </div>
        </details>
      </div>
      {!policyFromDraft(context.id, draft) && (
        <p className="sar-hint">{t('明确方向；可选等级须唯一，可选阈值须为有限数值。')}</p>
      )}
      {draft.grades.trim() && draft.threshold.trim() && (
        <p role="alert">{t('等级顺序与数值阈值不能同时使用。')}</p>
      )}
    </fieldset>
  );
}
