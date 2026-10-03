import type { Activity, ActivityColumn, Compound } from '../api/types';
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
export interface ActivityObservation {
  activity: Activity;
  index: number;
  sourceKey: string | undefined;
}
export type ActivitySourceCallback = (row: Compound, activity: Activity, key?: string) => void;
export function activityColumnObservations(
  row: Compound,
  columns: TableActivityColumn[],
): ActivityObservation[][] {
  const exact = new Map<string, ActivityObservation[]>(),
    byName = new Map<string, ActivityObservation[]>();
  for (const [index, activity] of row.activities.entries()) {
    // Preserve the original observation index before grouping columns.
    const observation = { activity, index, sourceKey: row.activity_source_keys?.[index] };
    const key = activityContextKey(activity);
    if (!exact.has(key)) exact.set(key, []);
    exact.get(key)!.push(observation);
    if (!byName.has(activity.name)) byName.set(activity.name, []);
    byName.get(activity.name)!.push(observation);
  }
  return columns.map(
    (column) =>
      (column.legacy ? byName.get(column.name) : exact.get(activityContextKey(column))) ?? [],
  );
}
