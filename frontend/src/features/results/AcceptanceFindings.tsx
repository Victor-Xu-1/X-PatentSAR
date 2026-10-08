import { useTranslation } from '../../i18n';
import { acceptanceIssueGroups } from '../../model/acceptanceIssues';
import type { AcceptanceIssue } from '../../model/acceptanceIssues';

function Issues({ issues }: { issues: readonly AcceptanceIssue[] }) {
  const { locale, t } = useTranslation();
  return (
    <ul>
      {issues.map((issue) => (
        <li key={issue.message}>
          <span>{issue.message}</span>
          {issue.stages.length > 0 && (
            <small className="muted">
              {issue.stages.map((stage) => t(stage)).join(locale === 'en' ? ', ' : '、')}
            </small>
          )}
        </li>
      ))}
    </ul>
  );
}

export function AcceptanceFindings({ errors, open }: { errors: readonly string[]; open: boolean }) {
  const { locale, t } = useTranslation();
  const groups = acceptanceIssueGroups(errors);
  if (groups.length === 0) return null;
  const subjects = groups.filter((group) => group.subject !== null).length;
  const other = groups.find((group) => group.subject === null)?.issues.length ?? 0;
  const count = [
    subjects ? t('{count} 条结构', { count: subjects }) : '',
    other ? t('{count} 项其他检查', { count: other }) : '',
  ]
    .filter(Boolean)
    .join(locale === 'en' ? ', ' : '、');
  return (
    <details open={open}>
      <summary>{t('查看核心验收问题（{count}）', { count })}</summary>
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
