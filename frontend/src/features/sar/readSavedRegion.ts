import { ApiError } from '../../api/errors';
import { sarStudyApi } from '../../api/sarStudyApi';
import type { Region, RegionRequest } from '../../api/sarTypes';
import { UiError } from '../../i18n';

/** Read the existing profile authority. Never retry a POST or infer a region identity. */
export async function readSavedRegion(datasetId: string, request: RegionRequest): Promise<Region> {
  let profile;
  try {
    profile = await sarStudyApi.profile(
      datasetId,
      request.expected_dataset_revision,
      new AbortController().signal,
    );
  } catch (error) {
    if (error instanceof ApiError)
      throw new ApiError(error.status, error.code, error.source, true, error.values);
    throw new ApiError(
      0,
      'sar_region_readback_invalid',
      error instanceof UiError ? error.source : '无法核对已保存选区，请稍后再次检查。',
      true,
      error instanceof UiError ? error.values : {},
    );
  }
  // These defaults are the public RegionRequest contract, not UI translations.
  const name = request.name ?? 'Region',
    kind = request.kind ?? 'variable';
  const atoms = [...request.atom_indices].sort((a, b) => a - b).join(',');
  const matches = profile.regions.filter(
    (region) =>
      region.dataset_id === datasetId &&
      region.dataset_revision === request.expected_dataset_revision &&
      region.molecule_id === request.molecule_id &&
      region.graph_sha256 === request.expected_graph_sha256 &&
      region.name === name &&
      region.kind === kind &&
      [...region.atom_indices].sort((a, b) => a - b).join(',') === atoms,
  );
  if (matches.length !== 1)
    throw new ApiError(
      0,
      'sar_region_not_confirmed',
      '尚未找到唯一匹配的已保存选区，请稍后再次检查。',
      true,
    );
  return matches[0]!;
}
