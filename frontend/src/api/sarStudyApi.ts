import { client } from './index';
import type { ApiClient } from './client';
import { ContractError } from './validation';
import { decodeStudyPreview } from './sarPreviewDecoder';
import { decodeStudyMatrix } from './sarMatrixDecoder';
import { decodeSARJob } from './sarJobDecoders';
import { createSARMutation } from './sarMutation';
import { sarTransport } from './sarTransport';
import { createDrawingBatch } from './sarDrawingBatch';
import { drawingBatchDecoder } from './sarDrawingBatchDecoder';
import {
  decodeStudyCatalog,
  decodeStudyRegionDetail,
  decodeStudyProfile,
  decodeStudyRows,
} from './sarStudyDecoders';
import type { StudyExportFormat, StudyFilter, StudyRequest } from './sarStudyTypes';
export function createSARStudyApi(shared: ApiClient, rawFetch?: typeof fetch) {
  const mutate = createSARMutation(shared),
    raw = sarTransport(shared, rawFetch);
  const path = (id: string) => '/sar/jobs/' + encodeURIComponent(id) + '/study';
  const drawing = createDrawingBatch((selection, keys, signal) => {
    const query = new URLSearchParams({ kind: selection.kind });
    if (selection.region) query.set('region_id', selection.region);
    keys.forEach((key) => query.append('identifier', key));
    return shared.get(
      path(selection.job) + '/drawings?' + query,
      drawingBatchDecoder(selection, keys),
      signal,
    );
  });
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
        path(id) + '/catalog',
        (v) => {
          const result = decodeStudyCatalog(v);
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
    region: (id: string, dataset: string, region: string, signal: AbortSignal) =>
      raw.readReport(
        path(id) + '/regions/' + encodeURIComponent(region),
        (value) => {
          const result = decodeStudyRegionDetail(value);
          checkJob(result.job, id, dataset);
          if (
            result.job.status !== 'complete' ||
            result.region.region.id !== region ||
            result.region.region.dataset_id !== dataset ||
            result.activity_basis.source_input_sha256 !== result.job.input_sha256
          )
            throw new ContractError('$.region_detail_identity');
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
      pageSize = 50,
    ) => {
      if (
        filter.query.length > 200 ||
        !Number.isInteger(pageSize) ||
        pageSize < 1 ||
        pageSize > 200
      )
        throw new ContractError('$.query');
      return shared.get(
        path(id) +
          '/rows?' +
          new URLSearchParams({
            page: String(page),
            page_size: String(pageSize),
            ...filter,
            sort_by: sort.column || 'label',
            sort_direction: sort.direction,
          }),
        (v) => {
          const result = decodeStudyRows(v);
          checkJob(result.job, id, dataset);
          if (
            result.page !== page ||
            result.page_size !== pageSize ||
            result.job.status !== 'complete'
          )
            throw new ContractError('$.study_page');
          return result;
        },
        signal,
      );
    },
    drawing,
    preview: (
      id: string,
      dataset: string,
      regionId: string,
      moleculeId: string,
      signal: AbortSignal,
    ) =>
      shared.get(
        path(id) +
          '/preview?' +
          new URLSearchParams({ region_id: regionId, molecule_id: moleculeId }),
        (value) => {
          const result = decodeStudyPreview(value);
          checkJob(result.job, id, dataset);
          if (result.region.id !== regionId || result.candidate.molecule_id !== moleculeId)
            throw new ContractError('$.preview_selection');
          return result;
        },
        signal,
      ),
    export: (id: string, format: StudyExportFormat, signal: AbortSignal) =>
      raw.export(path(id) + '/export?format=' + format, format, signal),
    matrix: (
      id: string,
      dataset: string,
      reference: string,
      selections: readonly { region_id: string; molecule_id: string }[],
      signal: AbortSignal,
    ) => {
      if (
        !selections.length ||
        selections.length > 6 ||
        new Set(selections.map((item) => item.molecule_id)).size !== selections.length
      )
        throw new ContractError('$.matrix_selection');
      const query = new URLSearchParams({ reference_id: reference });
      selections.forEach((item) => {
        query.append('region_id', item.region_id);
        query.append('molecule_id', item.molecule_id);
      });
      return shared.get(
        path(id) + '/matrix?' + query,
        (value) => {
          const result = decodeStudyMatrix(value);
          if (
            result.previews.length !== selections.length ||
            result.reference_drawing.id !== reference
          )
            throw new ContractError('$.matrix_selection');
          result.previews.forEach((item, index) => {
            checkJob(item.job, id, dataset);
            if (
              item.job.status !== 'complete' ||
              item.region.id !== selections[index]!.region_id ||
              item.candidate.molecule_id !== selections[index]!.molecule_id
            )
              throw new ContractError('$.matrix_selection');
          });
          return result;
        },
        signal,
      );
    },
  };
}
export const sarStudyApi = createSARStudyApi(client);
