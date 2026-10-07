import type { StageName } from '../api/types';
import { stageLabels } from './presentation';

export interface AcceptanceIssue {
  message: string;
  stages: string[];
}
export interface AcceptanceIssueGroup {
  subject: string | null;
  issues: AcceptanceIssue[];
}

const stageAliases: Record<string, StageName> = { final_export: 'final', final_qa: 'qa' };
const explicitIdentifier =
  /^(Compound\s+[A-Za-z0-9][A-Za-z0-9._/-]{0,79}|(?:[IVX]{1,5}-)?\d{1,8}[A-Za-z]{0,6}(?:[-.]\d+[A-Za-z]*)*):\s*(.+)$/u;

/** Presentation only: retain every distinct message and its reporting stages. */
export function acceptanceIssueGroups(errors: readonly string[]): AcceptanceIssueGroup[] {
  const groups = new Map<string | null, AcceptanceIssueGroup>();
  for (const raw of errors) {
    let text = raw;
    let source: string | null = null;
    const prefix = /^([a-z_]+):\s*(.+)$/su.exec(text);
    if (prefix) {
      const stage = Object.hasOwn(stageAliases, prefix[1]!)
        ? stageAliases[prefix[1]!]!
        : prefix[1]!;
      if (Object.hasOwn(stageLabels, stage)) {
        source = stageLabels[stage as StageName];
        text = prefix[2]!;
      }
    }
    const identifier = explicitIdentifier.exec(text);
    const subject = identifier?.[1] ?? null;
    const message = identifier?.[2] ?? text;
    let group = groups.get(subject);
    if (!group) {
      group = { subject, issues: [] };
      groups.set(subject, group);
    }
    let issue = group.issues.find((value) => value.message === message);
    if (!issue) {
      issue = { message, stages: [] };
      group.issues.push(issue);
    }
    if (source && !issue.stages.includes(source)) issue.stages.push(source);
  }
  return [...groups.values()];
}

export function acceptanceIssueCount(groups: readonly AcceptanceIssueGroup[]): string {
  const subjects = groups.filter((group) => group.subject !== null).length;
  const other = groups.find((group) => group.subject === null)?.issues.length ?? 0;
  return [subjects ? `${subjects} 条结构` : '', other ? `${other} 项其他检查` : '']
    .filter(Boolean)
    .join('、');
}
