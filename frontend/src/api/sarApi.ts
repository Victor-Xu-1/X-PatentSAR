import { client } from './index';
import type { ApiClient } from './client';
import {
  decodeCSVPreview,
  decodeDataset,
  decodeDatasets,
  decodeDrawing,
  decodeMolecule,
  decodeMolecules,
  decodeRegion,
} from './sarDecoders';
import { decodePairs, decodeSARJob, decodeSARJobs } from './sarJobDecoders';
import type {
  AnalysisRequest,
  CSVMapping,
  ProjectSnapshot,
  RegionRequest,
  ResumeRequest,
} from './sarTypes';
import { ContractError } from './validation';
import { createSARMutation } from './sarMutation';
import { sarTransport } from './sarTransport';

export function createSARApi(shared: ApiClient, rawFetch?: typeof fetch) {
  const raw = sarTransport(shared, rawFetch);
  const mutate = createSARMutation(shared);
  const datasetPath = (id: string) => `/sar/datasets/${encodeURIComponent(id)}`;
  const jobPath = (id: string) => `/sar/jobs/${encodeURIComponent(id)}`;
  const scopedJob = (datasetId: string, jobId?: string) => (v: unknown) => {
    const result = decodeSARJob(v);
    if (result.dataset_id !== datasetId || (jobId !== undefined && result.id !== jobId))
      throw new ContractError('$.sar_job_identity');
    return result;
  };
  return {
    datasets: (signal: AbortSignal) => shared.get('/sar/datasets', decodeDatasets, signal),
    preview: (file: File) =>
      raw.upload(
        `/sar/csv/preview?${new URLSearchParams({ filename: file.name })}`,
        file,
        decodeCSVPreview,
      ),
    discardPreview: (token: string) => raw.remove(`/sar/csv/${encodeURIComponent(token)}`),
    createCSV: (payload: CSVMapping) =>
      mutate('/sar/datasets/csv', payload, (v) => {
        const result = decodeDataset(v);
        if (result.source_kind !== 'csv') throw new ContractError('$.source_kind');
        return result;
      }),
    createProject: (payload: ProjectSnapshot) =>
      mutate('/sar/datasets/project', payload, (v) => {
        const result = decodeDataset(v);
        if (result.source_kind !== 'project' || result.source_project_id !== payload.project_id)
          throw new ContractError('$.source_project_id');
        return result;
      }),
    dataset: (id: string, signal: AbortSignal) =>
      shared.get(
        datasetPath(id),
        (v) => {
          const result = decodeDataset(v);
          if (result.id !== id) throw new ContractError('$.id');
          return result;
        },
        signal,
      ),
    removeDataset: (id: string) => raw.remove(datasetPath(id)),
    molecules: (id: string, page: number, query: string, signal: AbortSignal) => {
      if (query.length > 200) throw new ContractError('$.query');
      return shared.get(
        `${datasetPath(id)}/molecules?${new URLSearchParams({ page: String(page), page_size: '50', query })}`,
        (v) => {
          const result = decodeMolecules(v);
          if (result.page !== page || result.page_size !== 50)
            throw new ContractError('$.molecule_page');
          return result;
        },
        signal,
      );
    },
    molecule: (id: string, moleculeId: string, signal: AbortSignal) =>
      shared.get(
        `${datasetPath(id)}/molecules/${encodeURIComponent(moleculeId)}`,
        (v) => {
          const result = decodeMolecule(v);
          if (result.id !== moleculeId) throw new ContractError('$.molecule.id');
          return result;
        },
        signal,
      ),
    drawing: (id: string, moleculeId: string, signal: AbortSignal) =>
      shared.get(
        `${datasetPath(id)}/molecules/${encodeURIComponent(moleculeId)}/drawing`,
        (v) => {
          const result = decodeDrawing(v);
          if (result.molecule.id !== moleculeId) throw new ContractError('$.molecule.id');
          return result;
        },
        signal,
      ),
    saveRegion: (id: string, payload: RegionRequest) =>
      mutate(`${datasetPath(id)}/regions`, payload, (v) => {
        const result = decodeRegion(v);
        if (
          result.dataset_id !== id ||
          result.molecule_id !== payload.molecule_id ||
          result.dataset_revision !== payload.expected_dataset_revision ||
          result.graph_sha256 !== payload.expected_graph_sha256 ||
          [...result.atom_indices].sort((a, b) => a - b).join() !==
            [...payload.atom_indices].sort((a, b) => a - b).join()
        )
          throw new ContractError('$.region_identity');
        return result;
      }),
    jobs: (id: string, signal: AbortSignal) =>
      shared.get(
        `${datasetPath(id)}/jobs`,
        (v) => {
          const result = decodeSARJobs(v);
          if (result.items.some((item) => item.dataset_id !== id))
            throw new ContractError('$.jobs');
          return result;
        },
        signal,
      ),
    analyse: (id: string, payload: AnalysisRequest) =>
      mutate(`${datasetPath(id)}/jobs`, payload, (v) => {
        const result = scopedJob(id)(v);
        if (result.region_id !== payload.region_id || result.metric_id !== payload.metric_id)
          throw new ContractError('$.analysis_identity');
        return result;
      }),
    job: (id: string, datasetId: string, signal: AbortSignal) =>
      shared.get(jobPath(id), scopedJob(datasetId, id), signal),
    cancel: (id: string, datasetId: string) =>
      mutate(`${jobPath(id)}/cancel`, {}, scopedJob(datasetId, id)),
    removeJob: (id: string) => raw.remove(jobPath(id)),
    resume: (id: string, datasetId: string, payload: ResumeRequest) =>
      mutate(`${jobPath(id)}/resume`, payload, (v) => {
        const result = scopedJob(datasetId)(v);
        if (result.input_sha256 !== payload.expected_input_sha256)
          throw new ContractError('$.input_sha256');
        return result;
      }),
    pairs: (id: string, datasetId: string, page: number, signal: AbortSignal) =>
      shared.get(
        `${jobPath(id)}/pairs?${new URLSearchParams({ page: String(page), page_size: '50' })}`,
        (v) => {
          const result = decodePairs(v);
          if (
            result.job.id !== id ||
            result.job.dataset_id !== datasetId ||
            result.page !== page ||
            result.page_size !== 50
          )
            throw new ContractError('$.pair_page');
          return result;
        },
        signal,
      ),
    export: (id: string, format: 'csv' | 'json', signal: AbortSignal) =>
      raw.export(`${jobPath(id)}/export?format=${format}`, format, signal),
  };
}
export const sarApi = createSARApi(client);
