import { ApiClient } from './client';
import {
  decodeHealth,
  decodeJob,
  decodeJobs,
  decodePage,
  decodeProject,
  decodeProjects,
  decodeResults,
  decodeReview,
  decodeRuntime,
} from './decoders';
import type { ActivityFocusSelection, Filters, JobOptions, ReviewDecision } from './types';
import { decodeAdmet, decodeEvidenceSummary, decodeRecognition } from './analysisDecoders';
import { ContractError, count } from './validation';
import { environmentApi } from './environmentApi';
import { correctionApi } from './correctionApi';
import { historyApi } from './historyApi';
import { validActivityFocus } from './activitySourceDecoders';
import { decodeFilterValues } from './filterValueDecoders';

export const client = new ApiClient();
const segment = encodeURIComponent;
const projectPath = (id: string) => `/projects/${segment(id)}`;
function resultQuery(filters: Filters, pagination = true): URLSearchParams {
  const query = new URLSearchParams({
    q: filters.q,
    confidence: filters.confidence,
    review: filters.review,
    target: filters.target,
  });
  if (pagination) {
    query.set('page', String(filters.page));
    query.set('page_size', String(filters.page_size));
  }
  if (filters.column_filters !== undefined)
    query.set('column_filters', JSON.stringify(filters.column_filters));
  if (filters.sort_column) {
    query.set('sort_column', filters.sort_column);
    query.set('sort_direction', filters.sort_direction ?? 'asc');
    if (filters.sort_band) query.set('sort_band', filters.sort_band);
  }
  return query;
}
export const api = {
  ...environmentApi(client),
  ...correctionApi(client),
  ...historyApi(client),
  session: () => client.bootstrap(),
  health: (signal: AbortSignal) => client.get('/health', decodeHealth, signal),
  projects: (signal: AbortSignal) => client.get('/projects', decodeProjects, signal),
  project: (id: string, signal: AbortSignal) => client.get(projectPath(id), decodeProject, signal),
  results: (id: string, filters: Filters, signal: AbortSignal) => {
    const query = resultQuery(filters);
    return client.get(`${projectPath(id)}/results?${query}`, decodeResults, signal);
  },
  filterValues: (
    id: string,
    column: string,
    filters: Filters,
    search: string,
    page: number,
    signal: AbortSignal,
  ) => {
    if (
      !column ||
      Array.from(column).length > 100 ||
      Array.from(search).length > 500 ||
      !Number.isInteger(page) ||
      page < 1 ||
      page > 25000
    )
      throw new ContractError('$.filter_values_query');
    const query = resultQuery(filters, false);
    for (const key of ['sort_column', 'sort_direction', 'sort_band']) query.delete(key);
    query.set('column', column);
    query.set('search', search);
    query.set('page', String(page));
    query.set('page_size', '200');
    return client.get(
      `${projectPath(id)}/filter-values?${query}`,
      (input) => {
        const choices = decodeFilterValues(input);
        if (choices.column !== column || choices.page !== page || choices.page_size !== 200)
          throw new ContractError('$.filter_values');
        return choices;
      },
      signal,
    );
  },
  page: (id: string, page: number, signal: AbortSignal, focus?: ActivityFocusSelection) => {
    if (focus !== undefined && !validActivityFocus(focus))
      throw new ContractError('$.activity_focus');
    const query = focus
      ? new URLSearchParams({ focus_compound: focus.compoundId, focus_activity: focus.key })
      : null;
    return client.get(
      `${projectPath(id)}/pages/${page}${query ? `?${query}` : ''}`,
      (input) => {
        const result = decodePage(input);
        if (
          result.page !== page ||
          (result.activity_focus &&
            (!focus ||
              result.activity_focus.compound_id !== focus.compoundId ||
              result.activity_focus.activity_key !== focus.key))
        )
          throw new ContractError('$.activity_focus');
        return result;
      },
      signal,
    );
  },
  jobs: (projectId: string | null, signal: AbortSignal) =>
    client.get(`/jobs${projectId ? `?project_id=${segment(projectId)}` : ''}`, decodeJobs, signal),
  job: (id: string, signal: AbortSignal) => client.get(`/jobs/${segment(id)}`, decodeJob, signal),
  createJob: (id: string, resumeId: string | null = null, options: JobOptions = {}) =>
    client.mutate(
      `${projectPath(id)}/jobs`,
      'POST',
      {
        ...(resumeId ? {} : { include_admet: true, ...options }),
        allow_partial: false,
        advisory: false,
        resume_job_id: resumeId,
      },
      decodeJob,
    ),
  cancelJob: (id: string) => client.mutate(`/jobs/${segment(id)}/cancel`, 'POST', {}, decodeJob),
  reauthorizeJobLLM: (id: string, expectedRevision: number) =>
    client.mutate(
      `/jobs/${segment(id)}/llm-authorization`,
      'POST',
      { expected_revision: count(expectedRevision, '$.expected_revision'), consent: true },
      (input) => {
        const job = decodeJob(input);
        if (job.id !== id) throw new ContractError('$.id');
        return job;
      },
    ),
  review: (
    id: string,
    compoundId: string,
    decision: ReviewDecision,
    note: string,
    revision: number,
  ) =>
    client.mutate(
      `${projectPath(id)}/reviews/${segment(compoundId)}`,
      'PUT',
      { decision, note, expected_revision: revision },
      decodeReview,
    ),
  upload: (file: File, title: string, patentId = '') =>
    client.upload(
      `/projects?${new URLSearchParams({ filename: file.name, title, ...(patentId.trim() ? { patent_id: patentId.trim() } : {}) })}`,
      file,
      decodeProject,
    ),
  attachPdf: (id: string, file: File) =>
    client.upload(
      `${projectPath(id)}/pdf?${new URLSearchParams({ filename: file.name })}`,
      file,
      decodeProject,
    ),
  export: (id: string, format: 'csv' | 'json', ids: string[], filters?: Filters) => {
    const query = filters ? resultQuery(filters, false) : null;
    return client.download(`${projectPath(id)}/export${query ? `?${query}` : ''}`, {
      format,
      compound_ids: ids,
    });
  },
  runtime: (signal: AbortSignal) => client.get('/runtime', decodeRuntime, signal),
  admet: (smiles: string[], signal: AbortSignal) =>
    client.mutate('/analysis/admet', 'POST', { smiles }, decodeAdmet, {
      signal,
      timeoutMs: 190_000,
    }),
  recognize: (id: string, compoundId: string, signal: AbortSignal) =>
    client.mutate(
      `${projectPath(id)}/compounds/${segment(compoundId)}/recognize`,
      'POST',
      {},
      (value) => {
        const result = decodeRecognition(value);
        if (result.compound_id !== compoundId) throw new ContractError('$.compound_id');
        return result;
      },
      { signal, timeoutMs: 190_000 },
    ),
  evidenceSummary: (id: string, signal: AbortSignal) =>
    client.get(
      `${projectPath(id)}/evidence-summary`,
      (value) => {
        const summary = decodeEvidenceSummary(value);
        if (summary.project_id !== id) throw new ContractError('$.project_id');
        return summary;
      },
      signal,
    ),
};

export function safeAssetUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value, window.location.origin);
    if (
      url.origin !== window.location.origin ||
      url.username ||
      url.password ||
      !/^\/api\/v1\/projects\/[^/]+\/(pages\/\d+\/image|structures\/[^/]+\/(image|redraw))$/.test(
        url.pathname,
      )
    )
      return null;
    return `${url.pathname}${url.search}`;
  } catch {
    return null;
  }
}
