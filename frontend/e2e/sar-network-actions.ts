import { expect, type Page } from '@playwright/test';
import type { StudyRegionSummary } from '../src/api/sarStudyTypes';
import { compactNetworkSites } from '../src/features/sar/study/networkSites';

export function portSite(
  summaries: StudyRegionSummary[],
  label: string,
  candidate: string,
  ports: number,
) {
  const visible = compactNetworkSites(
    summaries.filter(
      (item) => item.reference_label === label && item.matched && !item.no_variation,
    ),
  );
  const chosen = visible
    .map((item, index) => ({ item, index }))
    .filter(
      ({ item }) =>
        item.region.attachment_count === ports &&
        item.fragments.some((fragment) => fragment.molecule_ids.includes(candidate)),
    )
    .sort((a, b) => a.item.region.atom_indices.length - b.item.region.atom_indices.length)[0];
  expect(chosen).toBeDefined();
  return chosen!;
}

const terminalCSV =
  'id,smiles,IC50 (nM),t_half (h),target,assay,cell_line,duration\n1,COc1ccc(Cl)cc1,10,1,T,controlled,C,1h\n2,CCOc1ccc(Cl)cc1,1,2,T,controlled,C,1h\n3,COc1ccc(Br)cc1,0.1,3,T,controlled,C,1h\n4,CCCOc1ccc(Cl)cc1,,4,T,controlled,C,1h\n,CO,0.00001,99,T,controlled,C,1h\nIntermediate 18,CCO,0.00001,99,T,controlled,C,1h\n';

export async function createNetwork(page: Page, width: number, csv = terminalCSV) {
  await page.goto('/#/sar');
  const imports = page.getByRole('region', { name: 'Import data', exact: true });
  await imports.getByRole('button', { name: 'CSV file', exact: true }).click();
  await imports.getByLabel('Choose a CSV file', { exact: true }).setInputFiles({
    name: `single-site-${width}.csv`,
    mimeType: 'text/csv',
    buffer: Buffer.from(csv),
  });
  await imports.getByRole('button', { name: 'Preview on server', exact: true }).click();
  await imports
    .getByRole('combobox', { name: 'Source identifier column', exact: true })
    .selectOption('id');
  await imports
    .getByRole('combobox', { name: 'SMILES column', exact: true })
    .selectOption('smiles');
  for (const name of ['IC50 (nM)', 't_half (h)'])
    await imports.getByRole('checkbox', { name, exact: true }).check();
  for (const [label, column] of [
    ['Target column (optional)', 'target'],
    ['Assay column (optional)', 'assay'],
    ['Cell-line column (optional)', 'cell_line'],
    ['Duration column (optional)', 'duration'],
  ] as const)
    await imports.getByRole('combobox', { name: label, exact: true }).selectOption(column);
  await imports.getByRole('button', { name: 'Create CSV dataset', exact: true }).click();
  await expect(page).toHaveURL(/dataset=[a-f0-9]{32}/);
  const setup = page.getByRole('region', { name: 'Study setup', exact: true });
  await setup.getByRole('checkbox', { name: /IC50/ }).check();
  await setup.getByRole('checkbox', { name: /t_half/ }).check();
  await setup
    .getByRole('combobox', { name: 'Activity direction', exact: true })
    .first()
    .selectOption('lower');
  await setup
    .getByRole('combobox', { name: 'Activity direction', exact: true })
    .nth(1)
    .selectOption('higher');
  await setup.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(
    setup.getByRole('checkbox', { name: 'Find single-site changes', exact: true }),
  ).toBeChecked();
  await setup.getByRole('button', { name: 'Run full study', exact: true }).click();
  await expect(page).toHaveURL(/job=[a-f0-9]{32}/);
  const params = new URLSearchParams(new URL(page.url()).hash.split('?')[1]);
  const job = params.get('job')!,
    dataset = params.get('dataset')!;
  const report = page.getByRole('region', { name: 'Study report', exact: true });
  await expect(report.getByRole('button', { name: 'Variable regions', exact: true })).toBeVisible({
    timeout: 20000,
  });
  return { job, dataset, report };
}
