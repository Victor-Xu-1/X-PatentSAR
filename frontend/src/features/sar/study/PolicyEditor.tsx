import type { IndicatorDefault, StudyContext } from '../../../api/sarStudyTypes';
import { useState } from 'react';
import { useTranslation } from '../../../i18n';
import { contextLabel } from '../presentation';
import { policyFromDraft } from './policyDraft';
import type { PolicyDraft } from './policyDraft';
import { IndicatorDirection } from '../IndicatorDirection';
export function PolicyEditor({
  context,
  draft,
  onChange,
  hint,
}: {
  context: StudyContext;
  draft: PolicyDraft;
  onChange: (draft: PolicyDraft) => void;
  hint?: IndicatorDefault | undefined;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <fieldset className="sar-policy">
      <legend>{contextLabel(context)}</legend>
      <div className="sar-form-grid sar-policy-controls">
        <IndicatorDirection
          value={draft.direction}
          hint={hint}
          onChange={(direction) => onChange({ ...draft, direction })}
        />
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
      {(draft.direction || (hint && hint.direction !== 'unknown')) &&
        !policyFromDraft(context.id, draft, hint) && (
          <p className="sar-hint">{t('明确方向；原文等级须唯一。')}</p>
        )}
      {!draft.grades.trim() && (!hint || hint.rule === 'potency') && (
        <p className="sar-hint">{t('浓度活性自动按第十名数量级分档。')}</p>
      )}
    </fieldset>
  );
}
