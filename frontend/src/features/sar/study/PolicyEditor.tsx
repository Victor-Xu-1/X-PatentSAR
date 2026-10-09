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
          <summary>{t('原文等级（可选）')}</summary>
          <div hidden={!open}>
            <label>
              {t('等级顺序（可选，最强在前，每行一个原始等级）')}
              <textarea
                maxLength={6000}
                rows={2}
                value={draft.grades}
                onChange={(e) => onChange({ ...draft, grades: e.target.value })}
              />
            </label>
          </div>
        </details>
      </div>
      {!policyFromDraft(context.id, draft) && (
        <p className="sar-hint">{t('明确方向；原文等级须唯一。')}</p>
      )}
      {!draft.grades.trim() && <p className="sar-hint">{t('浓度活性自动按第十名数量级分档。')}</p>}
    </fieldset>
  );
}
