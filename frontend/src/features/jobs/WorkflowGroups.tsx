import { CheckCircle2, ChevronRight, Circle, CircleAlert, LoaderCircle } from 'lucide-react';
import type { Job } from '../../api/types';
import { workflowGroups, workflowGroupStateText } from '../../model/workflowGroups';

export function WorkflowGroups({ job }: { job: Job | null }) {
  const groups = workflowGroups(job);
  if (!job || groups.length < 2) return null;
  return (
    <span className="workflow-groups" aria-label="阶段分组">
      {groups.map((group, index) => (
        <span
          className={`workflow-group ${group.state}`}
          key={group.key}
          title={group.description}
          aria-label={`${group.label}：${workflowGroupStateText[group.state]}`}
        >
          {index > 0 && (
            <ChevronRight size={14} className="workflow-group-separator" aria-hidden="true" />
          )}
          {group.state === 'ok' ? (
            <CheckCircle2 size={20} aria-hidden="true" />
          ) : group.state === 'running' ? (
            <LoaderCircle size={20} className="spin" aria-hidden="true" />
          ) : ['failed', 'review', 'warnings'].includes(group.state) ? (
            <CircleAlert size={20} aria-hidden="true" />
          ) : (
            <Circle size={20} aria-hidden="true" />
          )}
          <span>{group.label}</span>
        </span>
      ))}
    </span>
  );
}
