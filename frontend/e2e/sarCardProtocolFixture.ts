import { expect, type Page } from '@playwright/test';
import type { Dataset, Molecule } from '../src/api/sarTypes';
import { studyJob, studyReport, studyRow } from '../tests/sar-fixtures';

/** Layout-only report DTOs; no fake record is inserted into a server job store.
 * Drawings come from the real installed RDKit dataset endpoint. Scientific
 * report correctness is deliberately not asserted by this protocol fixture.
 */
export async function cardProtocol(page: Page, dataset: Dataset) {
  const rows = await page.request.get(
    `/api/v1/sar/datasets/${dataset.id}/molecules?page=1&page_size=50`,
  );
  expect(rows.ok()).toBe(true);
  const molecule: Molecule = (await rows.json()).items.find(
    (row: Molecule) => row.label === 'Compound 30',
  );
  expect(molecule?.eligible).toBe(true);
  const job = { ...studyJob, id: 'a'.repeat(32), dataset_id: dataset.id };
  const report = structuredClone(studyReport);
  report.dataset_id = dataset.id;
  report.dataset_revision = dataset.revision;
  report.title = 'Controlled card protocol fixture — not a scientific report';
  report.candidates[0]!.molecule_id = molecule.id;
  report.candidates[0]!.label = molecule.label;
  report.candidates[0]!.properties = molecule.properties ?? {};
  report.scaffolds[0]!.smiles = molecule.smiles;
  report.scaffolds[0]!.molecule_ids = [molecule.id];
  report.regions[0]!.region = {
    ...report.regions[0]!.region,
    dataset_id: dataset.id,
    dataset_revision: dataset.revision,
    molecule_id: molecule.id,
    graph_sha256: molecule.graph_sha256!,
  };
  report.regions[0]!.reference_label = molecule.label;
  report.regions[0]!.fragments[0]!.smiles = molecule.smiles!;
  report.regions[0]!.fragments[0]!.molecule_ids = [molecule.id];
  const drawings: Array<{ kind: string; identifier: string }> = [];
  const rowRequests: Array<Record<string, string>> = [];
  await page.route(`**/api/v1/sar/datasets/${dataset.id}/jobs`, (route) =>
    route.fulfill({ json: { items: [job], total: 1 } }),
  );
  await page.route(`**/api/v1/sar/jobs/${job.id}**`, async (route) => {
    expect(route.request().method()).toBe('GET');
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/study/drawing')) {
      const identifier = url.searchParams.get('identifier')!;
      drawings.push({ kind: url.searchParams.get('kind')!, identifier });
      const response = await page.request.get(
        `/api/v1/sar/datasets/${dataset.id}/molecules/${molecule.id}/drawing`,
      );
      expect(response.ok()).toBe(true);
      await route.fulfill({ json: { id: identifier, svg: (await response.json()).svg } });
    } else if (url.pathname.endsWith('/study/rows')) {
      const filters = Object.fromEntries(url.searchParams);
      rowRequests.push(filters);
      const query = (filters.query ?? '').toLocaleLowerCase();
      const matched = !query || molecule.label.toLocaleLowerCase().includes(query);
      await route.fulfill({
        json: {
          job,
          page: Number(filters.page),
          page_size: 50,
          total: matched ? 1 : 0,
          items: matched
            ? [
                {
                  ...studyRow,
                  molecule_id: molecule.id,
                  label: molecule.label,
                  properties: molecule.properties ?? {},
                },
              ]
            : [],
        },
      });
    } else if (url.pathname.endsWith('/study')) {
      await route.fulfill({ json: { job, report } });
    } else if (url.pathname.endsWith('/' + job.id)) {
      await route.fulfill({ json: job });
    } else {
      throw new Error('Unexpected protocol-fixture request: ' + url.pathname);
    }
  });
  await page.goto(`/?card-protocol=${dataset.id}#/sar?dataset=${dataset.id}&job=${job.id}`);
  await expect(page.getByRole('region', { name: 'Study report', exact: true })).toBeVisible();
  return { drawings, molecule, report, rowRequests, job };
}
