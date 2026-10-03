import type { Activity, ActivityColumn } from '../api/types';
import { activityContextKey } from '../api/activityColumnDecoders';

export interface TableActivityColumn extends ActivityColumn {
  legacy?: true;
}
export function tableActivityColumns(
  catalog: ActivityColumn[] | undefined,
  names: string[],
): TableActivityColumn[] {
  // Name-only legacy API observations cannot claim a complete context catalog.
  // Current software always supplies the project-wide catalog before pagination.
  if (catalog === undefined)
    return names.map((name) => ({
      id: `legacy:${name}`,
      name,
      unit: null,
      target: null,
      assay: null,
      legacy: true,
    }));
  const selectedNames = new Set(names);
  return catalog.filter((column) => selectedNames.has(column.name));
}
export function activityColumnLabel(column: TableActivityColumn): string {
  return column.unit && !column.name.includes(`(${column.unit})`)
    ? `${column.name} (${column.unit})`
    : column.name;
}
export function activityColumnContext(column: TableActivityColumn): string {
  return [column.target, column.assay]
    .filter((value): value is string => Boolean(value))
    .join(' · ');
}
export function activityColumnValues(
  activities: Activity[],
  columns: TableActivityColumn[],
): Activity[][] {
  const exact = new Map<string, Activity[]>(),
    byName = new Map<string, Activity[]>();
  for (const activity of activities) {
    const key = activityContextKey(activity);
    if (!exact.has(key)) exact.set(key, []);
    exact.get(key)!.push(activity);
    if (!byName.has(activity.name)) byName.set(activity.name, []);
    byName.get(activity.name)!.push(activity);
  }
  return columns.map(
    (column) =>
      (column.legacy ? byName.get(column.name) : exact.get(activityContextKey(column))) ?? [],
  );
}
