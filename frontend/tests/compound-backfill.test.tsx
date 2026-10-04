import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { client } from '../src/api';
import type { Compound, Job, Results } from '../src/api/types';
import { METRIC_SPECS } from '../src/api/predictionTypes';
import { compound, health, job, json, page, project, results, session } from './fixtures';

describe('existing-project completion through the single job polling path', () => {
  it('refreshes a source-only row and its open SMILES detail at phase transition, then its six values on completion', async () => {
    const missing: Compound = {
      ...compound,
      id: 'Compound8',
      display_id: 'Compound 8',
      activities: [],
      record_kind: 'structure_only',
    };
    const recognized: Compound = {
      ...missing,
      smiles: 'CCO',
      recognition: {
        status: 'valid',
        quality_flag: 'clean',
        model_fingerprint: null,
        token_confidence: null,
      },
    };
    const running: Job = {
      ...job,
      id: '4'.repeat(32),
      include_admet: true,
      admet_only: true,
      stages: [],
      admet_stage: {
        name: 'admet',
        status: 'running',
        count: 0,
        duration_seconds: 1,
        reused_checkpoint: false,
        progress: {
          phase: 'recognition',
          completed: 1,
          total: 7,
          cache_hits: 1,
          failures: 0,
          device: 'cpu',
          peak_rss_mb: null,
        },
      },
    };
    let currentJob: Job | null = null;
    let currentResults: Results = { ...results, items: [missing], metrics: [], targets: [] };
    let resultReads = 0;
    let detailReads = 0;
    const transport = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/session')) return json(session);
      if (url.endsWith('/health'))
        return json({ ...health, capabilities: { admet: true, summary: false } });
      if (url.endsWith(`/projects/${project.id}`)) return json(project);
      if (url.includes('/results?')) {
        resultReads++;
        return json(currentResults);
      }
      if (url.includes('/pages/')) return json(page);
      if (url.endsWith(`/jobs/${running.id}`)) {
        detailReads++;
        return json(currentJob);
      }
      if (url.endsWith(`/jobs?project_id=${project.id}`))
        return json({ items: currentJob ? [currentJob] : [] });
      if (url.endsWith(`/projects/${project.id}/jobs`) && init?.method === 'POST') {
        currentJob = running;
        return json(currentJob, 201);
      }
      throw new Error(`Unexpected isolated completion request: ${url}`);
    });
    client.resetSession();
    vi.stubGlobal('fetch', transport);
    window.location.hash = `#/projects/${project.id}?page=4`;
    render(<App />);
    await screen.findByRole('button', { name: '查看 Compound 8 结构详情' });
    fireEvent.click(screen.getByRole('button', { name: '列表选项' }));
    const action = screen.getByRole('button', { name: '补齐结构与指标' });
    expect(action).toBeEnabled();
    vi.useFakeTimers();
    await act(async () => fireEvent.click(action));
    expect(document.querySelector('.stage-current')).toHaveTextContent('结构识别 · 进行中 · 1 / 7');
    expect(action).toBeDisabled();
    const writes = transport.mock.calls.filter(([, init]) => init?.method === 'POST');
    expect(writes).toHaveLength(1);
    expect(writes[0]?.[0]).toBe(`/api/v1/projects/${project.id}/jobs`);
    expect(JSON.parse(String(writes[0]?.[1]?.body))).toEqual({
      include_admet: true,
      admet_only: true,
      allow_partial: false,
      advisory: false,
      resume_job_id: null,
    });
    fireEvent.click(
      within(screen.getByRole('dialog', { name: '列表选项' })).getByRole('button', {
        name: '关闭对话框',
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: '查看 Compound 8 结构详情' }));
    const detail = screen.getByRole('dialog', { name: '结构详情 · Compound 8' });
    expect(within(detail).queryByLabelText('当前 SMILES')).not.toBeInTheDocument();
    const beforeTransition = resultReads;
    const beforePoll = detailReads;
    currentResults = { ...currentResults, items: [recognized] };
    currentJob = {
      ...running,
      admet_stage: {
        ...running.admet_stage!,
        progress: {
          ...running.admet_stage!.progress!,
          phase: 'properties',
          completed: 0,
          total: 1,
          cache_hits: 0,
        },
      },
    };
    await act(async () => vi.advanceTimersByTimeAsync(3000));
    expect(detailReads).toBe(beforePoll + 1);
    expect(resultReads).toBe(beforeTransition + 1);
    expect(document.querySelector('.stage-current')).toHaveTextContent('指标计算 · 进行中 · 0 / 1');
    expect(within(detail).getByLabelText('当前 SMILES')).toHaveValue('CCO');

    currentResults = {
      ...currentResults,
      items: [
        {
          ...recognized,
          admet: {
            status: 'complete',
            properties: METRIC_SPECS.map((spec, index) => ({
              ...spec,
              value: [46.069, -0.1, 20.23, 1, 1, -3.2][index]!,
            })),
            source_fingerprint: '1'.repeat(64),
            smiles_sha256: '2'.repeat(64),
            engine: { name: 'ADMET-AI', version: '2.0.1', model_sha256: '3'.repeat(64) },
            generated_at: '2026-10-04T08:00:00Z',
            job_id: running.id,
            warnings: [],
            error: null,
            review_only: true,
          },
        },
      ],
    };
    currentJob = {
      ...currentJob,
      status: 'complete',
      admet_stage: {
        ...currentJob.admet_stage!,
        status: 'ok',
        count: 1,
        progress: { ...currentJob.admet_stage!.progress!, completed: 1 },
      },
    };
    await act(async () => vi.advanceTimersByTimeAsync(3000));
    expect(resultReads).toBe(beforeTransition + 2);
    expect(within(detail).getByText('六项指标 · 已计算')).toBeVisible();
    expect(
      document.querySelector('tr[data-compound="Compound8"] [data-property="molecular_weight"]'),
    ).toHaveTextContent('46.07');
    expect(
      document.querySelector('tr[data-compound="Compound8"] [data-property="Solubility_AqSolDB"]'),
    ).toHaveTextContent('-3.20');
    expect(within(detail).getByLabelText('当前 SMILES')).toHaveValue('CCO');
    const afterCompletion = resultReads;
    await act(async () => vi.advanceTimersByTimeAsync(10_000));
    expect(resultReads).toBe(afterCompletion);
    expect(transport.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
  });
});
