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
import type { Filters, JobOptions, ReviewDecision } from './types';
import { decodeAdmet, decodeEvidenceSummary, decodeRecognition } from './analysisDecoders';
import { ContractError } from './validation';
import { environmentApi } from './environmentApi';
import { correctionApi } from './correctionApi';

export const client = new ApiClient();
const segment = encodeURIComponent;
const projectPath = (id: string) => `/projects/${segment(id)}`;
export const api = {
  ...environmentApi(client),
  ...correctionApi(client),
  session: () => client.bootstrap(),
  health: (signal: AbortSignal) => client.get('/health', decodeHealth, signal),
  projects: (signal: AbortSignal) => client.get('/projects', decodeProjects, signal),
  project: (id: string, signal: AbortSignal) => client.get(projectPath(id), decodeProject, signal),
  results: (id: string, filters: Filters, signal: AbortSignal) => {
    const query = new URLSearchParams(Object.entries(filters).map(([k, v]) => [k, String(v)]));
    return client.get(`${projectPath(id)}/results?${query}`, decodeResults, signal);
  },
  page: (id: string, page: number, signal: AbortSignal) =>
    client.get(`${projectPath(id)}/pages/${page}`, decodePage, signal),
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
    const query = filters
      ? new URLSearchParams({
          q: filters.q,
          confidence: filters.confidence,
          review: filters.review,
          target: filters.target,
        })
      : null;
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
