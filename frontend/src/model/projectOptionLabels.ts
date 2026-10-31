import type { Project } from '../api/types';
import { t } from '../i18n';
import { acceptanceLabels, dateText } from './presentation';

/** Display-only disambiguation; neither source identity nor title is rewritten. */
export function sourceProjectLabels(projects: readonly Project[]): Map<string, string> {
  const titleCounts = new Map<string, number>();
  for (const project of projects)
    titleCounts.set(project.title, (titleCounts.get(project.title) ?? 0) + 1);

  const labels = new Map<string, string>();
  const identicalLabels = new Map<string, string[]>();
  for (const project of projects) {
    const label =
      titleCounts.get(project.title)! > 1
        ? [
            dateText(project.created_at),
            t(project.read_error ? '结果数据需修复' : acceptanceLabels[project.acceptance.state]),
            project.title,
          ].join(' · ')
        : project.title;
    labels.set(project.id, label);
    const ids = identicalLabels.get(label) ?? [];
    ids.push(project.id);
    identicalLabels.set(label, ids);
  }
  for (const [label, ids] of identicalLabels) {
    if (ids.length < 2) continue;
    // Equal timestamps/states are still distinct sources. Stable ordinals avoid
    // exposing internal IDs or silently collapsing records when lists reorder.
    ids.sort().forEach((id, index) => {
      labels.set(id, `${t('来源 {number}', { number: index + 1 })} · ${label}`);
    });
  }
  return labels;
}
