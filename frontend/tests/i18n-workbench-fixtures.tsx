import { act } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';
import type { Filters } from '../src/api/types';
import { setLocale, useTranslation } from '../src/i18n';
import { resultColumns } from '../src/model/resultColumns';
import { ColumnMenu } from '../src/features/results/ColumnMenu';
import { EDITOR_CHANNEL } from '../src/features/structure-editor/protocol';
import { compound, project, results } from './fixtures';

/** Explicit English test setup with the same cleanup contract in every spec. */
export function setupWorkbenchLocale() {
  beforeEach(() => setLocale('en'));
  afterEach(() => {
    setLocale('zh-CN');
    vi.restoreAllMocks();
  });
}

/** Raw data deliberately collides with UI source strings to guard the boundary. */
export const switchTo = (locale: 'zh-CN' | 'en') => act(() => setLocale(locale));
export const activity = {
  id: 'a'.repeat(64),
  name: '原文编号',
  unit: 'nM',
  target: '保存',
  assay: '原始实验',
};
export const row = {
  ...compound,
  identifier_label: '取消',
  smiles: 'C[C@H](O)Cl',
  activities: [{ ...activity, value: '< 10', page: 5 }],
};
export function paneProps() {
  return {
    project,
    resource: {
      data: { ...results, items: [row], activity_columns: [activity] },
      loading: false,
      error: null,
      reload: vi.fn(),
    },
    filters: { q: '', confidence: '', review: '', target: '', page: 1, page_size: 10 },
    selected: new Set([row.id]),
    focusedId: null,
    onFilters: vi.fn(),
    onSelect: vi.fn(),
    onSelectPage: vi.fn(),
    onJump: vi.fn(),
    onActivitySource: vi.fn(),
    onCrop: vi.fn(),
    onReview: vi.fn(),
    onExport: vi.fn(),
    onUpload: vi.fn(),
  };
}

export function FilterMenu({
  onFilters,
  columnId = 'compound',
}: {
  onFilters: (patch: Partial<Filters>) => void;
  columnId?: string;
}) {
  useTranslation();
  return (
    <ColumnMenu
      projectId={project.id}
      column={resultColumns().find((column) => column.id === columnId)!}
      filters={paneProps().filters}
      onFilters={onFilters}
      onHide={vi.fn()}
    />
  );
}
export function frameMessage(frame: HTMLIFrameElement, payload: object) {
  act(() =>
    window.dispatchEvent(
      new MessageEvent('message', {
        origin: window.location.origin,
        source: frame.contentWindow,
        data: { channel: EDITOR_CHANNEL, ...payload },
      }),
    ),
  );
}
