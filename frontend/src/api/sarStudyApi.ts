import { client } from './index';
import type { ApiClient } from './client';
import { ContractError } from './validation';
import { decodeSARJob } from './sarJobDecoders';
import { createSARMutation } from './sarMutation';
import { sarTransport } from './sarTransport';
import {
  decodeStudyDrawing,
  decodeStudyOverview,
  decodeStudyProfile,
  decodeStudyRows,
} from './sarStudyDecoders';
import type {
  StudyDrawingKind,
  StudyExportFormat,
  StudyFilter,
  StudyRequest,
} from './sarStudyTypes';
export function createSARStudyApi(shared: ApiClient, rawFetch?: typeof fetch) {
  const mutate = createSARMutation(shared),
    raw = sarTransport(shared, rawFetch);
  const path = (id: string) => '/sar/jobs/' + encodeURIComponent(id) + '/study';
  const checkJob = (job: ReturnType<typeof decodeSARJob>, id: string, dataset: string) => {
    if (job.id !== id || job.dataset_id !== dataset || job.kind !== 'study')
      throw new ContractError('$.study_job_identity');
  };
  return {
    profile: (id: string, revision: number, signal: AbortSignal) =>
      shared.get(
        '/sar/datasets/' + encodeURIComponent(id) + '/profile',
        (v) => {
          const result = decodeStudyProfile(v);
          if (result.dataset_id !== id || result.dataset_revision !== revision)
            throw new ContractError('$.study_profile_identity');
          return result;
        },
        signal,
      ),
    start: (id: string, payload: StudyRequest) =>
      mutate('/sar/datasets/' + encodeURIComponent(id) + '/studies', payload, (v) => {
        const result = decodeSARJob(v);
        if (result.dataset_id !== id || result.kind !== 'study')
          throw new ContractError('$.study_job_identity');
        return result;
      }),
    overview: (id: string, dataset: string, signal: AbortSignal) =>
      raw.readReport(
        path(id),
        (v) => {
          const result = decodeStudyOverview(v);
          checkJob(result.job, id, dataset);
          if (
            result.job.status !== 'complete' ||
            result.report.dataset_id !== dataset ||
            result.report.input_sha256 !== result.job.input_sha256 ||
            result.report.rows.length !== 0
          )
            throw new ContractError('$.study_report_identity');
          return result;
        },
        signal,
      ),
    rows: (
      id: string,
      dataset: string,
      page: number,
      filter: StudyFilter,
      signal: AbortSignal,
      sort = { column: '', direction: 'asc' },
    ) => {
      if (filter.query.length > 200) throw new ContractError('$.query');
      return shared.get(
        path(id) +
          '/rows?' +
          new URLSearchParams({
            page: String(page),
            page_size: '50',
            ...filter,
            sort_by: sort.column || 'label',
            sort_direction: sort.direction,
          }),
        (v) => {
          const result = decodeStudyRows(v);
          checkJob(result.job, id, dataset);
          if (result.page !== page || result.page_size !== 50 || result.job.status !== 'complete')
            throw new ContractError('$.study_page');
          return result;
        },
        signal,
      );
    },
    drawing: (
      id: string,
      kind: StudyDrawingKind,
      identifier: string,
      signal: AbortSignal,
      regionId = '',
    ) =>
      shared.get(
        path(id) +
          '/drawing?' +
          new URLSearchParams({ kind, identifier, ...(regionId ? { region_id: regionId } : {}) }),
        (v) => {
          const result = decodeStudyDrawing(v);
          if (result.id !== identifier) throw new ContractError('$.study_drawing_identity');
          return result;
        },
        signal,
      ),
    export: (id: string, format: StudyExportFormat, signal: AbortSignal) =>
      raw.export(path(id) + '/export?format=' + format, format, signal),
  };
}
export const sarStudyApi = createSARStudyApi(client);
