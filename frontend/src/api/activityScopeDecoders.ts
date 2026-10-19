import { ContractError, nullable, positive, string } from './validation';

/** Read-only original context metadata; absence preserves legacy API-v1 bytes. */
export interface ActivityScopeFields {
  source_scope?: string | null;
  source_table?: string | null;
  source_context_page?: number | null;
  source_conditions?: Record<string, string | null>;
}
export function decodeActivityScope(input: unknown, path = '$'): ActivityScopeFields {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new ContractError(path);
  const fields = input as Record<string, unknown>,
    result: ActivityScopeFields = {};
  if (Object.hasOwn(fields, 'source_scope')) {
    result.source_scope = nullable(string)(fields.source_scope, path + '.source_scope');
    if (
      result.source_scope !== null &&
      (result.source_scope.length !== 64 || !/^[a-f0-9]{64}$/.test(result.source_scope))
    )
      throw new ContractError(path + '.source_scope');
  }
  if (Object.hasOwn(fields, 'source_table')) {
    result.source_table = nullable(string)(fields.source_table, path + '.source_table');
    if (
      result.source_table !== null &&
      (result.source_table.length > 300 || result.source_table.includes('\0'))
    )
      throw new ContractError(path + '.source_table');
  }
  if (Object.hasOwn(fields, 'source_context_page')) {
    result.source_context_page = nullable(positive)(
      fields.source_context_page,
      path + '.source_context_page',
    );
    if (result.source_context_page !== null && result.source_context_page > 20000)
      throw new ContractError(path + '.source_context_page');
  }
  if (Object.hasOwn(fields, 'source_conditions')) {
    const values = fields.source_conditions;
    if (
      !values ||
      typeof values !== 'object' ||
      Array.isArray(values) ||
      Object.keys(values).length > 6
    )
      throw new ContractError(path + '.source_conditions');
    result.source_conditions = Object.fromEntries(
      Object.entries(values).map(([key, value]) => {
        if (
          ![
            'cell_line',
            'construct',
            'duration',
            'treatment_duration',
            'timepoint',
            'batch',
          ].includes(key)
        )
          throw new ContractError(path + '.source_conditions');
        const text = nullable(string)(value, path + '.source_conditions.' + key);
        if (text !== null && (text.length > 1000 || text.includes('\0')))
          throw new ContractError(path + '.source_conditions.' + key);
        return [key, text];
      }),
    );
  }
  if (
    (result.source_table != null ||
      result.source_context_page != null ||
      Object.keys(result.source_conditions ?? {}).length) &&
    !result.source_scope
  )
    throw new ContractError(path + '.source_scope');
  if (result.source_scope && result.source_context_page == null)
    throw new ContractError(path + '.source_context_page');
  return result;
}
