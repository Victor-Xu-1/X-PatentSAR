import { acceptanceIssueCount, acceptanceIssueGroups } from '../../model/acceptanceIssues';
import type { AcceptanceIssue } from '../../model/acceptanceIssues';

function Issues({ issues }: { issues: readonly AcceptanceIssue[] }) {
  return (
    <ul>
      {issues.map((issue) => (
        <li key={issue.message}>
          <span>{issue.message}</span>
          {issue.stages.length > 0 && <small className="muted">{issue.stages.join('、')}</small>}
        </li>
      ))}
    </ul>
  );
}

export function AcceptanceFindings({ errors, open }: { errors: readonly string[]; open: boolean }) {
  const groups = acceptanceIssueGroups(errors);
  if (groups.length === 0) return null;
  return (
    <details open={open}>
      <summary>查看核心验收问题（{acceptanceIssueCount(groups)}）</summary>
      {groups.map((group) =>
        group.subject === null ? (
          <Issues issues={group.issues} key="other" />
        ) : (
          <details key={group.subject}>
            <summary>
              <span>{group.subject}</span>
            </summary>
            <Issues issues={group.issues} />
          </details>
        ),
      )}
    </details>
  );
}
