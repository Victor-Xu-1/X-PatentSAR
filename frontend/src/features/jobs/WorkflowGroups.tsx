import { useTranslation } from '../../i18n';
import { CheckCircle2, ChevronRight, Circle, CircleAlert, LoaderCircle } from 'lucide-react';
import type { Job } from '../../api/types';
import { workflowGroups, workflowGroupStateText } from '../../model/workflowGroups';

export function WorkflowGroups({ job, verified = true }: { job: Job | null; verified?: boolean }) {
  const { t } = useTranslation();
  const groups = workflowGroups(job);
  if (!job || groups.length < 2) return null;
  return (
    <span className="workflow-groups" aria-label={t('阶段分组')}>
      {groups.map((group, index) => {
        const state = verified ? group.state : 'unknown';
        return (
          <span
            className={`workflow-group ${state}`}
            key={group.key}
            title={verified ? group.description : t('阶段状态未知')}
            aria-label={t('{label}：{state}', {
              label: group.label,
              state: t(workflowGroupStateText[state]),
            })}
          >
            {index > 0 && (
              <ChevronRight size={14} className="workflow-group-separator" aria-hidden="true" />
            )}
            {state === 'ok' ? (
              <CheckCircle2 size={20} aria-hidden="true" />
            ) : state === 'running' ? (
              <LoaderCircle size={20} className="spin" aria-hidden="true" />
            ) : ['failed', 'review', 'warnings'].includes(state) ? (
              <CircleAlert size={20} aria-hidden="true" />
            ) : (
              <Circle size={20} aria-hidden="true" />
            )}
            <span>{group.compactLabel}</span>
          </span>
        );
      })}
    </span>
  );
}
