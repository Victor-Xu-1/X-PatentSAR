import { UiError } from '../../i18n';
import { useEffect, useState } from 'react';
import { api } from '../../api';
import type { Filters, FilterValueKind, FilterValues } from '../../api/types';

interface ChoiceRequest {
  projectId: string | undefined;
  column: string;
  filters: Filters;
  search: string;
  page: number;
  retry: number;
}
interface ChoiceState {
  key: string;
  data: FilterValues | null;
  error: Error | null;
}

// This hook exists only in the open dropdown. It never loads all columns or
// falls back to the current result page / old eager activity-choice catalog.
export function useFilterValues(
  projectId: string | undefined,
  column: string,
  filters: Filters,
  search: string,
  page: number,
) {
  const [retry, setRetry] = useState(0);
  const [kind, setKind] = useState<FilterValueKind | null>(null);
  const key = JSON.stringify({
    projectId,
    column,
    search,
    page,
    retry,
    filters: {
      q: filters.q,
      confidence: filters.confidence,
      review: filters.review,
      target: filters.target,
      column_filters: filters.column_filters ?? [],
      page: 1,
      page_size: 200,
    },
  } satisfies ChoiceRequest);
  const [state, setState] = useState<ChoiceState>({ key: '', data: null, error: null });
  useEffect(() => {
    const request = JSON.parse(key) as ChoiceRequest;
    const controller = new AbortController();
    if (!request.projectId) {
      return () => controller.abort();
    }
    const timer = setTimeout(
      () => {
        void api
          .filterValues(
            request.projectId!,
            request.column,
            request.filters,
            request.search,
            request.page,
            controller.signal,
          )
          .then((data) => {
            if (!controller.signal.aborted) {
              setKind(data.kind);
              setState({ key, data, error: null });
            }
          })
          .catch((error: unknown) => {
            if (!controller.signal.aborted)
              setState({
                key,
                data: null,
                error: error instanceof Error ? error : new UiError('无法加载取值。'),
              });
          });
      },
      request.search ? 250 : 0,
    );
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [key]);
  const current = !projectId
    ? { data: null, error: new UiError('尚未选择项目，无法加载取值。') }
    : state.key === key
      ? state
      : { data: null, error: null };
  return {
    ...current,
    kind,
    loading: !current.data && !current.error,
    reload: () => setRetry((old) => old + 1),
  };
}
